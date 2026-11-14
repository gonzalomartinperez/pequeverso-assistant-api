"""Record and replay at the provider port (PVA-M2.5, ADR-0010).

A cassette pins one model call: the request key (sha256 of the instructions, inputs, output schema
and token cap; never the per-session safety identifier or cache key), the prompt version and sha,
the catalog sha, the model, the structured output and the usage. Two kinds exist: `recorded` (a
real, owner-authorized model run) and `scripted` (a hand-authored model output, including
deliberately misbehaving ones that prove the server-side guards). Replay never falls back to the
fixture provider: a missing or stale cassette fails the item with a re-record message.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from app.ai.prompt import PROMPT_VERSION, prompt_fingerprint
from app.ai.provider import ModelChunk, ModelProvider, ModelRequest, TextChunk, UsageChunk
from app.domain.budget import Usage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

SCHEMA_VERSION = 1
CHUNK_CHARS = 32
Kind = Literal["recorded", "scripted"]


def request_key(request: ModelRequest) -> str:
    """Hash the parts of a request that determine the model's answer."""
    payload = {
        "instructions": request.instructions,
        "inputs": [[item.role, item.text] for item in request.inputs],
        "output_schema": request.output_schema,
        "max_output_tokens": request.max_output_tokens,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class CassetteError(LookupError):
    """A replay could not be served: the cassette is missing, stale or malformed."""


@dataclass
class Turn:
    """Where the runner is: the cassette file name for the next model call."""

    item_id: str = ""
    turn: int = 0

    @property
    def name(self) -> str:
        """Return the cassette file name for this item and turn."""
        return f"{self.item_id}.{self.turn}.json"


@dataclass
class ReplayProvider:
    """Serve recorded or scripted outputs by request key; never touch the network."""

    directory: Path
    position: Turn = field(default_factory=Turn)
    served: list[str] = field(default_factory=list)

    @property
    def model(self) -> str:
        """Return the provider name reported in run metrics."""
        return "cassette-replay"

    def load(self, request: ModelRequest) -> dict[str, Any]:
        """Return the cassette for the current turn, or raise with a re-record message."""
        path = self.directory / self.position.name
        key = request_key(request)
        if not path.is_file():
            raise CassetteError(
                f"{path.name}: no cassette for this model call (key {key[:12]}); author a scripted "
                "cassette with `python -m evals.runner golden --author` or record one in an "
                "owner-authorized live run"
            )
        cassette: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if cassette.get("schema_version") != SCHEMA_VERSION:
            raise CassetteError(f"{path.name}: unsupported cassette schema")
        if cassette["request_sha256"] != key:
            stale = (
                "prompt changed"
                if cassette["prompt_sha256"] != prompt_fingerprint()["prompt_sha256"]
                else "request changed"
            )
            raise CassetteError(
                f"{path.name}: stale cassette ({stale}: recorded key {cassette['request_sha256'][:12]}, "
                f"request key {key[:12]}); re-record it (recorded) or re-author it (scripted) and "
                "review the output against the new request"
            )
        return cassette

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        """Replay the cassette output in chunks, then its usage."""
        cassette = self.load(request)
        self.served.append(self.position.name)
        text = json.dumps(cassette["output"], ensure_ascii=False)
        for start in range(0, len(text), CHUNK_CHARS):
            yield TextChunk(text[start : start + CHUNK_CHARS])
        yield UsageChunk(Usage(**cassette["usage"]))


@dataclass
class CaptureProvider:
    """Authoring aid: serve a draft (or an existing scripted output) and keep the request key."""

    inner: ModelProvider
    directory: Path
    position: Turn = field(default_factory=Turn)
    captured: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def model(self) -> str:
        """Return the provider name reported in run metrics."""
        return "cassette-capture"

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        """Serve the existing scripted output when present, else the inner draft; record the key."""
        path = self.directory / self.position.name
        existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        if existing is not None and existing.get("kind") == "scripted":
            output = existing["output"]
        else:
            text = ""
            async for chunk in self.inner.stream(request):
                if isinstance(chunk, TextChunk):
                    text += chunk.text
            output = json.loads(text)
        self.captured[self.position.name] = cassette(
            request,
            output,
            kind="scripted",
            model="scripted",
            note=(existing or {}).get("note", ""),
        )
        body = json.dumps(output, ensure_ascii=False)
        yield TextChunk(body)
        yield UsageChunk(_usage(request, body))


def _usage(request: ModelRequest, body: str) -> Usage:
    return Usage(input_tokens=request.size_bytes() // 4, output_tokens=max(1, len(body) // 4))


def cassette(
    request: ModelRequest, output: dict[str, Any], *, kind: Kind, model: str, note: str = ""
) -> dict[str, Any]:
    """Build a cassette document for one model call (no keys, headers or private ids)."""
    from evals.schema import catalog_sha256  # local import: schema imports graders

    body = json.dumps(output, ensure_ascii=False)
    usage = _usage(request, body)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_fingerprint()["prompt_sha256"],
        "catalog_sha256": catalog_sha256(),
        "request_sha256": request_key(request),
        "note": note,
        "output": output,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
    }


@dataclass
class RecordingProvider:
    """Wrap a real provider during an owner-authorized live run and write `recorded` cassettes.

    Never used in CI (no network there). It stores only the structured output, the usage, the
    model name and the pins: no keys, headers, safety identifiers or private ids.
    """

    inner: ModelProvider
    directory: Path
    position: Turn = field(default_factory=Turn)
    written: list[str] = field(default_factory=list)

    @property
    def model(self) -> str:
        """Return the wrapped provider's model name."""
        return self.inner.model

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        """Pass every chunk through and write the cassette once the stream completes."""
        text = ""
        usage: Usage | None = None
        async for chunk in self.inner.stream(request):
            if isinstance(chunk, TextChunk):
                text += chunk.text
            else:
                usage = chunk.usage
            yield chunk
        document = cassette(request, json.loads(text), kind="recorded", model=self.inner.model)
        if usage is not None:
            document["usage"] = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            }
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / self.position.name
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.written.append(path.name)
