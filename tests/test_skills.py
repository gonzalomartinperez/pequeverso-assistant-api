"""Skills: canonical files in .agents/skills, thin Claude adapters with identical frontmatter."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / '.agents' / 'skills'
ADAPTERS = ROOT / '.claude' / 'skills'
FRONTMATTER = re.compile(r'\A---\nname: ([a-z0-9-]+)\ndescription: (.+?)\n---\n', re.DOTALL)


def test_every_skill_has_valid_frontmatter_and_an_adapter() -> None:
    names = sorted(p.name for p in CANONICAL.iterdir() if p.is_dir())
    assert names, 'no skills found'
    assert names == sorted(p.name for p in ADAPTERS.iterdir() if p.is_dir())
    for name in names:
        canonical = (CANONICAL / name / 'SKILL.md').read_text()
        adapter = (ADAPTERS / name / 'SKILL.md').read_text()
        match = FRONTMATTER.match(canonical)
        assert match and match.group(1) == name
        assert FRONTMATTER.match(adapter) and FRONTMATTER.match(adapter).group(0) == match.group(0)  # type: ignore[union-attr]
        assert f'.agents/skills/{name}/SKILL.md' in adapter


def test_skills_reference_existing_paths() -> None:
    for skill in CANONICAL.glob('*/SKILL.md'):
        for path in re.findall(
            r'`((?:app|docs|evals|scripts|tests|contracts|catalog)/[\w./-]+)`', skill.read_text()
        ):
            assert (ROOT / path.split(' ')[0]).exists(), f'{skill.parent.name}: {path}'


def test_no_skill_grants_standing_authorization() -> None:
    for skill in CANONICAL.glob('*/SKILL.md'):
        text = skill.read_text().lower()
        assert 'merge to main' not in text
        assert 'deploy to production' not in text


def test_every_skill_states_its_limits_and_exclusions() -> None:
    descriptions: set[str] = set()
    for skill in sorted(CANONICAL.glob('*/SKILL.md')):
        text = skill.read_text()
        match = FRONTMATTER.match(text)
        assert match, skill
        description = match.group(2)
        assert re.search(r'\bNot (for|an authorization)\b', description), f'{skill.parent.name}: exclusions'
        assert description not in descriptions, f'{skill.parent.name}: duplicate description'
        descriptions.add(description)
        assert re.search(r'^## Limits$', text, re.MULTILINE), f'{skill.parent.name}: Limits section'
        assert not re.search(r'\b(TODO|FIXME|TBD)\b|/home/|/Users/', text), (
            f'{skill.parent.name}: placeholder or path'
        )
        assert not re.search(r'\bsk-[A-Za-z0-9]{20,}', text), f'{skill.parent.name}: secret-like token'


def test_adapters_stay_thin() -> None:
    for adapter in ADAPTERS.glob('*/SKILL.md'):
        body = FRONTMATTER.sub('', adapter.read_text()).strip()
        assert len(body.splitlines()) <= 3, (
            f'{adapter.parent.name}: adapter must only point to the canonical skill'
        )
