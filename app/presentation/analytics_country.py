"""Optional socket-peer country boundary; configuration never proves upstream edge trust."""

from ipaddress import IPv6Address, ip_address

from fastapi import Request

from app.domain.analytics_country import country_label


def country_from_edge(request: Request, *, enabled: bool, trusted_peers: str) -> str:
    if not enabled or request.client is None:
        return 'unknown'
    try:
        peer = ip_address(request.client.host)
    except ValueError:
        return 'unknown'
    if isinstance(peer, IPv6Address) and peer.ipv4_mapped:
        peer = peer.ipv4_mapped
    if str(peer) not in trusted_peers.split(','):
        return 'unknown'
    values = request.headers.getlist('cf-ipcountry')
    return country_label(values[0]) if len(values) == 1 else 'unknown'
