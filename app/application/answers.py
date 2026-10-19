"""Turns a model draft into a presentable answer. Every id is resolved against the active catalog;
unknown ids are dropped, and an answer that breaks an answer rule is replaced as a whole.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from app.application.ports import Draft, DraftReference
from app.application.price_comparison import clarification, comparison_products
from app.domain.answer_policy import (
    AnswerRules,
    Violation,
    check_answer,
    fold,
    unsupported_checkout_policy,
)
from app.domain.catalog import (
    ActiveCatalog,
    Catalog,
    Image,
    PriceStatus,
    Product,
    Resource,
    mentioned_products,
)
from app.domain.conversation import (
    AnswerDetails,
    ImageRef,
    LinkRef,
    Message,
    Notice,
    PriceRef,
    ProductRef,
    ReferenceKind,
    ResourceRef,
    SourceRef,
)
from app.domain.language import Language
from app.domain.page_claims import unsupported_page_claim
from app.domain.web_evidence import WebEvidence, negated_at, unsupported_platform_policy

_MARKUP = re.compile(r'</?[A-Za-z][^<>]{0,300}>')
_MARKDOWN_LINK = re.compile(r'\[([^\]\n]{1,180})\]\(([^)\n]{0,512})\)')
_BRACKET_LABEL = re.compile(r'\[([^\[\]\n]{1,180})\](?!\()')
_PROVIDER_CITATION = re.compile(r'[ \t]*\ue200cite\ue202[^\ue200\ue201\n]{1,256}\ue201[ \t]*')
_PROVIDER_CITATION_MARKERS = ('\ue200', '\ue201', '\ue202')
MAX_ANSWER_CHARS = 2000
MAX_RESOURCES = 3
MAX_LINKS = 3
MAX_SOURCES = 3
MAX_FOLLOW_UPS = 3
MAX_FOLLOW_UP_CHARS = 90

REPLACEMENT_ANSWER = (
    'No puedo confirmar esa información con los datos que tengo del catálogo. '
    'Puedes revisar la información pública del producto y las opciones de ayuda de Hotmart.'
)
REPLACEMENT_ANSWER_EN = (
    "I can't confirm that with the store information I have. "
    'You can check the public product information and Hotmart help options.'
)
PAYMENT_REFUSAL_ANSWER = (
    'Por seguridad eliminé tu mensaje: no escribas datos de tarjetas en este chat. '
    'El pago se hace solo en la página segura de Hotmart. ¿Te ayudo con alguna duda sobre el producto?'
)
PAYMENT_REFUSAL_ANSWER_EN = (
    'For your security I removed your message: please do not type card details in this chat. '
    "Payment happens only on Hotmart's secure page. Can I help with a question about the product?"
)
UNSUPPORTED_LANGUAGE_ANSWER = (
    'Por ahora solo puedo responder en español o en inglés. ¿Me escribes tu pregunta en uno de '
    'esos idiomas?\n\nFor now I can only answer in Spanish or English. Could you write your '
    'question in one of them?'
)
UNSUPPORTED_LANGUAGE_ANSWER_ES = (
    'Por ahora te ayudo solo en español. ¿Qué te gustaría saber sobre Pequeverso?'
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


def price_comparison_reply(
    question: str,
    active: ActiveCatalog,
    history: Sequence[Message],
    language: Language,
    price_status: PriceStatus,
) -> FinalizedAnswer | None:
    """Do not generate a relation whose operands lack verified current prices."""
    products = comparison_products(question, active.catalog, history)
    if products is None:
        return None
    if products and price_status is PriceStatus.VERIFIED and all(p.price is not None for p in products):
        return None
    if not products:
        text = clarification(language)
    else:
        missing = tuple(p for p in products if p.price is None)
        names = ', '.join(f'«{p.name}»' for p in missing)
        if language is Language.EN:
            text = (
                f'I cannot compare their prices: I do not have a published price for {names}.'
                if missing
                else 'I cannot compare their prices without currently verified prices.'
            )
        else:
            text = (
                f'No puedo comparar sus precios: no tengo un precio publicado para {names}.'
                if missing
                else 'No puedo comparar sus precios sin precios actuales verificados.'
            )
        if price_status is PriceStatus.VERIFIED:
            for product in products:
                if product.price is not None:
                    text += (
                        f' The reference price for «{product.name}» is {product.price.display}.'
                        if language is Language.EN
                        else f' El precio de referencia de «{product.name}» es {product.price.display}.'
                    )
        text += (
            " Check each product's current final price, currency and applicable taxes before paying."
            if language is Language.EN
            else ' Revisa el precio final actual, la moneda y los impuestos de cada producto antes de pagar.'
        )
    return finalize(
        Draft(text, tuple(DraftReference(ReferenceKind.PRODUCT, p.id) for p in products), (), ()),
        active,
        price_status,
        answer_rules(active.catalog, price_status, ()),
        language,
    )


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
        known_price_pairs=frozenset(
            (p.price.amount, p.price.currency) for p in catalog.products if p.price is not None
        ),
    )


def support_link(catalog: Catalog, product_ids: frozenset[str] = frozenset()) -> tuple[LinkRef, ...]:
    link = catalog.link(catalog.site.support_link_id)
    if link and product_ids and not catalog.applies_to(link.product_ids, product_ids):
        link = next(
            (
                item
                for item in catalog.links
                if item.id.startswith('hotmart-') and catalog.applies_to(item.product_ids, product_ids)
            ),
            None,
        )
    return (LinkRef(link.id, link.label, link.url),) if link else ()


def replacement(
    catalog: Catalog,
    notice: Notice,
    language: Language = Language.ES,
    product_ids: frozenset[str] = frozenset(),
) -> AnswerDetails:
    return AnswerDetails(links=support_link(catalog, product_ids), notices=(notice,), language=language.value)


def _image(image: Image | None) -> ImageRef | None:
    return ImageRef(image.url, image.width, image.height, image.alt) if image else None


def product_ref(active: ActiveCatalog, product: Product, price_status: PriceStatus) -> ProductRef:
    catalog = active.catalog
    price = None
    if price_status is PriceStatus.VERIFIED and product.price is not None:
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
        kind=product.kind,
        format=product.format,
        disclosure=product.disclosure,
    )


def resource_ref(reference_id: str, owner: Product, resource: Resource) -> ResourceRef:
    return ResourceRef(
        reference_id, owner.id, resource.title, resource.pages, resource.description, _image(resource.image)
    )


def plain_text(text: str) -> str:
    """Answers are plain text by contract: markup-like tags are removed, not escaped or rendered."""
    return _MARKUP.sub('', text).strip()


def _readable_text(text: str) -> str:
    """After destination validation, flatten links and unfinished labels for plain-text clients.

    Keep an authorized URL visible instead of silently hiding it; structured reference links
    remain the only interactive navigation. Never run this before the destination guard.
    """
    # Raw destinations/prices were checked before this bounded presentation cleanup.
    text = _PROVIDER_CITATION.sub(' ', text).strip()
    text = _MARKDOWN_LINK.sub(lambda match: f'{match.group(1)} ({match.group(2)})', text)
    return _BRACKET_LABEL.sub(r'\1', text)


@dataclass(frozen=True, slots=True)
class CheckedContent:
    content: str
    violations: tuple[Violation, ...]

    @property
    def accepted(self) -> bool:
        return (
            bool(self.content)
            and len(self.content) <= MAX_ANSWER_CHARS
            and not self.violations
            and not any(marker in self.content for marker in _PROVIDER_CITATION_MARKERS)
        )


def check_content(
    text: str,
    catalog: Catalog,
    rules: AnswerRules,
    web_evidence: tuple[WebEvidence, ...] = (),
) -> CheckedContent:
    """The same normalization and business boundary for cumulative prefixes and final answers."""
    content = plain_text(text)
    raw_content = content
    violations = check_answer(content, rules) if content else []
    content = _readable_text(content)
    violations = list(dict.fromkeys([*violations, *check_answer(content, rules)]))
    # Product scopes are checked before AND after readable cleanup, including raw citation text.
    for candidate in (raw_content, content):
        for sentence in re.split(r'[!?;\n]+|[.](?!\d)|,(?!\d)', candidate):
            selected = mentioned_products(sentence, catalog)
            owners = tuple(p for p in catalog.products if p.id in selected)
            if not owners:
                continue
            if any(p.price is None for p in owners):
                scoped_rules = replace(rules, known_prices=frozenset(), known_price_pairs=frozenset())
                if Violation.UNKNOWN_PRICE in check_answer(sentence, scoped_rules):
                    violations.append(Violation.UNKNOWN_PRICE)
            if any(p.pdf_count is None for p in owners):
                normalized = fold(sentence)
                if any(
                    not negated_at(normalized, match.start())
                    for match in re.finditer(r'\b\d{1,5}\s+(?:pdfs?|archivos? pdf)\b', normalized)
                ):
                    violations.append(Violation.UNSUPPORTED_PAGE_CLAIM)
            policies = tuple(d.text for d in catalog.documents if catalog.applies_to(d.product_ids, selected))
            if unsupported_platform_policy(sentence, policies):
                violations.append(Violation.UNSUPPORTED_POLICY_CLAIM)
    # Merchant policy authority never depends on optional external evidence availability.
    for candidate in (raw_content, content):
        if unsupported_checkout_policy(candidate, tuple(d.text for d in catalog.documents)):
            violations.append(Violation.UNSUPPORTED_POLICY_CLAIM)
        if unsupported_platform_policy(candidate, tuple(d.text for d in catalog.documents)):
            violations.append(Violation.UNSUPPORTED_POLICY_CLAIM)
        if unsupported_page_claim(candidate, catalog):
            violations.append(Violation.UNSUPPORTED_PAGE_CLAIM)
    return CheckedContent(content, tuple(dict.fromkeys(violations)))


_COMPLETE_PREFIX = re.compile(r'[.!?](?=\s)|\n[ \t]*\n')


class ValidatedStreamPrefix:
    """Bounded, append-only presentation of checked complete sentences/paragraphs.

    A numeric decimal or URL dot without following whitespace is not a boundary. Ambiguous
    markup stays terminal-only; later text cannot retroactively rewrite an emitted prefix.
    These deterministic checks do not establish general semantic truth or citation entailment.
    """

    def __init__(self) -> None:
        self._buffer = ''
        self._emitted = ''
        self._blocked = False

    def feed(
        self,
        chunk: str,
        catalog: Catalog,
        rules: AnswerRules,
        web_evidence: tuple[WebEvidence, ...] = (),
    ) -> str:
        if self._blocked:
            return ''
        if len(self._buffer) + len(chunk) > MAX_ANSWER_CHARS:
            self._blocked = True
            return ''
        self._buffer += chunk
        if any(marker in self._buffer for marker in ('<', '>', '[', ']', *_PROVIDER_CITATION_MARKERS)):
            self._blocked = True
            return ''
        end = max((match.end() for match in _COMPLETE_PREFIX.finditer(self._buffer)), default=0)
        if not end:
            return ''
        checked = check_content(self._buffer[:end], catalog, rules, web_evidence)
        if not checked.accepted or not checked.content.startswith(self._emitted):
            self._blocked = True
            return ''
        return self._append(checked.content)

    def finish(self, final: FinalizedAnswer) -> str:
        # Full canonical validation has completed; never turn a replacement into fake typing.
        if self._blocked or Notice.ANSWER_REPLACED in final.details.notices:
            return ''
        if not final.content.startswith(self._emitted):
            self._blocked = True
            return ''
        return self._append(final.content)

    def _append(self, content: str) -> str:
        delta = content[len(self._emitted) :]
        self._emitted = content
        return delta


def finalize(
    draft: Draft,
    active: ActiveCatalog,
    price_status: PriceStatus,
    rules: AnswerRules,
    language: Language = Language.ES,
    web_evidence: tuple[WebEvidence, ...] = (),
    catalog_source_ids: frozenset[str] | None = None,
) -> FinalizedAnswer:
    catalog = active.catalog
    selected = frozenset(
        ref.id for ref in draft.references if ref.kind == ReferenceKind.PRODUCT and catalog.product(ref.id)
    )
    scoped = (
        replace(
            catalog,
            documents=tuple(d for d in catalog.documents if catalog.applies_to(d.product_ids, selected)),
        )
        if selected
        else catalog
    )
    if selected and all((p := catalog.product(pid)) is not None and p.price is None for pid in selected):
        rules = replace(rules, known_prices=frozenset(), known_price_pairs=frozenset())
    checked = check_content(draft.answer, scoped, rules, web_evidence)
    content = checked.content
    if not checked.accepted:
        return FinalizedAnswer(
            replacement_text(language),
            replacement(catalog, Notice.ANSWER_REPLACED, language, selected),
            checked.violations,
            len(draft.references),
        )

    products: dict[str, ProductRef] = {}
    resources: dict[str, ResourceRef] = {}
    links: dict[str, LinkRef] = {}
    dropped = 0
    for reference in draft.references:
        if reference.kind == ReferenceKind.PRODUCT and (product := catalog.product(reference.id)):
            products.setdefault(product.id, product_ref(active, product, price_status))
        elif (
            reference.kind == ReferenceKind.RESOURCE
            and (found := catalog.resource(reference.id))
            and (not selected or found[0].id in selected)
        ):
            owner, resource = found
            if len(resources) < MAX_RESOURCES:
                resources.setdefault(reference.id, resource_ref(reference.id, owner, resource))
        elif (
            reference.kind == ReferenceKind.LINK
            and (link := catalog.link(reference.id))
            and (not selected or catalog.applies_to(link.product_ids, selected))
        ):
            if len(links) < MAX_LINKS:
                links.setdefault(link.id, LinkRef(link.id, link.label, link.url))
        else:
            dropped += 1

    sources: dict[str, SourceRef] = {}
    external_sources = {item.id: item for item in web_evidence}
    for source_id in draft.sources:
        document = catalog.document(source_id)
        if document is None and (external := external_sources.get(source_id)):
            if len(sources) < MAX_SOURCES:
                sources.setdefault(
                    external.id, SourceRef(external.id, external.source.title, external.source.url)
                )
        elif (
            document is None
            or (selected and not catalog.applies_to(document.product_ids, selected))
            or (catalog_source_ids is not None and source_id not in catalog_source_ids)
        ):
            dropped += 1
        elif len(sources) < MAX_SOURCES:
            sources.setdefault(document.id, SourceRef(document.id, document.title, document.url))

    follow_ups: list[str] = []
    for suggestion in draft.follow_ups:
        raw_text = ' '.join(plain_text(suggestion).split())
        if check_answer(raw_text, rules):
            continue
        text = _readable_text(raw_text)
        if (
            0 < len(text) <= MAX_FOLLOW_UP_CHARS
            and text not in follow_ups
            and not check_answer(text, rules)
            and len(follow_ups) < MAX_FOLLOW_UPS
        ):
            follow_ups.append(text)

    disclosures = tuple(
        p.disclosure
        for p in catalog.products
        if p.kind == 'affiliate'
        and p.disclosure
        and (p.id in products or p.name.casefold() in content.casefold())
    )
    for disclosure in disclosures:
        if disclosure not in content:
            enriched = f'{content}\n\n{disclosure}'
            if len(enriched) > MAX_ANSWER_CHARS:
                return FinalizedAnswer(
                    replacement_text(language),
                    replacement(catalog, Notice.ANSWER_REPLACED, language, selected),
                    (),
                    dropped,
                )
            checked_enriched = check_content(enriched, scoped, rules, web_evidence)
            if not checked_enriched.accepted:
                return FinalizedAnswer(
                    replacement_text(language),
                    replacement(catalog, Notice.ANSWER_REPLACED, language, selected),
                    checked_enriched.violations,
                    dropped,
                )
            content = checked_enriched.content
    details = AnswerDetails(
        products=tuple(products.values()),
        resources=tuple(resources.values()),
        links=tuple(links.values()),
        sources=tuple(sources.values()),
        follow_ups=tuple(follow_ups),
        language=language.value,
    )
    return FinalizedAnswer(content, details, (), dropped)
