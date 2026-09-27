"""Wire schema of `assistant/catalog.v1.json`, published by the storefront build.

Parsing is strict (unknown fields rejected, bounded sizes, https links on allowlisted hosts) and
produces domain objects. Text stays data: nothing here interprets it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.domain import catalog as domain

MAX_CATALOG_BYTES = 256 * 1024

Id = Annotated[str, StringConstraints(pattern=r'^[a-z0-9][a-z0-9.-]{0,63}$')]
Path = Annotated[str, StringConstraints(pattern=r'^/[A-Za-z0-9/_.#-]{0,200}$')]
Short = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=1500)]


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)


class PriceIn(_Model):
    amount: Decimal = Field(gt=0, lt=10000, decimal_places=2)
    currency: Literal['USD']
    display: Short
    note: Text
    tax_note: Short


class ImageIn(_Model):
    url: str
    width: int = Field(ge=1, le=8000)
    height: int = Field(ge=1, le=8000)
    alt: Short


class ResourceIn(_Model):
    id: Id
    title: Short
    pages: int | None = Field(ge=1, le=5000)
    description: Text
    image: ImageIn | None = None


class AgeGuidanceIn(_Model):
    label: Short
    hint: Text


class ProductIn(_Model):
    id: Id
    name: Short
    path: Path
    purchase_path: Path
    summary: Text
    age_range: Short
    format: Text
    usage: Text
    pdf_count: int = Field(ge=1, le=100)
    page_count: int = Field(ge=1, le=10000)
    price: PriceIn
    image: ImageIn | None = None
    resources: list[ResourceIn] = Field(min_length=1, max_length=40)
    method: list[Short] = Field(default_factory=list, max_length=12)
    audience_for: list[Short] = Field(default_factory=list, max_length=12)
    audience_not_for: list[Short] = Field(default_factory=list, max_length=12)
    age_guidance: list[AgeGuidanceIn] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def unique_resources(self) -> ProductIn:
        _unique(r.id for r in self.resources)
        return self


class DocumentIn(_Model):
    id: Id
    kind: Literal['faq', 'policy', 'support']
    title: Short
    text: Text
    url: str


class LinkIn(_Model):
    id: Id
    label: Short
    url: str


class SiteIn(_Model):
    name: Short
    origin: str
    language: Literal['es']
    support_email: Annotated[str, StringConstraints(pattern=r'^[^@\s]+@[^@\s]+\.[a-z]{2,}$')]
    support_link_id: Id


class SourceIn(_Model):
    repository: Short
    revision: Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9._-]{1,64}$')]


class CatalogIn(_Model):
    schema_version: Literal[1]
    generated_at: datetime
    source: SourceIn
    site: SiteIn
    products: list[ProductIn] = Field(min_length=1, max_length=20)
    documents: list[DocumentIn] = Field(max_length=80)
    links: list[LinkIn] = Field(max_length=20)
    forbidden_terms: list[Short] = Field(default_factory=list, max_length=20)

    @field_validator('generated_at')
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError('generated_at must include a timezone')
        return value

    @model_validator(mode='after')
    def consistent(self) -> CatalogIn:
        _unique(p.id for p in self.products)
        _unique(d.id for d in self.documents)
        _unique(link.id for link in self.links)
        if self.site.support_link_id not in {link.id for link in self.links}:
            raise ValueError('site.support_link_id must name a link')
        return self


def _unique(ids: Iterable[str]) -> None:
    seen: set[str] = set()
    for item in ids:
        if item in seen:
            raise ValueError(f'duplicate id {item!r}')
        seen.add(item)


class CatalogParser:
    """Validates a catalog document; links and document URLs must be https on allowed hosts."""

    def __init__(self, allowed_link_hosts: frozenset[str], require_https: bool = True) -> None:
        self._hosts = allowed_link_hosts
        self._require_https = require_https

    def __call__(self, body: bytes) -> domain.Catalog:
        if len(body) > MAX_CATALOG_BYTES:
            raise ValueError('catalog too large')
        parsed = CatalogIn.model_validate(json.loads(body))
        origin = self._check_url(parsed.site.origin, allow_path=False)
        return domain.Catalog(
            schema_version=parsed.schema_version,
            generated_at=parsed.generated_at,
            source_revision=parsed.source.revision,
            site=domain.Site(
                name=parsed.site.name,
                origin=origin,
                language=parsed.site.language,
                support_email=parsed.site.support_email,
                support_link_id=parsed.site.support_link_id,
            ),
            products=tuple(self._product(p) for p in parsed.products),
            documents=tuple(
                domain.Document(d.id, domain.DocumentKind(d.kind), d.title, d.text, self._check_url(d.url))
                for d in parsed.documents
            ),
            links=tuple(domain.Link(link.id, link.label, self._check_url(link.url)) for link in parsed.links),
            forbidden_terms=tuple(parsed.forbidden_terms),
        )

    def _check_url(self, url: str, allow_path: bool = True) -> str:
        parts = urlsplit(url)
        if parts.scheme != 'https' and (self._require_https or parts.scheme != 'http'):
            raise ValueError('catalog URLs must use https')
        if parts.username or parts.password or not parts.hostname or parts.hostname not in self._hosts:
            raise ValueError('catalog URL host is not allowed')
        if not allow_path and parts.path not in ('', '/'):
            raise ValueError('site origin must not include a path')
        return url.rstrip('/') if not allow_path else url

    def _image(self, image: ImageIn | None) -> domain.Image | None:
        if image is None:
            return None
        return domain.Image(self._check_url(image.url), image.width, image.height, image.alt)

    def _product(self, p: ProductIn) -> domain.Product:
        return domain.Product(
            id=p.id,
            name=p.name,
            path=p.path,
            purchase_path=p.purchase_path,
            summary=p.summary,
            age_range=p.age_range,
            format=p.format,
            usage=p.usage,
            pdf_count=p.pdf_count,
            page_count=p.page_count,
            price=domain.Price(
                p.price.amount, p.price.currency, p.price.display, p.price.note, p.price.tax_note
            ),
            resources=tuple(
                domain.Resource(r.id, r.title, r.pages, r.description, self._image(r.image))
                for r in p.resources
            ),
            image=self._image(p.image),
            method=tuple(p.method),
            audience_for=tuple(p.audience_for),
            audience_not_for=tuple(p.audience_not_for),
            age_guidance=tuple(domain.AgeGuidance(g.label, g.hint) for g in p.age_guidance),
        )
