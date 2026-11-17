# Project state

## Current milestone

Milestone 4: Retrieval and integrations.

## Current task

SiteOne adapter remains disabled.

## Implemented

- Local FastAPI shell binds only to `127.0.0.1:8765`.
- Cross-platform launcher: `python3 run.py`, `./run.sh`, or `run.bat`
  (installs Chromium once into `.playwright/`, no sudo / install-deps).
- SQLite stores Companion settings, checklist templates, reviews, snapshots,
  evidence, handoffs, imports, reviewer edits, and approvals.
- Headless website scan opens the review HTTPS URL, scrolls for common
  privacy/cookie/consent/newsletter indicators, and stores screenshots plus a
  text summary. Capture is limited to the review host / www twin; private IPs
  are blocked.
- HITL headed capture: start → waiting_for_human → continue/cancel job API;
  reviewer completes CF/login/consent; scan resumes in the same context.
- Full sitemap scrape mode + `python3 -m app.headless` companion prompt stdout.
- Clariti Legal Companion system prompt in handoffs.
- PDF export embeds all screenshot artifacts.
- Companion handoff zip includes screenshots/ + text/ + prompt.
- Install/bootstrap lives in `app/install.py` (`python3 -m app.install`).
- Manual Companion handoff, strict JSON import, reviewer edits, sign-off.
- Draft/final CSV and PDF exports use effective findings (imports + edits).
- Simplified UI with auto-scan as the primary evidence action.

## Tests

- `.venv/bin/python -m pytest -q` passed: 23 tests.
- Headless smoke: `python3 -m app.headless https://example.com` printed companion prompt; PDF had 4 pages.
- Live capture smoke: `example.com` and `wikipedia.org` produced screenshots.
- Playwright Chromium launched headless as user `ua` with
  `PLAYWRIGHT_BROWSERS_PATH=.playwright` (no sudo).

## Limitations and blockers

- SiteOne remains disabled.
- Automated screenshots do not prove tracking behaviour or notice completeness.
- Sitemap scrape caps page texts / screenshots to keep local runs bounded.

## Next action

Add verified, constrained SiteOne adapter if still required; otherwise harden
live sitemap crawl tests against fixture HTTP.
