"""Real LangSmith local runner: synthetic IDs only, no network or provider execution."""

import asyncio
import socket

import pytest

from app.adapters.graph.local_evaluation import SyntheticRetrievalResult, evaluate_synthetic_retrieval


def test_local_runner_scores_frozen_results_without_tracing_or_uploads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted: list[object] = []

    def forbidden_connect(*args: object, **kwargs: object) -> None:
        attempted.append(args)
        raise AssertionError('local evaluation must not attempt network access')

    monkeypatch.setattr(socket.socket, 'connect', forbidden_connect)
    monkeypatch.setenv('LANGSMITH_TRACING', 'true')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'true')
    monkeypatch.setenv('LANGSMITH_ENDPOINT', 'https://192.0.2.1')
    records = (
        SyntheticRetrievalResult('synthetic.comparison', ('product:kit', 'product:course'), ('product:kit',)),
        SyntheticRetrievalResult('synthetic.policy', ('document:policy',), ('document:policy',)),
    )
    # SDK 0.14.9 explicitly marks offline upload_results=False as beta. Assert its exact
    # warning instead of weakening the repository-wide warnings-as-errors policy.
    with pytest.warns(
        (UserWarning, DeprecationWarning), match=r"'upload_results' parameter|'asyncio\.iscoroutinefunction'"
    ) as captured:
        scores = asyncio.run(evaluate_synthetic_retrieval(records, manifest_sha256='a' * 64))
    expected_warnings = {
        "'upload_results' parameter is in beta.",
        (
            "'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16; "
            'use inspect.iscoroutinefunction() instead'
        ),
    }
    assert {str(warning.message) for warning in captured} == expected_warnings
    assert {score.case_id: score.recall for score in scores} == {
        'synthetic.comparison': 0.5,
        'synthetic.policy': 1.0,
    }
    assert attempted == []


@pytest.mark.parametrize('case_id', ['private.visitor', 'synthetic.user@example.com'])
def test_private_or_contact_identifiers_are_rejected(case_id: str) -> None:
    with pytest.raises(ValueError, match='synthetic fixture case identifiers'):
        SyntheticRetrievalResult(case_id, ('document:policy',), ())


def test_local_evaluation_rejects_unknown_or_duplicate_manifests() -> None:
    record = SyntheticRetrievalResult('synthetic.policy', ('document:policy',), ())
    with pytest.raises(ValueError, match='exact frozen manifest'):
        asyncio.run(evaluate_synthetic_retrieval((record,), manifest_sha256='latest'))
    with pytest.raises(ValueError, match='unique synthetic cases'):
        asyncio.run(evaluate_synthetic_retrieval((record, record), manifest_sha256='a' * 64))
