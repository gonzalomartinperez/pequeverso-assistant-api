"""Record content-free evidence for isolated CI candidates; never publish images."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

BUILD_INPUTS = (
    '.github/workflows/quality.yml',
    '.python-version',
    '.dockerignore',
    'infra/docker/app/Dockerfile',
    'infra/docker/postgres/Dockerfile',
    'infra/docker/postgres/Dockerfile.dockerignore',
    'infra/docker/neo4j/Dockerfile',
    'infra/docker/neo4j/Dockerfile.dockerignore',
    'infra/docker/neo4j/neo4j.conf',
    'pyproject.toml',
    'uv.lock',
)
IMAGES = frozenset({'pequeverso-assistant-api:smoke', 'pv-knowledge-pg:ci', 'pv-knowledge-neo:ci'})


def identity(root: Path, env: dict[str, str]) -> dict[str, object]:
    source = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if env.get('GITHUB_SHA') != source:
        raise ValueError('Checked-out source differs from the CI candidate')
    workflow = env.get('GITHUB_WORKFLOW_SHA', '')
    base = env.get('CI_BASE_SHA', '')
    if not re.fullmatch(r'[a-f0-9]{40}', workflow) or (base and not re.fullmatch(r'[a-f0-9]{40}', base)):
        raise ValueError('Invalid workflow/base revision')
    for name in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
        if not re.fullmatch(r'[1-9][0-9]*', env.get(name, '')):
            raise ValueError('Invalid CI run identity')
    clean = subprocess.run(
        ['git', '-C', str(root), 'diff', '--quiet', 'HEAD', '--'], capture_output=True, check=False
    )
    if clean.returncode != 0:
        raise ValueError('Tracked inputs differ from the reviewed source')
    return {
        'schema_version': 1,
        'source_sha': source,
        'base_sha': base or None,
        'workflow_sha': workflow,
        'run_id': env['GITHUB_RUN_ID'],
        'run_attempt': env['GITHUB_RUN_ATTEMPT'],
        'job': env.get('GITHUB_JOB'),
        'platform': {'os': env.get('RUNNER_OS'), 'architecture': env.get('RUNNER_ARCH')},
        'build_inputs_sha256': {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in BUILD_INPUTS
        },
        'image_transport': 'none; isolated same-source builds only',
    }


def image_identity(image: str) -> str:
    if image not in IMAGES:
        raise ValueError('Unexpected CI image reference')
    digest = subprocess.check_output(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'], text=True)
    digest = digest.strip()
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('Invalid local image identity')
    return digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', action='append', default=[])
    args = parser.parse_args()
    report = identity(Path.cwd(), dict(os.environ))
    report['images'] = {image: image_identity(image) for image in args.image}
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
