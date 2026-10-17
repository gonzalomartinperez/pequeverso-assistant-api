"""Explicit offline import; composition and safe error handling live in bootstrap."""

import asyncio

from app.bootstrap.import_database import main

if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
