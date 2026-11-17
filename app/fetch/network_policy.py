"""Outbound URL policy: public HTTPS review hosts only (no private/admin LAN)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class NetworkPolicyError(ValueError):
    pass


# Hostnames that imply local / admin / directory services — never capture targets.
BLOCKED_HOSTNAME_SUFFIXES: tuple[str, ...] = (
    ".local",
    ".localhost",
    ".internal",
    ".intranet",
    ".corp",
    ".lan",
    ".home",
    ".home.arpa",
)

BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "kubernetes.default",
        "kubernetes.default.svc",
    }
)


def hostname_of(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.hostname:
        raise NetworkPolicyError("URL host is missing.")
    return parsed.hostname.rstrip(".").lower()


def allowlist_for_website(website: str) -> set[str]:
    """Allow the review host and its www / apex twin only."""
    host = hostname_of(website)
    _assert_hostname_not_local(host)
    allowed = {host}
    if host.startswith("www."):
        allowed.add(host[4:])
    else:
        allowed.add(f"www.{host}")
    return allowed


def _assert_hostname_not_local(host: str) -> None:
    if host in BLOCKED_HOSTNAMES:
        raise NetworkPolicyError(f"Hostname {host!r} is blocked (local/admin).")
    if any(host == suffix[1:] or host.endswith(suffix) for suffix in BLOCKED_HOSTNAME_SUFFIXES):
        raise NetworkPolicyError(
            f"Hostname {host!r} looks like a private/local network name and is blocked."
        )
    # Raw IPv6 literals or dotted quads as host — still resolved below, but fail fast
    # for obvious loopback/link-local literals.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if not ip.is_global:
        raise NetworkPolicyError(
            f"Literal address {host!r} is not a public Internet address."
        )


def _assert_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Block private, loopback, link-local, multicast, CGNAT, and reserved ranges."""
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (hasattr(ip, "is_site_local") and ip.is_site_local)  # type: ignore[attr-defined]
        or not ip.is_global
    ):
        raise NetworkPolicyError(
            f"Address {ip} is not a public Internet address "
            "(private/local/admin network targets are blocked)."
        )
    # Extra explicit cloud metadata / CGNAT style ranges sometimes marked oddly.
    if isinstance(ip, ipaddress.IPv4Address):
        if ip in ipaddress.ip_network("169.254.0.0/16"):
            raise NetworkPolicyError("Link-local address blocked.")
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            raise NetworkPolicyError("Shared/CGNAT address blocked.")
        if ip in ipaddress.ip_network("0.0.0.0/8"):
            raise NetworkPolicyError("Reserved address blocked.")


def validate_public_https_url(url: str, allowed_domains: set[str]) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise NetworkPolicyError("Only HTTPS URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise NetworkPolicyError("URL credentials are not allowed.")
    # Non-default privileged ports are unusual for evidence capture; allow 443 only
    # unless explicitly present as default.
    if parsed.port is not None and parsed.port not in {443}:
        raise NetworkPolicyError(
            "Only HTTPS on port 443 is allowed (avoids local/admin service probes)."
        )
    host = parsed.hostname.rstrip(".").lower()
    _assert_hostname_not_local(host)
    if not any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
        raise NetworkPolicyError("URL host is outside review allowlist.")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise NetworkPolicyError("URL host could not be resolved.") from error
    if not addresses:
        raise NetworkPolicyError("URL host could not be resolved.")
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        _assert_public_ip(ip)
    return url
