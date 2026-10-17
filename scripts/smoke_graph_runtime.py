"""Run real HTTP fixtures against exclusively leased loopback PG/Neo services.

Input is a private fixture-only connection file, never command-line credentials. This mode
borrows services without deleting their data/containers; it owns and drops only UUID LOGIN
roles it creates. A separate CI job must own service/image acquisition and teardown.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'private': 'pequeverso_private_runtime',
    'knowledge': 'pequeverso_knowledge_runtime',
    'indexer': 'pequeverso_knowledge_indexer',
    'embedding': 'pequeverso_embedding_accounting',
}


def private_input(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError('fixture input must be an ordinary0600 file')
    if path.stat().st_uid != os.getuid() or path.stat().st_size > 32768:
        raise ValueError('fixture input ownership or size is invalid')
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise TypeError('fixture input must be an object')
    values: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError('fixture connection fields must be strings')
        values[key] = value
    location = urlsplit(values['postgres_dsn'])
    if (
        location.scheme != 'postgresql'
        or location.hostname != '127.0.0.1'
        or location.port != 55440
        or not location.path.startswith('/pv_')
    ):
        raise ValueError('only the exclusive fixture PostgreSQL loopback database is accepted')
    if values['neo4j_uri'] != 'bolt://127.0.0.1:17689':
        raise ValueError('only the exclusive fixture Neo4j loopback service is accepted')
    return values


def fixture_environment(source: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(('OPENAI_', 'LANGSMITH_', 'LANGCHAIN_', 'OTEL_'))
    }
    environment.update(
        {
            'AI_PROVIDER': 'fixture',
            'ALLOW_PAID_AI': 'false',
            'PYTHONPATH': str(source),
            'PYTHONDONTWRITEBYTECODE': '1',
        }
    )
    return environment


async def provision(values: dict[str, str], roles: list[str]) -> dict[str, object]:
    configuration: dict[str, object] = {
        'isolated_fixture': True,
        'runtime_roles_verified_non_owner': True,
        'postgres_admin_dsn': values['postgres_dsn'],
        'neo4j_uri': values['neo4j_uri'],
        'neo4j_username': values['neo4j_username'],
        'neo4j_password': values['neo4j_password'],
    }
    location = urlsplit(values['postgres_dsn'])
    async with await psycopg.AsyncConnection.connect(values['postgres_dsn'], autocommit=True) as connection:
        for suffix, group in GROUPS.items():
            name, password = f'pv_http_{secrets.token_hex(8)}_{suffix}', secrets.token_hex(24)
            await connection.execute(
                sql.SQL(
                    'CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT PASSWORD {}'
                ).format(sql.Identifier(name), sql.Literal(password))
            )
            roles.append(name)  # Record ownership immediately, including later grant failure.
            await connection.execute(
                sql.SQL('GRANT {} TO {}').format(sql.Identifier(group), sql.Identifier(name))
            )
            row = await (
                await connection.execute(
                    'SELECT NOT r.rolsuper AND NOT r.rolbypassrls AND NOT r.rolcreatedb AND NOT r.rolcreaterole'
                    ' AND NOT EXISTS(SELECT FROM pg_class WHERE relowner=r.oid)'
                    ' AND NOT EXISTS(SELECT FROM pg_database WHERE datdba=r.oid)'
                    " AND pg_has_role(r.oid,%s,'MEMBER') FROM pg_roles r WHERE rolname=%s",
                    (group, name),
                )
            ).fetchone()
            if row != (True,):
                raise RuntimeError('fixture LOGIN least-privilege verification failed')
            configuration[f'postgres_{suffix}_dsn'] = (
                f'postgresql://{quote(name, safe="")}:{quote(password, safe="")}@127.0.0.1:55440{location.path}'
            )
    return configuration


async def cleanup(values: dict[str, str], roles: list[str]) -> None:
    async with await psycopg.AsyncConnection.connect(values['postgres_dsn'], autocommit=True) as connection:
        for name in reversed(roles):
            # Only names actually created by this process are eligible for removal.
            await connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--services-config', type=Path, required=True)
    parser.add_argument('--receipt-dir', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path, default=ROOT)
    parser.add_argument('--test-file', type=Path, default=ROOT / 'tests/test_graph_http_live_services.py')
    args = parser.parse_args()
    roles: list[str] = []
    values: dict[str, str] | None = None
    output = args.receipt_dir.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    private = output / 'http-fixture-private.json'
    environment = fixture_environment(args.source_dir.resolve())
    result = 1
    private_created = False
    try:
        values = private_input(args.services_config)
        environment['POSTGRES_MIGRATION_DSN'] = values['postgres_dsn']
        with (output / 'migration.log').open('x') as log:
            migrated = subprocess.run(
                [sys.executable, '-m', 'app.bootstrap.knowledge_jobs', 'migrate'],
                cwd=args.source_dir,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=30,
                check=False,
            )
        environment.pop('POSTGRES_MIGRATION_DSN')
        if migrated.returncode:
            raise RuntimeError('explicit fixture migrations failed')
        configuration = asyncio.run(provision(values, roles))
        descriptor = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        private_created = True
        with os.fdopen(descriptor, 'w') as target:
            json.dump(configuration, target)
        environment['PV_GRAPH_HTTP_FIXTURE_CONFIG'] = str(private)
        environment['PV_GRAPH_HTTP_ARTIFACT_DIR'] = str(output)
        with (output / 'http-tests.log').open('x') as log:
            tested = subprocess.run(
                [
                    sys.executable,
                    '-m',
                    'pytest',
                    str(args.test_file.resolve()),
                    '-c',
                    str(args.source_dir.resolve() / 'pyproject.toml'),
                    '--import-mode=importlib',
                    '-o',
                    f'cache_dir={output / "pytest-cache"}',
                    '-q',
                    f'--junitxml={output / "http-tests.xml"}',
                ],
                cwd=output,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=180,
                check=False,
            )
        result = tested.returncode
        receipt = {
            'fixture_only': True,
            'real_services': ['PostgreSQL18.6/pgvector0.8.7', 'Neo4j5.26'],
            'provider': 'scripted; no SDK',
            'paid_calls': 0,
            'deployment': False,
            'pytest_exit': result,
            'login_roles_created': len(roles),
            'login_roles_non_owner': True,
            'scope': 'borrowed exclusively leased services; only own temporary LOGIN roles cleaned',
        }
        (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    except Exception as error:  # noqa: BLE001 - never render DSNs, passwords or SQL exception details
        print(f'Graph HTTP fixture failed ({type(error).__name__}); inspect private artifacts.')
    finally:
        if values is not None and roles:
            try:
                asyncio.run(cleanup(values, roles))
            except Exception as error:  # noqa: BLE001 - preserve private errors without raw values
                print(f'Owned fixture role cleanup failed ({type(error).__name__}); manual cleanup required.')
                result = 1
        if private_created and private.exists():
            private.unlink()
    return result


if __name__ == '__main__':
    raise SystemExit(main())
