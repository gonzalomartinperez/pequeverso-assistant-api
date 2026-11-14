"""Route-derived security coverage; bootstrap and cookieless analytics are explicit exceptions."""

from typing import TYPE_CHECKING

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient

from app.bootstrap.container import create_app
from tests.support import JSON_HEADERS, client, mutation_headers, open_session, settings
from tests.test_product_analytics import event
from tests.test_product_analytics_http import Store
from tests.test_product_analytics_http import client as analytics_client

if TYPE_CHECKING:
    from pathlib import Path

TOKEN = "synthetic-matrix-token-not-a-secret"
# Every optional, flag-gated route is registered. Product analytics cannot be enabled through
# create_app offline (it requires PostgreSQL), so its router is exercised separately below.
FULL = {"ops_read_token": TOKEN, "observability_enabled": True}
# Routes that are neither HTTP routes nor containers of routes (websocket, raw ASGI mount).
# Empty on purpose: a new one must be listed here with a security justification.
RAW_ROUTE_EXCEPTIONS: frozenset[str] = frozenset()
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Check applicability is deliberate: session bootstrap cannot require an existing CSRF token;
# analytics is cookieless, disabled in the default app and validated separately when enabled.
MATRIX = {
    ("POST", "/api/v1/session"): {"origin", "body"},
    ("DELETE", "/api/v1/session"): {"origin", "csrf", "session"},
    ("POST", "/api/v1/messages"): {"origin", "csrf", "session", "body"},
    ("POST", "/api/v1/runs/{run_id}/cancel"): {"origin", "csrf", "session", "ownership"},
    ("POST", "/api/v1/analytics/events"): {"origin", "body", "disabled"},
}


def inventory(app):
    """FastAPI's walker expands lazy included routers; recurse through Starlette mounts too."""

    def walk(routes, prefix=""):
        for context in iter_route_contexts(routes):
            route = context.route
            path = prefix + context.path
            if getattr(route, "routes", None) is not None:
                yield from walk(route.routes, path)
            else:
                methods = getattr(route, "methods", None)
                if methods is None:
                    assert path in RAW_ROUTE_EXCEPTIONS, f"uninventoried route kind: {path}"
                for method in methods or ():
                    kind = (
                        "internal (bearer)"
                        if path.startswith("/internal/")
                        else "health"
                        if path.startswith("/health/")
                        else "public mutating"
                        if method in MUTATING
                        else "public read"
                    )
                    yield method, path, kind

    return set(walk(app.routes))


def test_every_registered_mutation_has_exactly_one_matrix_entry(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path, **FULL))
    routes = inventory(app)
    assert {path for _, path, kind in routes if kind == "internal (bearer)"} >= {
        "/internal/v1/ops/telemetry",
        "/internal/v1/ops/metrics",
        "/internal/v1/ops/summary",
    }
    assert {(method, path) for method, path, _ in routes if method in MUTATING} == set(MATRIX)


CASES = [
    (method, path, check) for (method, path), checks in MATRIX.items() for check in sorted(checks)
]


@pytest.mark.parametrize(("method", "path", "check"), CASES)
def test_public_mutation_matrix(tmp_path: Path, method: str, path: str, check: str) -> None:
    if check == "ownership":
        assert_foreign_active_run_is_indistinguishable_from_unknown(tmp_path)
        return
    if path.endswith("analytics/events") and check == "body":
        with analytics_client(Store()) as c:
            from tests.test_product_analytics_http import HEADERS

            # Positive control: the identical event without the extra field is accepted.
            assert c.post(path, headers=HEADERS, json=event()).status_code == 204
            assert (
                c.post(path, headers=HEADERS, json=event(unexpected="forbidden")).status_code == 422
            )
        return
    with client(tmp_path) as c:
        csrf = open_session(c)
        headers = mutation_headers(csrf)
        body = {"content": "Hola"} if path.endswith("messages") else {}
        status, code = 403, "origin_denied"
        if check == "origin":
            headers["Origin"] = "https://unapproved.invalid"
        elif check == "csrf":
            for token in (None, "wrong-token"):
                changed = {k: v for k, v in headers.items() if k != "X-CSRF-Token"}
                if token is not None:
                    changed["X-CSRF-Token"] = token
                response = c.request(
                    method, path.replace("{run_id}", "unknown"), headers=changed, json=body
                )
                assert response.status_code == 403
                assert response.json()["error"]["code"] == "csrf_failed"
            return
        elif check == "session":
            c.cookies.clear()
            status, code = 401, "session_expired"
        elif check == "body":
            body["unexpected"] = "forbidden"
            status, code = 422, "invalid_request"
        elif check == "disabled":
            c.cookies.clear()
            assert c.request(method, path, headers=JSON_HEADERS, json=event()).status_code == 404
            return
        response = c.request(
            method, path.replace("{run_id}", "unknown"), headers=headers, json=body
        )
        assert response.status_code == status
        assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("authorization", [None, "Bearer ", "Bearer wrong-token"])
def test_internal_route_matrix(tmp_path: Path, authorization: str | None) -> None:
    with client(tmp_path, **FULL) as c:
        routes = inventory(c.app)
        internal = [(method, path) for method, path, kind in routes if kind == "internal (bearer)"]
        assert internal
        for method, path in internal:
            headers = {} if authorization is None else {"Authorization": authorization}
            response = c.request(method, path, headers=headers)
            # Analytics is deliberately hidden while its channel is disabled.
            assert response.status_code == (404 if path.endswith("product-analytics") else 401)
            assert c.request(method, "/api/v1" + path, headers=headers).status_code == 404
    with analytics_client(Store()) as c:
        response = c.get("/internal/v1/ops/product-analytics", headers=headers)
        assert response.status_code == 401
        assert (
            c.get("/api/v1/internal/v1/ops/product-analytics", headers=headers).status_code == 404
        )


def test_internal_routes_accept_a_valid_token(tmp_path: Path) -> None:
    valid = {"Authorization": f"Bearer {TOKEN}"}
    with client(tmp_path, **FULL) as c:
        internal = [(m, p) for m, p, kind in inventory(c.app) if kind == "internal (bearer)"]
        for method, path in internal:
            expected = 404 if path.endswith("product-analytics") else 200
            assert c.request(method, path, headers=valid).status_code == expected, path
    with analytics_client(Store()) as c:
        from tests.test_product_analytics_http import AUTH

        assert c.get("/internal/v1/ops/product-analytics", headers=AUTH).status_code == 200


def assert_foreign_active_run_is_indistinguishable_from_unknown(tmp_path: Path) -> None:
    """Keep Alice's actual run active without consuming it or dispatching generation."""
    with client(tmp_path) as alice:
        csrf_a = open_session(alice)
        services = alice.app.state.services

        async def start():
            session = await services.sessions.require(
                alice.cookies.get(services.settings.cookie.name), csrf_a
            )
            return await services.chat.start(
                session, "Hola", None, "matrix-owner-001", "synthetic-client", None
            )

        run = alice.portal.call(start)
        handle = services.chat.registry._runs[run.id]
        try:
            bob = TestClient(alice.app, base_url="http://localhost:8000")
            csrf_b = open_session(bob)
            responses = [
                bob.post(f"/api/v1/runs/{rid}/cancel", headers=mutation_headers(csrf_b))
                for rid in (run.id, "unknown")
            ]
            # Bob's cancel of Alice's real run must be a no-op, not just look like one.
            assert not handle.cancel.is_set()
            for response in responses:
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "run_not_found"
            errors = [response.json()["error"] for response in responses]
            for error in errors:
                error.pop("request_id")
            assert errors[0] == errors[1]
            assert set(responses[0].json()) == set(responses[1].json())
            assert not handle.cancel.is_set()
            assert (
                alice.post(
                    f"/api/v1/runs/{run.id}/cancel", headers=mutation_headers(csrf_a)
                ).status_code
                == 202
            )
            assert handle.cancel.is_set()
        finally:
            alice.portal.call(run.aclose)
