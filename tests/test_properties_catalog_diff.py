"""Semantic catalog variation detection."""

from dataclasses import replace
from decimal import Decimal

from hypothesis import example, given
from hypothesis import strategies as st

from app.adapters.catalog_schema import CatalogParser
from app.application.catalog_diff import diff
from app.bootstrap.config import Settings
from tests.support import CATALOG_BYTES

BASE = CatalogParser(frozenset(Settings.model_fields["catalog_allowed_hosts"].default))(
    CATALOG_BYTES
)
VARIATIONS = st.tuples(
    st.integers(0, len(BASE.products) - 1),
    st.integers(0, 99_999),
    st.text(alphabet="abc áéñ", max_size=20),
)


def variant(spec):
    index, cents, title = spec
    product = BASE.products[index]
    template = product.price or next(p.price for p in BASE.products if p.price is not None)
    price = replace(template, amount=Decimal(cents) / 100)
    products = list(BASE.products)
    products[index] = replace(product, name=title, price=price)
    return replace(BASE, products=tuple(products))


@given(left=VARIATIONS, right=VARIATIONS, identical=st.booleans())
@example(left=(0, 1499, "Título"), right=(0, 1599, "Título"), identical=False)
@example(left=(1, 0, "Igual"), right=(1, 0, "Igual"), identical=True)
def test_diff_empty_iff_catalogs_equal(left, right, identical):
    """Row 8: price/title variations are detected in either diff direction."""
    a = variant(left)
    b = a if identical else variant(right)
    assert diff(a, b).empty == (a == b)
    assert diff(b, a).empty == (a == b)
