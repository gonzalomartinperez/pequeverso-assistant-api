"""Validate the declared PostgreSQL image identity before creating disposable resources."""

from __future__ import annotations

import json
import sys


def postgres_fixture_identity(value: object) -> str:
    """Allow the reviewed Alpine profile and reproducible historical Debian fixtures only."""
    if not isinstance(value, str) or value not in ('70:70', '999:999'):
        raise ValueError('PostgreSQL fixture image must declare a reviewed non-root UID and GID')
    return value


def main() -> int:
    try:
        serialized = sys.stdin.read(257)
        if len(serialized) > 256:
            raise ValueError('image identity metadata exceeds its bound')
        identity = postgres_fixture_identity(json.loads(serialized))
    except (ValueError, TypeError):
        print('PostgreSQL fixture image identity was refused', file=sys.stderr)
        return 2
    print(identity)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
