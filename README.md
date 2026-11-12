# Clariti Website Privacy Review Workbench

Local desktop app for collecting evidence and preparing draft privacy review
findings. Findings are evidence-based drafts, not legal advice, certification,
or a compliance decision.

Works on Windows, macOS, and Linux with Python 3.10+.

## Setup and run

From the project folder:

```bash
python3 run.py
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
2. Click **Scan website for privacy indicators** to open the site in a headless
   browser, scroll for privacy/cookie/consent/newsletter UI, and store
   screenshots plus a text summary. You can still add manual evidence.
3. Prepare a Companion handoff, copy the prompt, upload evidence manually.
4. Paste the Companion JSON response to import draft findings.
5. Optionally edit findings, sign off the revision, and export CSV/PDF.

First launch installs Chromium once via Playwright (needs network).

## Current support

- Persistent editable Companion name and HTTPS navigation URL.
- Versioned checklist templates and immutable snapshots for new reviews.
- Automated headless website scan (scroll + screenshots for common privacy UI).
- Manual text evidence and reviewed PNG/JPEG screenshot upload.
- Manual Companion handoff, strict JSON import, reviewer edits, sign-off.
- Draft and final CSV/PDF exports (final requires current sign-off).
- Local UI with no CDN, telemetry, or frontend build.
- Host, Origin, and CSRF checks on state-changing endpoints.
- Capture limited to the review site host (and www twin); private IPs blocked.

## Not implemented

- Full sitemap ingestion and SiteOne integration.
- Automated Companion login or authenticated chat APIs.

## Security limitations

Manual evidence is local but may contain personal data. Review and redact
files before upload. Opening or uploading to the Companion is user-directed
external processing. Captured text is rendered as text, never active HTML.

## Companion link

Use **Companion settings** in the findings panel, then **Save**. The app
validates HTTPS navigation URLs without embedded credentials. **Open** opens
only the currently saved URL after a user click.
