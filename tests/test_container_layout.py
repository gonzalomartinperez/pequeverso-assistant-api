"""Exercise real recipe consumers and narrowly allowed database build contexts."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
RECIPES = frozenset(
    f"infra/docker/{service}/Dockerfile" for service in ("app", "postgres", "neo4j")
)
OLD_PATHS = (
    "Dockerfile",
    "Dockerfile.postgres",
    "Dockerfile.neo4j",
    "Dockerfile.neo4j.dockerignore",
    "docker/neo4j/neo4j.conf",
)


def _build_recipe(line: str) -> str:
    tokens = shlex.split(line.strip().removesuffix(">/dev/null").strip())
    assert tokens[:2] == ["docker", "build"]
    assert "-f" in tokens, "Every build must explicitly select the owned recipe"
    recipe = tokens[tokens.index("-f") + 1]
    assert recipe in RECIPES, "Unknown or legacy Dockerfile path"
    assert tokens[-1] == ".", "The repository root remains the build context"
    return recipe


def _recipe_files(root: Path) -> None:
    assert all((root / path).is_file() for path in RECIPES)
    assert not any((root / path).exists() for path in OLD_PATHS)
    assert (root / "infra/docker/neo4j/neo4j.conf").is_file()


def _database_filters(root: Path) -> None:
    expected = {
        "postgres": ["*", "!LICENSE", "!NOTICE.md"],
        "neo4j": [
            "*",
            "!infra/",
            "infra/*",
            "!infra/docker/",
            "infra/docker/*",
            "!infra/docker/neo4j/",
            "infra/docker/neo4j/*",
            "!infra/docker/neo4j/neo4j.conf",
            "!LICENSE",
            "!NOTICE.md",
        ],
    }
    for service, allowed in expected.items():
        lines = (root / f"infra/docker/{service}/Dockerfile.dockerignore").read_text().splitlines()
        policy = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        assert policy == allowed, "Ordered database filters admit only reviewed public payloads"


def test_real_build_consumers_select_owned_recipes_and_repository_context() -> None:
    paths = (".github/workflows/ci.yml", "scripts/smoke_container.sh")
    commands = [
        line.strip()
        for path in paths
        for line in (ROOT / path).read_text().splitlines()
        if line.strip().startswith("docker build ")
    ]
    assert {_build_recipe(command) for command in commands} == RECIPES
    _recipe_files(ROOT)
    _database_filters(ROOT)
    neo = (ROOT / "infra/docker/neo4j/Dockerfile").read_text()
    assert "COPY --chown=7474:7474 infra/docker/neo4j/neo4j.conf /conf/neo4j.conf" in neo


@pytest.mark.parametrize(
    "command",
    [
        "docker build .",
        "docker build -f Dockerfile .",
        "docker build -f infra/docker/app/Dockerfile infra/docker/app",
        "docker build -f infra/docker/other/Dockerfile .",
    ],
)
def test_real_build_command_gate_rejects_implicit_legacy_or_wrong_context(command: str) -> None:
    with pytest.raises(AssertionError):
        _build_recipe(command)


def test_legacy_recipe_cannot_silently_become_a_second_source(tmp_path: Path) -> None:
    for recipe in RECIPES:
        path = tmp_path / recipe
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    (tmp_path / "infra/docker/neo4j/neo4j.conf").touch()
    _recipe_files(tmp_path)
    (tmp_path / "Dockerfile").touch()
    with pytest.raises(AssertionError):
        _recipe_files(tmp_path)


@pytest.mark.parametrize("service", ["postgres", "neo4j"])
def test_database_context_gate_rejects_broad_application_inclusion(
    tmp_path: Path, service: str
) -> None:
    for name in ("postgres", "neo4j"):
        source = ROOT / f"infra/docker/{name}/Dockerfile.dockerignore"
        target = tmp_path / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text())
    _database_filters(tmp_path)
    bad = tmp_path / f"infra/docker/{service}/Dockerfile.dockerignore"
    bad.write_text(bad.read_text() + "!app/\n")
    with pytest.raises(AssertionError):
        _database_filters(tmp_path)


def test_dependabot_keeps_all_three_real_recipe_directories_under_manual_weekly_policy() -> None:
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    updates = [update for update in config["updates"] if update["package-ecosystem"] == "docker"]
    assert len(updates) == 1
    update = updates[0]
    assert set(update["directories"]) == {
        "/infra/docker/app",
        "/infra/docker/postgres",
        "/infra/docker/neo4j",
    }
    assert "directory" not in update
    group = config["multi-ecosystem-groups"]["weekly-all"]
    assert update["multi-ecosystem-group"] == "weekly-all"
    assert group["target-branch"] == "develop"
    assert group["schedule"]["interval"] == "weekly"
    assert group["open-pull-requests-limit"] == 1
    assert update["cooldown"]["default-days"] == 7


def test_app_dockerfile_keeps_canonical_reproducible_shape() -> None:
    text = (ROOT / "infra/docker/app/Dockerfile").read_text()
    for expected in (
        "uv sync --locked --no-editable --no-build --no-dev --no-install-project",
        "id=pva-uv-py314",
        "UV_PYTHON_DOWNLOADS=0",
        "ARG SOURCE_DATE_EPOCH",
        "org.opencontainers.image.title=",
        "org.opencontainers.image.source=",
        'org.opencontainers.image.licenses="MIT"',
        'org.opencontainers.image.revision="${SERVICE_REVISION}"',
        "USER 65532:65532",
        "/health/ready",
    ):
        assert expected in text
    assert "vps-ops" not in text
    assert text.index("ARG SERVICE_REVISION") > text.index("COPY LICENSE NOTICE.md")
    for config in (".hadolint.yaml", ".grype.yaml", "infra/docker/app/structure-test.yaml"):
        assert (ROOT / config).is_file()
    grype = (ROOT / ".grype.yaml").read_text()
    assert "fail-on-severity: high" in grype and "only-fixed: true" in grype


def test_grype_ignores_are_tracked_and_unexpired():
    from datetime import date, timedelta

    text = (ROOT / ".grype.yaml").read_text()
    ignores = yaml.safe_load(text)["ignore"]
    blocks = text.split("\n  - vulnerability: ")[1:]
    assert len(blocks) == len(ignores)
    header = text.split("\nignore:", 1)[1]
    comments = [chunk for chunk in header.split("\n  - vulnerability: ")][: len(ignores)]
    today = date.today()
    for entry, comment in zip(ignores, comments, strict=True):
        assert entry["vulnerability"] in text
        assert (
            "issue: https://github.com/gonzalomartinperez/pequeverso-assistant-api/issues/"
            in comment
        )
        expiry = date.fromisoformat(comment.split("# expires: ", 1)[1][:10])
        assert today <= expiry <= today + timedelta(days=90), entry["vulnerability"]
