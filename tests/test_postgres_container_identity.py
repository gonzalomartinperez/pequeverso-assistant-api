from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:' + 'a' * 64


class PostgresSmokeIdentityTests(unittest.TestCase):
    def invoke_smoke(self, identity: object) -> list[list[str]]:
        """Exercise the actual shell harness; the fake Docker stops before any server starts."""
        with tempfile.TemporaryDirectory(prefix='pv-pg-identity-') as temporary:
            private = Path(temporary)
            calls = private / 'docker-calls.jsonl'
            fake = private / 'docker'
            fake.write_text(
                '#!/usr/bin/env python3\n'
                'import json,os,sys\n'
                'args=sys.argv[1:]\n'
                'with open(os.environ["FAKE_DOCKER_CALLS"],"a") as f:\n'
                '    f.write(json.dumps(args)+"\\n")\n'
                'if args[:2]==["image","inspect"]:\n'
                '    if ".Config.User" in " ".join(args):\n'
                '        print(os.environ["FAKE_POSTGRES_USER_JSON"])\n'
                '    else:\n'
                '        print(json.dumps(["postgres"]))\n'
                'if args and args[0]=="run":\n'
                '    sys.exit(77)\n'
            )
            fake.chmod(0o700)
            environment = dict(os.environ)
            environment.update(
                PATH=str(private) + os.pathsep + os.environ['PATH'],
                FAKE_DOCKER_CALLS=str(calls),
                FAKE_POSTGRES_USER_JSON=json.dumps(identity),
            )
            completed = subprocess.run(
                ['bash', str(ROOT / 'scripts/smoke_knowledge_postgres.sh'), IMAGE, str(private / 'receipt')],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            assert completed.returncode != 0, 'fake Docker must never start PostgreSQL'
            return [json.loads(line) for line in calls.read_text().splitlines()]

    def test_alpine_image_uses_its_declared_nonroot_identity_and_socket_owner(self) -> None:
        calls = self.invoke_smoke('70:70')
        command = next(args for args in calls if args[0] == 'run')
        assert command[command.index('--user') + 1] == '70:70'
        assert '/var/run/postgresql:rw,nosuid,noexec,uid=70,gid=70,mode=3775,size=16m' in command
        assert '--read-only' in command
        assert 'no-new-privileges' in command

    def test_root_image_is_refused_before_any_runtime_resource_creation(self) -> None:
        for identity in ('0:0', 'root', '', None, '70:0', '70:70 --privileged'):
            with self.subTest(identity=identity):
                calls = self.invoke_smoke(identity)
                assert not any(args[0] == 'run' for args in calls)
                assert not any(args[:2] in (['network', 'create'], ['volume', 'create']) for args in calls)

    def test_historical_debian_fixture_retains_its_explicit_identity(self) -> None:
        calls = self.invoke_smoke('999:999')
        command = next(args for args in calls if args[0] == 'run')
        assert command[command.index('--user') + 1] == '999:999'


class PostgresIdentityBoundaryTests(unittest.TestCase):
    def test_only_reviewed_numeric_pairs_are_accepted(self) -> None:
        from scripts.postgres_fixture_identity import postgres_fixture_identity

        for valid in ('70:70', '999:999'):
            assert postgres_fixture_identity(valid) == valid
        for invalid in (None, 70, True, {}, [], '', 'root', '0:0', '70', '70:0', '0:70', '070:070', '70:70\n', '65532:65532'):
            try:
                postgres_fixture_identity(invalid)
            except ValueError:
                continue
            raise AssertionError('unsupported image identity was accepted')

    def test_cli_bounds_input_and_does_not_echo_rejected_metadata(self) -> None:
        for value in ('0:0', '70:70 --privileged', 'PRIVATE_CANARY_' + 'x' * 300):
            result = subprocess.run(
                [sys.executable, str(ROOT / 'scripts/postgres_fixture_identity.py')],
                input=json.dumps(value),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            assert result.returncode == 2
            assert result.stdout == ''
            assert value not in result.stderr


class GraphPostgresIdentityTests(unittest.TestCase):
    def test_graph_harness_uses_both_reviewed_profiles_and_rejects_root_before_creation(self) -> None:
        from scripts import smoke_graph_runtime as harness

        class DispatchObservedError(Exception):
            pass

        fake_module = ModuleType('scripts.smoke_knowledge_neo4j')

        def fake_graph(*_args: object) -> SimpleNamespace:
            return SimpleNamespace(network='own-net', volumes=['own-neo-data'], container='own-neo')

        fake_module.__dict__['GraphFixture'] = fake_graph
        for identity in ('70:70', '999:999', '0:0', ''):
            with tempfile.TemporaryDirectory(prefix='pv-graph-pg-identity-') as temporary:
                output = Path(temporary) / 'receipt'
                output.mkdir()
                calls: list[list[str]] = []

                def docker(arguments: list[str]) -> str:
                    calls.append(arguments)
                    if '.Config.User' in ' '.join(arguments):
                        return json.dumps(identity)
                    if '.Config.Cmd' in ' '.join(arguments):
                        return json.dumps(['postgres'])
                    if arguments[0] == 'run':
                        raise DispatchObservedError
                    return ''

                with (
                    patch.dict('sys.modules', {'scripts.smoke_knowledge_neo4j': fake_module}),
                    patch.object(harness, 'docker', docker),
                    patch.object(harness, 'resource_exists', return_value=False),
                    patch.object(harness, 'teardown_services'),
                ):
                    try:
                        with harness.owned_services(IMAGE, IMAGE, output, ROOT):
                            raise AssertionError('fake Docker must stop before starting a real service')
                    except (DispatchObservedError, ValueError):
                        pass
                commands = [args for args in calls if args[0] == 'run']
                if identity in ('70:70', '999:999'):
                    assert len(commands) == 1
                    command = commands[0]
                    assert command[command.index('--user') + 1] == identity
                    uid, gid = identity.split(':')
                    assert f'/var/run/postgresql:rw,nosuid,noexec,uid={uid},gid={gid},mode=3775,size=16m' in command
                    assert '--read-only' in command
                    assert 'no-new-privileges:true' in command
                else:
                    assert commands == []
                    assert not any(args[:2] in (['network', 'create'], ['volume', 'create']) for args in calls)


if __name__ == '__main__':
    unittest.main()
