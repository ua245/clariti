# Clariti Website Privacy Review Workbench

Local desktop app for collecting evidence and preparing draft privacy review
findings. Findings are evidence-based drafts, not legal advice, certification,
or a compliance decision.

Works on Windows, macOS, and Linux with Python 3.10+.

## Setup and run

From the project folder:

```bash
python3 -m app.install   # venv + deps + Chromium (no sudo)
python3 run.py           # install if needed, then start UI
```

Windows (PowerShell or Command Prompt):

```bat
run.bat
```

macOS / Linux:

```bash
./run.sh
```

The launcher creates `.venv`, installs pinned dependencies only when
`requirements.txt` changes, starts Uvicorn on `127.0.0.1:8765`, and opens the
local browser. Stop with `Ctrl+C`.

Optional: if [uv](https://github.com/astral-sh/uv) is installed, the launcher
uses it for faster environment setup.

Run tests:

```bash
.venv/bin/python -m pytest          # macOS / Linux
.venv\Scripts\python.exe -m pytest  # Windows
```

## Workflow

1. Create a review (website + scope + checklist items).
2. Click **Scan website for privacy indicators**. Default mode is **Full sitemap
   scrape (headed)**: a visible browser opens so you complete Cloudflare/login,
   then Continue to crawl in that session (Continue again if another challenge
   appears). Clariti does not bypass those controls.
3. Prepare a Companion handoff, copy the updated legal companion prompt, upload
   evidence manually.
4. Paste the Companion JSON response to import draft findings.
5. Optionally edit findings, sign off the revision, and export CSV/PDF (PDF embeds
   **all** screenshots).

Headless / chat output (no UI):

```bash
python3 -m app.headless https://example.com --headed --json-summary
python3 -m app.headless https://example.com --pdf /tmp/clariti-draft.pdf \
  --package /tmp/clariti-handoff.zip
```

Use `--headed` when Cloudflare/auth blocks the site (press Enter in the terminal
after you finish the browser gate).

The command prints the Clariti Legal Companion system prompt + handoff manifest
to stdout so you can paste it into chat. The handoff zip includes **all screenshots**
under `screenshots/` for Companion upload.

First launch installs Chromium once via Playwright into project-local
`.playwright/` (needs network). This does **not** run `playwright install-deps`
or require sudo/admin rights.

## Current support

- Persistent editable Companion name and HTTPS navigation URL.
- Versioned checklist templates and immutable snapshots for new reviews.
- Full sitemap scrape (bounded): robots.txt + sitemap XML, static HTML text
  extracts, prioritized screenshots, homepage indicator scan.
- Homepage-only headless indicator scan.
- Human-assisted (HITL) headed capture for Cloudflare / consent / authorized
  login walls; reviewer completes gates; no automated bypass.
- Headless CLI (`python3 -m app.headless`) prints companion prompt for chat.
- PDF export embeds every stored screenshot.
- Manual text evidence and reviewed PNG/JPEG screenshot upload.
- Manual Companion handoff, strict JSON import, reviewer edits, sign-off.
- Draft and final CSV/PDF exports (final requires current sign-off).
- Local UI with no CDN, telemetry, or frontend build.
- Host, Origin, and CSRF checks on state-changing endpoints.
- Capture limited to the review site host (and www twin); private IPs blocked.

## Not implemented

- SiteOne integration.
- Automated Companion login or authenticated chat APIs.

## Security limitations

Manual evidence is local but may contain personal data. Review and redact
files before upload. Opening or uploading to the Companion is user-directed
external processing. Captured text is rendered as text, never active HTML.

Clariti is designed **not** to trip device-admin / MDM / public–private network
firewall policies: no sudo/`install-deps`, no Administrator/root runs, UI bound
to `127.0.0.1` only, Chromium keeps its sandbox (never `--no-sandbox`), and
capture blocks private/LAN/local hostnames and non-443 targets.

## Companion link

Use **Companion settings** in the findings panel, then **Save**. The app
validates HTTPS navigation URLs without embedded credentials. **Open** opens
only the currently saved URL after a user click.
