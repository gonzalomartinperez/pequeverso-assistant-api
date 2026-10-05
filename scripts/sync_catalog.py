"""Regenerate catalog/catalog.v1.json from a *published* Pequeverso storefront commit.

    uv run python scripts/sync_catalog.py --storefront ../pequeverso --revision <sha>

Guarantees:
- Only published content: the revision must be reachable from the storefront's production
  branch (`origin/main` by default; fetch it first). A develop-only change cannot alter prices or
  promises the assistant makes in production.
- Read-only on the storefront: the commit is read with `git archive` into a temporary directory;
  no working tree, branch or index is touched. Its installed node_modules are linked read-only.
- Validated before writing: the exporter's output must pass the runtime catalog schema; on any
  failure the committed snapshot is left untouched.
- Reviewable provenance: `catalog/sync-report.json` records the source revision, the previous
  revision, hashes (snapshot, exporter), times and a semantic diff (retired products, price,
  resource, document and link changes). Review it in the PR like any code change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.adapters.catalog_schema import CatalogParser
from app.application.catalog_diff import diff
from app.bootstrap.config import Settings
from app.domain.catalog import Catalog

EXPORTER = ROOT / 'tools' / 'catalog' / 'export.ts'
OUTPUT = ROOT / 'catalog' / 'catalog.v1.json'
REPORT = ROOT / 'catalog' / 'sync-report.json'


def _git(storefront: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['git', '-C', str(storefront), *args], check=check, capture_output=True, text=True)


def _parser() -> CatalogParser:
    return CatalogParser(frozenset(Settings.model_fields['catalog_allowed_hosts'].default))


def _previous(path: Path) -> Catalog | None:
    try:
        return _parser()(path.read_bytes())
    except (OSError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--storefront', type=Path, required=True, help='local clone of gonzalomartinperez/pequeverso'
    )
    parser.add_argument('--revision', required=True, help='full commit sha to export')
    parser.add_argument(
        '--published-ref', default='origin/main', help='production branch the revision must be on'
    )
    parser.add_argument('--origin', default='https://pequeverso.com')
    parser.add_argument('--generated-at', default=None, help='ISO timestamp (defaults to now, UTC)')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--report', type=Path, default=REPORT)
    args = parser.parse_args()

    storefront = args.storefront.resolve()
    revision = _git(storefront, 'rev-parse', '--verify', f'{args.revision}^{{commit}}').stdout.strip()
    published = _git(storefront, 'merge-base', '--is-ancestor', revision, args.published_ref, check=False)
    if published.returncode != 0:
        print(
            f'refused: {revision[:12]} is not reachable from {args.published_ref} (unpublished content); '
            f'fetch the storefront and sync a commit that is live in production',
            file=sys.stderr,
        )
        return 2
    archive = _git_bytes(storefront, 'archive', revision)
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

    body = result.stdout.encode()
    try:
        catalog = _parser()(body)
    except ValueError as error:
        print(f'refused: exported catalog failed validation ({error}); snapshot unchanged', file=sys.stderr)
        return 3
    previous = _previous(args.output)
    changes = diff(previous, catalog)
    report = {
        'schema_version': 1,
        'source': {
            'repository': 'gonzalomartinperez/pequeverso',
            'revision': revision,
            'published_ref': args.published_ref,
        },
        'previous_revision': previous.source_revision if previous else None,
        'generated_at': generated_at,
        'snapshot_sha256': hashlib.sha256(body).hexdigest(),
        'exporter_sha256': hashlib.sha256(EXPORTER.read_bytes()).hexdigest(),
        'counts': {
            'products': len(catalog.products),
            'resources': sum(len(p.resources) for p in catalog.products),
            'documents': len(catalog.documents),
            'links': len(catalog.links),
        },
        'changes': changes.as_dict(),
    }
    args.output.write_bytes(body)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(
        f'wrote {args.output.name} from {revision[:12]} ({"no fact changes" if changes.empty else "fact changes"})'
    )
    if changes.products_retired:
        print('retired products: ' + ', '.join(changes.products_retired))
    for product, (before, after) in changes.price_changes.items():
        print(f'price change {product}: {before} -> {after}')
    return 0


def _git_bytes(storefront: Path, *args: str) -> bytes:
    return subprocess.run(['git', '-C', str(storefront), *args], check=True, capture_output=True).stdout


if __name__ == '__main__':
    sys.exit(main())
