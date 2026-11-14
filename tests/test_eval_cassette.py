"""Cassettes at the provider port (PVA-M2.5): keys, replay, and clear failures."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from app.ai.prompt import INSTRUCTIONS, OUTPUT_SCHEMA
from app.ai.provider import ModelInput, ModelRequest, TextChunk, UsageChunk
from app.domain.budget import Usage
from evals.cassette import CassetteError, ReplayProvider, Turn, cassette, request_key
from evals.runner import CASSETTES, DRAFT, _Replay

if TYPE_CHECKING:
    from pathlib import Path

REQUEST = ModelRequest(
    instructions=INSTRUCTIONS,
    inputs=(ModelInput("user", 'visitor_turn:\n{"question": "hola"}'),),
    output_schema=OUTPUT_SCHEMA,
    max_output_tokens=600,
    safety_identifier="session-a",
    cache_key="cache-a",
)
OUTPUT = {"answer": "Hola", "references": [], "sources": [], "follow_ups": []}


def collect(provider: ReplayProvider) -> list[Any]:
    async def run() -> list[Any]:
        return [chunk async for chunk in provider.stream(REQUEST)]

    return asyncio.run(run())


def test_key_ignores_session_identifiers_but_not_content() -> None:
    same = replace(REQUEST, safety_identifier="session-b", cache_key="cache-b")
    assert request_key(same) == request_key(REQUEST)
    assert request_key(replace(REQUEST, instructions=INSTRUCTIONS + " ")) != request_key(REQUEST)
    assert request_key(replace(REQUEST, max_output_tokens=601)) != request_key(REQUEST)


def write(directory: Path, document: dict[str, Any], name: str = "g-x.0.json") -> None:
    (directory / name).write_text(json.dumps(document), encoding="utf-8")


def test_replay_streams_the_output_and_usage(tmp_path: Path) -> None:
    write(tmp_path, cassette(REQUEST, OUTPUT, kind="scripted", model="scripted"))
    provider = ReplayProvider(tmp_path, Turn("g-x", 0))
    chunks = collect(provider)
    text = "".join(c.text for c in chunks if isinstance(c, TextChunk))
    assert json.loads(text) == OUTPUT
    assert isinstance(chunks[-1], UsageChunk)
    assert provider.served == ["g-x.0.json"]


def test_missing_cassette_names_the_fix(tmp_path: Path) -> None:
    with pytest.raises(CassetteError, match=r"no cassette for this model call.*--author"):
        collect(ReplayProvider(tmp_path, Turn("g-x", 0)))


def test_changed_prompt_fails_with_a_re_record_message(tmp_path: Path) -> None:
    document = cassette(REQUEST, OUTPUT, kind="recorded", model="m")
    document |= {"request_sha256": "0" * 64, "prompt_sha256": "f" * 64}
    write(tmp_path, document)
    with pytest.raises(CassetteError, match=r"stale cassette \(prompt changed.*re-record"):
        collect(ReplayProvider(tmp_path, Turn("g-x", 0)))


def test_changed_request_with_the_same_prompt_is_reported_as_such(tmp_path: Path) -> None:
    write(
        tmp_path,
        cassette(REQUEST, OUTPUT, kind="scripted", model="s") | {"request_sha256": "0" * 64},
    )
    with pytest.raises(CassetteError, match="request changed"):
        collect(ReplayProvider(tmp_path, Turn("g-x", 0)))


def test_unsupported_schema_and_drafts_are_refused(tmp_path: Path) -> None:
    write(tmp_path, cassette(REQUEST, OUTPUT, kind="scripted", model="s") | {"schema_version": 9})
    with pytest.raises(CassetteError, match="unsupported cassette schema"):
        collect(ReplayProvider(tmp_path, Turn("g-x", 0)))
    write(tmp_path, cassette(REQUEST, OUTPUT, kind="scripted", model="s", note=f"{DRAFT}: x"))
    provider = _Replay(tmp_path)
    provider.position = Turn("g-x", 0)
    with pytest.raises(CassetteError, match="draft cassette"):
        collect(provider)
    assert provider.errors["g-x"]


def test_committed_cassettes_hold_no_secrets_or_drafts() -> None:
    allowed = {
        "schema_version",
        "kind",
        "model",
        "prompt_version",
        "prompt_sha256",
        "catalog_sha256",
        "request_sha256",
        "note",
        "output",
        "usage",
    }
    paths = sorted(CASSETTES.glob("*.json"))
    assert paths
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert set(document) == allowed, path.name
        assert document["kind"] in {"recorded", "scripted"}
        assert not document["note"].startswith(DRAFT), path.name
        assert set(document["usage"]) <= {"input_tokens", "output_tokens"}


def test_report_bounds_and_strata() -> None:
    from evals.runner import _bound, summarize

    assert _bound(0, 60) == 0.05
    assert _bound(0, 0) is None
    assert _bound(2, 60) > 0.05
    rows = [
        {
            "id": "a",
            "strata": ["answerable", "typo"],
            "locale": "es",
            "split": "dev",
            "passed": True,
            "problems": {},
        },
        {
            "id": "b",
            "strata": ["abstain"],
            "locale": "en",
            "split": "holdout",
            "passed": False,
            "problems": {"x": ["y"]},
        },
    ]
    report = summarize(rows)
    assert report["overall"] == {"items": 2, "passed": 1, "failure_rate_upper_95": 1.0}
    assert report["by_stratum"]["typo"]["items"] == 1
    assert report["failures"] == {"b": {"x": ["y"]}}


def test_recording_provider_writes_a_replayable_recorded_cassette(tmp_path: Path) -> None:
    from evals.cassette import RecordingProvider

    class Fake:
        model = "fake-model"

        async def stream(self, request: ModelRequest):
            yield TextChunk(json.dumps(OUTPUT))
            yield UsageChunk(Usage(input_tokens=10, output_tokens=3))

    recorder = RecordingProvider(Fake(), tmp_path, Turn("g-x", 0))

    async def run() -> list[Any]:
        return [chunk async for chunk in recorder.stream(REQUEST)]

    chunks = asyncio.run(run())
    assert isinstance(chunks[-1], UsageChunk)
    document = json.loads((tmp_path / "g-x.0.json").read_text(encoding="utf-8"))
    assert document["kind"] == "recorded"
    assert document["model"] == "fake-model"
    assert document["usage"] == {"input_tokens": 10, "output_tokens": 3}
    replayed = collect(ReplayProvider(tmp_path, Turn("g-x", 0)))
    assert json.loads("".join(c.text for c in replayed if isinstance(c, TextChunk))) == OUTPUT


def test_replay_fails_on_unused_and_missing_cassettes_and_on_zero_items(tmp_path: Path) -> None:
    import shutil

    from evals import runner, schema

    item = next(i for i in schema.load() if i["id"] == "g-001")
    shutil.copy(CASSETTES / "g-001.0.json", tmp_path / "g-001.0.json")
    report, unused = runner.replay([item], tmp_path)
    assert report["overall"] == {"items": 1, "passed": 1, "failure_rate_upper_95": 1.0}
    assert unused == []
    (tmp_path / "g-001.1.json").write_text("{}", encoding="utf-8")
    assert runner.replay([item], tmp_path)[1] == ["g-001.1.json"]
    (tmp_path / "g-001.1.json").unlink()
    (tmp_path / "g-001.0.json").unlink()
    report, _ = runner.replay([item], tmp_path)
    assert report["overall"]["passed"] == 0
    assert "pipeline.gates" in report["failures"]["g-001"]
