"""Golden-set runner: the real HTTP/SSE path with cassettes at the provider port (PVA-M2.5).

    uv run python -m evals.runner golden --replay           # PR gate: no network, 100% required
    uv run python -m evals.runner golden --author [--rekey]  # write cassettes for new model calls

Replay runs the application path (session, CSRF, SSE, evidence packing, `finalize`, persistence)
with `ReplayProvider`, grades every item with `evals.graders` and prints a JSON report on stdout
(application logs go to stderr). Any failing item, missing or stale cassette makes the exit code 1.
Authoring writes a cassette skeleton for each model call that has none: a fixture-provider draft
marked `DRAFT`, which replay refuses until a person replaces the output and removes the marker.
`--rekey` also re-keys existing scripted cassettes after a reviewed prompt or catalog change.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.adapters.providers.fixture_provider import FixtureProvider
from app.bootstrap.container import create_app
from app.domain.catalog import PriceStatus
from evals import graders, schema
from evals.cassette import CaptureProvider, CassetteError, ReplayProvider, Turn
from scripts import evaluate_conversations as conv
from scripts.evaluate_corpus import STALE_AFTER_DAYS, settings_for_eval

ROOT = Path(__file__).resolve().parents[1]
CASSETTES = ROOT / "evals" / "golden" / "cassettes"
DRAFT = "DRAFT"


class GoldenClock:
    """Deterministic clock: the catalog export time plus the item's offset (never wall time).

    The corpus clock (`max(now, generated_at) + offset`) makes a bundled snapshot stale a week after
    its export, so the same item would send different requests (prices dropped) depending on the
    day it runs, and cassettes would go stale by themselves.
    """

    def __init__(self, offset_days: int) -> None:
        self._now = conv.CATALOG.generated_at + timedelta(days=offset_days, hours=1)

    def now(self) -> datetime:
        """Return the pinned time."""
        return self._now


def _ask(
    client: TestClient, csrf: str, item: dict[str, Any], content: str, n: int
) -> tuple[list[dict[str, Any]], str | None]:
    headers = {**conv.HEADERS, "X-CSRF-Token": csrf, "Idempotency-Key": f"golden-{n:08d}"}
    body: dict[str, Any] = {"content": content, "page": item.get("page") or "product"}
    if "legacy-client" not in item["strata"]:
        body["response_language"] = "es"  # the native storefront assistant (v1 revision 1.4)
    with client.stream("POST", "/api/v1/messages", headers=headers, json=body) as response:
        text = "".join(response.iter_text())
    if response.status_code != 200:
        return [], f"request refused: HTTP {response.status_code} {text[:120]}"
    return conv._events(text), None


def run_items(
    items: list[dict[str, Any]], provider: ReplayProvider | CaptureProvider
) -> list[dict[str, Any]]:
    """Run each item in a fresh session and grade the final message."""
    by_clock: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_clock[int(item["clock_offset_days"])].append(item)
    results: list[dict[str, Any]] = []
    counter = 0
    for offset, members in sorted(by_clock.items()):
        stale = offset > STALE_AFTER_DAYS
        status = PriceStatus.UNVERIFIED if stale else PriceStatus.VERIFIED
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for_eval().model_copy(
                update={"database_path": f"{tmp}/golden.sqlite3"}
            )
            app = create_app(settings, provider=provider, clock=GoldenClock(offset))
            with TestClient(app, base_url="http://localhost:8000") as client:
                for item in members:
                    client.cookies.clear()
                    csrf = client.post("/api/v1/session", headers=conv.HEADERS, json={}).json()[
                        "csrf_token"
                    ]
                    gates: list[str] = []
                    final: dict[str, Any] | None = None
                    user_notices: set[str] = set()
                    for turn_index, turn in enumerate(item["turns"]):
                        counter += 1
                        provider.position = Turn(item["id"], turn_index)
                        events, error = _ask(client, csrf, item, turn, counter)
                        if error:
                            gates.append(error)
                            continue
                        gates += conv._safety(events, status)
                        started = next((e for e in events if e["type"] == "run.started"), None)
                        if started and started.get("user_message"):
                            user_notices = set(started["user_message"]["notices"])
                        completed = [e for e in events if e["type"] == "message.completed"]
                        final = completed[0]["message"] if completed else None
                    errors = getattr(provider, "errors", {}).pop(item["id"], [])
                    context = graders.GradeContext(
                        item=item,
                        final=final,
                        stale=stale,
                        user_notices=frozenset(user_notices),
                        gates=(*errors, *gates),
                    )
                    problems = graders.grade(context)
                    results.append(
                        {
                            "id": item["id"],
                            "strata": item["strata"],
                            "locale": item["locale"],
                            "split": item["split"],
                            "passed": not problems,
                            "problems": problems,
                        }
                    )
    return results


def _bound(failures: int, n: int) -> float | None:
    """Return the 95% upper bound of the failure rate (rule of three when nothing failed)."""
    if n == 0:
        return None
    return (
        round(3 / n, 3)
        if failures == 0
        else round(min(1.0, (failures + 1.96 * math.sqrt(failures)) / n), 3)
    )


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Count passes per stratum, tag, locale and split, with the failure-rate bound."""

    def block(rows: list[dict[str, Any]]) -> dict[str, Any]:
        failed = sum(not r["passed"] for r in rows)
        return {
            "items": len(rows),
            "passed": len(rows) - failed,
            "failure_rate_upper_95": _bound(failed, len(rows)),
        }

    tags = sorted({t for r in results for t in r["strata"]})
    return {
        "overall": block(results),
        "by_stratum": {t: block([r for r in results if t in r["strata"]]) for t in tags},
        "by_locale": {
            lo: block([r for r in results if r["locale"] == lo])
            for lo in sorted({r["locale"] for r in results})
        },
        "by_split": {s: block([r for r in results if r["split"] == s]) for s in ("dev", "holdout")},
        "failures": {r["id"]: r["problems"] for r in results if not r["passed"]},
    }


class _Replay(ReplayProvider):
    """Replay that records cassette errors per item and refuses unreviewed drafts."""

    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        self.errors: dict[str, list[str]] = defaultdict(list)

    def load(self, request: Any) -> dict[str, Any]:  # noqa: ANN401 - ModelRequest passthrough
        try:
            cassette = super().load(request)
        except CassetteError as error:
            self.errors[self.position.item_id].append(str(error))
            raise
        if str(cassette.get("note", "")).startswith(DRAFT):
            message = (
                f"{self.position.name}: draft cassette; author the output, drop the DRAFT note"
            )
            self.errors[self.position.item_id].append(message)
            raise CassetteError(message)
        return cassette


def replay(
    items: list[dict[str, Any]], directory: Path = CASSETTES
) -> tuple[dict[str, Any], list[str]]:
    """Run the golden set in replay; return the report and unused cassette files."""
    provider = _Replay(directory)
    results = run_items(items, provider)
    report = {
        "lane": "golden-replay",
        "prompt_sha256": graders_prompt_sha(),
        "catalog_sha256": schema.catalog_sha256(),
        **summarize(results),
        "cassettes_served": len(provider.served),
    }
    unused = sorted({p.name for p in directory.glob("*.json")} - set(provider.served))
    return report, unused


def graders_prompt_sha() -> str:
    """Return the pinned prompt hash the run used."""
    from app.ai.prompt import prompt_fingerprint

    return prompt_fingerprint()["prompt_sha256"]


def author(
    items: list[dict[str, Any]], directory: Path = CASSETTES, *, rekey: bool = False
) -> list[str]:
    """Write cassettes for model calls that have none (drafts), or re-key scripted ones."""
    provider = CaptureProvider(FixtureProvider(), directory)
    run_items(items, provider)
    directory.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, document in sorted(provider.captured.items()):
        path = directory / name
        if path.is_file():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if (
                existing["request_sha256"] == document["request_sha256"]
                or not rekey
                or existing["kind"] != "scripted"
            ):
                continue
            document = {**document, "note": existing.get("note", "")}
        else:
            document = {
                **document,
                "note": f"{DRAFT}: fixture draft, replace the output and this note",
            }
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(name)
    return written


def main(argv: list[str] | None = None) -> int:
    """Command line entry point."""
    parser = argparse.ArgumentParser(
        description="Golden-set runner (cassette replay or authoring)."
    )
    parser.add_argument("set", choices=["golden"])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replay", action="store_true", help="grade with cassettes, no network")
    mode.add_argument(
        "--author", action="store_true", help="write cassette drafts for new model calls"
    )
    parser.add_argument(
        "--rekey", action="store_true", help="with --author: re-key scripted cassettes"
    )
    parser.add_argument("--only", nargs="*", help="item ids to run (default: all active items)")
    args = parser.parse_args(argv)
    items = [
        i
        for i in schema.load()
        if i["status"] == "active" and (not args.only or i["id"] in args.only)
    ]
    if problems := schema.validate(schema.load()):
        print("\n".join(problems), file=sys.stderr)
        return 1
    with contextlib.redirect_stdout(sys.stderr):
        if args.author:
            written = author(items, rekey=args.rekey)
        else:
            report, unused = replay(items)
    if args.author:
        print(json.dumps({"written": written}, indent=2))
        return 0
    report["unused_cassettes"] = unused
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["overall"]["passed"] == report["overall"]["items"] and not unused else 1


if __name__ == "__main__":
    raise SystemExit(main())
