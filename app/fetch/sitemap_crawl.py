"""Discover and parse sitemap trees for a review host (bounded, allowlisted)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.fetch.network_policy import (
    NetworkPolicyError,
    allowlist_for_website,
    hostname_of,
    validate_public_https_url,
)
from app.fetch.sitemap import MAX_URLS, parse_sitemap
from app.fetch.static_fetch import fetch_public_https

ROBOTS_SITEMAP_RE = re.compile(r"(?im)^\s*sitemap:\s*(\S+)\s*$")
MAX_SITEMAP_DEPTH = 3
MAX_SITEMAP_FILES = 25
DEFAULT_CANDIDATES = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml")

PRIVACY_KEYWORDS = (
    "privacy",
    "cookie",
    "consent",
    "legal",
    "terms",
    "gdpr",
    "rgpd",
    "datenschutz",
    "confidentialit",
    "newsletter",
    "subscribe",
    "notice",
    "policy",
)


@dataclass
class SitemapCrawlResult:
    website: str
    discovered_sitemaps: list[str] = field(default_factory=list)
    page_urls: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    limitations: str = (
        "Sitemap URLs prove discovery only, not page content, tracking behaviour, "
        "or notice completeness. Nested/off-host sitemaps are skipped."
    )

    def summary_text(self) -> str:
        lines = [
            "Sitemap crawl summary",
            f"Website: {self.website}",
            f"Sitemap files fetched: {len(self.discovered_sitemaps)}",
            f"Unique on-host page URLs: {len(self.page_urls)}",
            "",
            "Sitemap files:",
        ]
        lines.extend(f"- {url}" for url in self.discovered_sitemaps or ["(none)"])
        lines.append("")
        lines.append("Page URLs:")
        lines.extend(f"- {url}" for url in self.page_urls or ["(none)"])
        if self.errors:
            lines.append("")
            lines.append("Errors / skips:")
            lines.extend(f"- {err}" for err in self.errors)
        lines.append("")
        lines.append(f"Limitations: {self.limitations}")
        return "\n".join(lines)[:100_000]


def _is_sitemap_index(content: bytes) -> bool:
    head = content[:4000].lower()
    return b"<sitemapindex" in head


def _on_host(url: str, allowed: set[str]) -> bool:
    try:
        host = hostname_of(url)
    except NetworkPolicyError:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed)


def prioritize_urls(urls: list[str], *, limit: int) -> list[str]:
    """Prefer homepage-ish and privacy/legal paths, then fill remaining slots."""
    if limit <= 0:
        return []
    scored: list[tuple[int, int, str]] = []
    for index, url in enumerate(urls):
        path = (urlsplit(url).path or "/").lower()
        score = 0
        if path in {"", "/"}:
            score += 100
        if any(keyword in path or keyword in url.lower() for keyword in PRIVACY_KEYWORDS):
            score += 50
        if path.count("/") <= 2:
            score += 5
        scored.append((-score, index, url))
    scored.sort()
    return [url for _, _, url in scored[:limit]]


async def _load_robots_sitemaps(website: str, allowed: set[str]) -> list[str]:
    parsed = urlsplit(website)
    robots_url = f"https://{parsed.hostname}/robots.txt"
    try:
        result = await fetch_public_https(robots_url, allowed, max_bytes=256_000)
    except Exception:
        return []
    if result.status_code >= 400:
        return []
    text = result.body.decode("utf-8", errors="replace")
    found: list[str] = []
    for match in ROBOTS_SITEMAP_RE.finditer(text):
        candidate = match.group(1).strip()
        try:
            found.append(validate_public_https_url(candidate, allowed))
        except NetworkPolicyError:
            continue
    return found


async def discover_sitemap_urls(website: str) -> SitemapCrawlResult:
    allowed = allowlist_for_website(website)
    start = validate_public_https_url(website, allowed)
    parsed = urlsplit(start)
    origin = f"https://{parsed.hostname}"

    seed: list[str] = []
    seed.extend(await _load_robots_sitemaps(start, allowed))
    for path in DEFAULT_CANDIDATES:
        try:
            seed.append(validate_public_https_url(f"{origin}{path}", allowed))
        except NetworkPolicyError as error:
            # Should not happen for constructed same-host URLs.
            continue

    # De-dupe while preserving order.
    queue: list[str] = list(dict.fromkeys(seed))
    seen_sitemaps: set[str] = set()
    page_urls: list[str] = []
    result = SitemapCrawlResult(website=start)

    depth_by_url = {url: 0 for url in queue}
    while queue and len(result.discovered_sitemaps) < MAX_SITEMAP_FILES:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        depth = depth_by_url.get(sitemap_url, 0)
        try:
            fetched = await fetch_public_https(sitemap_url, allowed)
        except Exception as error:
            result.errors.append(f"{sitemap_url}: {error.__class__.__name__}: {error}")
            continue
        if fetched.status_code >= 400:
            result.errors.append(f"{sitemap_url}: HTTP {fetched.status_code}")
            continue
        ctype = fetched.content_type
        if ctype and "xml" not in ctype and "gzip" not in ctype and "text" not in ctype:
            # Still try parse; many servers mislabel XML.
            pass
        try:
            locs = parse_sitemap(fetched.body)
        except ValueError as error:
            result.errors.append(f"{sitemap_url}: {error}")
            continue

        result.discovered_sitemaps.append(fetched.final_url)
        if _is_sitemap_index(fetched.body) and depth < MAX_SITEMAP_DEPTH:
            for loc in locs:
                if not _on_host(loc, allowed):
                    result.errors.append(f"Skipped off-host nested sitemap: {loc}")
                    continue
                try:
                    validated = validate_public_https_url(loc, allowed)
                except NetworkPolicyError:
                    result.errors.append(f"Skipped unsafe nested sitemap: {loc}")
                    continue
                if validated not in seen_sitemaps:
                    queue.append(validated)
                    depth_by_url[validated] = depth + 1
            continue

        for loc in locs:
            if not _on_host(loc, allowed):
                continue
            try:
                page_urls.append(validate_public_https_url(loc, allowed))
            except NetworkPolicyError:
                continue

    # Always include the review homepage.
    page_urls.insert(0, start)
    result.page_urls = list(dict.fromkeys(page_urls))[:MAX_URLS]
    if not result.discovered_sitemaps:
        result.errors.append(
            "No sitemap XML discovered via robots.txt or common sitemap paths; "
            "homepage only was retained."
        )
    return result
