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
import sys
from collections import Counter, defaultdict
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

pytestmark = pytest.mark.schemathesis

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
# Status codes seen per "METHOD path", filled by every test below and asserted by the last one.
_STATUS: dict[str, Counter[int]] = defaultdict(Counter)
# Link traversals observed by the stateful test: link name -> times a step used it.
_LINKS: Counter[str] = Counter()
_LINK_STATUS: dict[str, Counter[int]] = defaultdict(Counter)
# Limits are raised so generated volume never exhausts the quotas and turns every case into a 429/401.
_LIMITS = {
    "sessions_per_client_per_hour": 10**6,
    "messages_per_client_per_hour": 10**6,
    "messages_per_session_per_day": 10**6,
}
VALID_MESSAGE = {
    "content": "¿Qué incluye el kit?",
    "page": "product",
    "response_language": "es",
}


@pytest.fixture
def api_schema(tmp_path: Path) -> Any:
    app = create_app(app_settings(tmp_path, **_LIMITS), clock=FixedClock())
    _CURRENT["app"] = app
    loaded = schemathesis.openapi.from_dict(_SPEC)
    loaded.app = app
    loaded.config.update(base_url="http://testserver")
    return loaded


schema = schemathesis.pytest.from_fixture("api_schema")


def _authenticate(case: schemathesis.Case) -> None:
    """Hand-built cases bypass the auth provider: apply the same session by hand."""
    case.headers = case.headers or {}
    visitor = VisitorSession()
    visitor.set(case, visitor.get(case, None), None)  # type: ignore[arg-type]


@schemathesis.auth(refresh_interval=None)
class VisitorSession:
    """Open a real session per case: Origin, session cookie and CSRF token."""

    def get(self, case: schemathesis.Case, context: schemathesis.AuthContext) -> dict[str, str]:
        # Schemathesis' own in-process client starts the app lifespan once and shares it.
        with asgi.get_client(_CURRENT["app"]) as c:
            r = c.post("/api/v1/session", headers={"Origin": ORIGIN}, json={})
            assert r.status_code in (200, 201), f"session call failed: {r.status_code} {r.text}"
            cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
            csrf = str(r.json().get("csrf_token", ""))
            assert cookie and csrf, "session call returned no cookie or CSRF token"
            return {"cookie": cookie, "csrf": csrf}

    def set(self, case: schemathesis.Case, data: dict[str, str], context: Any) -> None:
        case.headers = case.headers or {}
        case.headers["Origin"] = ORIGIN
        case.headers["Cookie"] = data["cookie"]
        # The spec declares `x-csrf-token` as an optional header parameter, so the generator may
        # have produced one in any case; drop it and always send the real token.
        for name in [k for k in case.headers if k.lower() == "x-csrf-token"]:
            del case.headers[name]
        case.headers["X-CSRF-Token"] = data["csrf"]


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


def _record(case: schemathesis.Case, response: schemathesis.Response) -> None:
    _STATUS[f"{case.method.upper()} {case.operation.path}"][response.status_code] += 1


def _check(case: schemathesis.Case, response: schemathesis.Response) -> None:
    _record(case, response)
    if response.status_code in UNDOCUMENTED_ENVELOPES:
        # Spec gap (audit P2-1, completed in M3): the transport-level rejections are served but not
        # declared. Still require the documented error envelope and no 5xx, instead of skipping.
        body = response.json()
        assert set(body) == {"error"} and isinstance(body["error"]["code"], str), body
        return
    case.validate_response(response, checks=CHECKS)


def test_valid_message_reaches_the_event_stream(api_schema: Any) -> None:
    """Hand-built valid message: generated bodies rarely satisfy the app's content rules."""
    case = api_schema["/api/v1/messages"]["POST"].Case(
        headers={"Idempotency-Key": "schemathesis-valid-1"}, body=VALID_MESSAGE
    )
    _authenticate(case)
    response = case.call()
    assert response.status_code == 200, response.text
    assert response.headers["content-type"][0].startswith("text/event-stream")
    _check(case, response)


def test_cancel_unknown_run_uses_the_error_envelope(api_schema: Any) -> None:
    """A run id exists only inside the SSE stream, never in a JSON response, so no link can supply a
    real one (the spec cannot express it). The reachable path is an unknown id: documented envelope."""
    case = api_schema["/api/v1/runs/{run_id}/cancel"]["POST"].Case(
        path_parameters={"run_id": "run_does_not_exist"}
    )
    _authenticate(case)
    response = case.call()
    assert response.status_code == 404, response.text
    body = response.json()
    assert set(body) == {"error"} and isinstance(body["error"]["code"], str), body
    _check(case, response)


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
        def step(self, input: Any) -> Any:
            output = super().step(input)
            if input.transition is not None:
                # Transition ids read "POST /api/v1/session -> [200] <link name> -> POST ...".
                link = input.transition.id.split(" -> ")[1].split("] ", 1)[-1]
                _LINKS[link] += 1
                _LINK_STATUS[link][output.response.status_code] += 1
            return output

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


@pytest.fixture(scope="module", autouse=True)
def every_operation_and_link_was_exercised() -> Any:
    """Guard against a vacuous suite: runs after the last test of the module, in any order."""
    yield
    if os.environ.get("PYTEST_XDIST_WORKER") or not _STATUS:
        # Under xdist the tests are spread over workers; the dedicated CI step runs serially.
        return
    sys.stdout.write(
        f"\nstatus codes per operation: { ({k: dict(v) for k, v in sorted(_STATUS.items())}) }"
        f"\nlink traversals: { ({k: dict(v) for k, v in sorted(_LINK_STATUS.items())}) }\n"
    )
    for operation in ("POST /api/v1/session", "DELETE /api/v1/session", "POST /api/v1/messages"):
        codes = _STATUS[operation]
        assert any(200 <= code < 300 for code in codes), f"{operation} never 2xx: {dict(codes)}"
    assert set(_STATUS["POST /api/v1/runs/{run_id}/cancel"]) <= {401, 403, 404, 409, 422, 429}
    declared = set(_SPEC["paths"]["/api/v1/session"]["post"]["responses"]["200"]["links"])
    assert declared <= set(_LINKS), f"links never traversed: {declared - set(_LINKS)}"
    # Generated message bodies rarely pass the content rules (documented 422); the 2xx path of
    # POST /messages is covered by test_valid_message_reaches_the_event_stream.
    assert all(code < 500 for codes in _LINK_STATUS.values() for code in codes), _LINK_STATUS
