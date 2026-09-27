"""Conversation state owned by one anonymous session, and the references an answer may carry."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Role(StrEnum):
    USER = 'user'
    ASSISTANT = 'assistant'


class ReferenceKind(StrEnum):
    PRODUCT = 'product'
    RESOURCE = 'resource'
    LINK = 'link'


class Notice(StrEnum):
    """Why a final answer differs from what a model would have produced."""

    ANSWER_REPLACED = 'answer_replaced'
    PAYMENT_DATA_REFUSED = 'payment_data_refused'
    CONTACT_DATA_REDACTED = 'contact_data_redacted'


@dataclass(frozen=True, slots=True)
class ImageRef:
    url: str
    width: int
    height: int
    alt: str


@dataclass(frozen=True, slots=True)
class PriceRef:
    """A catalog price as quoted at answer time, with the time its source was confirmed."""

    amount: str
    currency: str
    display: str
    note: str
    tax_note: str
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class ProductRef:
    id: str
    name: str
    summary: str
    age_range: str
    url: str
    purchase_url: str
    image: ImageRef | None
    price: PriceRef | None
    """None when the price could not be confirmed as current (see docs/api-contract.md)."""


@dataclass(frozen=True, slots=True)
class ResourceRef:
    id: str
    product_id: str
    title: str
    pages: int | None
    description: str
    image: ImageRef | None


@dataclass(frozen=True, slots=True)
class LinkRef:
    id: str
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class SourceRef:
    id: str
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class AnswerDetails:
    """Validated, catalog-backed parts of an assistant message."""

    products: tuple[ProductRef, ...] = ()
    resources: tuple[ResourceRef, ...] = ()
    links: tuple[LinkRef, ...] = ()
    sources: tuple[SourceRef, ...] = ()
    follow_ups: tuple[str, ...] = ()
    notices: tuple[Notice, ...] = ()


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    role: Role
    content: str
    created_at: datetime
    details: AnswerDetails = field(default_factory=AnswerDetails)


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    csrf_token: str
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime
