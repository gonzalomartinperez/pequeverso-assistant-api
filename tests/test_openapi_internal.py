"""Published OpenAPI artifacts and the runtime public documentation boundary."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from jsonschema import Draft202012Validator

from app.bootstrap.container import create_app
from app.presentation.product_analytics import PUBLIC_PATH
from contracts.export import OPS_EXPORT_PLACEHOLDER
from tests.support import settings

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"
HEALTH = {"/health/live", "/health/ready", "/healthz", "/readyz"}
OPS = {
    f"/internal/v1/ops/{suffix}"
    for suffix in ("summary", "telemetry", "metrics", "product-analytics")
}


def _read(name: str) -> dict[str, Any]:
    return json.loads((CONTRACTS / name).read_text())


def test_public_and_internal_openapi_have_disjoint_paths(tmp_path: Path) -> None:
    internal = _read("openapi.internal.json")
    assert set(internal["paths"]) == HEALTH | OPS
    assert internal["components"]["securitySchemes"]["OpsBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
    for path in OPS:
        assert internal["paths"][path]["get"]["security"] == [{"OpsBearer": []}]
    for path in HEALTH:
        assert "security" not in internal["paths"][path]["get"]

    app = create_app(
        settings(tmp_path, ops_read_token=OPS_EXPORT_PLACEHOLDER, observability_enabled=True)
    )

    async def served_paths() -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            served = await http.get("/api/v1/openapi.json")
            assert served.status_code == 200
            assert (await http.get("/api/v1/openapi.internal.json")).status_code == 404
            return served.json()["paths"]

    public_paths = _read("openapi.json")["paths"]
    assert public_paths.keys() == asyncio.run(served_paths()).keys()
    assert {(path, method.upper()) for path, ops in public_paths.items() for method in ops} == {
        (route.path, method)
        for route in iter_route_contexts(app.routes)
        if isinstance(route.original_route, APIRoute) and (route.path or "").startswith("/api/v1/")
        for method in route.methods or ()
    }
    assert PUBLIC_PATH in public_paths
    assert all(not path.startswith(("/internal", "/health")) for path in public_paths)
    assert "/readyz" not in public_paths


def test_analytics_event_example_validates_against_the_public_request_schema() -> None:
    operation = _read("openapi.json")["paths"][PUBLIC_PATH]["post"]
    assert set(operation["responses"]) == {
        "204",
        "403",
        "404",
        "408",
        "413",
        "415",
        "422",
        "429",
        "503",
    }
    body = operation["requestBody"]
    assert body["required"]
    schema = body["content"]["application/json"]["schema"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    event = _read("examples/product-analytics.event.json")
    validator.validate(event)
    assert "$defs" not in schema and "$ref" not in json.dumps(schema)  # inline, self-contained
    assert UUID(event["event_id"]).version == 4
    assert not validator.is_valid({**event, "section_id": "incluye"})
    assert not validator.is_valid({**event, "cell_x": None})


@pytest.mark.parametrize("name", ["openapi.json", "openapi.internal.json"])
def test_openapi_contains_no_credentials(name: str) -> None:
    spec = (CONTRACTS / name).read_text()
    assert OPS_EXPORT_PLACEHOLDER not in spec
    assert not re.search(
        r"\b(?:sk-[\w-]{16,}|(?:gh[pousr]_|github_pat_)[\w]+|AKIA[A-Z0-9]{16}|"
        r"eyJ[\w-]+\.[\w-]+\.[\w-]+|Bearer [\w.-]{16,})\b",
        spec,
    )
