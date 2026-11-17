"""Extract plain text from HTML for evidence (never execute or re-render HTML)."""

from __future__ import annotations

from bs4 import BeautifulSoup

MAX_TEXT_CHARS = 80_000


def html_to_evidence_text(html: bytes | str, *, source_url: str) -> str:
    if isinstance(html, bytes):
        raw = html.decode("utf-8", errors="replace")
    else:
        raw = html
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""
    text = " ".join(soup.get_text(" ", strip=True).split())
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split())[:120]
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        if any(
            key in f"{label} {href}".lower()
            for key in ("privacy", "cookie", "consent", "terms", "legal", "newsletter")
        ):
            links.append(f"- {label or '(no label)'}: {href}")
        if len(links) >= 40:
            break
    parts = [
        f"Source URL: {source_url}",
        f"Title: {title}" if title else "Title: (none)",
        "",
        "Extracted visible text:",
        text[:MAX_TEXT_CHARS],
    ]
    if links:
        parts.extend(["", "Privacy-relevant links observed:", *links])
    return "\n".join(parts)[:100_000]
