import ipaddress
import socket
from urllib.parse import urlsplit


class NetworkPolicyError(ValueError):
    pass


def validate_public_https_url(url: str, allowed_domains: set[str]) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise NetworkPolicyError("Only HTTPS URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise NetworkPolicyError("URL credentials are not allowed.")
    host = parsed.hostname.rstrip(".").lower()
    if not any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains):
        raise NetworkPolicyError("URL host is outside review allowlist.")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise NetworkPolicyError("URL host could not be resolved.") from error
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global:
            raise NetworkPolicyError("URL resolves to a non-public address.")
    return url
