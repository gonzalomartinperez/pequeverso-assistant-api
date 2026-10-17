"""Catalog facts published by the storefront, as the assistant is allowed to use them.

The catalog is untrusted data: it grounds answers and validates references, but its text never
becomes instructions. Prices are volatile facts; `ActiveCatalog.price_status` decides whether they
may be quoted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal


class PriceStatus(StrEnum):
    VERIFIED = 'verified'
    UNVERIFIED = 'unverified'


@dataclass(frozen=True, slots=True)
class Price:
    amount: Decimal
    currency: str
    display: str
    note: str
    tax_note: str


@dataclass(frozen=True, slots=True)
class Image:
    url: str
    width: int
    height: int
    alt: str


@dataclass(frozen=True, slots=True)
class Resource:
    id: str
    title: str
    pages: int | None
    description: str
    image: Image | None = None


@dataclass(frozen=True, slots=True)
class AgeGuidance:
    label: str
    hint: str


@dataclass(frozen=True, slots=True)
class Product:
    id: str
    name: str
    path: str
    purchase_path: str
    summary: str
    age_range: str
    format: str
    usage: str
    pdf_count: int | None
    page_count: int | None
    price: Price | None
    resources: tuple[Resource, ...]
    image: Image | None = None
    method: tuple[str, ...] = ()
    audience_for: tuple[str, ...] = ()
    audience_not_for: tuple[str, ...] = ()
    age_guidance: tuple[AgeGuidance, ...] = ()
    kind: Literal['core', 'affiliate'] = 'core'
    disclosure: str | None = None
    guarantee_days: int | None = None
    topics: tuple[str, ...] = ()


class DocumentKind(StrEnum):
    FAQ = 'faq'
    POLICY = 'policy'
    SUPPORT = 'support'


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    kind: DocumentKind
    title: str
    text: str
    url: str
    product_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Link:
    id: str
    label: str
    url: str
    product_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Site:
    name: str
    origin: str
    """Storefront origin without a trailing slash; product paths are relative to it."""
    language: str
    support_email: str
    support_link_id: str


@dataclass(frozen=True, slots=True)
class Catalog:
    schema_version: int
    generated_at: datetime
    source_revision: str
    site: Site
    products: tuple[Product, ...]
    documents: tuple[Document, ...]
    links: tuple[Link, ...]
    forbidden_terms: tuple[str, ...] = field(default=())

    def product(self, product_id: str) -> Product | None:
        return next((p for p in self.products if p.id == product_id), None)

    def resource(self, resource_id: str) -> tuple[Product, Resource] | None:
        for product in self.products:
            for resource in product.resources:
                if resource_key(product.id, resource.id) == resource_id:
                    return product, resource
        return None

    def link(self, link_id: str) -> Link | None:
        return next((link for link in self.links if link.id == link_id), None)

    def document(self, document_id: str) -> Document | None:
        return next((d for d in self.documents if d.id == document_id), None)

    def url(self, path: str) -> str:
        return f'{self.site.origin}{path}'

    def prices(self) -> frozenset[Decimal]:
        return frozenset(p.price.amount for p in self.products if p.price is not None)

    def applies_to(self, product_ids: tuple[str, ...], selected: frozenset[str]) -> bool:
        # Legacy unscoped merchant facts belong to the original core products, never to
        # a newly added third-party product. New exports name scopes explicitly.
        owners = product_ids or tuple(p.id for p in self.products if p.kind == 'core')
        return bool(selected.intersection(owners))


def resource_key(product_id: str, resource_id: str) -> str:
    """Globally unique reference id of a resource inside a product."""
    return f'{product_id}/{resource_id}'


@dataclass(frozen=True, slots=True)
class ActiveCatalog:
    """The catalog currently in force plus the freshness facts needed to quote prices."""

    catalog: Catalog
    sha256: str
    verified_at: datetime
    """When the storefront facts (prices included) were last confirmed."""
    max_price_age: timedelta

    def price_status(self, now: datetime) -> PriceStatus:
        if now - self.verified_at <= self.max_price_age:
            return PriceStatus.VERIFIED
        return PriceStatus.UNVERIFIED


def mentioned_products(text: str, catalog: Catalog) -> frozenset[str]:
    """Bounded catalog aliases; topic words select evidence, never create product facts."""
    import re
    import unicodedata

    normalized = ''.join(
        c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn'
    )
    selected: set[str] = set()
    for product in catalog.products:
        name = ''.join(
            c for c in unicodedata.normalize('NFD', product.name.lower()) if unicodedata.category(c) != 'Mn'
        )
        aliases = (name, product.id.replace('-', ' '), *(r.id.replace('-', ' ') for r in product.resources))
        if (
            any(alias in normalized for alias in aliases)
            or (
                product.kind == 'affiliate'
                and re.search(
                    r'\b(?:alimentacion|complementaria|bebe|bebes|comidas|recetas|feeding|baby|babies)\b',
                    normalized,
                )
            )
            or (
                product.kind == 'core'
                and re.search(
                    r'\b(?:grafismo|fonetico|kit|lectura|leer|silabas|reading|phonics)\b', normalized
                )
            )
        ):
            selected.add(product.id)
    return frozenset(selected)
