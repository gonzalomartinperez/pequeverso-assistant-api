"""Compare two single-image OCI layout tarballs and explain any difference.

Exit 0 when both manifests are identical; otherwise print the config and layer differences
(file paths with changed content, size, mode or mtime, at most 40 per layer) and exit 1.
Standard library only; reads local files produced by `docker buildx build --output type=oci`.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

Entry = tuple[str, int, int, int, str]


def blob(layout: tarfile.TarFile, digest: str) -> bytes:
    member = layout.extractfile('blobs/' + digest.replace(':', '/'))
    if member is None:
        raise ValueError(f'missing blob {digest}')
    return member.read()


def manifest(layout: tarfile.TarFile) -> tuple[str, dict[str, Any]]:
    index = json.loads(blob_from_name(layout, 'index.json'))
    digest = str(index['manifests'][0]['digest'])
    return digest, json.loads(blob(layout, digest))


def blob_from_name(layout: tarfile.TarFile, name: str) -> bytes:
    member = layout.extractfile(name)
    if member is None:
        raise ValueError(f'missing {name}')
    return member.read()


def entries(data: bytes) -> dict[str, Entry]:
    raw = gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data
    found: dict[str, Entry] = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as layer:
        for item in layer:
            content = layer.extractfile(item) if item.isfile() else None
            digest = hashlib.sha256(content.read()).hexdigest()[:12] if content else item.linkname
            found[item.name] = (item.name, item.size, item.mode, int(item.mtime), digest)
    return found


def compare(first: Path, second: Path) -> list[str]:
    report: list[str] = []
    with tarfile.open(first) as one, tarfile.open(second) as two:
        (digest_one, left), (digest_two, right) = manifest(one), manifest(two)
        if digest_one == digest_two:
            return report
        report.append(f'manifest {digest_one} != {digest_two}')
        if left['config']['digest'] != right['config']['digest']:
            report.append('config differs:')
            a = json.loads(blob(one, left['config']['digest']))
            b = json.loads(blob(two, right['config']['digest']))
            report.extend(f'  {key}' for key in sorted(set(a) | set(b)) if a.get(key) != b.get(key))
        layers = zip(left['layers'], right['layers'], strict=False)
        for number, (la, lb) in enumerate(layers):
            if la['digest'] == lb['digest']:
                continue
            report.append(f'layer {number} differs ({la["digest"][:19]} vs {lb["digest"][:19]}):')
            ea, eb = entries(blob(one, la['digest'])), entries(blob(two, lb['digest']))
            changed = sorted(name for name in set(ea) | set(eb) if ea.get(name) != eb.get(name))
            for name in changed[:40]:
                report.append(f'  {name}: {ea.get(name)} vs {eb.get(name)}')
            if len(changed) > 40:
                report.append(f'  ... {len(changed) - 40} more')
        if len(left['layers']) != len(right['layers']):
            report.append('layer count differs')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', type=Path)
    parser.add_argument('second', type=Path)
    args = parser.parse_args()
    report = compare(args.first, args.second)
    print('\n'.join(report) if report else 'identical manifests')
    return 1 if report else 0


if __name__ == '__main__':
    raise SystemExit(main())
