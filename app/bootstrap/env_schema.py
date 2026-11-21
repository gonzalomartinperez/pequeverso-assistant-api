"""Published environment schema (ecosystem 8.5): names, secret flag and production requirement.

`vps-ops` validates its deploy environment against `contracts/env.schema.json` before a deploy.
The file is generated from `Settings`, so a new variable cannot ship undocumented. No value or
default is written (defaults live in `.env.example` and `app/bootstrap/config.py`).
"""

from __future__ import annotations

from typing import Any, get_args

from pydantic import SecretStr

from app.bootstrap.config import Settings

# What `Settings.fail_closed` demands of an answering production deployment (OpenAI answers,
# PostgreSQL application storage and GraphRAG). `tests/test_env_schema.py` proves each one is
# really required by removing it from an otherwise valid production environment.
PRODUCTION_REQUIRED = frozenset(
    {
        "ENVIRONMENT",
        "AI_PROVIDER",
        "ALLOW_PAID_AI",
        "OPENAI_API_KEY",
        "ALLOWED_ORIGINS",
        "SESSION_COOKIE_SECURE",
        "CLIENT_HASH_KEY",
        "APPLICATION_STORAGE",
        "KNOWLEDGE_BACKEND",
        "POSTGRES_PRIVATE_DSN",
        "POSTGRES_KNOWLEDGE_DSN",
        "NEO4J_URI",
        "NEO4J_PASSWORD",
    }
)


# Read directly by explicit operator jobs, never by the API runtime (`Settings`).
JOB_VARIABLES = (
    ("POSTGRES_MIGRATION_DSN", "python -m app.bootstrap.knowledge_jobs migrate"),
    ("POSTGRES_IMPORT_DSN", "python -m app.bootstrap.import_database"),
)


def _is_secret(annotation: object) -> bool:
    return annotation is SecretStr or SecretStr in get_args(annotation)


def env_schema() -> dict[str, Any]:
    variables = []
    for name, field in sorted(Settings.model_fields.items()):
        variables.append(
            {
                "name": name.upper(),
                "secret": _is_secret(field.annotation),
                "required_in_production": name.upper() in PRODUCTION_REQUIRED,
            }
        )
    return {
        "schema_version": "1",
        "service": "pequeverso-assistant-api",
        "description": (
            "variables: API runtime settings. required_in_production applies to an answering "
            "production deployment (ASSISTANT_ENABLED=true, AI_PROVIDER=openai); other values "
            "follow docs/deployment-contract.md. jobs: secrets read only by explicit operator "
            "jobs, never by the API container."
        ),
        "variables": variables,
        "jobs": [{"name": n, "secret": True, "job": job} for n, job in JOB_VARIABLES],
    }
