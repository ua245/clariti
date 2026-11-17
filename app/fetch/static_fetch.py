"""Bounded HTTPS GET with allowlist-safe redirects (no SSRF to private IPs)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.fetch.network_policy import NetworkPolicyError, validate_public_https_url

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
REQUEST_TIMEOUT_S = 20.0
USER_AGENT = "ClaritiPrivacyReview/1.0 (+local; evidence-capture)"


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    body: bytes
    redirected: bool


def _content_type(headers: httpx.Headers) -> str:
    return (headers.get("content-type") or "").split(";")[0].strip().lower()


async def fetch_public_https(
    url: str,
    allowed_domains: set[str],
    *,
    max_bytes: int = MAX_BODY_BYTES,
) -> FetchResult:
    """GET a public HTTPS URL; each hop must stay on the allowlist."""
    current = validate_public_https_url(url, allowed_domains)
    redirected = False
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=REQUEST_TIMEOUT_S,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            response = await client.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise NetworkPolicyError("Redirect missing Location header.")
                next_url = str(httpx.URL(current).join(location))
                if urlsplit(next_url).scheme != "https":
                    raise NetworkPolicyError("Redirect to non-HTTPS URL is blocked.")
                current = validate_public_https_url(next_url, allowed_domains)
                redirected = True
                continue

            body = response.content
            if len(body) > max_bytes:
                raise ValueError(f"Response body exceeds {max_bytes} bytes.")
            final = validate_public_https_url(str(response.url), allowed_domains)
            return FetchResult(
                requested_url=url,
                final_url=final,
                status_code=response.status_code,
                content_type=_content_type(response.headers),
                body=body,
                redirected=redirected,
            )
    raise NetworkPolicyError("Too many redirects.")
