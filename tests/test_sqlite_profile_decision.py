"""ADR-0020: the SQLite fixture profile and the ledger-extension script retire only by a new ADR."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs" / "decisions"
KEPT = (
    "app/adapters/sqlite/database.py",
    "app/adapters/sqlite/stores.py",
    "app/adapters/sqlite/ledger.py",
    "app/adapters/sqlite/operations.py",
    "app/adapters/sqlite/catalog_repository.py",
    "scripts/extend_evaluation_envelope.py",
)


def superseded() -> bool:
    return any(
        "supersedes ADR-0020" in path.read_text(encoding="utf-8")
        for path in DECISIONS.glob("ADR-*.md")
    )


def test_kept_profile_and_script_exist_until_a_superseding_adr() -> None:
    adr = next(DECISIONS.glob("ADR-0020-*.md")).read_text(encoding="utf-8")
    assert "Status: accepted" in adr
    if superseded():
        return
    missing = [path for path in KEPT if not (ROOT / path).is_file()]
    assert missing == [], "retiring these needs an ADR that supersedes ADR-0020"


def test_sqlite_is_the_default_fixture_store() -> None:
    from app.bootstrap.config import Settings

    settings = Settings(_env_file=None)
    assert settings.application_storage == "sqlite"
    assert settings.ai_provider == "fixture"
