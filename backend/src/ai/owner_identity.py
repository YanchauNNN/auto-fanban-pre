from __future__ import annotations

from ipaddress import ip_address


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
