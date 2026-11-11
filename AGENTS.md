# Clariti recovery guide

## Permanent constraints

- Run locally on Windows with Python 3.10+ and project-local `.venv`.
- Bind the application only to `127.0.0.1`; never enable permissive CORS.
- Do not log captured content, personal data, credentials, or secrets.
- Use parameterized SQLite queries. Treat all captured/imported content as untrusted text.
- Render no captured HTML. Escape untrusted text in UI and reporting.
- State-changing requests require same-origin checks and CSRF validation.
- Companion handoff is manual upload/import only. Never automate authenticated Companion chat or inspect its URL.
- Evidence is immutable. Derived redacted evidence must link to its original.
- Findings are draft evidence reviews, never legal advice or a compliance verdict.

## Architecture

- `app/main.py`: FastAPI application and HTTP routes.
- `app/config.py`: local paths and default Companion settings.
- `app/storage/`: SQLite schema and repositories.
- `app/checklist/`: validated versioned checklist templates.
- `app/evidence/`: safe manual evidence storage.
- `app/ui/`: local static HTML, CSS, and JavaScript.
- `tests/`: offline pytest tests.
- `data/`: local database and artifacts; ignored by Git.

## Commands

```powershell
.\run.bat
.\.venv\Scripts\python.exe -m pytest
```

## Recovery

At session start, read `AGENTS.md`, `PROJECT_STATE.md`, `TASKS.md`, and
`docs\DECISIONS.md`; inspect `git status` if available; then resume the first
unfinished checkbox in `TASKS.md`. Before stopping, update all recovery files
with changed files, exact tests run, results, limitations, and next action.
