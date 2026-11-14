"""Injection fixtures keep their shape for the M4 validators (PVA-M2-X)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "injection_passages.json").read_text(encoding="utf-8")
)["fixtures"]
CARRIERS = {"passage", "block"}
ATTACKS = {
    "instruction_override",
    "prompt_extraction",
    "url_exfiltration",
    "price_bait",
    "memory_poisoning",
    "role_hijack",
    "markup_injection",
    "namespace_injection",
}
EXPECTED = {"ignored", "dropped", "discarded"}


def test_fixture_shape() -> None:
    assert len(FIXTURES) >= 8
    assert len({f["id"] for f in FIXTURES}) == len(FIXTURES)
    for fixture in FIXTURES:
        assert set(fixture) == {"id", "carrier", "attack", "expected", "text"}
        assert re.fullmatch(r"inj-\d{3}", fixture["id"])
        assert fixture["carrier"] in CARRIERS
        assert fixture["attack"] in ATTACKS
        assert fixture["expected"] in EXPECTED
        assert 20 <= len(fixture["text"]) <= 600


def test_every_attack_class_and_carrier_is_covered() -> None:
    assert {f["attack"] for f in FIXTURES} == ATTACKS
    assert {f["carrier"] for f in FIXTURES} == CARRIERS


def test_fixtures_hold_no_real_contact_data() -> None:
    blob = json.dumps(FIXTURES)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", blob)
    assert not re.search(r"\+?\d[\d\s-]{8,}\d", blob)
    hosts = {
        urlsplit(url).hostname
        for f in FIXTURES
        for url in re.findall(r"https?://[^\s\"'<>)]+", f["text"])
    }
    assert hosts <= {"evil.example.net"}, hosts  # only the reserved example domain
