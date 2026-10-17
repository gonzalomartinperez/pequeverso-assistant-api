"""Run explicit project migrations with an operator-provided privileged identity."""

import asyncio

from app.bootstrap.knowledge_jobs import migrate_main

if __name__ == '__main__':
    raise SystemExit(asyncio.run(migrate_main()))
