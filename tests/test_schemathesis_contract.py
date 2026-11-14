"""Schemathesis conformance of the committed OpenAPI contract against the in-process app.

PVA-M2.10. Fixture provider and a temporary SQLite file, no network and no model call.
`SCHEMATHESIS_MAX_EXAMPLES` sets the budget per operation: 50 on pull requests (default),
500 in the nightly lane. Generation is derandomized so a CI failure reproduces.

Checks run: not_a_server_error, status_code_conformance, content_type_conformance,
response_schema_conformance. Excluded, with reasons:
- positive_data_acceptance, negative_data_rejection: the app answers contract-shaped but
  policy-rejected input with documented 4xx envelopes (origin, CSRF, quota, language), so
  "valid input is accepted" is not a property of this API.
- response_headers_conformance, use_after_free, ensure_resource_availability, missing_required_header:
  the spec declares no response headers, and these need resource semantics the v1 spec lacks (M3).
- Undocumented 400/404/413/415 (malformed body, unknown run id, body limit, media type) are accepted only with the
  standard error envelope: a known spec gap that PVA-M3 closes; remove UNDOCUMENTED_ENVELOPES then.
The SSE body of /api/v1/messages is declared as text/event-stream without a schema; its
conformance is covered by tests/test_sse_conformance.py and contracts/sse.schema.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import schemathesis
from hypothesis import HealthCheck, Phase, settings
from hypothesis.stateful import run_state_machine_as_test
from schemathesis.python import asgi

from app.bootstrap.container import create_app
from tests.support import FixedClock
from tests.support import settings as app_settings

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = "http://localhost:3000"
MAX_EXAMPLES = int(os.environ.get("SCHEMATHESIS_MAX_EXAMPLES", "50"))
# Served for malformed or oversized bodies, wrong media types and unknown run ids, absent from the spec.
UNDOCUMENTED_ENVELOPES = frozenset({400, 404, 413, 415})
CHECKS = (
    schemathesis.checks.not_a_server_error,
    schemathesis.checks.status_code_conformance,
    schemathesis.checks.content_type_conformance,
    schemathesis.checks.response_schema_conformance,
)

_SPEC: dict[str, Any] = json.loads((ROOT / "contracts" / "openapi.json").read_text())
# Schemathesis ends an ASGI lifespan with each test and an app cannot restart, so every test gets a
# fresh app; the auth provider below reaches the current one through this holder.
_CURRENT: dict[str, Any] = {}


@pytest.fixture
def api_schema(tmp_path: Path) -> Any:
    app = create_app(app_settings(tmp_path), clock=FixedClock())
    _CURRENT["app"] = app
    loaded = schemathesis.openapi.from_dict(_SPEC)
    loaded.app = app
    loaded.config.update(base_url="http://testserver")
    return loaded


schema = schemathesis.pytest.from_fixture("api_schema")


@schemathesis.auth(refresh_interval=None)
class VisitorSession:
    """Open a real session per case: Origin, session cookie and CSRF token."""

    def get(self, case: schemathesis.Case, context: schemathesis.AuthContext) -> dict[str, str]:
        # Schemathesis' own in-process client starts the app lifespan once and shares it.
        with asgi.get_client(_CURRENT["app"]) as c:
            r = c.post("/api/v1/session", headers={"Origin": ORIGIN}, json={})
            cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
            return {"cookie": cookie, "csrf": str(r.json().get("csrf_token", ""))}

    def set(self, case: schemathesis.Case, data: dict[str, str], context: Any) -> None:
        case.headers = case.headers or {}
        case.headers["Origin"] = ORIGIN
        case.headers["Cookie"] = data["cookie"]
        case.headers.setdefault("X-CSRF-Token", data["csrf"])


@schema.parametrize()
@settings(
    max_examples=MAX_EXAMPLES,
    derandomize=True,
    deadline=None,
    phases=[Phase.generate],
    suppress_health_check=list(HealthCheck),
)
def test_operations_conform(case: schemathesis.Case) -> None:
    _check(case, case.call())


def _check(case: schemathesis.Case, response: schemathesis.Response) -> None:
    if response.status_code in UNDOCUMENTED_ENVELOPES:
        # Spec gap (audit P2-1, completed in M3): the transport-level rejections are served but not
        # declared. Still require the documented error envelope and no 5xx, instead of skipping.
        body = response.json()
        assert set(body) == {"error"} and isinstance(body["error"]["code"], str), body
        return
    case.validate_response(response, checks=CHECKS)


def test_session_links_are_declared() -> None:
    """Three stateful flows: session -> post message, -> cancel run, -> delete session."""
    responses = _SPEC["paths"]["/api/v1/session"]["post"]["responses"]
    for status in ("200", "201"):
        links = responses[status]["links"]
        assert {link["operationId"] for link in links.values()} == {
            "post_message_api_v1_messages_post",
            "cancel_run_api_v1_runs__run_id__cancel_post",
            "delete_session_api_v1_session_delete",
        }


def test_stateful_session_flows(api_schema: Any) -> None:
    """Follow the declared links from a created session; same checks as the stateless run."""

    class Flows(api_schema.as_state_machine()):  # type: ignore[misc]
        def validate_response(self, response: Any, case: Any, additional_checks: Any = ()) -> None:
            _check(case, response)

    run_state_machine_as_test(
        Flows,
        settings=settings(
            max_examples=MAX_EXAMPLES,
            stateful_step_count=4,
            derandomize=True,
            deadline=None,
            suppress_health_check=list(HealthCheck),
        ),
    )
