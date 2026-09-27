import json

import pytest

from app.ai.output import AnswerStreamParser
from app.domain.errors import RejectedError


def _feed(raw: str, size: int) -> tuple[str, AnswerStreamParser]:
    parser = AnswerStreamParser()
    streamed = ''.join(parser.feed(raw[i : i + size]) for i in range(0, len(raw), size))
    return streamed, parser


@pytest.mark.parametrize('size', [1, 2, 3, 5, 64])
def test_answer_streams_exactly_regardless_of_chunking(size: int) -> None:
    answer = 'Línea 1\n"comillas" \\ barra — emoji 🌟 y ñ'
    raw = json.dumps(
        {
            'answer': answer,
            'references': [{'kind': 'product', 'id': 'x'}],
            'sources': [],
            'follow_ups': ['¿Y luego?'],
        }
    )
    streamed, parser = _feed(raw, size)
    assert streamed == answer
    draft = parser.finish()
    assert draft.answer == answer
    assert draft.references[0].id == 'x'
    assert draft.follow_ups == ('¿Y luego?',)


def test_ascii_escaped_surrogate_pairs_decode() -> None:
    raw = json.dumps(
        {'answer': 'hola 🌟', 'references': [], 'sources': [], 'follow_ups': []}, ensure_ascii=True
    )
    streamed, _ = _feed(raw, 1)
    assert streamed == 'hola 🌟'


def test_invalid_output_fails_generation() -> None:
    parser = AnswerStreamParser()
    parser.feed('{"answer": "incompleto')
    with pytest.raises(RejectedError):
        parser.finish()


def test_output_is_bounded() -> None:
    parser = AnswerStreamParser()
    with pytest.raises(RejectedError):
        parser.feed('{"answer": "' + 'a' * 20_000)
