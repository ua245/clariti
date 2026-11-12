# Project state

## Current milestone

Milestone 4: Retrieval and integrations.

## Current task

Complete safe sitemap/static HTTP evidence capture. SiteOne remains disabled.

## Implemented

- Local FastAPI shell binds only to `127.0.0.1:8765`.
- Cross-platform launcher: `python3 run.py`, `./run.sh`, or `run.bat`
  (installs Chromium once via Playwright).
- SQLite stores Companion settings, checklist templates, reviews, snapshots,
  evidence, handoffs, imports, reviewer edits, and approvals.
- Headless website scan opens the review HTTPS URL, scrolls for common
  privacy/cookie/consent/newsletter indicators, and stores screenshots plus a
  text summary. Capture is limited to the review host / www twin; private IPs
  are blocked.
- Manual Companion handoff, strict JSON import, reviewer edits, sign-off.
- Draft/final CSV and PDF exports use effective findings (imports + edits).
- Simplified UI with auto-scan as the primary evidence action.

## Tests

- `.venv/bin/python -m pytest -q` passed: 15 tests.
- Live capture smoke: `example.com` and `wikipedia.org` produced screenshots.

## Limitations and blockers

- Sitemap/static capture endpoints and SiteOne remain incomplete.
- Automated screenshots do not prove tracking behaviour or notice completeness.

## Next action

Expose bounded, redirect-safe static retrieval using the policy module, with
XML namespace/gzip and public/private IPv4/IPv6 tests. Keep SiteOne disabled.
