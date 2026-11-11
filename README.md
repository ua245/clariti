# Clariti Website Privacy Review Workbench

Local Windows application for collecting evidence and preparing draft privacy
review findings. Findings are evidence-based drafts, not legal advice,
certification, or a compliance decision.

## Setup and run

Verified local runtime: Python 3.13.9. SiteOne is not yet inspected or
integrated.

```powershell
cd "C:\Users\umer.ahmed\OneDrive - L'Oréal\Documents\clariti"
.\run.bat
```

`run.bat` creates `.venv`, installs pinned dependencies only when
`requirements.txt` changes, starts Uvicorn on `127.0.0.1:8765`, and opens the
local browser page. Stop Uvicorn with `Ctrl+C`.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Current support

- Persistent editable Companion name and HTTPS navigation URL.
- Explicit Companion reset to default. Saved values survive restart.
- Versioned checklist templates and immutable snapshots for new reviews.
- Manual text evidence and reviewed PNG/JPEG screenshot upload.
- Local three-column UI with no CDN, telemetry, or frontend build.
- Host, Origin, and CSRF checks on state-changing endpoints.

## Disabled or not implemented

- Companion handoff, response import, findings, reviewer edits, sign-off, CSV,
  and PDF reporting.
- Sitemap/HTTP retrieval, SiteOne, and browser capture.
- SiteOne version and capabilities remain unverified. No executable is run.

## Security limitations

Manual evidence is local but may contain personal data. Review and redact
files before upload. Opening or uploading to the Companion is user-directed
external processing, not local processing. Captured text is rendered as text,
never active HTML. This early version does not detect personal data.

## Change Companion link

Use **Companion configuration** in the right column, then select **Save
Companion**. The app validates HTTPS navigation URLs without embedded
credentials. **Open Companion** opens only the currently saved URL after a
user click; it does not fetch or inspect the destination.

## L'OréalGPT access

Authenticate to `gpt.loreal.net` yourself in your normal browser session before
selecting **Open Companion**. Clariti does not automate login, reuse profiles,
cookies, SSO tokens, or authenticated chat APIs. Copy the generated prompt and
upload reviewed evidence manually, then paste raw JSON results back into Clariti.

## Resume interrupted development

Read `AGENTS.md`, `PROJECT_STATE.md`, `TASKS.md`, and `docs\DECISIONS.md`.
Inspect the working tree if Git is initialized. Resume the first incomplete
task in `TASKS.md`; update recovery files with exact test results before
stopping.
