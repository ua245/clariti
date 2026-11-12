"""Headless browser capture for common privacy-review indicators."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.fetch.network_policy import (
    NetworkPolicyError,
    allowlist_for_website,
    hostname_of,
    validate_public_https_url,
)

MAX_SCREENSHOTS = 8
MAX_SCROLL_STEPS = 6
PAGE_TIMEOUT_MS = 30_000
SETTLE_MS = 1_200
VIEWPORT = {"width": 1280, "height": 800}

INDICATOR_SCAN_JS = r"""
() => {
  const patterns = [
    {id: "privacy-link", re: /privacy|confidentialit[eé]|datenschutz|politique\s+de\s+confidentialit/i},
    {id: "cookie-notice", re: /cookie|consent|consentement|preferen|gdpr|rgpd|manage\s+cookies|cookie\s+settings/i},
    {id: "newsletter", re: /newsletter|subscribe|abonnement|sign\s*up\s*for\s*(our\s*)?email/i},
  ];
  const bannerHints = [
    "[id*='onetrust' i]",
    "[class*='onetrust' i]",
    "[id*='cookie' i]",
    "[class*='cookie' i]",
    "[id*='consent' i]",
    "[class*='consent' i]",
    "[aria-label*='cookie' i]",
    "[aria-label*='consent' i]",
    "#tc-privacy-wrapper",
    ".qc-cmp2-container",
  ];

  function visible(el) {
    if (!el || !(el instanceof Element)) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 8 && rect.height > 8;
  }

  function labelFor(el) {
    return (el.innerText || el.getAttribute("aria-label") || el.getAttribute("alt") || el.getAttribute("title") || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 240);
  }

  const hits = [];
  const seen = new Set();

  function addHit(kind, el, extra) {
    if (!visible(el)) return;
    const rect = el.getBoundingClientRect();
    const key = `${kind}:${Math.round(rect.top)}:${Math.round(rect.left)}:${labelFor(el).slice(0, 40)}`;
    if (seen.has(key)) return;
    seen.add(key);
    hits.push({
      kind,
      tag: el.tagName.toLowerCase(),
      text: labelFor(el),
      href: el.href || el.getAttribute("href") || null,
      y: Math.max(0, Math.floor(window.scrollY + rect.y)),
      ...extra,
    });
  }

  for (const selector of bannerHints) {
    try {
      for (const el of document.querySelectorAll(selector)) {
        addHit("cookie-banner", el, {selector});
        if (hits.length >= 20) break;
      }
    } catch (_) {}
  }

  const candidates = document.querySelectorAll(
    "a, button, [role='button'], summary, label, h1, h2, h3, p, span, div"
  );
  for (const el of candidates) {
    const text = labelFor(el);
    if (!text || text.length < 4) continue;
    for (const pattern of patterns) {
      if (pattern.re.test(text)) {
        addHit(pattern.id, el, {});
        break;
      }
    }
    if (hits.length >= 40) break;
  }

  return {
    title: document.title || "",
    scrollHeight: document.documentElement.scrollHeight || 0,
    hits: hits.slice(0, 24),
  };
}
"""


@dataclass
class CaptureShot:
    label: str
    png_bytes: bytes
    source_url: str
    note: str


@dataclass
class CaptureResult:
    final_url: str
    page_title: str
    summary_text: str
    shots: list[CaptureShot] = field(default_factory=list)
    limitations: str = (
        "Automated headless capture. Screenshots show observable UI only; "
        "they do not prove tracking behaviour, script execution, or notice completeness."
    )


def _host_allowed(url: str, allowed: set[str]) -> bool:
    try:
        host = hostname_of(url)
    except NetworkPolicyError:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed)


def _unique_shots(shots: list[CaptureShot]) -> list[CaptureShot]:
    result: list[CaptureShot] = []
    digests: set[str] = set()
    for shot in shots:
        digest = hashlib.sha256(shot.png_bytes).hexdigest()
        if digest in digests:
            continue
        digests.add(digest)
        result.append(shot)
        if len(result) >= MAX_SCREENSHOTS:
            break
    return result


async def _assert_destination(page: Any, allowed: set[str]) -> str:
    return validate_public_https_url(page.url, allowed)


async def capture_privacy_indicators(website: str) -> CaptureResult:
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is not installed. Re-run python3 run.py to install browser support."
        ) from error

    allowed = allowlist_for_website(website)
    start_url = validate_public_https_url(website, allowed)
    shots: list[CaptureShot] = []
    findings: list[str] = []
    title = ""
    final_url = start_url

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport=VIEWPORT,
                java_script_enabled=True,
                ignore_https_errors=False,
            )
            page = await context.new_page()
            page.set_default_timeout(PAGE_TIMEOUT_MS)

            response = await page.goto(start_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(SETTLE_MS)
            final_url = await _assert_destination(page, allowed)
            status = response.status if response is not None else None
            title = await page.title()

            initial = await page.screenshot(type="png", full_page=False)
            shots.append(
                CaptureShot(
                    label="initial-viewport",
                    png_bytes=initial,
                    source_url=final_url,
                    note="Initial viewport after load (consent UI often appears here).",
                )
            )
            findings.append(
                f"Opened {final_url}"
                + (f" (HTTP {status})" if status is not None else "")
                + f" title={title!r}."
            )

            seen_hit_keys: set[str] = set()

            async def collect_hits(phase: str) -> None:
                nonlocal shots
                scan = await page.evaluate(INDICATOR_SCAN_JS)
                hits = scan.get("hits") or []
                if not hits:
                    findings.append(
                        f"{phase}: no common privacy/cookie/newsletter indicators visible."
                    )
                    return
                for hit in hits:
                    key = f"{hit.get('kind')}:{hit.get('text', '')[:60]}:{hit.get('y')}"
                    if key in seen_hit_keys:
                        continue
                    seen_hit_keys.add(key)
                    kind = str(hit.get("kind") or "indicator")
                    text = str(hit.get("text") or "").strip()
                    href = hit.get("href")
                    href_note = ""
                    if href:
                        absolute = urljoin(page.url, str(href))
                        if _host_allowed(absolute, allowed) or urlsplit(absolute).scheme in {
                            "http",
                            "https",
                        }:
                            href_note = f" href={absolute}"
                            if not _host_allowed(absolute, allowed):
                                href_note += " (outside review host; not visited)"
                    findings.append(
                        f"{phase}: found {kind}"
                        + (f" text={text!r}" if text else "")
                        + href_note
                    )
                    if len(shots) >= MAX_SCREENSHOTS:
                        return
                    try:
                        y = max(0, int(hit.get("y") or 0) - 80)
                        await page.evaluate("(top) => window.scrollTo(0, top)", y)
                        await page.wait_for_timeout(350)
                        await _assert_destination(page, allowed)
                        png = await page.screenshot(type="png", full_page=False)
                        shots.append(
                            CaptureShot(
                                label=f"{kind}-{len(shots)}",
                                png_bytes=png,
                                source_url=page.url,
                                note=f"Auto-scrolled to {kind}. Observable text: {text[:180]}",
                            )
                        )
                    except Exception:
                        continue

            await collect_hits("after-load")

            scroll_height = await page.evaluate(
                "() => document.documentElement.scrollHeight || 0"
            )
            step = max(VIEWPORT["height"] - 120, 400)
            for index in range(1, MAX_SCROLL_STEPS + 1):
                if len(shots) >= MAX_SCREENSHOTS:
                    break
                target = min(index * step, max(int(scroll_height) - VIEWPORT["height"], 0))
                await page.evaluate("(top) => window.scrollTo(0, top)", target)
                await page.wait_for_timeout(400)
                await _assert_destination(page, allowed)
                await collect_hits(f"scroll-{index}")

            await page.evaluate(
                "() => window.scrollTo(0, document.documentElement.scrollHeight)"
            )
            await page.wait_for_timeout(500)
            await _assert_destination(page, allowed)
            if len(shots) < MAX_SCREENSHOTS:
                footer = await page.screenshot(type="png", full_page=False)
                shots.append(
                    CaptureShot(
                        label="page-footer",
                        png_bytes=footer,
                        source_url=page.url,
                        note="Footer viewport after scrolling to page end.",
                    )
                )
            await collect_hits("footer")
            final_url = await _assert_destination(page, allowed)
            await context.close()
        finally:
            await browser.close()

    shots = _unique_shots(shots)
    if not any("found " in line for line in findings):
        findings.append(
            "No labelled privacy/cookie/newsletter controls matched common patterns. "
            "This is Not verified, not Fail."
        )
    summary = "Automated privacy-indicator scan\n\n" + "\n".join(findings)
    return CaptureResult(
        final_url=final_url,
        page_title=title,
        summary_text=summary[:100_000],
        shots=shots,
    )


def capture_privacy_indicators_sync(website: str) -> CaptureResult:
    return asyncio.run(capture_privacy_indicators(website))
