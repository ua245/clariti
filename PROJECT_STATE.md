# Project state

## Current milestone

Milestone 3: Review and reports.

## Current task

Add reviewer edits/history and revision-specific sign-off before CSV/PDF export.

## Implemented

- Local FastAPI shell binds only to `127.0.0.1:8765`.
- SQLite stores persistent Companion settings, versioned checklist templates,
  reviews, immutable snapshots, selected checklist IDs, and manual evidence.
- Companion name and HTTPS URL can be saved or explicitly reset; saved values
  survive application restart.
- Reviews validate selected checklist items and retain template snapshots.
- Manual text evidence and reviewer-confirmed PNG/JPEG screenshots are stored
  as immutable local records. Website content is rendered only as text.
- Accessible black, white, and grey three-column UI supports review creation,
  checklist selection, evidence capture, and Companion configuration.
- State changes enforce exact local Host, same Origin, and CSRF token checks.
- `run.bat` creates `.venv`, installs changed pinned requirements, then opens
  the browser only after local startup succeeds.
- Manual Companion handoff creates persistent batches with evidence manifests,
  schema-generated response contract, reviewed attachment links, and inert
  evidence instructions.
- Strict Companion JSON import accepts raw JSON or one JSON fence, rejects
  duplicate keys, unknown fields, wrong IDs, cross-batch evidence, duplicate
  checklist items, and evidence-free Pass/Fail/Partial.
- Original imported output and AI draft findings are retained locally.

## Files changed

- `.gitignore`, `requirements.txt`, `run.bat`, `README.md`
- `app/config.py`, `app/main.py`, `app/launch.py`
- `app/companions/*`
- `app/checklist/*`, `app/storage/*`, `app/evidence/*`, `app/ui/static/*`
- `tests/test_foundation.py`, `tests/test_companion.py`
- `AGENTS.md`, `PROJECT_STATE.md`, `TASKS.md`, `docs/DECISIONS.md`

## Tests

- `.\.venv\Scripts\python.exe -m compileall -q app` passed.
- `.\.venv\Scripts\python.exe -m pytest -q` passed: 9 tests.
- Local launcher smoke check passed: `GET /health` returned
  `200 {"status":"ok"}`.
- Pytest emitted one third-party Starlette deprecation warning about
  `anyio.abc.BlockingPortal`.

## Limitations and blockers

- Project began in an empty folder; no Git repository exists.
- Reviewer edits, sign-off, CSV/PDF, sitemap/HTTP retrieval, SiteOne, and
  browser capture remain unimplemented.
- SiteOne executable/version and attachment capability limits remain unknown;
  no SiteOne executable has been run.

## Next action

Add reviewer edit history and approval records. Changes to scope, evidence,
findings, or checklist must invalidate approval before report generation.
