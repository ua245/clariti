"""Browser capture for common privacy-review indicators.

Headless mode runs fully automated. HITL mode opens a headed Chromium window
so a reviewer can complete Cloudflare challenges, consent prompts, or an
authorized login themselves; Clariti never automates those gates.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

from app.fetch.network_policy import (
    NetworkPolicyError,
    allowlist_for_website,
    hostname_of,
    validate_public_https_url,
)
from app.security_runtime import (
    browser_context_kwargs,
    chromium_launch_kwargs,
    ensure_user_browser_env,
)


def _ensure_user_browser_path() -> None:
    """Prefer project-local browsers so capture never needs admin install-deps."""
    ensure_user_browser_env()


MAX_SCREENSHOTS = 8
MAX_SCROLL_STEPS = 6
PAGE_TIMEOUT_MS = 30_000
SETTLE_MS = 1_200
VIEWPORT = {"width": 1280, "height": 800}

HITL_LIMITATIONS = (
    "Human-assisted headed capture. The reviewer completed any Cloudflare, "
    "consent, or login gates themselves; Clariti does not bypass those controls. "
    "Screenshots show observable UI only; they do not prove tracking behaviour, "
    "script execution, or notice completeness."
)

HEADLESS_LIMITATIONS = (
    "Automated headless capture. Screenshots show observable UI only; "
    "they do not prove tracking behaviour, script execution, or notice completeness."
)

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

# Returns a challenge code string, or null when the page looks normal.
# Mid-crawl must treat null as "keep going" — never a generic instructional message.
CHALLENGE_HINT_JS = r"""
() => {
  const title = (document.title || "").toLowerCase();
  const href = (location.href || "").toLowerCase();
  const body = (document.body && document.body.innerText || "").slice(0, 2500).toLowerCase();
  const hasTurnstile = !!document.querySelector(
    "iframe[src*='challenges.cloudflare.com'], iframe[src*='turnstile'], .cf-turnstile, [name='cf-turnstile-response']"
  );
  const hasCfChallengeForm = !!document.querySelector("#challenge-form, #cf-challenge-running, .cf-browser-verification");
  if (
    title.includes("just a moment") ||
    title.includes("attention required") ||
    href.includes("cdn-cgi/challenge") ||
    href.includes("/cdn-cgi/chl") ||
    body.includes("checking your browser before accessing") ||
    body.includes("verify you are human") ||
    body.includes("enable javascript and cookies to continue") ||
    hasTurnstile ||
    hasCfChallengeForm
  ) {
    return "cf_challenge";
  }
  // Hard login interstitial only (avoid cookie/newsletter password fields).
  const pwd = document.querySelector("input[type='password']");
  const form = pwd && pwd.closest("form");
  const formText = ((form && form.innerText) || "").toLowerCase();
  if (
    pwd &&
    form &&
    (/sign\s*in|log\s*in|authenticate|password/i.test(title) ||
      /sign\s*in|log\s*in|authenticate/.test(formText)) &&
    !/newsletter|subscribe|cookie|consent/.test(formText)
  ) {
    return "login_wall";
  }
  return null;
}
"""

CHALLENGE_MESSAGES = {
    "cf_challenge": (
        "Cloudflare/bot-check interstitial detected. Complete it in the browser, "
        "then click Continue in Clariti."
    ),
    "login_wall": (
        "Login wall detected. Complete authorized sign-in in the browser if required, "
        "then click Continue in Clariti."
    ),
}

INITIAL_HITL_HINT = (
    "Complete any Cloudflare, consent, or login steps in this browser window if "
    "needed, then click Continue in Clariti. The crawl will continue automatically "
    "after that unless another real challenge appears."
)


CaptureMode = Literal["headless", "hitl", "sitemap", "sitemap_headless"]
HitlStatus = Literal[
    "starting",
    "waiting_for_human",
    "scanning",
    "completed",
    "cancelled",
    "failed",
]


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
    limitations: str = HEADLESS_LIMITATIONS


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


async def _scan_loaded_page(
    page: Any,
    allowed: set[str],
    *,
    prefix_findings: list[str] | None = None,
    limitations: str = HEADLESS_LIMITATIONS,
    summary_heading: str = "Automated privacy-indicator scan",
) -> CaptureResult:
    shots: list[CaptureShot] = []
    findings: list[str] = list(prefix_findings or [])
    final_url = await _assert_destination(page, allowed)
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
    if not any(line.startswith("Opened ") for line in findings):
        findings.append(f"Opened {final_url} title={title!r}.")

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
    title = await page.title()

    shots = _unique_shots(shots)
    if not any("found " in line for line in findings):
        findings.append(
            "No labelled privacy/cookie/newsletter controls matched common patterns. "
            "This is Not verified, not Fail."
        )
    summary = summary_heading + "\n\n" + "\n".join(findings)
    return CaptureResult(
        final_url=final_url,
        page_title=title,
        summary_text=summary[:100_000],
        shots=shots,
        limitations=limitations,
    )


async def capture_privacy_indicators(website: str) -> CaptureResult:
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is not installed. Re-run python3 run.py to install browser support."
        ) from error

    _ensure_user_browser_path()
    allowed = allowlist_for_website(website)
    start_url = validate_public_https_url(website, allowed)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**chromium_launch_kwargs(headless=True))
        try:
            context = await browser.new_context(**browser_context_kwargs())
            page = await context.new_page()
            page.set_default_timeout(PAGE_TIMEOUT_MS)

            response = await page.goto(start_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(SETTLE_MS)
            final_url = await _assert_destination(page, allowed)
            status = response.status if response is not None else None
            title = await page.title()
            prefix = [
                f"Opened {final_url}"
                + (f" (HTTP {status})" if status is not None else "")
                + f" title={title!r}."
            ]
            result = await _scan_loaded_page(
                page,
                allowed,
                prefix_findings=prefix,
                limitations=HEADLESS_LIMITATIONS,
                summary_heading="Automated privacy-indicator scan",
            )
            await context.close()
            return result
        finally:
            await browser.close()


def capture_privacy_indicators_sync(website: str) -> CaptureResult:
    return asyncio.run(capture_privacy_indicators(website))


class HitlCaptureSession:
    """Headed browser session that pauses for human gate completion."""

    def __init__(self, website: str) -> None:
        self.website = website
        self.status: HitlStatus = "starting"
        self.hint: str | None = None
        self.error: str | None = None
        self.result: CaptureResult | None = None
        self.page_url: str | None = None
        self.page_title: str | None = None
        self._continue = asyncio.Event()
        self._cancel = asyncio.Event()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._allowed: set[str] = set()

    def snapshot(self) -> dict[str, object]:
        return {
            "status": self.status,
            "hint": self.hint,
            "error": self.error,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "has_result": self.result is not None,
        }

    def request_continue(self) -> None:
        self._continue.set()

    def request_cancel(self) -> None:
        self._cancel.set()

    async def run(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            self.status = "failed"
            self.error = (
                "Playwright is not installed. Re-run python3 run.py to install browser support."
            )
            raise RuntimeError(self.error) from error

        _ensure_user_browser_path()
        try:
            self._allowed = allowlist_for_website(self.website)
            start_url = validate_public_https_url(self.website, self._allowed)
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                **chromium_launch_kwargs(headless=False)
            )
            self._context = await self._browser.new_context(**browser_context_kwargs())
            self._page = await self._context.new_page()
            self._page.set_default_timeout(PAGE_TIMEOUT_MS)
            response = await self._page.goto(start_url, wait_until="domcontentloaded")
            await self._page.wait_for_timeout(SETTLE_MS)
            self.page_url = await _assert_destination(self._page, self._allowed)
            self.page_title = await self._page.title()
            status = response.status if response is not None else None
            try:
                code = await self._page.evaluate(CHALLENGE_HINT_JS)
            except Exception:
                code = None
            self.hint = (
                CHALLENGE_MESSAGES.get(str(code))
                if isinstance(code, str) and code in CHALLENGE_MESSAGES
                else INITIAL_HITL_HINT
            )
            self.status = "waiting_for_human"

            while True:
                cont_task = asyncio.create_task(self._continue.wait())
                cancel_task = asyncio.create_task(self._cancel.wait())
                done, pending = await asyncio.wait(
                    {cont_task, cancel_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if cancel_task in done:
                    self.status = "cancelled"
                    return
                # Human signalled continue; re-check destination then scan.
                self._continue.clear()
                try:
                    self.page_url = await _assert_destination(self._page, self._allowed)
                    self.page_title = await self._page.title()
                except NetworkPolicyError as error:
                    self.status = "failed"
                    self.error = str(error)
                    return

                self.status = "scanning"
                prefix = [
                    "HITL: reviewer completed interactive gates in a headed browser "
                    "(Clariti does not bypass Cloudflare or authentication).",
                    f"Opened {self.page_url}"
                    + (f" (HTTP {status})" if status is not None else "")
                    + f" title={self.page_title!r}.",
                ]
                self.result = await _scan_loaded_page(
                    self._page,
                    self._allowed,
                    prefix_findings=prefix,
                    limitations=HITL_LIMITATIONS,
                    summary_heading="Human-assisted privacy-indicator scan",
                )
                self.status = "completed"
                return
        except Exception as error:
            if self.status not in {"cancelled", "completed"}:
                self.status = "failed"
                self.error = f"{error.__class__.__name__}: {error}"
            raise
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        for closer in (
            getattr(self._context, "close", None),
            getattr(self._browser, "close", None),
            getattr(self._playwright, "stop", None),
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception:
                continue
        self._context = None
        self._browser = None
        self._playwright = None
        self._page = None
