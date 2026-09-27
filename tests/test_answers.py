from datetime import timedelta

from app.adapters.catalog_schema import CatalogParser
from app.application.answers import REPLACEMENT_ANSWER, answer_rules, finalize
from app.application.ports import Draft, DraftReference
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import Notice
from tests.support import CATALOG_BYTES

CATALOG = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
    CATALOG_BYTES
)
ACTIVE = ActiveCatalog(CATALOG, 'sha', CATALOG.generated_at, timedelta(hours=168))


def _finalize(draft: Draft, status: PriceStatus = PriceStatus.VERIFIED):  # type: ignore[no-untyped-def]
    return finalize(draft, ACTIVE, status, answer_rules(CATALOG, status, ()))


def test_invented_ids_are_dropped_and_real_ones_get_catalog_metadata() -> None:
    draft = Draft(
        answer='Te recomiendo el kit y dos bonos.',
        references=(
            DraftReference('product', 'grafismo-fonetico'),
            DraftReference('product', 'kit-inventado'),
            DraftReference('resource', 'grafismo-fonetico/juega'),
            DraftReference('resource', 'grafismo-fonetico/no-existe'),
            DraftReference('link', 'support'),
            DraftReference('link', 'javascript:alert(1)'),
            DraftReference('video', 'x'),
        ),
        sources=('faq.grafismo-fonetico.05', 'faq.inventada'),
        follow_ups=('¿Qué incluye?', 'Visita https://evil.example', '¿Qué incluye?'),
    )
    final = _finalize(draft)
    assert final.content == 'Te recomiendo el kit y dos bonos.'
    (product,) = final.details.products
    assert product.url == 'https://pequeverso.com/grafismo-fonetico/'
    assert product.purchase_url == 'https://pequeverso.com/grafismo-fonetico/#comprar'
    assert product.price is not None and product.price.display == 'US$14,99'
    assert product.image is not None and product.image.url.startswith('https://pequeverso.com/media/')
    assert [r.id for r in final.details.resources] == ['grafismo-fonetico/juega']
    assert [link.id for link in final.details.links] == ['support']
    assert [s.id for s in final.details.sources] == ['faq.grafismo-fonetico.05']
    assert final.details.follow_ups == ('¿Qué incluye?',)
    assert final.dropped_references == 5


def test_unverified_price_is_withheld_from_product_metadata() -> None:
    final = _finalize(
        Draft('El kit.', (DraftReference('product', 'grafismo-fonetico'),), (), ()), PriceStatus.UNVERIFIED
    )
    assert final.details.products[0].price is None


def test_rule_breaking_answer_is_replaced_whole() -> None:
    for answer in ('Usa el cupón PEQUE50.', 'Cuesta US$5.', 'Mejor lleva también Imprime y Juega.', ''):
        final = _finalize(Draft(answer, (DraftReference('product', 'grafismo-fonetico'),), (), ('¿Y?',)))
        assert final.content == REPLACEMENT_ANSWER
        assert final.details.notices == (Notice.ANSWER_REPLACED,)
        assert final.details.products == ()
        assert final.details.follow_ups == ()
        assert [link.id for link in final.details.links] == ['support']
