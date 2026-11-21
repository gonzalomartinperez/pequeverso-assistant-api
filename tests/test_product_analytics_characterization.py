"""Characterize analytics validation errors and ingest guard precedence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.presentation.product_analytics import ReportOut, build_router
from contracts.product_analytics import artifacts
from tests.test_product_analytics import event
from tests.test_product_analytics_http import HEADERS, ORIGIN, PATH, Clock, Store, client

if TYPE_CHECKING:
    from datetime import datetime

    from app.domain.product_analytics import Event

COUNTS = {"page_views": 2, "section_views": 3, "public_clicks": 4}
DAY = {"day": "2026-10-18", **COUNTS}
CELL = {"x": 2, "y": 4, "count": 3}
GRID = {
    "available": True,
    "visible_clicks": 3,
    "withheld_clicks": 1,
    "unselected_clicks": 0,
    "cells": [CELL],
}
UNSELECTED = {
    "period": "day",
    "offset": 0,
    "route": "all",
    "section_id": "all",
    "viewport_bucket": "all",
    "locale": "es",
}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"last_observed_at": "2026-10-18T13:00:00+01:00", "partial": False},
            "report timestamps must be aware UTC",
        ),
        ({"partial": False}, "inconsistent calendar window"),
        ({"daily": [DAY, DAY]}, "daily buckets must be ordered and unique"),
        ({"daily": [{**DAY, "page_views": 9994}]}, "daily count/window bound violated"),
        ({"countries": [{"code": "unknown", "count": 8}]}, "country totals do not reconcile"),
        (
            {"countries": [{"code": "withheld", "count": 1}, {"code": "unknown", "count": 8}]},
            "country buckets must be unique and ordered",
        ),
        (
            {
                "daily": [],
                "totals": dict.fromkeys(COUNTS, 0),
                "countries": [],
                "last_observed_at": None,
            },
            "empty report has no observations",
        ),
        ({"first_observed_at": None}, "invalid observed interval"),
        ({"last_observed_at": None}, "invalid observed interval"),
        ({"last_observed_at": "2026-10-18T13:00:00Z"}, "invalid observed interval"),
        ({"grid": {**GRID, "available": False}}, "invalid grid selection/order"),
        ({"grid": {**GRID, "cells": [CELL, CELL]}}, "invalid grid selection/order"),
        ({"grid": {**GRID, "visible_clicks": 4}}, "cell totals do not reconcile"),
        ({"grid": {**GRID, "withheld_clicks": 0}}, "click totals do not reconcile"),
        (
            {"grid": {**GRID, "withheld_clicks": 0, "unselected_clicks": 1}},
            "unselected regions cannot produce a blended grid",
        ),
        (
            {"selection": UNSELECTED, "grid": {**GRID, "available": False}},
            "unselected regions cannot produce a blended grid",
        ),
    ],
)
def test_report_consistency_error(changes: dict[str, object], message: str) -> None:
    report = json.loads(artifacts()["examples/product-analytics.json"])["report"]
    with pytest.raises(ValidationError) as error:
        ReportOut.model_validate({**report, **changes})
    assert [(entry["loc"], entry["msg"]) for entry in error.value.errors()] == [
        ((), f"Value error, {message}")
    ]


def test_ingest_without_service_hides_endpoint_before_header_validation() -> None:
    app = FastAPI()
    app.include_router(
        build_router(None, enabled=True, token_digest=None, origins=(ORIGIN,), clock=Clock())
    )
    with TestClient(app) as http:
        response = http.post(PATH, content=b"{")
    assert response.status_code == 404
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ([], 403),
        ([("Origin", ORIGIN)], 415),
        ([*HEADERS.items(), ("Content-Type", "application/json")], 415),
        (list(HEADERS.items()), 422),
    ],
    ids=["origin-before-content-type", "missing-content-type", "duplicate-content-type", "json"],
)
def test_ingest_validates_headers_then_json_before_storage(
    headers: list[tuple[str, str]], status: int
) -> None:
    store = Store()
    store.available = False
    with client(store) as http:
        response = http.post(PATH, content=b"{", headers=headers)
    assert response.status_code == status
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert store.checks == store.calls == 0


def test_ingest_accepts_normalized_utf8_content_type_at_body_limit() -> None:
    payload = json.dumps(event()).encode().ljust(1024)
    with client(Store()) as http:
        response = http.post(
            PATH,
            content=payload,
            headers={"Origin": ORIGIN, "Content-Type": "Application/JSON; Charset=UTF-8"},
        )
    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"


def test_ingest_storage_exception_has_empty_unavailable_response() -> None:
    class FailingStore(Store):
        async def ingest(self, value: Event, now: datetime) -> bool:
            raise RuntimeError("synthetic storage error")

    with client(FailingStore()) as http:
        response = http.post(PATH, json=event(), headers=HEADERS)
    assert response.status_code == 503
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
