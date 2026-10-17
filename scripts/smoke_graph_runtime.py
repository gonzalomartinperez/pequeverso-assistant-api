"""Run real HTTP fixtures against exclusively leased loopback PG/Neo services.

Borrow existing exclusively leased services through a private connection file, or own isolated
containers from exact local image IDs. Credentials never enter command arguments; cleanup
affects only this process's UUID resources/LOGIN roles. Receipts require a new external directory.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
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


def docker(arguments: list[str]) -> str:
    return subprocess.run(
        ['docker', *arguments], check=True, capture_output=True, text=True, timeout=150
    ).stdout.strip()


def resource_exists(kind: str, name: str) -> bool:
    return (
        subprocess.run(
            ['docker', kind, 'inspect', name], capture_output=True, text=True, timeout=15, check=False
        ).returncode
        == 0
    )


@contextmanager
def owned_services(pg_image: str, neo_image: str, output: Path, source: Path) -> Iterator[Path]:
    """Own fixture resources only; no pull, publish, global prune or host networking."""
    import re

    if any(not re.fullmatch(r'sha256:[a-f0-9]{64}', image) for image in (pg_image, neo_image)):
        raise ValueError('CI fixtures require exact immutable local image IDs')
    # Reuse the reviewed project Neo4j runtime recipe; do not copy a sibling repository.
    sys.path.insert(0, str(source.resolve()))
    from scripts.smoke_knowledge_neo4j import GraphFixture

    with tempfile.TemporaryDirectory(prefix='pv-graph-http-', dir=output.parent) as temporary:
        private = Path(temporary)
        private.chmod(0o700)
        neo = GraphFixture(neo_image, output / 'neo-startup', private)
        pg_name = f'pv-graph-http-pg-{uuid.uuid4().hex[:12]}'
        pg_volume = f'{pg_name}-data'
        created: list[tuple[str, str]] = []
        resource_receipt: dict[str, object] = {
            'postgres_image': pg_image,
            'neo4j_image': neo_image,
            'fixture_only': True,
            'deployment': False,
            'paid_calls': 0,
            'network': 'exclusive bridge; loopback host bindings; not an egress firewall',
            'capacity': 'local functional cgroup limits, not a VPS capacity benchmark',
            'security': 'candidate-image CVE gates remain open; fixture use is not acceptance',
        }
        try:
            docker(['image', 'inspect', pg_image])
            docker(['image', 'inspect', neo_image])
            if any(
                resource_exists(kind, name)
                for kind, name in (
                    ('network', neo.network),
                    ('volume', pg_volume),
                    ('volume', neo.volumes[0]),
                    ('container', pg_name),
                    ('container', neo.container),
                )
            ):
                raise RuntimeError('unexpected UUID fixture resource collision')
            # Register own absent names before creation: Docker can create a container and
            # then report an error (for example on port binding), which still needs cleanup.
            created.append(('network', neo.network))
            docker(['network', 'create', neo.network])
            for volume in (pg_volume, neo.volumes[0]):
                created.append(('volume', volume))
                docker(['volume', 'create', volume])
            password = secrets.token_hex(24)
            envfile = private / 'postgres.env'
            envfile.write_text(
                f'POSTGRES_USER=graph_fixture_admin\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=pv_graph_http\n'
            )
            envfile.chmod(0o600)
            command = json.loads(docker(['image', 'inspect', '--format', '{{json .Config.Cmd}}', pg_image]))
            if not isinstance(command, list) or not command or command[0] != 'postgres':
                raise ValueError('PostgreSQL image has no reviewed server command')
            created.append(('container', pg_name))
            docker(
                [
                    'run',
                    '-d',
                    '--name',
                    pg_name,
                    '--network',
                    neo.network,
                    '--user',
                    '999:999',
                    '--read-only',
                    '--cap-drop',
                    'ALL',
                    '--security-opt',
                    'no-new-privileges:true',
                    '--memory',
                    '384m',
                    '--cpus',
                    '1',
                    '--pids-limit',
                    '128',
                    '--shm-size',
                    '64m',
                    '--tmpfs',
                    '/tmp:rw,nosuid,noexec,size=16m',  # noqa: S108 - Container tmpfs, not host storage.
                    '--tmpfs',
                    '/var/run/postgresql:rw,nosuid,noexec,uid=999,gid=999,mode=3775,size=16m',
                    '--mount',
                    f'type=volume,src={pg_volume},dst=/var/lib/postgresql',
                    '--env-file',
                    str(envfile),
                    '-p',
                    '127.0.0.1:55440:5432',
                    pg_image,
                    *command,
                    '-c',
                    'shared_buffers=32MB',
                    '-c',
                    'max_connections=24',
                    '-c',
                    'work_mem=2MB',
                    '-c',
                    'maintenance_work_mem=32MB',
                    '-c',
                    'max_wal_size=128MB',
                ]
            )
            created.append(('container', neo.container))
            neo.runtime(neo.volumes[0])
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    docker(
                        [
                            'exec',
                            pg_name,
                            'pg_isready',
                            '-q',
                            '-U',
                            'graph_fixture_admin',
                            '-d',
                            'pv_graph_http',
                        ]
                    )
                    break
                except subprocess.CalledProcessError:
                    time.sleep(0.25)
            else:
                raise RuntimeError('fixture PostgreSQL never became ready')
            resource_receipt['neo_tcp_liveness_seconds'] = neo.tcp_liveness()
            config = private / 'service-connections.json'
            config.write_text(
                json.dumps(
                    {
                        'postgres_dsn': f'postgresql://graph_fixture_admin:{password}@127.0.0.1:55440/pv_graph_http',
                        'neo4j_uri': 'bolt://127.0.0.1:17689',
                        'neo4j_username': 'neo4j',
                        'neo4j_password': neo.password,
                    }
                )
            )
            config.chmod(0o600)
            yield config
            resource_receipt['completed_http_handoff'] = True
        finally:

            def capture_logs() -> None:
                logs = output / 'service-private'
                logs.mkdir(mode=0o700)
                if ('container', neo.container) in created:
                    neo.logs()
                    shutil.copy2(neo.private / 'server-last.log', logs / 'neo4j.log')
                if ('container', pg_name) in created:
                    pg_log = subprocess.run(
                        ['docker', 'logs', pg_name], capture_output=True, text=True, timeout=15, check=False
                    )
                    pg_path = logs / 'postgres.log'
                    pg_path.write_text(pg_log.stdout + pg_log.stderr)
                    pg_path.chmod(0o600)

            teardown_services(created, output, resource_receipt, capture_logs)


def teardown_services(
    created: list[tuple[str, str]],
    output: Path,
    receipt: dict[str, object],
    capture_logs: Callable[[], None],
) -> None:
    """Diagnostics cannot prevent any independently attempted owned-resource cleanup."""
    failures: list[str] = []
    try:
        capture_logs()
    except Exception as error:  # noqa: BLE001 - diagnostic failure must not leak resources
        failures.append(f'logs:{type(error).__name__}')

    def execute(arguments: list[str], operation: str, timeout: int) -> str | None:
        try:
            result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, check=False)
            if result.returncode:
                failures.append(f'{operation}:exit-{result.returncode}')
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception as error:  # noqa: BLE001 - continue every other independent cleanup
            failures.append(f'{operation}:{type(error).__name__}')
            return None

    for kind, name in reversed(created):
        if kind == 'container':
            execute(['docker', 'stop', '--time', '30', name], f'stop:{name}', 40)
            state = execute(
                ['docker', 'inspect', '--format', '{{.State.ExitCode}} {{.State.OOMKilled}}', name],
                f'inspect:{name}',
                15,
            )
            receipt[f'{name}-stop'] = state
            if state != '0 false':
                failures.append(f'shutdown:{name}:unsafe-or-unknown')
    for kind in ('container', 'volume', 'network'):
        for created_kind, name in reversed(created):
            if kind == created_kind:
                execute(
                    ['docker', kind, 'rm', *(['-f'] if kind == 'container' else []), name],
                    f'remove:{kind}:{name}',
                    40,
                )
    receipt['cleanup_failures'] = failures
    try:
        (output / 'owned-services.json').write_text(json.dumps(receipt, indent=2) + '\n')
    except Exception as error:  # noqa: BLE001 - all cleanup already attempted, preserve failure status
        failures.append(f'receipt:{type(error).__name__}')
    if failures:
        raise RuntimeError('owned fixture diagnostics, shutdown or cleanup did not complete safely')


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


def index_jobs(
    source: Path, output: Path, environment: dict[str, str], configuration: dict[str, object]
) -> None:
    """Exercise the documented offline image entry point with separate real capabilities."""
    env = {**environment, 'AI_PROVIDER': 'fixture', 'ALLOW_PAID_AI': 'false'}
    for field, name in (
        ('postgres_indexer_dsn', 'POSTGRES_INDEXER_DSN'),
        ('postgres_embedding_dsn', 'POSTGRES_EMBEDDING_DSN'),
        ('neo4j_uri', 'NEO4J_URI'),
        ('neo4j_username', 'NEO4J_USERNAME'),
        ('neo4j_password', 'NEO4J_PASSWORD'),
    ):
        value = configuration[field]
        if not isinstance(value, str):
            raise TypeError('offline fixture capabilities must be private connection strings')
        env[name] = value
    catalog = source / 'catalog/catalog.v1.json'
    digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
    versions = []
    for label in ('first', 'reused'):
        receipt = output / f'index-{label}.json'
        with (output / f'index-{label}.log').open('x') as log:
            result = subprocess.run(
                [
                    sys.executable,
                    '-m',
                    'app.bootstrap.knowledge_jobs',
                    'index',
                    '--catalog',
                    str(catalog),
                    '--expected-catalog-sha256',
                    digest,
                    '--receipt',
                    str(receipt),
                ],
                cwd=source,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=60,
                check=False,
            )
        if result.returncode:
            raise RuntimeError('explicit fixture index job failed')
        if stat.S_IMODE(receipt.stat().st_mode) != 0o600:
            raise RuntimeError('index receipt did not retain private0600 permissions')
        proof = json.loads(receipt.read_text())
        if (
            proof['status'] != 'verified'
            or proof['provider'] != 'fixture'
            or proof['embedding']['provider'] != 'fixture'
            or proof['catalog_sha256'] != digest
            or proof['result']['reused_vectors'] is not True
        ):
            raise RuntimeError('idempotent offline indexing proof did not match the fixture')
        versions.append(proof['result']['version'])
    if len(set(versions)) != 1:
        raise RuntimeError('idempotent index job changed the prepared public revision')


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
        failures = 0
        for name in reversed(roles):
            # Only names actually created by this process are eligible for removal.
            try:
                await connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
            except Exception:  # noqa: BLE001 - attempt the remaining owned roles independently
                failures += 1
        if failures:
            raise RuntimeError('one or more owned fixture roles could not be removed')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--services-config', type=Path)
    parser.add_argument('--postgres-image')
    parser.add_argument('--neo4j-image')
    parser.add_argument('--with-index-jobs', action='store_true')
    parser.add_argument('--receipt-dir', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path, default=ROOT)
    parser.add_argument('--test-file', type=Path, default=ROOT / 'tests/test_graph_http_live_services.py')
    args = parser.parse_args()
    roles: list[str] = []
    values: dict[str, str] | None = None
    output = args.receipt_dir.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    private = output / 'http-fixture-private.json'
    environment = fixture_environment(args.source_dir.resolve())
    result = 1
    private_created = False
    services = ExitStack()
    receipt: dict[str, object] = {'fixture_only': True, 'paid_calls': 0, 'deployment': False}
    try:
        input_path = args.services_config
        if input_path is None:
            if not args.postgres_image or not args.neo4j_image:
                raise ValueError('provide leased services configuration or both exact candidate images')
            input_path = services.enter_context(
                owned_services(args.postgres_image, args.neo4j_image, output, args.source_dir)
            )
        elif args.postgres_image or args.neo4j_image:
            raise ValueError('borrowed and owned service modes cannot be combined')
        values = private_input(input_path)
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
        xml = (output / 'http-tests.xml').read_bytes()
        if len(xml) > 1_048_576:
            raise ValueError('own pytest XML exceeds fixture report bounds')
        text = xml.decode('utf-8')
        if '<!doctype' in text.lower() or '<!entity' in text.lower():
            raise ValueError('own pytest XML must not contain DTDs or entities')
        # This private report was generated by our own pytest process; reject DTD/entity
        # declarations and bound UTF-8 input before parsing without additional dependencies.
        suites = list(ET.fromstring(text).iter('testsuite'))  # noqa: S314 - Bounded own report, no DTDs.
        counts = {
            key: sum(int(suite.attrib.get(key, '0')) for suite in suites)
            for key in ('tests', 'failures', 'errors', 'skipped')
        }
        if result == 0 and (
            counts['tests'] != 2 or any(counts[key] for key in ('failures', 'errors', 'skipped'))
        ):
            raise RuntimeError('required real-service tests did not both execute successfully')
        if result == 0 and args.with_index_jobs:
            index_jobs(args.source_dir.resolve(), output, environment, configuration)
        receipt = {
            'fixture_only': True,
            'real_services': ['PostgreSQL18.6/pgvector0.8.7', 'Neo4j5.26'],
            'provider': 'scripted; no SDK',
            'paid_calls': 0,
            'deployment': False,
            'pytest_exit': result,
            'test_counts': counts,
            'offline_index_jobs': 2 if result == 0 and args.with_index_jobs else 0,
            'login_roles_created': len(roles),
            'login_roles_non_owner': True,
            'scope': 'owned isolated services'
            if args.services_config is None
            else 'borrowed exclusively leased services',
        }
        (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    except Exception as error:  # noqa: BLE001 - never render DSNs, passwords or SQL exception details
        result = 1
        receipt['failure_class'] = type(error).__name__
        print(f'Graph HTTP fixture failed ({type(error).__name__}); inspect private artifacts.')
    finally:
        if values is not None and roles:
            try:
                asyncio.run(cleanup(values, roles))
            except Exception as error:  # noqa: BLE001 - preserve private errors without raw values
                print(f'Owned fixture role cleanup failed ({type(error).__name__}); manual cleanup required.')
                result = 1
        try:
            if private_created and private.exists():
                private.unlink()
        except Exception as error:  # noqa: BLE001 - file cleanup must not skip owned-service cleanup
            print(f'Private fixture cleanup failed ({type(error).__name__}); inspect private artifacts.')
            result = 1
        try:
            services.close()
        except Exception as error:  # noqa: BLE001 - report cleanup failure without private details
            print(f'Owned service cleanup failed ({type(error).__name__}); inspect private artifacts.')
            result = 1
        receipt['harness_exit'] = result
        receipt['owned_login_roles_removed'] = len(roles) if result == 0 else 'inspect cleanup state'
        (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return result


if __name__ == '__main__':
    raise SystemExit(main())
