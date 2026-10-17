"""Manual LangSmith evaluation of completed synthetic retrieval results, without uploads.

This module never generates answers or calls an embedding/model provider. Expected source IDs
must come from the frozen public fixture manifest, separately from the completed retrieval run.
The score measures source-ID recall, not response correctness or semantic model quality.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from langsmith import Client, tracing_context
from langsmith.evaluation import aevaluate
from langsmith.schemas import Example

_ID = re.compile(r'[a-z0-9][a-z0-9.:/\-]{0,159}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')


@dataclass(frozen=True, slots=True)
class SyntheticRetrievalResult:
    case_id: str
    expected_ids: tuple[str, ...]
    retrieved_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id.startswith('synthetic.') or not _ID.fullmatch(self.case_id):
            raise ValueError('only explicit synthetic fixture case identifiers are accepted')
        for ids in (self.expected_ids, self.retrieved_ids):
            if len(ids) > 64 or len(set(ids)) != len(ids) or any(not _ID.fullmatch(item) for item in ids):
                raise ValueError('evaluation accepts bounded unique public source identifiers only')
        if not self.expected_ids:
            raise ValueError('recall requires an independently declared expected source')


@dataclass(frozen=True, slots=True)
class LocalRecall:
    case_id: str
    recall: float


async def evaluate_synthetic_retrieval(
    records: Sequence[SyntheticRetrievalResult], *, manifest_sha256: str
) -> tuple[LocalRecall, ...]:
    if not 1 <= len(records) <= 256 or len({record.case_id for record in records}) != len(records):
        raise ValueError('a local evaluation requires one to 256 unique synthetic cases')
    if not _SHA.fullmatch(manifest_sha256):
        raise ValueError('an exact frozen manifest sha256 is required')
    dataset_id = uuid5(NAMESPACE_URL, f'pequeverso:synthetic-retrieval:{manifest_sha256}')
    examples = [
        Example(
            id=uuid5(dataset_id, record.case_id),
            dataset_id=dataset_id,
            created_at=datetime(2026, 10, 17, tzinfo=UTC),
            inputs={'case_id': record.case_id, 'retrieved_ids': list(record.retrieved_ids)},
            outputs={'expected_ids': list(record.expected_ids)},
        )
        for record in records
    ]

    async def completed_result(inputs: dict[str, Any]) -> dict[str, Any]:
        return {'retrieved_ids': inputs['retrieved_ids']}

    def recall(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, str | float]:
        expected = set(reference_outputs['expected_ids'])
        observed = set(outputs['retrieved_ids'])
        return {'key': 'source_id_recall', 'score': len(expected.intersection(observed)) / len(expected)}

    # Explicit loopback client prevents ambient API keys/endpoints being selected. It is not a
    # running local service: any attempted network access is a defect, covered by a socket guard.
    with (
        closing(
            Client(
                api_url='http://127.0.0.1:9',
                api_key='local-synthetic-only',
                auto_batch_tracing=False,
                tracing_sampling_rate=0,
            )
        ) as local_client,
        tracing_context(enabled=False),
    ):
        results = await aevaluate(
            completed_result,
            data=examples,
            evaluators=[recall],
            client=local_client,
            max_concurrency=0,
            num_repetitions=1,
            upload_results=False,
            disable_evaluator_tracing=True,
            metadata={'synthetic': True, 'manifest_sha256': manifest_sha256},
        )
        scores: list[LocalRecall] = []
        async for result in results:
            inputs = result['example'].inputs
            if inputs is None or not isinstance(case_id := inputs.get('case_id'), str):
                raise RuntimeError('local evaluation lost its synthetic identity')
            feedback = result['evaluation_results']['results']
            if len(feedback) != 1 or feedback[0].score is None:
                raise RuntimeError('local evaluation did not produce one recall score')
            scores.append(LocalRecall(case_id, float(feedback[0].score)))
        return tuple(scores)
