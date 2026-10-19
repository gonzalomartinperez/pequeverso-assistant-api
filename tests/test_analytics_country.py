"""Offline exact-peer country and calendar semantics, never a Cloudflare/network proof."""

from datetime import datetime
from ipaddress import IPv4Address

import pytest
from fastapi import Request
from pydantic import ValidationError

from app.bootstrap.config import Settings
from app.domain.analytics_country import COUNTRIES
from app.domain.product_analytics import Selection, window
from app.presentation.analytics_country import country_from_edge
from contracts.analytics_semantics import SEMANTICS


@pytest.mark.parametrize('case', SEMANTICS['country_cases'], ids=lambda case: case['name'])
def test_shared_exact_socket_country_cases(case):
    request = Request(
        {
            'type': 'http',
            'headers': [(b'cf-ipcountry', value.encode()) for value in case['headers']],
            'client': (case['peer'], 123) if case['peer'] is not None else None,
        }
    )
    assert (
        country_from_edge(request, enabled=case['enabled'], trusted_peers=case['trusted_peers'])
        == case['expected']
    )


@pytest.mark.parametrize('case', SEMANTICS['periods'])
def test_shared_utc_calendar_cases(case):
    start, end = window(
        datetime.fromisoformat(case['instant']), Selection(period=case['period'], offset=case['offset'])
    )
    assert start.date().isoformat() == case['start'] and end.date().isoformat() == case['end']
    now = datetime.fromisoformat(case['instant'])
    assert (start <= now < end) == case['partial']


def test_country_never_uses_forwarded_ip_or_locale_and_allowlist_has_249_labels():
    assert len(COUNTRIES) == 249
    request = Request(
        {
            'type': 'http',
            'headers': [
                (b'x-forwarded-for', b'172.20.0.5'),
                (b'cf-ipcountry', b'AR'),
                (b'accept-language', b'es-AR'),
            ],
            'client': ('203.0.113.10', 123),
        }
    )
    assert country_from_edge(request, enabled=True, trusted_peers='172.20.0.5') == 'unknown'


@pytest.mark.parametrize(
    'addresses',
    [
        '*',
        '172.20.0.0/16',
        'proxy',
        str(IPv4Address(0)),
        '::ffff:' + str(IPv4Address(0)),
        '::ffff:224.0.0.1',
        '::',
        '224.0.0.1',
        'fe80::1%eth0',
        ',127.0.0.1',
        '127.0.0.1,',
        ','.join(f'192.0.2.{i}' for i in range(1, 18)),
    ],
)
def test_proxy_configuration_rejects_non_exact_or_unbounded_trust(addresses):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, product_analytics_country_proxy_ips=addresses)


def test_proxy_configuration_canonicalizes_deduplicates_and_requires_explicit_enabled_trust():
    settings = Settings(
        _env_file=None, product_analytics_country_proxy_ips=' ::ffff:172.20.0.5,172.20.0.5,2001:DB8::1 '
    )
    assert settings.product_analytics_country_proxy_ips == '172.20.0.5,2001:db8::1'
    with pytest.raises(ValidationError):
        Settings(_env_file=None, product_analytics_country_enabled=True)
