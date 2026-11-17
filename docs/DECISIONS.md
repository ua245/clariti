# Decisions

## 2026-11-11: Local FastAPI foundation

Use FastAPI, SQLite, static HTML/CSS/JavaScript, and a project-local virtual
environment. This avoids a Node build chain and supports local-only deployment.

## 2026-11-11: Manual Companion transport

Companion link opens only after a user action. Evidence upload and response
import remain manual because the link is a browser navigation URL, not a known
API endpoint or credential.

## 2026-11-11: Foundation before retrieval

Implement manual evidence before network retrieval. This preserves a usable,
low-risk workflow while SSRF, browser, and SiteOne controls are designed and
tested in later milestones.

## 2026-11-11: Immutable review snapshots and evidence

Each review stores its selected checklist IDs and full checklist JSON snapshot.
New checklist versions become active only for later reviews. Text evidence and
reviewer-confirmed PNG/JPEG uploads use generated IDs and immutable files;
application UI renders evidence with DOM text nodes, not HTML parsing.

## 2026-11-11: Local request defences

State-changing requests require the exact configured local Host, matching
Origin, and a random same-site CSRF cookie/header pair. This supports local
browser use without exposing a network API or enabling CORS.

## 2026-11-11: Strict manual Companion contract

Manual handoffs persist a batch manifest and schema generated from authoritative
Pydantic models. Response import accepts raw JSON or one JSON fence only,
rejects duplicate object keys before validation, and never repairs model output.
The application stores original output separately from draft findings.

## 2026-11-12: Constrained Playwright capture

Use Playwright Chromium for optional headless capture of the review website
only. Destination checks require HTTPS, the review host allowlist (including
www/apex twin), and public resolvable addresses. Capture scrolls for common
privacy/cookie/consent/newsletter indicators and stores local screenshots plus
a text summary. It does not follow off-host links or automate Companion chat.

## 2026-11-17: User-local Playwright browsers (no admin)

Install Chromium with `playwright install chromium` into project-local
`.playwright/` (`PLAYWRIGHT_BROWSERS_PATH`). Do not run `install-deps` /
`--with-deps` from Clariti; those require elevated OS privileges. The launcher
verifies a headless launch after download and fails with a non-sudo remediation
message if shared libraries are missing.

## 2026-11-17: HITL capture for interactive gates

When headless capture is blocked by Cloudflare interstitials, consent walls, or
an authorized login, Clariti offers a human-assisted headed session: open the
review URL, pause for the reviewer to complete the gate themselves, then resume
the same privacy-indicator scan with that live browser context. Clariti must
not automate Cloudflare challenge solving, Turnstile forging, WAF evasion, or
credential theft. Cookies stay in the live context only (not persisted).

## 2026-11-17: Full sitemap scrape + legal companion prompt + PDF screenshots

Sitemap mode discovers on-host sitemaps via robots.txt and common paths, parses
nested indexes with depth/size caps, stores static HTML text extracts (scripts
stripped), and takes prioritized headed/headless screenshots plus a homepage
indicator scan. The Companion handoff uses the Clariti Legal Companion system
prompt. Draft/final PDFs embed every screenshot artifact. Headless CLI
`python3 -m app.headless` prints the prompt for chat paste.

## 2026-11-17: Handoff zip includes screenshots; install lives in app library

Companion handoff packages are zip files containing `prompt.txt`, `manifest.json`,
`screenshots/*`, and `text/*`. UI and headless expose the package for upload.
Install/bootstrap logic lives in `app/install.py` (`python3 -m app.install`);
`run.py` is a thin launcher wrapper.

## 2026-11-17: No device-admin / public-private network policy triggers

Clariti refuses elevated (Administrator/root) processes, binds only to
`127.0.0.1`, keeps Playwright browsers project-local, never runs
`install-deps`/`sudo`, and launches Chromium with sandbox enabled plus flags
that disable private/local-network access permission prompts. Outbound capture
allows only public HTTPS :443 on the review allowlist (no private/LAN/.local).
