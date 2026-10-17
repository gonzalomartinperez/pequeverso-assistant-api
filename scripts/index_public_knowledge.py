"""Run the explicit public indexing job; never called by HTTP startup."""

import asyncio

from app.bootstrap.knowledge_jobs import index_main

if __name__ == '__main__':
    raise SystemExit(asyncio.run(index_main()))
