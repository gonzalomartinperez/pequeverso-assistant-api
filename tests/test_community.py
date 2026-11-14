"""Community files, the AGENTS/justfile command parity and the retired-domain ban."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RETIRED_DOMAIN = 'digitalproducts' + 'team.com'


def _norm(text: str) -> str:
    return ' '.join(text.split())


def _justfile_check() -> str:
    lines = (ROOT / 'justfile').read_text(encoding='utf-8').splitlines()
    start = lines.index('check:')
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith((' ', '\t')):
            break
        if line.strip():
            body.append(line.strip())
    return _norm(' '.join(body))


def _agents_before_a_pr() -> str:
    text = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
    after = text.split('Before a PR:', 1)[1]
    chain = re.findall(r'`(uv run [^`]+)`', after)[0]
    return _norm(chain)


def test_agents_before_a_pr_equals_justfile_check() -> None:
    assert _agents_before_a_pr() == _justfile_check()
    assert _justfile_check().startswith('uv run ruff check . && ')


def test_retired_domain_is_absent_outside_plan_and_changelog() -> None:
    tracked = subprocess.run(
        ['git', 'ls-files', '-z'],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b'\0')
    offenders: list[str] = []
    for raw in tracked:
        if not raw:
            continue
        rel = raw.decode()
        if rel.startswith('docs/master-plan/') or rel == 'CHANGELOG.md':
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b'\0' in data:
            continue
        if RETIRED_DOMAIN in data.decode('utf-8', errors='ignore').lower():
            offenders.append(rel)
    assert offenders == []


def test_community_files_exist() -> None:
    for name in (
        'SECURITY.md',
        'SUPPORT.md',
        'CODE_OF_CONDUCT.md',
        'CONTRIBUTING.md',
        '.github/CODEOWNERS',
        '.github/PULL_REQUEST_TEMPLATE.md',
        '.github/ISSUE_TEMPLATE/bug.yml',
        '.github/ISSUE_TEMPLATE/feature.yml',
        '.github/ISSUE_TEMPLATE/assistant-answer.yml',
        '.github/ISSUE_TEMPLATE/config.yml',
    ):
        assert (ROOT / name).is_file(), name
    config = yaml.safe_load((ROOT / '.github/ISSUE_TEMPLATE/config.yml').read_text('utf-8'))
    assert config['blank_issues_enabled'] is False
    form = yaml.safe_load((ROOT / '.github/ISSUE_TEMPLATE/assistant-answer.yml').read_text('utf-8'))
    assert form['labels'] == ['bug', 'assistant-quality']


def test_security_policy_has_no_retired_domain_or_mailto() -> None:
    text = (ROOT / 'SECURITY.md').read_text(encoding='utf-8').lower()
    assert RETIRED_DOMAIN not in text
    assert 'mailto:' not in text
