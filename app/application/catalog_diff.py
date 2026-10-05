"""Semantic difference between two catalog documents, for review and provenance.

Works on the parsed domain catalog so formatting changes do not show up as fact changes. A
product missing from the new snapshot is reported as retired: the assistant stops naming it the
moment the new snapshot is active, because every reference is resolved against the active one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.catalog import Catalog


@dataclass(frozen=True, slots=True)
class CatalogDiff:
    products_added: list[str] = field(default_factory=list)
    products_retired: list[str] = field(default_factory=list)
    price_changes: dict[str, tuple[str, str]] = field(default_factory=dict)
    resources_added: list[str] = field(default_factory=list)
    resources_removed: list[str] = field(default_factory=list)
    resources_changed: list[str] = field(default_factory=list)
    documents_added: list[str] = field(default_factory=list)
    documents_removed: list[str] = field(default_factory=list)
    documents_changed: list[str] = field(default_factory=list)
    links_changed: list[str] = field(default_factory=list)
    forbidden_terms_changed: bool = False

    @property
    def empty(self) -> bool:
        return not any(
            (
                self.products_added,
                self.products_retired,
                self.price_changes,
                self.resources_added,
                self.resources_removed,
                self.resources_changed,
                self.documents_added,
                self.documents_removed,
                self.documents_changed,
                self.links_changed,
                self.forbidden_terms_changed,
            )
        )

    def as_dict(self) -> dict[str, object]:
        return {
            'products_added': self.products_added,
            'products_retired': self.products_retired,
            'price_changes': {k: {'before': a, 'after': b} for k, (a, b) in self.price_changes.items()},
            'resources_added': self.resources_added,
            'resources_removed': self.resources_removed,
            'resources_changed': self.resources_changed,
            'documents_added': self.documents_added,
            'documents_removed': self.documents_removed,
            'documents_changed': self.documents_changed,
            'links_changed': self.links_changed,
            'forbidden_terms_changed': self.forbidden_terms_changed,
        }


def diff(before: Catalog | None, after: Catalog) -> CatalogDiff:
    old_products = {p.id: p for p in before.products} if before else {}
    new_products = {p.id: p for p in after.products}
    prices = {
        pid: (
            f'{old_products[pid].price.amount} {old_products[pid].price.currency}',
            f'{p.price.amount} {p.price.currency}',
        )
        for pid, p in new_products.items()
        if pid in old_products
        and (old_products[pid].price.amount, old_products[pid].price.currency)
        != (p.price.amount, p.price.currency)
    }
    old_resources = {
        f'{p.id}/{r.id}': (r.title, r.pages, r.description)
        for p in old_products.values()
        for r in p.resources
    }
    new_resources = {
        f'{p.id}/{r.id}': (r.title, r.pages, r.description)
        for p in new_products.values()
        for r in p.resources
    }
    old_docs = {d.id: (d.title, d.text, d.url) for d in before.documents} if before else {}
    new_docs = {d.id: (d.title, d.text, d.url) for d in after.documents}
    old_links = {link.id: (link.label, link.url) for link in before.links} if before else {}
    new_links = {link.id: (link.label, link.url) for link in after.links}
    return CatalogDiff(
        products_added=sorted(new_products.keys() - old_products.keys()),
        products_retired=sorted(old_products.keys() - new_products.keys()),
        price_changes=prices,
        resources_added=sorted(new_resources.keys() - old_resources.keys()),
        resources_removed=sorted(old_resources.keys() - new_resources.keys()),
        resources_changed=sorted(
            k for k in new_resources.keys() & old_resources.keys() if new_resources[k] != old_resources[k]
        ),
        documents_added=sorted(new_docs.keys() - old_docs.keys()),
        documents_removed=sorted(old_docs.keys() - new_docs.keys()),
        documents_changed=sorted(k for k in new_docs.keys() & old_docs.keys() if new_docs[k] != old_docs[k]),
        links_changed=sorted(
            k for k in new_links.keys() | old_links.keys() if new_links.get(k) != old_links.get(k)
        ),
        forbidden_terms_changed=before is not None
        and set(before.forbidden_terms) != set(after.forbidden_terms),
    )
