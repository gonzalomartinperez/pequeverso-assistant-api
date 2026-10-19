"""Keep software permission, reserved content and runtime notices consistent."""

import tomllib
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_software_license_matches_reviewed_official_mit_text() -> None:
    # Official GitHub MIT template, year/holder substituted after first-commit audit;
    # body also checked against OSI. Scope belongs in NOTICE, never in the MIT grant.
    license_text = (ROOT / 'LICENSE').read_bytes()
    assert (
        sha256(license_text).hexdigest() == '55bcc3f7588606c0cb322cc2a687929429726ffdac2448d465cc9ced30025d72'
    )
    metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    assert metadata['license'] == 'MIT'
    assert metadata['license-files'] == ['LICENSE', 'NOTICE.md']


def test_license_scope_and_distribution_notices_are_preserved() -> None:
    notice = (ROOT / 'NOTICE.md').read_text()
    for excluded in ('brand identity', 'catalog/**', 'private data', 'Third-party software'):
        assert excluded in notice
    readme = (ROOT / 'README.md').read_text()
    assert '[MIT License](LICENSE)' in readme
    assert '[NOTICE.md](NOTICE.md)' in readme
    assert 'no license is granted' not in readme
    dockerfile = (ROOT / 'infra/docker/app/Dockerfile').read_text()
    assert 'COPY LICENSE NOTICE.md ./' in dockerfile
    context = (ROOT / '.dockerignore').read_text().splitlines()
    assert '!LICENSE' in context
    assert '!NOTICE.md' in context


def test_project_database_recipes_carry_software_notices_without_overriding_vendor_licenses() -> None:
    for name, uid in (('postgres', 70), ('neo4j', 7474)):
        recipe = (ROOT / 'infra/docker' / name / 'Dockerfile').read_text()
        assert (
            f'COPY --chown={uid}:{uid} LICENSE NOTICE.md /usr/share/licenses/pequeverso-assistant-api/'
            in recipe
        )
    graph_context = (ROOT / 'infra/docker/neo4j/Dockerfile.dockerignore').read_text().splitlines()
    assert '!LICENSE' in graph_context and '!NOTICE.md' in graph_context
