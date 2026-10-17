"""Explicit offline import only; never read or alter the source in application startup."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

from psycopg import Error

from app.adapters.postgres.database import PostgresDatabase
from app.adapters.postgres.import_sqlite import import_snapshot


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--source-quiescent', action='store_true', required=True)
    args = parser.parse_args()
    dsn = os.environ.get('PRIVATE_DATABASE_URL')
    if not dsn:
        print('PRIVATE_DATABASE_URL is required; values are never accepted in command arguments')
        return 2
    db = PostgresDatabase(dsn, pool_size=2)
    try:
        await db.open()
        # Migrations are a separate, explicit operator job; this command never creates the target.
        receipt = await import_snapshot(db, args.snapshot, source_quiescent=args.source_quiescent)
        output = json.dumps(asdict(receipt), indent=2) + '\n'
        descriptor = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as target:
            target.write(output)
        print('Import verified; content-free private receipt written. No source data removed.')
        return 0
    except (Error, ValueError, OSError, LookupError) as error:
        # DB error details can contain private row values. Never print the exception text/traceback.
        print(f'Import failed ({type(error).__name__}); inspect private state before retrying.')
        return 1
    finally:
        await db.close()


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
