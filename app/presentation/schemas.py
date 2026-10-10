"""Public v1 wire models. These are the contract (contracts/*.json is generated from them); they
never carry provider payloads, prompts, reasoning, HTML or executable UI.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.conversation import AnswerDetails, Message

SCHEMA_VERSION: Literal['1'] = '1'


class _Out(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class ImageOut(_Out):
    url: str = Field(description='Absolute https URL on the storefront origin.')
    width: int
    height: int
    alt: str


class PriceOut(_Out):
    amount: str = Field(description='Decimal string, e.g. "14.99".', examples=['14.99'])
    currency: Literal['USD']
    display: str = Field(description='Customer-facing format, e.g. "US$14,99".')
    note: str = Field(description='Local-currency explanation; show it next to the price.')
    tax_note: str
    verified_at: datetime = Field(description='When the storefront price was last confirmed.')


class ProductOut(_Out):
    id: str = Field(description='Authoritative storefront product id (slug).')
    name: str
    summary: str
    age_range: str
    url: str = Field(description='Product page on the storefront (allowlisted).')
    purchase_url: str = Field(
        description="Storefront purchase section; checkout itself stays in the store's flow."
    )
    image: ImageOut | None
    price: PriceOut | None = Field(description='null when the price cannot be confirmed as current.')


class ResourceOut(_Out):
    id: str = Field(description='"<product_id>/<resource_id>".')
    product_id: str
    title: str
    pages: int | None
    description: str
    image: ImageOut | None


class LinkOut(_Out):
    id: str
    label: str
    url: str


class SourceOut(_Out):
    id: str
    title: str
    url: str


Notice = Literal['answer_replaced', 'payment_data_refused', 'contact_data_redacted', 'language_unsupported']
Locale = Literal['es', 'en']
CONTRACT_REVISION = '1.2'


class MessageOut(_Out):
    id: str
    role: Literal['user', 'assistant']
    content: str = Field(
        description='Plain text; may contain **bold** and "- " list lines. Render as text, never as HTML. '
        'Independently useful without the fields below.'
    )
    created_at: datetime
    products: list[ProductOut] = Field(default_factory=list)
    resources: list[ResourceOut] = Field(default_factory=list)
    links: list[LinkOut] = Field(default_factory=list)
    sources: list[SourceOut] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list, description='Optional suggested next questions.')
    notices: list[Notice] = Field(default_factory=list)
    language: Locale = Field(
        default='es', description='Language of `content` (since 1.1). Use it as the lang attribute.'
    )

    @classmethod
    def of(cls, message: Message) -> MessageOut:
        d: AnswerDetails = message.details
        return cls(
            id=message.id,
            role=message.role.value,
            content=message.content,
            created_at=message.created_at,
            products=[
                ProductOut(
                    id=p.id,
                    name=p.name,
                    summary=p.summary,
                    age_range=p.age_range,
                    url=p.url,
                    purchase_url=p.purchase_url,
                    image=ImageOut(**asdict(p.image)) if p.image else None,
                    price=PriceOut(
                        amount=p.price.amount,
                        currency='USD',
                        display=p.price.display,
                        note=p.price.note,
                        tax_note=p.price.tax_note,
                        verified_at=p.price.verified_at,
                    )
                    if p.price
                    else None,
                )
                for p in d.products
            ],
            resources=[
                ResourceOut(
                    id=r.id,
                    product_id=r.product_id,
                    title=r.title,
                    pages=r.pages,
                    description=r.description,
                    image=ImageOut(**asdict(r.image)) if r.image else None,
                )
                for r in d.resources
            ],
            links=[LinkOut(id=link.id, label=link.label, url=link.url) for link in d.links],
            sources=[SourceOut(id=s.id, title=s.title, url=s.url) for s in d.sources],
            follow_ups=list(d.follow_ups),
            notices=[n.value for n in d.notices],
            language='en' if d.language == 'en' else 'es',
        )


Availability = Literal['available', 'unavailable']
UnavailableReason = Literal['assistant_disabled', 'catalog_unavailable', 'budget_exhausted']


class AvailabilityOut(_Out):
    status: Availability
    reason: UnavailableReason | None = None


class LimitsOut(_Out):
    max_message_chars: int
    messages_per_day: int


class SessionOut(_Out):
    schema_version: Literal['1'] = SCHEMA_VERSION
    csrf_token: str = Field(description='Send as X-CSRF-Token on every mutation. Keep in memory only.')
    expires_at: datetime = Field(description='Sliding: extended by each question and each session open.')
    created: bool = Field(description='True when this call created a new session.')
    messages: list[MessageOut] = Field(description='Stored history, oldest first (bounded).')
    availability: AvailabilityOut
    limits: LimitsOut
    starters: list[str] = Field(
        default_factory=list,
        description='Up to 4 opening questions from approved catalog topics, in the requested locale (since 1.1).',
    )
    contract_revision: str = Field(default=CONTRACT_REVISION, description='Additive revision within v1.')


class SessionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    locale: Locale | None = Field(default=None, description='Interface language; a preference, not an order.')


Page = Literal['home', 'product', 'support']


class MessageIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: Annotated[str, Field(min_length=1, max_length=2000)]
    page: Page | None = Field(default=None, description='Storefront page the visitor is on, if embedded.')
    locale: Locale | None = Field(
        default=None,
        description='Interface language (since 1.1). The answer language follows the message and the '
        'conversation; the locale only breaks ties.',
    )


class ErrorBody(_Out):
    code: str
    message: str = Field(description='English, for developers; localize from `code`.')
    retryable: bool
    request_id: str


class ErrorOut(_Out):
    error: ErrorBody
