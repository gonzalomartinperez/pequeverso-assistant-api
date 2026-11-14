"""Exercise real fixture HTTP/SSE sockets with concurrent virtual visitors.

All latencies are seconds; rates use message attempts (including rejections) as
denominator. Session setup failures also count as errors and attempts. In-flight
messages drain after the admission deadline, so the final close is measured.
"""

from __future__ import annotations

import argparse
import asyncio
import codecs
import io
import json
import math
import random
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator

TTFE_P95_LIMIT = 1.5
GAP_P95_LIMIT = 0.5
# Generous: an overloaded CI or developer host can take tens of seconds to import and bind.
READY_TIMEOUT_SECONDS = 60
ERROR_RATE_LIMIT = 0.005
PREMATURE_CLOSE_RATE_LIMIT = 0.005
RSS_GROWTH_LIMIT_PERCENT = 20.0
RSS_MIN_DURATION = 600
RSS_SAMPLE_SECONDS = 10
ROOT = Path(__file__).resolve().parents[2]
HEADERS = {"Origin": "http://localhost:3000", "Content-Type": "application/json"}
TERMINAL = frozenset({"run.completed", "run.failed", "run.cancelled"})
QUESTIONS = (
    "¿Qué incluye Grafismo Fonético?",
    "¿Para qué edades es Grafismo Fonético?",
    "¿Cómo puedo usar el kit de Grafismo Fonético?",
    "¿En qué formato recibo Grafismo Fonético?",
)
SERVER = """
import sys
import uvicorn
from app.bootstrap.config import Settings
from app.bootstrap.container import create_app
settings = Settings(
    _env_file=None, environment='test', ai_provider='fixture', allow_paid_ai=False,
    database_path=sys.argv[1], messages_per_session_per_day=1000000000,
    messages_per_client_per_hour=1000000000, sessions_per_client_per_hour=1000000000,
    price_input_per_million='0', price_cached_input_per_million='0',
    price_cache_write_per_million='0', price_output_per_million='0',
)
uvicorn.run(create_app(settings), host='127.0.0.1', port=int(sys.argv[2]),
            log_config=None, access_log=False, timeout_graceful_shutdown=5)
"""


class SSEParser:
    """Incrementally decode UTF-8 SSE data frames, excluding comment heartbeats.

    An unterminated final frame is deliberately not dispatched (SSE semantics).
    The newline decoder handles CR, LF and CRLF even across byte boundaries.
    """

    def __init__(self):
        self.decoder = io.IncrementalNewlineDecoder(codecs.getincrementaldecoder("utf-8")(), True)
        self.buffer = ""
        self.data: list[str] = []

    def feed(self, chunk: bytes, *, final: bool = False) -> list[dict[str, object]]:
        self.buffer += self.decoder.decode(chunk, final=final)
        lines = self.buffer.split("\n")
        self.buffer = lines.pop()
        events = []
        for line in lines:
            if not line:
                if self.data:
                    event = json.loads("\n".join(self.data))
                    self.data.clear()
                    if not isinstance(event, dict):
                        raise ValueError("SSE data must be a JSON object")
                    events.append(event)
            elif line.startswith("data:"):
                self.data.append(line[5:].removeprefix(" "))
        return events


async def iter_sse(chunks: AsyncIterable[bytes]) -> AsyncIterator[dict[str, object]]:
    parser = SSEParser()
    async for chunk in chunks:
        for event in parser.feed(chunk):
            yield event
    for event in parser.feed(b"", final=True):
        yield event


def percentile(values: list[float], percent: float) -> float | None:
    """Linear interpolation on sorted samples, with inclusive endpoints."""
    if not 0 <= percent <= 100:
        raise ValueError("percentile must be between 0 and 100")
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percent / 100
    lower = math.floor(index)
    upper = math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "samples": len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": max(values, default=None),
    }


def event_timings(started: float, timestamps: list[float]) -> tuple[float | None, list[float]]:
    """Calculate first-event latency and consecutive gaps from monotonic observations."""
    if not timestamps:
        return None, []
    return timestamps[0] - started, [right - left for left, right in pairwise(timestamps)]


def rss_kib(status: str) -> int | None:
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return None


def rss_growth(samples: list[int]) -> float | None:
    if len(samples) < 2 or samples[0] <= 0:
        return None
    return (samples[-1] - samples[0]) / samples[0] * 100


@dataclass
class Measurement:
    status: int | None = None
    ttfe: float | None = None
    gaps: list[float] = field(default_factory=list)
    terminal: str | None = None
    code: str | None = None
    transport_error: bool = False

    @property
    def rejected(self) -> bool:
        # middleware.STATUS/RETRY_AFTER document 429 and HTTP 503 busy backpressure;
        # domain.errors.RETRYABLE and events.FailureCodeOut also permit streamed busy.
        return self.status == 429 or (
            self.code == "busy"
            and (self.status == 503 or (self.status == 200 and self.terminal == "run.failed"))
        )

    @property
    def premature(self) -> bool:
        return self.status == 200 and self.terminal is None

    @property
    def error(self) -> bool:
        if self.rejected:
            return False
        return self.transport_error or self.status != 200 or self.terminal != "run.completed"


def evaluate_thresholds(report: dict, duration: float) -> dict[str, bool | None]:
    ttfe = report["ttfe_seconds"]["p95"]
    gap = report["gap_seconds"]["p95"]
    growth = report["rss"]["growth_percent"]
    return {
        "observations": report["counts"]["completed"] > 0,
        "ttfe_p95": ttfe is not None and ttfe < TTFE_P95_LIMIT,
        "gap_p95": gap is not None and gap < GAP_P95_LIMIT,
        "error_rate": report["error_rate"] < ERROR_RATE_LIMIT,
        "premature_close_rate": report["premature_close_rate"] < PREMATURE_CLOSE_RATE_LIMIT,
        "rss_growth": (growth is not None and growth < RSS_GROWTH_LIMIT_PERCENT)
        if duration >= RSS_MIN_DURATION
        else None,
    }


def build_report(
    measurements: list[Measurement],
    samples: list[int],
    duration: float,
    streams: int,
    *,
    session_errors: int = 0,
) -> dict:
    attempts = len(measurements) + session_errors
    errors = sum(m.error for m in measurements) + session_errors
    report = {
        "provider": "fixture",
        "duration_seconds": duration,
        "streams": streams,
        "max_concurrent_runs": 4,
        "fixture_token_prices": 0,
        "counts": {
            "messages": len(measurements),
            "attempts": attempts,
            "completed": sum(m.terminal == "run.completed" for m in measurements),
            "errors": errors,
            "premature_closes": sum(m.premature for m in measurements),
            "rejected": sum(m.rejected for m in measurements),
            "session_errors": session_errors,
            "http_status": dict(Counter(str(m.status) for m in measurements)),
            "terminal_events": dict(Counter(m.terminal for m in measurements if m.terminal)),
            "failure_codes": dict(Counter(m.code for m in measurements if m.code)),
        },
        "ttfe_seconds": distribution([m.ttfe for m in measurements if m.ttfe is not None]),
        "gap_seconds": distribution([gap for m in measurements for gap in m.gaps]),
        "error_rate": errors / attempts if attempts else 0,
        "premature_close_rate": sum(m.premature for m in measurements) / attempts
        if attempts
        else 0,
        "rejected_rate": sum(m.rejected for m in measurements) / attempts if attempts else 0,
        "rss": {
            "samples": len(samples),
            "first_kib": samples[0] if samples else None,
            "last_kib": samples[-1] if samples else None,
            "growth_percent": rss_growth(samples),
            "asserted": duration >= RSS_MIN_DURATION,
        },
        "thresholds": {
            "ttfe_p95_seconds_lt": TTFE_P95_LIMIT,
            "gap_p95_seconds_lt": GAP_P95_LIMIT,
            "error_rate_lt": ERROR_RATE_LIMIT,
            "premature_close_rate_lt": PREMATURE_CLOSE_RATE_LIMIT,
            "rss_growth_percent_lt": RSS_GROWTH_LIMIT_PERCENT,
            "rss_min_duration_seconds": RSS_MIN_DURATION,
        },
    }
    report["checks"] = evaluate_thresholds(report, duration)
    report["passed"] = all(value is not False for value in report["checks"].values())
    return report


async def measure_message(http: httpx.AsyncClient, csrf: str, question: str) -> Measurement:
    result = Measurement()
    started = time.monotonic()
    timestamps: list[float] = []
    try:
        async with http.stream(
            "POST",
            "/api/v1/messages",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": uuid4().hex},
            json={"content": question, "response_language": "es"},
        ) as response:
            result.status = response.status_code
            if response.status_code != 200:
                payload = json.loads(await response.aread())
                result.code = payload.get("error", {}).get("code")
                return result
            async for event in iter_sse(response.aiter_bytes()):
                timestamps.append(time.monotonic())
                if event.get("type") in TERMINAL:
                    result.terminal = str(event["type"])
                    result.code = event.get("code")
    except httpx.HTTPError, ValueError:
        result.transport_error = True
    result.ttfe, result.gaps = event_timings(started, timestamps)
    return result


async def visitor(url: str, deadline: float, index: int, measurements: list[Measurement]) -> int:
    rng = random.Random(index)
    async with httpx.AsyncClient(
        base_url=url,
        headers=HEADERS,
        timeout=90,
        trust_env=False,
    ) as http:
        try:
            response = await http.post("/api/v1/session", json={})
            response.raise_for_status()
            csrf = response.json()["csrf_token"]
        except httpx.HTTPError, ValueError, KeyError:
            return 1
        while time.monotonic() < deadline:
            result = await measure_message(http, csrf, rng.choice(QUESTIONS))
            measurements.append(result)
            # Avoid a tight refusal loop while keeping all visitors active.
            if result.rejected:
                await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))
    return 0


def sample_rss(pid: int, samples: list[int]) -> None:
    try:
        value = rss_kib(Path(f"/proc/{pid}/status").read_text())
    except OSError:
        return
    if value is not None:
        samples.append(value)


async def monitor_rss(pid: int, samples: list[int], stopped: asyncio.Event) -> None:
    sample_rss(pid, samples)
    while not stopped.is_set():
        try:
            await asyncio.wait_for(stopped.wait(), timeout=RSS_SAMPLE_SECONDS)
        except TimeoutError:
            sample_rss(pid, samples)
    sample_rss(pid, samples)


async def wait_ready(process: subprocess.Popen, url: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    async with httpx.AsyncClient(timeout=0.5, trust_env=False) as http:
        while time.monotonic() < deadline and process.poll() is None:
            try:
                if (await http.get(f"{url}/health/ready")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.02)
    raise RuntimeError("fixture subprocess did not become ready")


def stop_server(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def start_server(folder: Path, port: int, log) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 - fixed fixture program and isolated paths
        [sys.executable, "-c", SERVER, str(folder / "assistant.sqlite3"), str(port)],
        cwd=ROOT,
        env={
            "PATH": str(Path(sys.executable).parent),
            "AI_PROVIDER": "fixture",
            "ALLOW_PAID_AI": "false",
        },
        stdout=log,
        stderr=subprocess.STDOUT,
    )


async def run_load(streams: int, duration: float) -> dict:
    with tempfile.TemporaryDirectory(prefix="pva-sse-load-") as directory:
        folder = Path(directory)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        with (folder / "server.log").open("wb") as log:
            process = start_server(folder, port, log)
            try:
                await wait_ready(process, url)
                measurements: list[Measurement] = []
                samples: list[int] = []
                stopped = asyncio.Event()
                monitor = asyncio.create_task(monitor_rss(process.pid, samples, stopped))
                started = time.monotonic()
                try:
                    session_errors = await asyncio.gather(
                        *(
                            visitor(url, started + duration, index, measurements)
                            for index in range(streams)
                        )
                    )
                finally:
                    stopped.set()
                    await monitor
                report = build_report(
                    measurements,
                    samples,
                    duration,
                    streams,
                    session_errors=sum(session_errors),
                )
                report["elapsed_seconds"] = time.monotonic() - started
                return report
            finally:
                stop_server(process)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--streams", type=int, default=12)
    parser.add_argument("--duration", type=float, default=900)
    parser.add_argument("--report", type=Path, help="JSON destination (default: stdout)")
    args = parser.parse_args(argv)
    if args.streams < 1 or not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("streams and duration must be positive and finite")
    report = asyncio.run(run_load(args.streams, args.duration))
    output = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.report is None:
        sys.stdout.write(output)
    else:
        args.report.write_text(output, encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
