"""Turns a model draft into a presentable answer. Every id is resolved against the active catalog;
unknown ids are dropped, and an answer that breaks an answer rule is replaced as a whole.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.application.ports import Draft
from app.domain.answer_policy import AnswerRules, Violation, check_answer
from app.domain.catalog import ActiveCatalog, Catalog, Image, PriceStatus, Product, Resource
from app.domain.conversation import (
    AnswerDetails,
    ImageRef,
    LinkRef,
    Notice,
    PriceRef,
    ProductRef,
    ReferenceKind,
    ResourceRef,
    SourceRef,
)
from app.domain.language import Language

_MARKUP = re.compile(r'</?[A-Za-z][^<>]{0,300}>')
MAX_ANSWER_CHARS = 2000
MAX_RESOURCES = 3
MAX_LINKS = 3
MAX_SOURCES = 3
MAX_FOLLOW_UPS = 3
MAX_FOLLOW_UP_CHARS = 90

REPLACEMENT_ANSWER = (
    'No puedo confirmar esa información con los datos que tengo del catálogo. '
    'Puedes revisar la página del kit o escribirnos desde soporte y te respondemos.'
)
REPLACEMENT_ANSWER_EN = (
    "I can't confirm that with the store information I have. "
    'You can check the kit page or write to support and the team will reply.'
)
PAYMENT_REFUSAL_ANSWER = (
    'Por seguridad eliminé tu mensaje: no escribas datos de tarjetas en este chat. '
    'El pago se hace solo en la página segura de Hotmart. ¿Te ayudo con alguna duda sobre el kit?'
)
PAYMENT_REFUSAL_ANSWER_EN = (
    'For your security I removed your message: please do not type card details in this chat. '
    "Payment happens only on Hotmart's secure page. Can I help with a question about the kit?"
)
UNSUPPORTED_LANGUAGE_ANSWER = (
    'Por ahora solo puedo responder en español o en inglés. ¿Me escribes tu pregunta en uno de '
    'esos idiomas?\n\nFor now I can only answer in Spanish or English. Could you write your '
    'question in one of them?'
)


def replacement_text(language: Language) -> str:
    return REPLACEMENT_ANSWER_EN if language is Language.EN else REPLACEMENT_ANSWER


def payment_refusal_text(language: Language) -> str:
    return PAYMENT_REFUSAL_ANSWER_EN if language is Language.EN else PAYMENT_REFUSAL_ANSWER


@dataclass(frozen=True, slots=True)
class FinalizedAnswer:
    content: str
    details: AnswerDetails
    violations: tuple[Violation, ...]
    dropped_references: int


def answer_rules(
    catalog: Catalog, price_status: PriceStatus, extra_forbidden: tuple[str, ...]
) -> AnswerRules:
    hosts = {urlsplit(catalog.site.origin).hostname or ''}
    hosts.update(urlsplit(link.url).hostname or '' for link in catalog.links)
    hosts.update(urlsplit(doc.url).hostname or '' for doc in catalog.documents)
    hosts.discard('')
    urls = {catalog.site.origin}
    urls.update(link.url for link in catalog.links)
    urls.update(doc.url for doc in catalog.documents)
    urls.update(catalog.url(product.path) for product in catalog.products)
    urls.update(catalog.url(product.purchase_path) for product in catalog.products)
    # Published policy prose can name a bare official domain (refund.hotmart.com) while
    # its structured link points to /refund?lang=es. Permit that literal public mention,
    # without opening arbitrary paths on the same host or trusting new text-only hosts.
    for host in hosts:
        bare_host = re.compile(rf'(?<![\w/.-]){re.escape(host)}(?![\w/?#.-])', re.IGNORECASE)
        if any(bare_host.search(document.text) for document in catalog.documents):
            urls.add(f'https://{host}/')
    return AnswerRules(
        allowed_hosts=frozenset(hosts),
        allowed_emails=frozenset({catalog.site.support_email}),
        known_prices=catalog.prices(),
        prices_verified=price_status is PriceStatus.VERIFIED,
        forbidden_terms=(*catalog.forbidden_terms, *extra_forbidden),
        allowed_urls=frozenset(urls),
        known_price_pairs=frozenset((p.price.amount, p.price.currency) for p in catalog.products),
    )


def support_link(catalog: Catalog) -> tuple[LinkRef, ...]:
    link = catalog.link(catalog.site.support_link_id)
    return (LinkRef(link.id, link.label, link.url),) if link else ()


def replacement(catalog: Catalog, notice: Notice, language: Language = Language.ES) -> AnswerDetails:
    return AnswerDetails(links=support_link(catalog), notices=(notice,), language=language.value)


def _image(image: Image | None) -> ImageRef | None:
    return ImageRef(image.url, image.width, image.height, image.alt) if image else None


def product_ref(active: ActiveCatalog, product: Product, price_status: PriceStatus) -> ProductRef:
    catalog = active.catalog
    price = None
    if price_status is PriceStatus.VERIFIED:
        p = product.price
        price = PriceRef(f'{p.amount:.2f}', p.currency, p.display, p.note, p.tax_note, active.verified_at)
    return ProductRef(
        id=product.id,
        name=product.name,
        summary=product.summary,
        age_range=product.age_range,
        url=catalog.url(product.path),
        purchase_url=catalog.url(product.purchase_path),
        image=_image(product.image),
        price=price,
    )


def resource_ref(reference_id: str, owner: Product, resource: Resource) -> ResourceRef:
    return ResourceRef(
        reference_id, owner.id, resource.title, resource.pages, resource.description, _image(resource.image)
    )


def plain_text(text: str) -> str:
    """Answers are plain text by contract: markup-like tags are removed, not escaped or rendered."""
    return _MARKUP.sub('', text).strip()


def finalize(
    draft: Draft,
    active: ActiveCatalog,
    price_status: PriceStatus,
    rules: AnswerRules,
    language: Language = Language.ES,
) -> FinalizedAnswer:
    catalog = active.catalog
    content = plain_text(draft.answer)
    violations = check_answer(content, rules) if content else []
    if not content or len(content) > MAX_ANSWER_CHARS or violations:
        return FinalizedAnswer(
            replacement_text(language),
            replacement(catalog, Notice.ANSWER_REPLACED, language),
            tuple(violations),
            len(draft.references),
        )

    products: dict[str, ProductRef] = {}
    resources: dict[str, ResourceRef] = {}
    links: dict[str, LinkRef] = {}
    dropped = 0
    for reference in draft.references:
        if reference.kind == ReferenceKind.PRODUCT and (product := catalog.product(reference.id)):
            products.setdefault(product.id, product_ref(active, product, price_status))
        elif reference.kind == ReferenceKind.RESOURCE and (found := catalog.resource(reference.id)):
            owner, resource = found
            if len(resources) < MAX_RESOURCES:
                resources.setdefault(reference.id, resource_ref(reference.id, owner, resource))
        elif reference.kind == ReferenceKind.LINK and (link := catalog.link(reference.id)):
            if len(links) < MAX_LINKS:
                links.setdefault(link.id, LinkRef(link.id, link.label, link.url))
        else:
            dropped += 1

    sources: dict[str, SourceRef] = {}
    for source_id in draft.sources:
        document = catalog.document(source_id)
        if document is None:
            dropped += 1
        elif len(sources) < MAX_SOURCES:
            sources.setdefault(document.id, SourceRef(document.id, document.title, document.url))

    follow_ups: list[str] = []
    for suggestion in draft.follow_ups:
        text = ' '.join(plain_text(suggestion).split())
        if (
            0 < len(text) <= MAX_FOLLOW_UP_CHARS
            and text not in follow_ups
            and not check_answer(text, rules)
            and len(follow_ups) < MAX_FOLLOW_UPS
        ):
            follow_ups.append(text)

    details = AnswerDetails(
        products=tuple(products.values()),
        resources=tuple(resources.values()),
        links=tuple(links.values()),
        sources=tuple(sources.values()),
        follow_ups=tuple(follow_ups),
        language=language.value,
    )
    return FinalizedAnswer(content, details, (), dropped)
