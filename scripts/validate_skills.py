"""Validate local paired skill discovery without executing skills or following URLs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
        require(value.endswith("'") and len(value) >= 2, 'Invalid quoted scalar')
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


def inside(path: Path, root: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SkillValidationError('Broken local reference') from error
    require(resolved.is_relative_to(root), 'Local reference escapes checkout')
    return resolved


def validate(root: Path) -> list[str]:
    root = root.resolve(strict=True)
    canonical = root / '.claude/skills'
    discovery = root / '.agents/skills'
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
            link.readlink().as_posix() == '../../.claude/skills/' + name
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
                r'\bsk-[A-Za-z0-9_-]{20,}|\bAKIA[0-9A-Z]{16}\b|-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----',
                text,
            ),
            name + ': secret-like material',
        )
        require(
            'merge to main' not in text.lower() and 'deploy to production' not in text.lower(),
            name + ': standing authorization phrase',
        )
        for path in folder.rglob('*'):
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
