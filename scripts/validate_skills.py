"""Validate local paired skill discovery without executing skills or following URLs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

SKILL_NAMES = frozenset(
    {
        'api-change-use-case',
        'api-maintain-knowledge',
        'api-verify-release',
        'api-change-contract',
        'api-review-dependency-update',
        'api-release-and-hotfix',
    }
)


class SkillValidationError(ValueError):
    """A local instruction or discovery boundary is malformed."""


def require(value: object, reason: str) -> None:
    if not value:
        raise SkillValidationError(reason)


def scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise SkillValidationError('Invalid quoted frontmatter scalar') from error
        require(isinstance(parsed, str), 'Frontmatter value must be text')
        return str(parsed)
    if value.startswith("'"):
        require(re.fullmatch(r"'(?:[^']|'')*'", value), 'Invalid quoted scalar')
        return value[1:-1].replace("''", "'")
    require(
        value.lower() not in {'true', 'false', 'null', '~'}
        and not value.startswith(('[', '{'))
        and not re.fullmatch(r'[-+]?\d+(?:\.\d+)?', value),
        'Frontmatter value must be text',
    )
    return value


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    require(lines and lines[0] == '---', 'Missing frontmatter')
    try:
        end = lines.index('---', 1)
    except ValueError as error:
        raise SkillValidationError('Unclosed frontmatter') from error
    values: dict[str, str] = {}
    index = 1
    while index < end:
        line = lines[index]
        if not line.strip() or line.startswith('#'):
            index += 1
            continue
        match = re.fullmatch(r'([a-z][a-z0-9_-]*):\s*(.*)', line)
        require(match is not None, 'Malformed frontmatter field')
        assert match is not None
        key, value = match.groups()
        require(key not in values, 'Duplicate frontmatter field')
        following: list[str] = []
        index += 1
        while index < end and (lines[index].startswith((' ', '\t')) or not lines[index].strip()):
            following.append(lines[index].strip())
            index += 1
        if key == 'metadata':
            require(not value, 'Metadata must be an indented block')
            values[key] = '\n'.join(line for line in following if line)
            continue
        if key not in {'name', 'description'}:
            # Optional metadata is not interpreted or executed by this validator.
            values[key] = value
            continue
        if value in {'>', '|', '>-', '|-'}:
            values[key] = (' ' if value.startswith('>') else '\n').join(following).strip()
        else:
            require(not following or not any(following), 'Unexpected scalar continuation')
            values[key] = scalar(value)
    require(values.get('name') and values.get('description'), 'Name and description are required')
    return values, '\n'.join(lines[end + 1 :]).strip()


def metadata_block(raw: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in raw.splitlines():
        match = re.fullmatch(r'([a-z][a-z0-9_-]*):\s*(\S.*)', line)
        require(match is not None, 'Malformed metadata entry')
        assert match is not None
        require(match.group(1) not in entries, 'Duplicate metadata entry')
        entries[match.group(1)] = match.group(2).strip()
    return entries


def validate_metadata(name: str, raw: str | None) -> None:
    require(raw, name + ': metadata block missing')
    assert raw is not None
    entries = metadata_block(raw)
    require(
        {'owner', 'last-reviewed', 'version'} <= entries.keys(),
        name + ': metadata needs owner, last-reviewed and version',
    )
    require(entries['owner'], name + ': metadata owner is empty')
    reviewed = entries['last-reviewed']
    require(re.fullmatch(r'\d{4}-\d{2}-\d{2}', reviewed), name + ': last-reviewed must be YYYY-MM-DD')
    try:
        date.fromisoformat(reviewed)
    except ValueError as error:
        raise SkillValidationError(name + ': last-reviewed is not a real date') from error
    require(re.fullmatch(r'\d+\.\d+\.\d+', entries['version']), name + ': version must be semver X.Y.Z')


def validate_triggers(name: str, folder: Path) -> None:
    path = folder / 'evals/triggers.json'
    require(path.is_file() and not path.is_symlink(), name + ': evals/triggers.json is required')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise SkillValidationError(name + ': triggers.json is not valid JSON') from error
    require(isinstance(data, dict), name + ': triggers.json must be an object')
    require(data.get('skill') == name, name + ': triggers.json skill does not match directory')
    queries = data.get('queries')
    require(isinstance(queries, list) and queries, name + ': triggers.json queries must be non-empty')
    assert isinstance(queries, list)
    flags: set[bool] = set()
    for entry in queries:
        require(
            isinstance(entry, dict)
            and isinstance(entry.get('query'), str)
            and entry['query'].strip()
            and isinstance(entry.get('should_trigger'), bool)
            and entry.get('split') in {'train', 'validation'},
            name + ': malformed trigger query',
        )
        flags.add(entry['should_trigger'])
    require(flags == {True, False}, name + ': triggers.json needs a positive and a negative query')


def inside(path: Path, root: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SkillValidationError('Broken local reference') from error
    require(resolved.is_relative_to(root), 'Local reference escapes checkout')
    return resolved


def validate(root: Path) -> list[str]:
    root = root.resolve(strict=True)
    canonical = root / '.agents/skills'
    discovery = root / '.claude/skills'
    require(
        canonical.is_dir()
        and not canonical.is_symlink()
        and discovery.is_dir()
        and not discovery.is_symlink(),
        'Both skill roots must be real directories',
    )
    require(
        {path.name for path in canonical.iterdir()} == SKILL_NAMES
        and {path.name for path in discovery.iterdir()} == SKILL_NAMES,
        'Six existing paired skill directories are required',
    )
    inside(canonical, root)
    inside(discovery, root)
    descriptions: set[str] = set()
    bodies: set[str] = set()
    for name in sorted(SKILL_NAMES):
        folder, link = canonical / name, discovery / name
        require(folder.is_dir() and not folder.is_symlink(), name + ': canonical directory must be real')
        require(link.is_symlink(), name + ': discovery must be a directory symlink, never a wrapper copy')
        require(
            link.readlink().as_posix() == '../../.agents/skills/' + name
            and inside(link, root) == folder.resolve(),
            name + ': incorrect discovery target',
        )
        skill = folder / 'SKILL.md'
        require(skill.is_file() and not skill.is_symlink(), name + ': canonical SKILL.md must be real')
        text = skill.read_text(encoding='utf-8')
        metadata, body = frontmatter(text)
        require(
            metadata['name'] == name and re.fullmatch(r'[a-z0-9-]{1,63}', metadata['name']),
            name + ': name does not match directory',
        )
        validate_metadata(name, metadata.get('metadata'))
        validate_triggers(name, folder)
        description = metadata['description']
        require(re.search(r'\bNot (?:for|an authorization)\b', description), name + ': exclusions missing')
        require(description not in descriptions, name + ': duplicate description')
        descriptions.add(description)
        fingerprint = hashlib.sha256(body.encode()).hexdigest()
        require(body and fingerprint not in bodies, name + ': missing or duplicate procedure')
        bodies.add(fingerprint)
        require(re.search(r'^## Limits$', body, re.MULTILINE), name + ': limits missing')
        require(
            not re.search(r'\b(?:TODO|FIXME|TBD|INSERT_HERE|REPLACE_ME)\b|/home/|/Users/', text),
            name + ': unfinished scaffold or machine-specific path',
        )
        require(
            not re.search(
                r'\bsk-[A-Za-z0-9_-]{20,}|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{36,}'
                r'|\bgithub_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----',
                text,
            ),
            name + ': secret-like material',
        )
        for path in folder.rglob('*'):
            require(not path.is_symlink(), name + ': canonical resources must be real files/directories')
            inside(path, root)
            require(not path.is_dir() or any(path.iterdir()), name + ': empty resource directory')
        references = [
            root / reference.rstrip('.')
            for reference in re.findall(
                r'(?<![\w./-])((?:app|docs|evals|scripts|tests|contracts|catalog|infra|\.github)/[\w./-]+)',
                body,
            )
            if '...' not in reference
        ]
        for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)', text):
            if target.startswith(('https://', 'http://', 'mailto:', '#')):
                continue
            require('://' not in target, name + ': unsupported reference scheme')
            target = target.split('#', 1)[0]
            if target:
                references.append(folder / target)
        for reference in references:
            inside(reference, root)
        # A single physical procedure backs both clients, preserving default discovery.
        require((link / 'SKILL.md').samefile(skill), name + ': discovery does not share canonical content')
    return sorted(SKILL_NAMES)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        skills = validate(args.root)
    except (OSError, UnicodeError, SkillValidationError) as error:
        parser.exit(1, f'Skill validation failed: {error}\n')
    print(f'Validated {len(skills)} canonical skills and paired discovery links.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
