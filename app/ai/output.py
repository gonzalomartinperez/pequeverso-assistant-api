"""Incremental reader for the structured answer.

The provider streams one JSON object whose first property is `answer` (property order follows
the schema). `feed` decodes the `answer` string as it arrives so visitors read the reply while it
is generated; `finish` parses the whole object, which is authoritative.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.application.ports import Draft, DraftReference
from app.domain.errors import FailureCode, RejectedError

_ANSWER_KEY = re.compile(r'"answer"\s*:\s*"')
_ESCAPES = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}
MAX_OUTPUT_CHARS = 16_000


class AnswerStreamParser:
    def __init__(self) -> None:
        self._buffer = ''
        self._position = 0
        self._state = 'seek'

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        if len(self._buffer) > MAX_OUTPUT_CHARS:
            raise RejectedError(FailureCode.GENERATION_FAILED)
        if self._state == 'seek':
            match = _ANSWER_KEY.search(self._buffer)
            if match is None:
                return ''
            self._position = match.end()
            self._state = 'string'
        if self._state != 'string':
            return ''
        return self._decode()

    def _decode(self) -> str:
        out: list[str] = []
        text = self._buffer
        i = self._position
        while i < len(text):
            char = text[i]
            if char == '"':
                self._state = 'done'
                i += 1
                break
            if char != '\\':
                out.append(char)
                i += 1
                continue
            if i + 1 >= len(text):
                break
            code = text[i + 1]
            if code != 'u':
                out.append(_ESCAPES.get(code, code))
                i += 2
                continue
            if i + 6 > len(text):
                break
            point = int(text[i + 2 : i + 6], 16)
            if 0xD800 <= point <= 0xDBFF:
                if i + 12 > len(text):
                    break
                low = int(text[i + 8 : i + 12], 16) if text[i + 6 : i + 8] == '\\u' else 0
                if 0xDC00 <= low <= 0xDFFF:
                    out.append(chr(0x10000 + ((point - 0xD800) << 10) + (low - 0xDC00)))
                    i += 12
                    continue
                out.append('�')
                i += 6
                continue
            out.append(chr(point))
            i += 6
        self._position = i
        return ''.join(out)

    def finish(self) -> Draft:
        try:
            data: Any = json.loads(self._buffer)
        except json.JSONDecodeError as error:
            raise RejectedError(FailureCode.GENERATION_FAILED) from error
        return parse_draft(data)


def _strings(value: Any, limit: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RejectedError(FailureCode.GENERATION_FAILED)
    return tuple(item for item in value[:limit] if isinstance(item, str))


def parse_draft(data: Any) -> Draft:
    if not isinstance(data, dict) or not isinstance(data.get('answer'), str):
        raise RejectedError(FailureCode.GENERATION_FAILED)
    raw_references = data.get('references', [])
    if not isinstance(raw_references, list):
        raise RejectedError(FailureCode.GENERATION_FAILED)
    references = tuple(
        DraftReference(kind=item['kind'], id=item['id'])
        for item in raw_references[:12]
        if isinstance(item, dict) and isinstance(item.get('kind'), str) and isinstance(item.get('id'), str)
    )
    return Draft(
        answer=data['answer'],
        references=references,
        sources=_strings(data.get('sources', []), 8),
        follow_ups=_strings(data.get('follow_ups', []), 6),
    )
