"""Validate the reference examples against the published v1 contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
DOC = ROOT / "docs/reference/api-contract.md"
MARKER = re.compile(
    r"^<!-- example: ([A-Z]+) (\S+) (?:request|response ([1-5]\d{2})) -->\n", re.MULTILINE
)
EXAMPLE = re.compile(
    r"```(?P<fence>json|sse|text)\n(?P<body>.*?)\n```$"
    r"|\[[^\]\n]+\]\(\.\./\.\./contracts/examples/(?P<file>[\w.-]+\.json)"
    r"(?:#/(?P<member>\w+))?\)$",
    re.MULTILINE | re.DOTALL,
)
MEDIA_TYPES = {"json": "application/json", "sse": "text/event-stream", "text": "text/plain"}
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_sse(excerpt: str) -> None:
    fixture = CONTRACTS / "examples/stream.recommendation.sse"
    assert fixture.read_text(encoding="utf-8").startswith(excerpt + "\n\n")
    schema = _read_json(CONTRACTS / "sse.schema.json")
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    for frame in excerpt.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in frame.splitlines())
        assert fields["event"] in schema["discriminator"]["mapping"]
        payload = json.loads(fields["data"])
        assert payload["type"] == fields["event"]
        validator.validate(payload)


def _example_value(example: re.Match[str]):
    if example["file"]:
        value = _read_json(CONTRACTS / "examples" / example["file"])
        return value[example["member"]] if example["member"] else value
    return json.loads(example["body"]) if example["fence"] == "json" else example["body"]


def _operations():
    operations = {}
    for name in ("openapi.json", "openapi.internal.json"):
        spec = _read_json(CONTRACTS / name)
        for path, path_item in spec["paths"].items():
            for method in path_item.keys() & HTTP_METHODS:
                operations[method.upper(), path] = (path_item[method], spec["components"])
    return operations


def test_documented_examples_match_the_contract() -> None:
    operations = _operations()
    doc = DOC.read_text(encoding="utf-8")
    markers = list(MARKER.finditer(doc))
    assert len(markers) == len(re.findall(r"^<!-- example:", doc, re.MULTILINE))
    covered = set()
    json_fences = set()
    for marker in markers:
        method, path, status = marker.groups()
        label = marker[0].strip()
        assert (method, path) in operations, label
        operation, components = operations[method, path]
        example = EXAMPLE.match(doc, marker.end())
        assert example is not None, label

        kind = example["fence"] or "json"
        if example["fence"] == "json":
            json_fences.add(example.start())
        message = operation["requestBody"] if status is None else operation["responses"][status]
        media = message["content"][MEDIA_TYPES[kind]]
        if kind == "sse":
            _validate_sse(example["body"])
        else:
            # Keep components at the root so references inside the selected schema can resolve.
            schema = {"components": components, **media["schema"]}
            validator = Draft202012Validator(
                schema, format_checker=Draft202012Validator.FORMAT_CHECKER
            )
            errors = [error.message for error in validator.iter_errors(_example_value(example))]
            assert not errors, f"{label}\n" + "\n".join(errors)
        covered.add((method, path))

    assert json_fences == {match.start() for match in re.finditer(r"^```json$", doc, re.MULTILINE)}
    missing = operations.keys() - covered
    assert not missing, sorted(missing)
