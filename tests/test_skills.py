"""Physical paired discovery and non-executing validation of real instruction files."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts.validate_skills import SKILL_NAMES, SkillValidationError, frontmatter, validate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    for directory in ('.claude/skills', '.agents/skills', 'docs'):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    (tmp_path / 'docs/procedure.md').write_text('Reviewed local reference.')
    for name in SKILL_NAMES:
        folder = tmp_path / '.claude/skills' / name
        folder.mkdir()
        (folder / 'SKILL.md').write_text(
            f'---\nname: {name}\ndescription: Handle {name}. Not for deployment.\n---\n\n'
            f'# {name}\n\nRead `docs/procedure.md`.\n\n## Limits\n\nProcedure only: {name}.\n'
        )
        (tmp_path / '.agents/skills' / name).symlink_to(
            '../../.claude/skills/' + name, target_is_directory=True
        )
    return tmp_path


def test_actual_repository_has_six_shared_physical_procedures() -> None:
    assert validate(ROOT) == sorted(SKILL_NAMES)
    for name in SKILL_NAMES:
        canonical = ROOT / '.claude/skills' / name / 'SKILL.md'
        assert canonical.samefile(ROOT / '.agents/skills' / name / 'SKILL.md')


@pytest.mark.parametrize('failure', ['broken', 'escape', 'wrapper-copy', 'absolute', 'wrong-skill'])
def test_discovery_rejects_broken_escaping_or_duplicated_instructions(
    checkout: Path, tmp_path: Path, failure: str
) -> None:
    name, other = sorted(SKILL_NAMES)[:2]
    link = checkout / '.agents/skills' / name
    link.unlink()
    if failure == 'broken':
        link.symlink_to('../../.claude/skills/missing', target_is_directory=True)
    elif failure == 'escape':
        outside = tmp_path.parent / 'foreign-skill'
        outside.mkdir(exist_ok=True)
        link.symlink_to(outside, target_is_directory=True)
    elif failure == 'wrapper-copy':
        shutil.copytree(checkout / '.claude/skills' / name, link)
    elif failure == 'absolute':
        link.symlink_to(checkout / '.claude/skills' / name, target_is_directory=True)
    else:
        link.symlink_to('../../.claude/skills/' + other, target_is_directory=True)
    with pytest.raises(SkillValidationError):
        validate(checkout)


@pytest.mark.parametrize(
    'failure',
    [
        'name',
        'description-copy',
        'procedure-copy',
        'duplicate-field',
        'missing-limits',
        'scaffold',
        'secret',
        'github-secret',
    ],
)
def test_metadata_limits_and_sensitive_material_fail_closed(checkout: Path, failure: str) -> None:
    name, other = sorted(SKILL_NAMES)[:2]
    path = checkout / '.claude/skills' / name / 'SKILL.md'
    text = path.read_text()
    if failure == 'name':
        text = text.replace('name: ' + name, 'name: api-other')
    elif failure == 'description-copy':
        text = text.replace('Handle ' + name, 'Handle ' + other)
    elif failure == 'procedure-copy':
        other_text = (checkout / '.claude/skills' / other / 'SKILL.md').read_text()
        text = (
            text.split('---', 2)[0]
            + '---'
            + text.split('---', 2)[1]
            + '---\n'
            + other_text.split('---', 2)[2]
        )
    elif failure == 'duplicate-field':
        text = text.replace('name: ' + name, 'name: ' + name + '\nname: ' + name)
    elif failure == 'missing-limits':
        text = text.replace('## Limits', '## Other')
    elif failure == 'scaffold':
        text += '\nTODO finish this procedure\n'
    elif failure == 'secret':
        text += '\nsk-' + 'x' * 30 + '\n'
    elif failure == 'github-secret':
        text += '\nghp_' + 'x' * 36 + '\n'
    path.write_text(text)
    with pytest.raises(SkillValidationError):
        validate(checkout)


@pytest.mark.parametrize(
    'failure',
    ['missing', 'plain-missing', 'escape', 'resource-symlink', 'inrepo-resource-symlink', 'empty-directory'],
)
def test_local_references_cannot_escape_or_point_to_missing_resources(
    checkout: Path, tmp_path: Path, failure: str
) -> None:
    folder = checkout / '.claude/skills' / min(SKILL_NAMES)
    skill = folder / 'SKILL.md'
    outside = tmp_path.parent / 'outside-reference.md'
    outside.write_text('Outside this checkout.')
    if failure == 'missing':
        skill.write_text(skill.read_text() + '\nRead [details](references/missing.md).\n')
    elif failure == 'plain-missing':
        skill.write_text(skill.read_text() + '\nRead docs/missing.md before proceeding.\n')
    elif failure == 'escape':
        skill.write_text(skill.read_text() + '\nRead [details](' + str(outside) + ').\n')
    elif failure == 'resource-symlink':
        (folder / 'reference.md').symlink_to(outside)
    elif failure == 'inrepo-resource-symlink':
        (folder / 'reference.md').symlink_to(checkout / 'docs/procedure.md')
    else:
        (folder / 'references').mkdir()
    with pytest.raises(SkillValidationError):
        validate(checkout)


def test_external_urls_are_data_and_never_followed(checkout: Path) -> None:
    skill = checkout / '.claude/skills' / min(SKILL_NAMES) / 'SKILL.md'
    skill.write_text(skill.read_text() + '\n[Official context](https://example.invalid/unreachable).\n')
    assert len(validate(checkout)) == 6


@pytest.mark.parametrize(
    'description',
    [
        'Plain task. Not for deployment.',
        '"Quoted task. Not for deployment."',
        '>\n  Folded task.\n  Not for deployment.',
    ],
)
def test_portable_frontmatter_scalars(description: str) -> None:
    metadata, body = frontmatter('---\nname: api-example\ndescription: ' + description + '\n---\nProcedure.')
    assert metadata['name'] == 'api-example'
    assert 'Not for deployment.' in metadata['description']
    assert body == 'Procedure.'


@pytest.mark.parametrize('description', ['false', '[]', '{}', '12', ''])
def test_non_text_or_empty_metadata_is_rejected(description: str) -> None:
    with pytest.raises(SkillValidationError):
        frontmatter('---\nname: api-example\ndescription: ' + description + '\n---\nProcedure.')


def test_valid_prohibition_is_ordinary_skill_text(checkout: Path) -> None:
    skill = checkout / '.claude/skills' / min(SKILL_NAMES) / 'SKILL.md'
    skill.write_text(skill.read_text() + '\nNever deploy to production without owner authorization.\n')
    assert validate(checkout) == sorted(SKILL_NAMES)


def test_single_quoted_frontmatter_requires_yaml_escape() -> None:
    text = "---\nname: api-example\ndescription: 'Task isn't escaped. Not for deployment.'\n---\nProcedure."
    with pytest.raises(SkillValidationError):
        frontmatter(text)
    metadata, _ = frontmatter(text.replace("isn't", "isn''t"))
    assert "isn't" in metadata['description']
