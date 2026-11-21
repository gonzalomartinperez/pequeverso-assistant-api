"""Env schema (ecosystem 8.5, PVA-M3.3): generated from Settings and consistent with .env.example."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.bootstrap.config import Settings
from app.bootstrap.env_schema import PRODUCTION_REQUIRED, env_schema

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_NAMES = set(
    re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (ROOT / ".env.example").read_text(), re.MULTILINE)
)
# Synthetic, obviously fake values; nothing here is a real credential.
PRODUCTION: dict[str, Any] = {
    "ENVIRONMENT": "production",
    "AI_PROVIDER": "openai",
    "ALLOW_PAID_AI": True,
    "OPENAI_API_KEY": "sk-test-not-a-real-key",
    "ALLOWED_ORIGINS": ["https://pequeverso.com"],
    "SESSION_COOKIE_SECURE": True,
    "CLIENT_HASH_KEY": "x" * 40,
    "APPLICATION_STORAGE": "postgres",
    "KNOWLEDGE_BACKEND": "graphrag",
    "POSTGRES_PRIVATE_DSN": "postgresql://app:fake@postgres:5432/assistant",
    "POSTGRES_KNOWLEDGE_DSN": "postgresql://reader:fake@postgres:5432/assistant",
    "NEO4J_URI": "bolt://neo4j:7687",
    "NEO4J_PASSWORD": "fake-password",
}


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def _settings(values: dict[str, Any]) -> Settings:
    return Settings(_env_file=None, **{k.lower(): v for k, v in values.items()})


def _variables() -> dict[str, dict[str, Any]]:
    return {v["name"]: v for v in env_schema()["variables"]}


def test_schema_lists_every_setting_with_flags_and_no_values() -> None:
    variables = _variables()
    assert set(variables) == {name.upper() for name in Settings.model_fields}
    for entry in variables.values():
        assert set(entry) == {"name", "secret", "required_in_production"}
    secrets = {n for n, v in variables.items() if v["secret"]}
    assert {"OPENAI_API_KEY", "CLIENT_HASH_KEY", "NEO4J_PASSWORD", "OPS_READ_TOKEN"} <= secrets
    assert "ENVIRONMENT" not in secrets
    assert {n for n, v in variables.items() if v["required_in_production"]} == PRODUCTION_REQUIRED


def test_published_file_matches_the_generator() -> None:
    published = json.loads((ROOT / "contracts" / "env.schema.json").read_text())
    assert published == env_schema()


def test_env_example_names_only_real_settings_and_documents_required_and_secrets() -> None:
    variables = _variables()
    assert set(variables) >= EXAMPLE_NAMES, sorted(EXAMPLE_NAMES - set(variables))
    must_document = {n for n, v in variables.items() if v["secret"] or v["required_in_production"]}
    assert must_document <= EXAMPLE_NAMES, sorted(must_document - EXAMPLE_NAMES)


def test_production_example_is_valid() -> None:
    assert _settings(PRODUCTION).environment == "production"


@pytest.mark.parametrize("name", sorted(PRODUCTION_REQUIRED - {"ENVIRONMENT"}))
def test_each_production_requirement_is_enforced(name: str) -> None:
    values = {k: v for k, v in PRODUCTION.items() if k != name}
    with pytest.raises(ValidationError):
        _settings(values)


def test_environment_selects_production_explicitly() -> None:
    assert Settings.model_fields["environment"].default != "production"
