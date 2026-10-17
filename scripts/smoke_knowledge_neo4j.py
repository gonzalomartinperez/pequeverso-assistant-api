"""Isolated local candidate-image smoke; never deploys, publishes or contacts a provider."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bootstrap.knowledge_evaluation import (
    fixture_corpus,
    safe_exception_hook,
    wait_for_fixture_projection,
)
from app.domain.knowledge import ProjectionStamp


def command(arguments: list[str]) -> str:
    result = subprocess.run(arguments, check=True, capture_output=True, text=True)
    return result.stdout.strip()


class GraphFixture:
    def __init__(self, image: str, receipt: Path, private: Path) -> None:
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
            raise ValueError('an immutable local candidate image ID is required')
        if any(p.resolve().is_relative_to(ROOT) for p in (receipt, private)):
            raise ValueError('receipts and private fixtures must stay outside the source checkout')
        self.image = image
        self.receipt = receipt
        self.private = private / f'neo4j-{uuid.uuid4().hex}'
        self.private.mkdir(parents=True, mode=0o700)
        self.private.chmod(0o700)
        self.receipt.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.backup = self.private / 'backup'
        self.backup.mkdir(mode=0o777)
        self.backup.chmod(0o777)  # Enclosed by a 0700 host-only parent; runtime UID owns dump files.
        self.password = secrets.token_hex(24)
        self.auth = self.private / 'neo4j-auth'
        self.auth.write_text(f'neo4j/{self.password}')
        self.auth.chmod(0o444)  # Read-only bind for UID7474; host parent prevents other-user traversal.
        self.prefix = f'pv-peque-neo-fixture-{uuid.uuid4().hex[:12]}'
        self.container = f'{self.prefix}-server'
        self.network = f'{self.prefix}-net'
        self.volumes = (f'{self.prefix}-data', f'{self.prefix}-restore')
        self.created: list[tuple[str, str]] = []
        self.result: dict[str, object] = {
            'image_id': image,
            'fixture_only': True,
            'provider_calls': 0,
            'paid_calls': 0,
            'production_security_gate': 'BLOCKED: upstream CVEs require disposition; no waiver',
            'network': 'dedicated bridge, host ports loopback only; not an egress firewall',
            'capacity': 'functional local cgroup evidence, not a VPS capacity benchmark',
        }

    def runtime(self, volume: str) -> None:
        args = [
            'docker',
            'run',
            '-d',
            '--name',
            self.container,
            '--network',
            self.network,
            '--user',
            '7474:7474',
            '--read-only',
            '--cap-drop',
            'ALL',
            '--security-opt',
            'no-new-privileges:true',
            '--cpus',
            '1',
            '--memory',
            '768m',
            '--memory-swap',
            '768m',
            '--pids-limit',
            '256',
            '--stop-timeout',
            '30',
            '--mount',
            f'type=volume,src={volume},dst=/data',
            '--mount',
            f'type=bind,src={self.auth},dst=/run/secrets/neo4j-auth,readonly',
        ]
        for path, mode, size in (
            ('/var/lib/neo4j/conf', '0700', '16m'),
            ('/var/lib/neo4j/run', '0700', '4m'),
            ('/logs', '0700', '32m'),
            ('/tmp', '1777', '64m'),  # noqa: S108 -- Container tmpfs, not host temporary storage.
        ):
            args.extend(
                ['--tmpfs', f'{path}:rw,nosuid,nodev,noexec,uid=7474,gid=7474,mode={mode},size={size}']
            )
        args.extend(
            [
                '-e',
                'NEO4J_AUTH_FILE=/run/secrets/neo4j-auth',
                '-p',
                '127.0.0.1:17689:7687',
                '-p',
                '127.0.0.1:17479:7474',
                self.image,
            ]
        )
        command(args)
        self.created.append(('container', self.container))

    def tcp_liveness(self) -> float:
        started = monotonic()
        while monotonic() - started < 120:
            state = command(
                [
                    'docker',
                    'inspect',
                    '--format',
                    '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}',
                    self.container,
                ]
            )
            if state == 'running healthy':
                return monotonic() - started
            if state.startswith('exited'):
                raise RuntimeError('fixture server exited; inspect private logs')
            # Readiness polling observes service state, never retries a paid generation.

            time.sleep(1)
        raise RuntimeError('fixture TCP liveness deadline exceeded')

    def tests(self, *, restored: bool = False) -> None:
        target = 'tests/test_neo4j_public_graph_live_service.py'
        if restored:
            target += '::test_real_bolt_existing_projection_is_verified_without_reindexing'
        # The password is synthetic and passed only in the child environment, never CLI/logs.

        environment = dict(
            os.environ,
            PV_TEST_NEO4J_URI='bolt://127.0.0.1:17689',
            PV_TEST_NEO4J_PASSWORD=self.password,
            PYTHONPATH=str(ROOT),
        )
        started = monotonic()
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', target, '-q', '--tb=short'],
            check=False,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        label = 'restore-readonly' if restored else 'initial-bolt'
        private_log = self.private / f'{label}.log'
        private_log.write_text(result.stdout + result.stderr)
        private_log.chmod(0o600)
        passed = re.search(r'(\d+) passed', result.stdout)
        self.result[label] = {
            'exit_code': result.returncode,
            'passed': int(passed[1]) if passed else 0,
            'duration_seconds': monotonic() - started,
        }
        if result.returncode:
            raise RuntimeError('fixture assertions failed; original private log retained')

    def admin(self, volume: str, operation: str) -> None:
        args = [
            'docker',
            'run',
            '--rm',
            '--network',
            'none',
            '--user',
            '7474:7474',
            '--read-only',
            '--cap-drop',
            'ALL',
            '--security-opt',
            'no-new-privileges:true',
            '--cpus',
            '1',
            '--memory',
            '768m',
            '--memory-swap',
            '768m',
            '--pids-limit',
            '256',
            '--tmpfs',
            '/logs:rw,nosuid,nodev,noexec,uid=7474,gid=7474,mode=0700,size=32m',
            '--tmpfs',
            '/tmp:rw,nosuid,nodev,noexec,uid=7474,gid=7474,mode=1777,size=64m',  # noqa: S108 -- Container tmpfs only.
            '-e',
            'HEAP_SIZE=256M',
            '--mount',
            f'type=volume,src={volume},dst=/data',
            '--mount',
            f'type=bind,src={self.backup},dst=/backups' + (',readonly' if operation == 'load' else ''),
            '--entrypoint',
            'neo4j-admin',
            self.image,
            'database',
            operation,
            'neo4j',
            '--from-path=/backups' if operation == 'load' else '--to-path=/backups',
            '--overwrite-destination=true',
        ]
        command(args)

    def logs(self) -> None:
        result = subprocess.run(
            ['docker', 'logs', self.container], check=False, capture_output=True, text=True
        )
        path = self.private / 'server-last.log'
        path.write_text(result.stdout + result.stderr)
        path.chmod(0o600)

    def run(self) -> None:
        try:
            command(['docker', 'network', 'create', self.network])
            self.created.append(('network', self.network))
            for volume in self.volumes:
                command(['docker', 'volume', 'create', volume])
                self.created.append(('volume', volume))
            self.runtime(self.volumes[0])
            self.result['tcp_liveness_seconds'] = self.tcp_liveness()
            self.result['native_hashes'] = command(
                [
                    'docker',
                    'exec',
                    self.container,
                    'sha256sum',
                    '/var/lib/neo4j/lib/jna-5.15.0.jar',
                    '/opt/pv-native/libjnidispatch.so',
                ]
            )
            self.tests()
            self.result['memory_current_bytes'] = int(
                command(['docker', 'exec', self.container, 'cat', '/sys/fs/cgroup/memory.current'])
            )
            self.result['memory_peak_bytes'] = int(
                command(['docker', 'exec', self.container, 'cat', '/sys/fs/cgroup/memory.peak'])
            )
            self.logs()
            started = monotonic()
            command(['docker', 'stop', self.container])
            self.result['graceful_stop_seconds'] = monotonic() - started
            self.result['stop_state'] = command(
                ['docker', 'inspect', '--format', '{{.State.ExitCode}} {{.State.OOMKilled}}', self.container]
            )
            command(['docker', 'rm', self.container])
            self.created.remove(('container', self.container))
            self.admin(self.volumes[0], 'dump')
            self.result['dump_bytes'] = (self.backup / 'neo4j.dump').stat().st_size
            self.admin(self.volumes[1], 'load')
            self.runtime(self.volumes[1])
            self.result['restored_tcp_liveness_seconds'] = self.tcp_liveness()
            corpus = fixture_corpus()
            expected = ProjectionStamp(
                corpus.revision.version,
                corpus.revision.catalog_sha256,
                len(corpus.chunks),
                len(corpus.entities),
                len(corpus.relations),
            )
            proof = asyncio.run(
                wait_for_fixture_projection('bolt://127.0.0.1:17689', 'neo4j', self.password, expected)
            )
            self.result['restored_readiness'] = asdict(proof)
            if not proof.ready:
                raise RuntimeError('restored projection never became queryable without reindexing')
            self.tests(restored=True)
            self.result['status'] = 'PASS'
        finally:
            self.logs()
            # Remove only resources this exact invocation successfully created.
            for kind in ('container', 'volume', 'network'):
                for created_kind, name in reversed(self.created):
                    if kind == created_kind:
                        args = ['docker', kind, 'rm'] + (['-f'] if kind == 'container' else []) + [name]
                        subprocess.run(args, check=False, capture_output=True, text=True)
            self.auth.unlink(missing_ok=True)
            self.result.setdefault('status', 'FAIL; inspect private logs')
            (self.receipt / 'receipt.json').write_text(json.dumps(self.result, indent=2) + '\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--private-dir', required=True, type=Path)
    args = parser.parse_args()
    GraphFixture(args.image, args.receipt, args.private_dir).run()


if __name__ == '__main__':
    sys.excepthook = safe_exception_hook
    main()
