"""ADR-0013 documents the v1 error codes for a future RFC 9457 mapping; keep its table exact."""

from __future__ import annotations

import re
from pathlib import Path

from app.domain.errors import RETRYABLE, FailureCode
from app.presentation.middleware import RETRY_AFTER, STATUS

ADR = (
    Path(__file__).resolve().parents[1]
    / "docs/decisions/ADR-0013-v1-error-envelope-and-rfc-9457-mapping.md"
)
ROW = re.compile(r"^\| `([a-z_]+)` \| (\d{3}) \| (true|false) \| *(\d*) *\|$")


def test_adr_0013_status_table_matches_the_code() -> None:
    rows = {
        m[1]: (int(m[2]), m[3] == "true", m[4])
        for line in ADR.read_text(encoding="utf-8").splitlines()
        if (m := ROW.match(line.strip()))
    }
    expected = {
        code.value: (STATUS[code], code in RETRYABLE, str(RETRY_AFTER.get(code, "")))
        for code in FailureCode
    }
    assert rows == expected
