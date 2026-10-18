"""Explicit GraphRAG configuration, secret redaction and production activation guards."""

import pytest
from pydantic import ValidationError

from app.bootstrap.config import Settings


def _settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_legacy_fixture_profile_remains_network_free_by_default() -> None:
    settings = _settings()
    assert settings.ai_provider == 'fixture'
    assert settings.application_storage == settings.knowledge_backend == 'sqlite'
    assert settings.postgres_private_dsn is settings.postgres_knowledge_dsn is None
    assert settings.neo4j_uri is settings.neo4j_password is None


def test_graph_configuration_requires_explicit_authenticated_connections() -> None:
    with pytest.raises(ValidationError, match='explicit PostgreSQL and authenticated Neo4j'):
        _settings(knowledge_backend='graphrag')
    with pytest.raises(ValidationError, match='POSTGRES_PRIVATE_DSN'):
        _settings(application_storage='postgres')
    settings = _settings(
        application_storage='postgres',
        knowledge_backend='graphrag',
        postgres_private_dsn='postgresql://private:synthetic@db/pequeverso',
        postgres_knowledge_dsn='postgresql://public:synthetic@db/pequeverso',
        neo4j_uri='bolt://graph:7687',
        neo4j_password='synthetic-graph-password',
    )
    assert settings.knowledge_backend == 'graphrag'
    assert 'synthetic-graph-password' not in repr(settings)
    assert 'postgresql://private:' not in repr(settings)


@pytest.mark.parametrize('uri', ['https://graph', 'bolt://user:password@graph', 'bolt://graph?secret=x'])
def test_graph_uri_cannot_carry_credentials_or_http_routing(uri: str) -> None:
    with pytest.raises(ValidationError, match='bare Bolt URI'):
        _settings(neo4j_uri=uri)


def test_production_cannot_answer_from_legacy_or_hash_fixture_storage() -> None:
    production = {
        'environment': 'production',
        'ai_provider': 'openai',
        'allow_paid_ai': True,
        'openai_api_key': 'synthetic-provider-never-used',
        'session_cookie_secure': True,
        'allowed_origins': ['https://pequeverso.com'],
        'client_hash_key': 'synthetic-private-hash-key-' * 2,
    }
    with pytest.raises(ValidationError, match='PostgreSQL application storage and GraphRAG'):
        _settings(**production)
    disabled = _settings(**production, assistant_enabled=False)
    assert not disabled.assistant_enabled
