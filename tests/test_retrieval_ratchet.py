"""Retrieval ratchet and committed baseline of the full set (PVA-M2.6)."""

from __future__ import annotations

import json
from collections import Counter

from scripts import evaluate_corpus
from scripts.retrieval_ratchet import BASELINE, RATCHET, check, counts, measure, raised

CASES = evaluate_corpus.load()
RATCHETS = json.loads(RATCHET.read_text(encoding="utf-8"))


def test_retrieval_does_not_drop_below_the_ratchet() -> None:
    assert check(measure(CASES), RATCHETS) == []


def test_a_drop_in_any_group_fails_the_ratchet() -> None:
    measured = measure(CASES)
    family = next(iter(measured["by_family"]))
    worse = json.loads(json.dumps(measured))
    worse["by_family"][family]["recall_at_5"] = RATCHETS["by_family"][family]["recall_at_5"] - 0.05
    worse["by_language"].popitem()
    problems = check(worse, RATCHETS)
    assert any(p.startswith(f"by_family.{family}.recall_at_5") for p in problems)
    assert any("no scored case left" in p for p in problems)


def test_raising_never_lowers_a_value() -> None:
    measured = measure(CASES)
    lower = json.loads(json.dumps(measured))
    lower["overall"]["mrr"] = 0.0
    assert raised(lower, RATCHETS)["overall"]["mrr"] == RATCHETS["overall"]["mrr"]
    assert raised(measured, None)["overall"]["recall_at_5"] == measured["overall"]["recall_at_5"]


def test_the_ratchet_covers_every_scored_family_and_language() -> None:
    scored = [c for c in CASES if c["gold_evidence_ids"]]
    assert set(RATCHETS["by_family"]) == {c["family"] for c in scored}
    assert set(RATCHETS["by_language"]) == {c["locale"] for c in scored}


def test_the_baseline_describes_the_committed_set() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert baseline["catalog_sha256"] == evaluate_corpus.catalog_sha256()
    assert baseline["corpus_version"] == evaluate_corpus.CORPUS_VERSION
    assert baseline["cases"] == counts(CASES)
    assert baseline["cases"]["by_family"] == dict(
        sorted(Counter(c["family"] for c in CASES).items())
    )


def test_every_case_has_gold_or_an_explicit_abstain_reason() -> None:
    assert [
        c["id"] for c in CASES if bool(c["gold_evidence_ids"]) == bool(c.get("abstain_reason"))
    ] == []
    assert {c["locale"] for c in CASES} <= evaluate_corpus.FULL_LOCALES
    # The two mislabelled out-of-scope items of corpus v1 now carry explicit empty qrels.
    by_id = {c["id"]: c for c in CASES}
    assert all(by_id[i]["gold_evidence_ids"] == [] for i in ("oos-009", "oos-012"))
