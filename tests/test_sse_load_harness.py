"""Deterministic load measurements and an opt-in real-socket smoke."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from tests.load.sse_load import (
    Measurement,
    SSEParser,
    build_report,
    event_timings,
    iter_sse,
    measure_message,
    percentile,
    rss_growth,
    rss_kib,
)


def completed(**overrides):
    return Measurement(
        **{
            "status": 200,
            "ttfe": 0.1,
            "gaps": [0.01, 0.02],
            "terminal": "run.completed",
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("values", "percent", "expected"),
    [
        ([], 95, None),
        ([7], 95, 7),
        ([4, 1, 3, 2], 50, 2.5),
        ([0, 10], 95, 9.5),
        ([4, 1], 0, 1),
        ([4, 1], 100, 4),
    ],
)
def test_percentile(values, percent, expected):
    assert percentile(values, percent) == expected


@pytest.mark.parametrize("percent", [-1, 101])
def test_invalid_percentile(percent):
    with pytest.raises(ValueError, match="percentile"):
        percentile([1], percent)


@pytest.mark.parametrize(
    ("samples", "expected"),
    [
        ([], None),
        ([100], None),
        ([0, 100], None),
        ([100, 120], 20),
        ([100, 90], -10),
        ([100, 200, 110], 10),
    ],
)
def test_rss_growth(samples, expected):
    assert rss_growth(samples) == expected


def test_event_timings_use_request_start_and_event_arrivals():
    assert event_timings(10, []) == (None, [])
    ttfe, gaps = event_timings(10, [10.25, 10.75, 12])
    assert ttfe == 0.25
    assert gaps == [0.5, 1.25]


class ChunkedStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b': heartbeat\n\ndata: {"type":"run.started"}\n\n'
        yield b'data: {"type":"run.completed"}\n\n'


def test_stream_measurement_without_sockets():
    async def scenario():
        def respond(request):
            assert request.headers["x-csrf-token"] == "synthetic-csrf"
            assert request.headers["idempotency-key"]
            assert json.loads(request.content)["response_language"] == "es"
            return httpx.Response(200, stream=ChunkedStream())

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1",
            transport=httpx.MockTransport(respond),
        ) as http:
            return await measure_message(http, "synthetic-csrf", "¿Qué incluye el kit?")

    result = asyncio.run(scenario())
    assert result.terminal == "run.completed"
    assert result.status == 200
    assert result.ttfe is not None and result.ttfe >= 0
    assert len(result.gaps) == 1
    assert not result.error and not result.premature


def test_linux_rss_status():
    assert rss_kib("Name:\tpython\nVmRSS:\t12345 kB\nVmSwap:\t0 kB\n") == 12345
    assert rss_kib("Name:\tpython\n") is None


@pytest.mark.parametrize("size", [1, 2, 7, 999])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_incremental_sse(size, newline):
    text = newline.join(
        [
            ": heartbeat",
            "",
            "id: 0",
            "event: message.delta",
            'data: {"type":"message.delta",',
            'data: "text":"niñez"}',
            "",
            'data:{"type":"run.completed"}',
            "",
            "",
        ]
    ).encode()

    async def chunks():
        for index in range(0, len(text), size):
            yield text[index : index + size]

    async def collect():
        return [event async for event in iter_sse(chunks())]

    assert asyncio.run(collect()) == [
        {"type": "message.delta", "text": "niñez"},
        {"type": "run.completed"},
    ]


def test_partial_sse_is_not_a_terminal_event():
    parser = SSEParser()
    assert parser.feed(b': heartbeat\n\ndata: {"type":"run.completed"}\n') == []
    assert parser.feed(b"", final=True) == []


@pytest.mark.parametrize("payload", [b"data: nope\n\n", b"data: []\n\n"])
def test_invalid_sse(payload):
    with pytest.raises(ValueError, match=r"Expecting value|JSON object"):
        SSEParser().feed(payload)


def test_report_counts_backpressure_and_failures():
    measurements = [
        completed(),
        Measurement(status=429),
        Measurement(status=503, code="busy"),
        completed(terminal="run.failed", code="busy"),
        completed(terminal="run.failed", code="generation_failed"),
        completed(terminal="run.cancelled"),
        Measurement(status=200, transport_error=True),
        Measurement(status=502),
        Measurement(transport_error=True),
        Measurement(status=503, code="budget_exhausted"),
    ]
    report = build_report(measurements, [100, 110], 30, 12, session_errors=1)
    assert report["counts"]["messages"] == 10
    assert report["counts"]["attempts"] == 11
    assert report["counts"]["errors"] == 7
    assert report["counts"]["rejected"] == 3
    assert report["counts"]["premature_closes"] == 1
    assert report["error_rate"] == 7 / 11
    assert report["rejected_rate"] == 3 / 11
    assert report["premature_close_rate"] == 1 / 11
    assert report["counts"]["http_status"]["503"] == 2
    assert report["checks"]["rss_growth"] is None
    assert not report["passed"]


def test_success_and_rss_duration_boundary():
    assert build_report([completed()], [100, 119], 600, 4)["passed"]
    short = build_report([completed()], [100, 120], 599, 4)
    assert short["passed"] and not short["rss"]["asserted"]
    assert not build_report([completed()], [100, 120], 600, 4)["passed"]
    assert not build_report([completed()], [], 600, 4)["passed"]


@pytest.mark.parametrize(
    "measurement",
    [completed(ttfe=1.5), completed(gaps=[0.5])],
)
def test_latency_limits_are_strict(measurement):
    assert not build_report([measurement], [], 10, 4)["passed"]


def test_error_and_premature_limits_are_strict():
    good = [completed()] * 199
    report = build_report([*good, Measurement(status=200)], [], 10, 4)
    assert report["error_rate"] == 0.005
    assert report["premature_close_rate"] == 0.005
    assert not report["checks"]["error_rate"]
    assert not report["checks"]["premature_close_rate"]
    assert build_report([*good, completed(), Measurement(status=200)], [], 10, 4)["passed"]


@pytest.mark.parametrize("measurements", [[], [Measurement(status=429)]])
def test_no_successful_traffic_cannot_pass(measurements):
    assert not build_report(measurements, [], 10, 4)["passed"]


@pytest.mark.skipif(os.environ.get("PVA_LOAD_SMOKE") != "1", reason="set PVA_LOAD_SMOKE=1")
def test_real_subprocess_smoke(tmp_path: Path):
    destination = tmp_path / "report.json"
    result = subprocess.run(  # noqa: S603 - fixed local fixture CLI
        [
            sys.executable,
            "-m",
            "tests.load.sse_load",
            "--streams",
            "4",
            "--duration",
            "10",
            "--report",
            str(destination),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    # 0 = thresholds met, 1 = a latency threshold missed (expected on a loaded host); anything
    # else is a crash. The smoke checks the harness, not the host's latency.
    assert result.returncode in {0, 1}, result.stderr
    report = json.loads(destination.read_text())
    assert report["provider"] == "fixture"
    assert report["streams"] == 4
    assert report["counts"]["messages"] > 0
    assert report["error_rate"] == 0
    assert report["premature_close_rate"] == 0
    assert set(report["ttfe_seconds"]) == {"samples", "p50", "p95", "max"}
    assert set(report["gap_seconds"]) == {"samples", "p50", "p95", "max"}
    assert report["rss"]["samples"] >= 2
    assert report["rss"]["first_kib"] > 0
    assert report["checks"]["rss_growth"] is None
    assert report["thresholds"]["ttfe_p95_seconds_lt"] == 1.5
    assert isinstance(report["passed"], bool)
