from __future__ import annotations

from ipaddress import ip_address


DEFAULT_TRUSTED_PROXY_HOSTS = frozenset({"127.0.0.1", "::1"})


def normalize_ip_host(value: object) -> str:
    host = str(value).strip()
    if not host:
        return "unknown"

    if host.startswith("["):
        closing_bracket = host.find("]")
        if closing_bracket > 1:
            bracketed_host = host[1:closing_bracket]
            try:
                return str(ip_address(bracketed_host))
            except ValueError:
                return host

    try:
        return str(ip_address(host))
    except ValueError:
        pass

    candidate, separator, port = host.rpartition(":")
    if separator and port.isdecimal():
        try:
            return str(ip_address(candidate))
        except ValueError:
            pass
    return host


def normalize_owner_key(value: object) -> str:
    owner_key = str(value).strip()
    if not owner_key.startswith("ip:"):
        return owner_key
    return f"ip:{normalize_ip_host(owner_key.removeprefix('ip:'))}"


def resolve_client_ip(
    peer_host: object,
    forwarded_for: object | None = None,
    *,
    trusted_proxy_hosts: frozenset[str] = DEFAULT_TRUSTED_PROXY_HOSTS,
) -> str:
    peer_ip = normalize_ip_host(peer_host)
    normalized_trusted_hosts = {
        normalize_ip_host(host) for host in trusted_proxy_hosts
    }
    if peer_ip not in normalized_trusted_hosts or forwarded_for is None:
        return peer_ip

    forwarded_host = str(forwarded_for).split(",", maxsplit=1)[0].strip()
    candidate = normalize_ip_host(forwarded_host)
    try:
        return str(ip_address(candidate))
    except ValueError:
        return peer_ip
