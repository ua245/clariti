"""Full-site evidence capture: sitemap crawl + static pages + prioritized screenshots.

Default path is headed HITL: reviewer completes Cloudflare/login once (or again if
a challenge reappears), then Clariti crawls in that same browser session.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from app.fetch.browser_capture import (
    CHALLENGE_HINT_JS,
    CHALLENGE_MESSAGES,
    INITIAL_HITL_HINT,
    CaptureResult,
    CaptureShot,
    HITL_LIMITATIONS,
    HEADLESS_LIMITATIONS,
    HitlStatus,
    _assert_destination,
    _ensure_user_browser_path,
    _scan_loaded_page,
    PAGE_TIMEOUT_MS,
    SETTLE_MS,
    VIEWPORT,
)
from app.fetch.html_text import html_to_evidence_text
from app.fetch.network_policy import allowlist_for_website, validate_public_https_url
from app.fetch.sitemap_crawl import SitemapCrawlResult, discover_sitemap_urls, prioritize_urls
from app.fetch.static_fetch import fetch_public_https
from app.security_runtime import browser_context_kwargs, chromium_launch_kwargs

MAX_STATIC_PAGES = 120
MAX_SCREENSHOT_PAGES = 40
MAX_SCREENSHOTS_TOTAL = 80

HitlKind = Literal["indicators", "sitemap"]


@dataclass
class PageTextEvidence:
    source_url: str
    final_url: str
    text: str
    http_status: int | None
    limitations: str


@dataclass
class SiteCaptureResult:
    website: str
    sitemap: SitemapCrawlResult
    pages: list[PageTextEvidence] = field(default_factory=list)
    shots: list[CaptureShot] = field(default_factory=list)
    indicator_summary: str = ""
    page_title: str = ""
    final_url: str = ""
    limitations: str = (
        "Sitemap + static/rendered capture. Sitemap URLs are discovery only. "
        "Extracted HTML text is inert evidence. Screenshots show observable UI only; "
        "they do not prove tracking behaviour, script execution, or notice completeness."
    )

    def overview_text(self) -> str:
        lines = [
            "Full-site privacy evidence capture",
            f"Website: {self.website}",
            f"Final homepage URL: {self.final_url or self.website}",
            f"Homepage title: {self.page_title!r}",
            f"Sitemap page URLs discovered: {len(self.sitemap.page_urls)}",
            f"Static page texts stored: {len(self.pages)}",
            f"Screenshots stored: {len(self.shots)}",
            "",
            self.sitemap.summary_text(),
            "",
            "Indicator scan notes:",
            self.indicator_summary or "(none)",
            "",
            f"Limitations: {self.limitations}",
        ]
        return "\n".join(lines)[:100_000]


async def _static_page_texts(
    urls: list[str], allowed: set[str]
) -> list[PageTextEvidence]:
    pages: list[PageTextEvidence] = []
    for url in urls[:MAX_STATIC_PAGES]:
        try:
            fetched = await fetch_public_https(url, allowed)
        except Exception as error:
            pages.append(
                PageTextEvidence(
                    source_url=url,
                    final_url=url,
                    text=f"Source URL: {url}\nFetch failed: {error.__class__.__name__}: {error}",
                    http_status=None,
                    limitations="Static fetch failed; no page body captured.",
                )
            )
            continue
        if fetched.status_code >= 400:
            pages.append(
                PageTextEvidence(
                    source_url=url,
                    final_url=fetched.final_url,
                    text=f"Source URL: {url}\nHTTP {fetched.status_code}",
                    http_status=fetched.status_code,
                    limitations="Non-success HTTP status; body not treated as notice content.",
                )
            )
            continue
        ctype = fetched.content_type
        if "html" not in ctype and not fetched.body.lstrip().startswith(
            (b"<!DOCTYPE", b"<html", b"<HTML", b"<!")
        ):
            pages.append(
                PageTextEvidence(
                    source_url=url,
                    final_url=fetched.final_url,
                    text=(
                        f"Source URL: {url}\nContent-Type: {ctype or '(unknown)'}\n"
                        "Non-HTML body skipped for text extraction."
                    ),
                    http_status=fetched.status_code,
                    limitations="Non-HTML response; no HTML text extracted.",
                )
            )
            continue
        text = html_to_evidence_text(fetched.body, source_url=fetched.final_url)
        pages.append(
            PageTextEvidence(
                source_url=url,
                final_url=fetched.final_url,
                text=text,
                http_status=fetched.status_code,
                limitations=(
                    "Static HTML text extraction only. Scripts not executed. "
                    "Does not prove visual prominence, consent interaction, or tracking."
                ),
            )
        )
    return pages


def challenge_message(code: str | None) -> str | None:
    """Map detector codes to UI text. Unknown/empty codes mean no pause."""
    if not code:
        return None
    return CHALLENGE_MESSAGES.get(str(code).strip())


async def _browser_site_shots(
    website: str,
    page_urls: list[str],
    *,
    headless: bool,
    page: Any | None = None,
    context: Any | None = None,
    wait_human: Any | None = None,
) -> tuple[str, str, str, list[CaptureShot], list[PageTextEvidence]]:
    """Screenshot + DOM text from a browser. Optionally reuse an open HITL page."""
    owned = page is None
    browser = None
    playwright = None
    pages_text: list[PageTextEvidence] = []
    shots: list[CaptureShot] = []
    indicator_summary = ""
    page_title = ""
    final_url = website
    limitations = HEADLESS_LIMITATIONS if headless else HITL_LIMITATIONS

    _ensure_user_browser_path()
    allowed = allowlist_for_website(website)
    start_url = validate_public_https_url(website, allowed)
    targets = prioritize_urls(
        list(dict.fromkeys([start_url, *page_urls])),
        limit=MAX_SCREENSHOT_PAGES,
    )

    try:
        if owned:
            try:
                from playwright.async_api import async_playwright
            except ImportError as error:
                raise RuntimeError(
                    "Playwright is not installed. Re-run python3 run.py to install browser support."
                ) from error
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                **chromium_launch_kwargs(headless=headless)
            )
            context = await browser.new_context(**browser_context_kwargs())
            page = await context.new_page()
            page.set_default_timeout(PAGE_TIMEOUT_MS)

        assert page is not None

        for index, target in enumerate(targets):
            if len(shots) >= MAX_SCREENSHOTS_TOTAL:
                break
            try:
                response = await page.goto(target, wait_until="domcontentloaded")
                await page.wait_for_timeout(SETTLE_MS)
                if wait_human is not None:
                    try:
                        code = await page.evaluate(CHALLENGE_HINT_JS)
                    except Exception:
                        code = None
                    message = challenge_message(code if isinstance(code, str) else None)
                    if message:
                        await wait_human(message)
                        await page.wait_for_timeout(SETTLE_MS)
                current = validate_public_https_url(page.url, allowed)
                title = await page.title()
                status = response.status if response is not None else None
                html = await page.content()
                pages_text.append(
                    PageTextEvidence(
                        source_url=target,
                        final_url=current,
                        text=html_to_evidence_text(html, source_url=current),
                        http_status=status,
                        limitations=(
                            "DOM text extracted from headed/rendered browser session after "
                            "human-assisted gates where applicable. Does not prove tracking."
                        ),
                    )
                )
                if index == 0:
                    final_url = current
                    page_title = title
                    scan = await _scan_loaded_page(
                        page,
                        allowed,
                        prefix_findings=[
                            f"Opened {current}"
                            + (f" (HTTP {status})" if status is not None else "")
                            + f" title={title!r}."
                        ],
                        limitations=limitations,
                        summary_heading="Homepage privacy-indicator scan",
                    )
                    indicator_summary = scan.summary_text
                    shots.extend(scan.shots)
                    continue

                png = await page.screenshot(type="png", full_page=False)
                shots.append(
                    CaptureShot(
                        label=f"sitemap-page-{index}",
                        png_bytes=png,
                        source_url=current,
                        note=(
                            f"Sitemap page screenshot title={title!r}"
                            + (f" HTTP {status}" if status is not None else "")
                        ),
                    )
                )
            except Exception as error:
                shots.append(
                    CaptureShot(
                        label=f"sitemap-page-{index}-failed",
                        png_bytes=b"",
                        source_url=target,
                        note=f"Screenshot failed: {error.__class__.__name__}: {error}",
                    )
                )
        if owned and context is not None:
            await context.close()
    finally:
        if owned:
            if browser is not None:
                await browser.close()
            if playwright is not None:
                await playwright.stop()

    shots = [shot for shot in shots if shot.png_bytes]
    return (
        final_url,
        page_title,
        indicator_summary,
        shots[:MAX_SCREENSHOTS_TOTAL],
        pages_text,
    )


async def capture_full_site(website: str, *, headless: bool = True) -> SiteCaptureResult:
    sitemap = await discover_sitemap_urls(website)
    allowed = allowlist_for_website(website)
    limitations = HEADLESS_LIMITATIONS if headless else HITL_LIMITATIONS
    if headless:
        pages = await _static_page_texts(sitemap.page_urls, allowed)
        final_url, page_title, indicator_summary, shots, _ = await _browser_site_shots(
            website,
            sitemap.page_urls,
            headless=True,
        )
    else:
        # Prefer browser DOM text (survives CF/auth after human step).
        final_url, page_title, indicator_summary, shots, pages = await _browser_site_shots(
            website,
            sitemap.page_urls,
            headless=False,
        )
    return SiteCaptureResult(
        website=website,
        sitemap=sitemap,
        pages=pages,
        shots=shots,
        indicator_summary=indicator_summary,
        page_title=page_title,
        final_url=final_url,
        limitations=(
            limitations
            + " Sitemap crawl used a headed session where Cloudflare/login were "
            "completed by the reviewer when required."
            if not headless
            else (
                "Sitemap + static/rendered capture. Sitemap URLs are discovery only. "
                "Extracted HTML text is inert evidence. Screenshots show observable UI only; "
                "they do not prove tracking behaviour, script execution, or notice completeness."
            )
        ),
    )


def site_capture_to_indicator_result(result: SiteCaptureResult) -> CaptureResult:
    """Adapter for callers that expect CaptureResult + overview text separately."""
    return CaptureResult(
        final_url=result.final_url or result.website,
        page_title=result.page_title,
        summary_text=result.overview_text(),
        shots=result.shots,
        limitations=result.limitations,
    )


class HitlSitemapSession:
    """Headed full-site sitemap scrape with human pause(s) for CF/auth."""

    def __init__(self, website: str) -> None:
        self.website = website
        self.status: HitlStatus = "starting"
        self.hint: str | None = None
        self.error: str | None = None
        self.result: CaptureResult | None = None
        self.site_result: SiteCaptureResult | None = None
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
            "has_result": self.site_result is not None or self.result is not None,
            "kind": "sitemap",
        }

    def request_continue(self) -> None:
        self._continue.set()

    def request_cancel(self) -> None:
        self._cancel.set()

    async def _wait_for_human(self, hint: str) -> None:
        self.hint = hint
        self.status = "waiting_for_human"
        self._continue.clear()
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
                raise asyncio.CancelledError("HITL sitemap capture cancelled.")
            self._continue.clear()
            self.status = "scanning"
            return

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
            await self._page.goto(start_url, wait_until="domcontentloaded")
            await self._page.wait_for_timeout(SETTLE_MS)
            self.page_url = await _assert_destination(self._page, self._allowed)
            self.page_title = await self._page.title()
            try:
                code = await self._page.evaluate(CHALLENGE_HINT_JS)
            except Exception:
                code = None
            # Always pause once at start so the reviewer can clear CF/auth.
            # Mid-crawl pauses only when challenge_message() returns a real hit.
            initial_hint = challenge_message(code if isinstance(code, str) else None) or INITIAL_HITL_HINT
            await self._wait_for_human(initial_hint)
            if self.status == "cancelled":
                return

            self.page_url = await _assert_destination(self._page, self._allowed)
            self.page_title = await self._page.title()
            self.status = "scanning"

            sitemap = await discover_sitemap_urls(self.website)

            async def wait_human(message: str) -> None:
                self.page_url = self._page.url if self._page else self.page_url
                try:
                    self.page_title = await self._page.title() if self._page else self.page_title
                except Exception:
                    pass
                await self._wait_for_human(message)

            final_url, page_title, indicator_summary, shots, pages = await _browser_site_shots(
                self.website,
                sitemap.page_urls,
                headless=False,
                page=self._page,
                context=self._context,
                wait_human=wait_human,
            )
            self.site_result = SiteCaptureResult(
                website=self.website,
                sitemap=sitemap,
                pages=pages,
                shots=shots,
                indicator_summary=indicator_summary,
                page_title=page_title or self.page_title or "",
                final_url=final_url or self.page_url or self.website,
                limitations=(
                    HITL_LIMITATIONS
                    + " Full sitemap scrape used a headed browser; the reviewer completed "
                    "Cloudflare/authentication gates. Clariti does not bypass those controls."
                ),
            )
            self.result = site_capture_to_indicator_result(self.site_result)
            self.page_url = self.site_result.final_url
            self.page_title = self.site_result.page_title
            self.status = "completed"
        except asyncio.CancelledError:
            self.status = "cancelled"
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
