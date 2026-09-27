"""Regenerate catalog/catalog.v1.json from a pinned Pequeverso storefront commit.

The storefront is read through `git archive <revision>` into a temporary directory, so no
working tree, branch or index of the storefront repository is touched. Its installed
node_modules are linked read-only for the registry's own dependencies (zod).

    uv run python scripts/sync_catalog.py --storefront ../pequeverso --revision <sha>
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / 'tools' / 'catalog' / 'export.ts'
OUTPUT = ROOT / 'catalog' / 'catalog.v1.json'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--storefront', type=Path, required=True, help='local clone of gonzalomartinperez/pequeverso'
    )
    parser.add_argument('--revision', required=True, help='full commit sha to export')
    parser.add_argument('--origin', default='https://pequeverso.com')
    parser.add_argument('--generated-at', default=None, help='ISO timestamp (defaults to now, UTC)')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()

    storefront = args.storefront.resolve()
    revision = subprocess.run(
        ['git', '-C', str(storefront), 'rev-parse', '--verify', f'{args.revision}^{{commit}}'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    archive = subprocess.run(
        ['git', '-C', str(storefront), 'archive', revision], check=True, capture_output=True
    ).stdout
    generated_at = args.generated_at or datetime.now(UTC).replace(microsecond=0).isoformat()

    with tempfile.TemporaryDirectory(prefix='pv-catalog-') as tmp:
        tree = Path(tmp)
        with tarfile.open(fileobj=BytesIO(archive)) as tar:
            tar.extractall(tree, filter='data')
        (tree / 'node_modules').symlink_to(storefront / 'node_modules', target_is_directory=True)
        exporter = tree / '__assistant_export.ts'
        exporter.write_text(EXPORTER.read_text())
        env = {
            'PATH': os.environ['PATH'],
            'HOME': os.environ.get('HOME', tmp),
            'NEXT_PUBLIC_SITE_URL': args.origin,
        }
        result = subprocess.run(
            ['node', str(exporter), args.origin, revision, generated_at],
            cwd=tree,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    args.output.write_text(result.stdout)
    print(f'wrote {args.output.relative_to(ROOT)} from {revision[:12]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
