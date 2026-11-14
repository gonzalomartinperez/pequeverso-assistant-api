"""Prompt contract: final-price and catalog-hint boundaries, and the prompt lock (ADR-0017).

No model quality claim.
"""

from datetime import timedelta

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.ai import prompt
from app.application.answers import answer_rules, finalize
from app.application.ports import Draft, DraftReference
from app.domain.catalog import ActiveCatalog, PriceStatus, mentioned_products
from app.domain.conversation import Notice
from scripts import prompt_lock
from tests.support import CATALOG_BYTES


@pytest.mark.parametrize(
    ("text", "replaced"),
    [
        ("No puedo confirmar si cuesta US$19,50; consulta el precio actual en Hotmart.", True),
        ("No puedo confirmar ese importe; consulta el precio actual en Hotmart.", False),
        ("I cannot confirm US$19.50; check the current price on Hotmart.", True),
        ("I cannot confirm that amount; check the current price on Hotmart.", False),
    ],
)
def test_unknown_price_echo_and_non_echo_follow_the_same_existing_final_policy(
    text: str, replaced: bool
) -> None:
    catalog = CatalogParser(
        frozenset({"pequeverso.com", "consumer.hotmart.com", "refund.hotmart.com"})
    )(CATALOG_BYTES)
    active = ActiveCatalog(catalog, "sha", catalog.generated_at, timedelta(hours=168))
    result = finalize(
        Draft(text, (DraftReference("product", "alimentacion-bebe"),), (), ()),
        active,
        PriceStatus.VERIFIED,
        answer_rules(catalog, PriceStatus.VERIFIED, ()),
    )
    assert (Notice.ANSWER_REPLACED in result.details.notices) is replaced
    if not replaced:
        assert result.content.startswith(text)
        assert tuple(product.id for product in result.details.products) == ("alimentacion-bebe",)


@pytest.mark.parametrize(
    "question",
    [
        "Compare the video course with the PDF kit.",
        "No quiero vídeos, prefiero PDF.",
    ],
)
def test_multiple_catalog_hints_keep_comparison_and_negation_available(question: str) -> None:
    catalog = CatalogParser(
        frozenset({"pequeverso.com", "consumer.hotmart.com", "refund.hotmart.com"})
    )(CATALOG_BYTES)
    assert mentioned_products(question, catalog) == frozenset(p.id for p in catalog.products)


# --- Prompt lock (ADR-0017, PVA-M2.13) -------------------------------------------------------


def _lock_case() -> tuple[dict, str]:
    lock = prompt_lock.load()
    changelog = prompt_lock.CHANGELOG.read_text(encoding="utf-8")
    return lock, changelog


def test_committed_prompt_matches_its_lock_entry() -> None:
    lock, changelog = _lock_case()
    assert (
        prompt_lock.problems(lock, prompt.PROMPT_VERSION, prompt.prompt_fingerprint(), changelog)
        == []
    )


def test_changing_instructions_without_a_version_bump_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prompt, "INSTRUCTIONS", prompt.INSTRUCTIONS + "\nNew rule.")
    lock, changelog = _lock_case()
    found = prompt_lock.problems(
        lock, prompt.PROMPT_VERSION, prompt.prompt_fingerprint(), changelog
    )
    assert any("changed but PROMPT_VERSION is still" in item for item in found)


def test_changing_the_output_schema_without_a_version_bump_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = {**prompt.OUTPUT_SCHEMA, "required": ["answer"]}
    monkeypatch.setattr(prompt, "OUTPUT_SCHEMA", schema)
    lock, changelog = _lock_case()
    found = prompt_lock.problems(
        lock, prompt.PROMPT_VERSION, prompt.prompt_fingerprint(), changelog
    )
    assert any("changed but PROMPT_VERSION is still" in item for item in found)


def test_a_bump_needs_a_lock_entry_and_a_changelog_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompt, "INSTRUCTIONS", prompt.INSTRUCTIONS + "\nNew rule.")
    lock, changelog = _lock_case()
    fingerprint = prompt.prompt_fingerprint()
    found = prompt_lock.problems(lock, "2099-01-01.1", fingerprint, changelog)
    assert any("is not the last lock entry" in item for item in found)
    bumped = prompt_lock.append(lock, "2099-01-01.1", fingerprint)
    found = prompt_lock.problems(bumped, "2099-01-01.1", fingerprint, changelog)
    assert found == [
        (
            "docs/reference/prompt-changelog.md has no row starting "
            f"'| 2099-01-01.1 | `{fingerprint['prompt_sha256'][:12]}` |'"
        )
    ]
    row = f"| 2099-01-01.1 | `{fingerprint['prompt_sha256'][:12]}` | test | - | - |\n"
    assert prompt_lock.problems(bumped, "2099-01-01.1", fingerprint, changelog + row) == []


def test_lock_is_append_only() -> None:
    lock, changelog = _lock_case()
    fingerprint = prompt.prompt_fingerprint()
    with pytest.raises(SystemExit, match="already locked"):
        prompt_lock.append(lock, prompt.PROMPT_VERSION, fingerprint)
    entry = lock["versions"][-1]
    reordered = {**lock, "versions": [{**entry, "version": "2099-01-01.1"}, entry]}
    found = prompt_lock.problems(reordered, prompt.PROMPT_VERSION, fingerprint, changelog)
    assert any("increasing order" in item for item in found)
    assert any("share the same prompt_sha256" in item for item in found)


def test_editing_a_locked_version_fails_against_the_base() -> None:
    lock, _ = _lock_case()
    assert prompt_lock.against_base(lock, lock) == []
    appended = prompt_lock.append(lock, "2099-01-01.1", prompt.prompt_fingerprint())
    assert prompt_lock.against_base(appended, lock) == []
    entry = {**lock["versions"][-1], "prompt_sha256": "0" * 64}
    edited = {**lock, "versions": [*lock["versions"][:-1], entry]}
    assert prompt_lock.against_base(edited, lock) == [
        "app/ai/prompt.lock.json: a version locked at the base revision was edited or removed"
    ]
