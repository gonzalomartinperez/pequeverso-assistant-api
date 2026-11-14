"""Golden-set item schema v2: loading and structural validation (PVA-M2.4).

`docs/master-plan/assistant-quality.md` section 3 defines the schema and the strata. The loader keeps
the corpus checks (unknown keys, catalog passage ids, group-preserving split, group integrity) and adds
the golden rules: answer items carry gold evidence and required facts, abstentions assert their shape,
stratum and locale counts match the plan, and ids never collide with the full set.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.ai.evidence import passages
from evals.graders import GRADERS, behavior_tags
from scripts import evaluate_conversations as conv
from scripts.evaluate_corpus import NOTICES, STALE_AFTER_DAYS, assign_splits

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "evals" / "golden" / "golden.jsonl"
CATALOG_FILE = ROOT / "catalog" / "catalog.v1.json"

SCHEMA_VERSION = 2
KEYS = frozenset(
    {
        "id",
        "schema_version",
        "assistant",
        "group",
        "family",
        "split",
        "locale",
        "page",
        "strata",
        "turns",
        "expected_behavior",
        "response_language",
        "required_facts",
        "forbidden_claims",
        "gold_evidence_ids",
        "assertions",
        "notices",
        "user_notices",
        "judge_rubric_id",
        "provenance",
        "reviewer",
        "created",
        "last_verified",
        "catalog_sha256",
        "clock_offset_days",
        "status",
        "status_reason",
        "owner",
        "deadline",
    }
)
REQUIRED = KEYS - {"judge_rubric_id", "status_reason", "owner", "deadline", "page"}
BEHAVIORS = frozenset({"answer", "clarify", "no_info", "decline", "refuse_payment_data"})
LANGUAGES = frozenset({"es", "en", "unsupported"})
LOCALES = frozenset({"es", "en", "mixed"})
PAGES = frozenset({None, "home", "product", "support"})
PRIMARY = ("answerable", "comparison", "abstain", "adversarial", "multi_turn")
TAGS = frozenset({"typo", "regional", "legacy-client", "english", "scripted-adversary"})
PROVENANCE = frozenset({"corpus", "real-run-2026-10", "scenario", "new"})
STATUSES = frozenset({"active", "quarantined", "retired"})

# assistant-quality.md section 3 (golden set v1).
STRATA_TARGETS = {
    "answerable": 21,
    "comparison": 9,
    "abstain": 15,
    "adversarial": 9,
    "multi_turn": 6,
}
LOCALE_TARGETS = {"es": 55, "en": 3, "mixed": 2}
TAG_TARGETS = {"typo": 8, "regional": 6}
ANSWERABLE_FAMILIES = {
    "product-contents": 3,
    "price-and-currency": 3,
    "refunds-guarantee-withdrawal": 3,
    "age-fit": 2,
    "usage-and-start": 2,
    "printing-and-format": 2,
    "delivery-and-access": 2,
    "commercial-rules": 2,
    "support": 2,
}
SPLIT_FAMILY = "golden"


def catalog_sha256() -> str:
    """Return the sha256 of the bundled catalog snapshot that every item pins."""
    return hashlib.sha256(CATALOG_FILE.read_bytes()).hexdigest()


def load(path: Path = GOLDEN) -> list[dict[str, Any]]:
    """Read one JSON object per non-empty line."""
    items: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise TypeError(f"{path.name}:{number}: an item must be a JSON object")
        items.append(item)
    return items


_ID = re.compile(r"g-\d{3}")
_STRING_LISTS = (
    "strata",
    "turns",
    "required_facts",
    "forbidden_claims",
    "gold_evidence_ids",
    "assertions",
    "notices",
    "user_notices",
)
_STRINGS = ("id", "group", "family", "split", "locale", "expected_behavior", "response_language")


def _type_problems(item: dict[str, Any], iid: str) -> list[str]:
    """Shape errors that would make the semantic checks crash or pass vacuously."""
    out = [
        f"{iid}: {key} must be a list of strings"
        for key in _STRING_LISTS
        if key in item
        and not (isinstance(item[key], list) and all(isinstance(v, str) for v in item[key]))
    ]
    out += [
        f"{iid}: {key} must be a string"
        for key in _STRINGS
        if key in item and not isinstance(item[key], str)
    ]
    if item.get("page") is not None and not isinstance(item.get("page"), str):
        out.append(f"{iid}: page must be a string or null")
    return out


def _item_problems(item: dict[str, Any], known: set[str], catalog_sha: str) -> list[str]:
    iid = str(item.get("id", "?"))
    out: list[str] = _type_problems(item, iid)
    if out:
        return out
    if not _ID.fullmatch(iid):
        out.append(f"{iid}: id must look like g-001")
    if missing := REQUIRED - set(item):
        out.append(f"{iid}: missing keys {sorted(missing)}")
    if extra := set(item) - KEYS:
        out.append(f"{iid}: unknown keys {sorted(extra)}")
    if item.get("schema_version") != SCHEMA_VERSION or item.get("assistant") != "pequeverso":
        out.append(f"{iid}: schema_version must be 2 and assistant pequeverso")
    turns = item.get("turns")
    if (
        not isinstance(turns, list)
        or not turns
        or not all(isinstance(t, str) and t.strip() for t in turns)
    ):
        out.append(f"{iid}: turns must be non-empty strings")
    elif any(len(t) > 600 for t in turns):
        out.append(f"{iid}: a turn exceeds the 600-character API limit")
    strata = item.get("strata", [])
    primary = [s for s in strata if s in PRIMARY]
    if len(primary) != 1 or set(strata) - set(PRIMARY) - TAGS:
        out.append(f"{iid}: strata needs exactly one primary stratum and known tags")
    if ("multi_turn" in strata) != (isinstance(turns, list) and len(turns) > 1):
        out.append(f"{iid}: multi_turn items, and only they, have several turns")
    behavior = item.get("expected_behavior")
    if behavior not in BEHAVIORS:
        out.append(f"{iid}: invalid expected_behavior")
    if item.get("response_language") not in LANGUAGES:
        out.append(f"{iid}: invalid response_language")
    if item.get("locale") not in LOCALES:
        out.append(f"{iid}: invalid locale")
    if item.get("page") not in PAGES:
        out.append(f"{iid}: invalid page")
    gold = item.get("gold_evidence_ids")
    if not isinstance(gold, list):
        out.append(f"{iid}: gold_evidence_ids must be a list (empty is explicit)")
        gold = []
    out += [f"{iid}: gold id {ref!r} is not a catalog passage" for ref in gold if ref not in known]
    facts = item.get("required_facts", [])
    if behavior == "answer" and (not gold or not facts):
        out.append(f"{iid}: an answer item needs gold_evidence_ids and required_facts")
    for fact in facts:
        if not fact.strip() or any(not option.strip() for option in fact.split("|")):
            out.append(f"{iid}: required fact {fact!r} has an empty alternative")
    assertions = item.get("assertions", [])
    if behavior == "answer" and not {"facts.required", "grounding.gold_referenced"} <= set(
        assertions
    ):
        out.append(f"{iid}: answer items assert facts.required and grounding.gold_referenced")
    if behavior == "refuse_payment_data" and "payment_data_refused" not in item.get("notices", []):
        out.append(f"{iid}: refuse_payment_data items expect the payment_data_refused notice")
    if (item.get("locale") == "en") != ("english" in strata):
        out.append(f"{iid}: the english tag marks exactly the items with locale en")
    out += [f"{iid}: unknown grader {a!r}" for a in assertions if a not in GRADERS]
    if behavior in {"clarify", "no_info", "decline"} and "abstain.shape" not in assertions:
        out.append(f"{iid}: {behavior} items assert abstain.shape (support route or question)")
    tags = behavior_tags()
    for claim in item.get("forbidden_claims", []):
        if not (claim.startswith("term:") and claim[5:].strip()) and claim not in tags:
            out.append(f"{iid}: unknown forbidden claim {claim!r}")
    for notice in [*item.get("notices", []), *item.get("user_notices", [])]:
        if notice not in NOTICES:
            out.append(f"{iid}: unknown notice {notice!r}")
    if item.get("provenance") not in PROVENANCE:
        out.append(f"{iid}: invalid provenance")
    if item.get("catalog_sha256") != catalog_sha:
        out.append(f"{iid}: catalog_sha256 does not pin the bundled catalog (re-verify the item)")
    offset = item.get("clock_offset_days")
    if type(offset) is not int or offset < 0:
        out.append(f"{iid}: clock_offset_days must be a non-negative integer")
    elif 0 < offset <= STALE_AFTER_DAYS:
        # The runner decides staleness as offset > 7 days; offsets near the boundary are ambiguous.
        out.append(
            f"{iid}: clock_offset_days must be 0 (fresh) or above {STALE_AFTER_DAYS} (stale)"
        )
    status = item.get("status")
    if status not in STATUSES:
        out.append(f"{iid}: invalid status")
    if status == "quarantined" and not (item.get("owner") and item.get("deadline")):
        out.append(f"{iid}: a quarantined item needs an owner and a deadline")
    if status == "retired" and not item.get("status_reason"):
        out.append(f"{iid}: a retired item needs a status_reason")
    return out


def validate(
    items: list[dict[str, Any]], *, full_set_ids: set[str] | None = None, counts: bool = True
) -> list[str]:
    """Every structural problem of the golden set (empty list when valid)."""
    known = {p.id for p in passages(conv.CATALOG)}
    catalog_sha = catalog_sha256()
    problems: list[str] = []
    ids = Counter(item.get("id") for item in items)
    problems += [f"{iid}: duplicate id" for iid, n in ids.items() if n > 1]
    if full_set_ids:
        problems += [f"{iid}: id collides with the full set" for iid in ids if iid in full_set_ids]
    for item in items:
        problems += _item_problems(item, known, catalog_sha)
    groups: dict[str, set[str]] = {}
    for item in items:
        groups.setdefault(item.get("group", ""), set()).add(item.get("split", ""))
    problems += [f"group {g!r} spans splits" for g, splits in groups.items() if len(splits) > 1]
    expected = assign_splits(SPLIT_FAMILY, [item.get("group", "") for item in items])
    problems += [
        f"{item.get('id')}: split must be {expected[item.get('group', '')]} (group-preserving rule)"
        for item in items
        if item.get("split") != expected.get(item.get("group", ""))
    ]
    if counts:
        problems += count_problems([i for i in items if i.get("status") != "retired"])
    return problems


def count_problems(items: list[dict[str, Any]]) -> list[str]:
    """Stratum, locale, tag and answerable-family counts against the plan."""
    problems: list[str] = []
    primary = Counter(next((s for s in i.get("strata", []) if s in PRIMARY), None) for i in items)
    for name, want in STRATA_TARGETS.items():
        if primary.get(name, 0) != want:
            problems.append(f"stratum {name}: {primary.get(name, 0)} items, plan says {want}")
    locales = Counter(i.get("locale") for i in items)
    for name, want in LOCALE_TARGETS.items():
        if locales.get(name, 0) != want:
            problems.append(f"locale {name}: {locales.get(name, 0)} items, plan says {want}")
    tags = Counter(t for i in items for t in i.get("strata", []) if t in TAG_TARGETS)
    for name, want in TAG_TARGETS.items():
        if tags.get(name, 0) != want:
            problems.append(f"tag {name}: {tags.get(name, 0)} items, plan says {want}")
    families = Counter(i.get("family") for i in items if "answerable" in i.get("strata", []))
    for name, want in ANSWERABLE_FAMILIES.items():
        if families.get(name, 0) != want:
            problems.append(f"answerable {name}: {families.get(name, 0)} items, plan says {want}")
    return problems
