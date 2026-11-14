from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

from scripts.compare_oci_images import compare


def add(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def layer(files: dict[str, bytes], mtime: int = 0) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime = len(data), mtime
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def layout(path: Path, files: dict[str, bytes], mtime: int = 0) -> Path:
    blobs: dict[str, bytes] = {}

    def store(data: bytes) -> str:
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        blobs[digest] = data
        return digest

    config = store(json.dumps({"architecture": "amd64"}).encode())
    first = store(layer(files, mtime))
    manifest = store(
        json.dumps(
            {"config": {"digest": config}, "layers": [{"digest": first}]}, sort_keys=True
        ).encode()
    )
    with tarfile.open(path, "w") as archive:
        add(archive, "index.json", json.dumps({"manifests": [{"digest": manifest}]}).encode())
        for digest, data in blobs.items():
            add(archive, "blobs/" + digest.replace(":", "/"), data)
    return path


def test_identical_layouts_report_nothing(tmp_path: Path) -> None:
    one = layout(tmp_path / "one.tar", {"app/a.py": b"x"})
    two = layout(tmp_path / "two.tar", {"app/a.py": b"x"})
    assert compare(one, two) == []


def test_differences_name_the_layer_and_file(tmp_path: Path) -> None:
    one = layout(tmp_path / "one.tar", {"app/a.py": b"x", "app/b.py": b"same"})
    two = layout(tmp_path / "two.tar", {"app/a.py": b"x", "app/b.py": b"same"}, mtime=5)
    report = compare(one, two)
    assert report[0].startswith("manifest ")
    assert any(line.startswith("layer 0 differs") for line in report)
    assert any("app/a.py" in line for line in report)
