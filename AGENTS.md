# Clariti recovery guide

## Permanent constraints

- Run locally on Windows, macOS, or Linux with Python 3.10+ and project-local `.venv`.
- Playwright Chromium lives in project-local `.playwright/` via
  `PLAYWRIGHT_BROWSERS_PATH`. Never call `playwright install-deps` or sudo;
  capture must run as a normal (non-Administrator/root) user.
- Never launch Chromium with `--no-sandbox` / LAN-probe features that trip
  device-admin, MDM, or public/private network firewall prompts. Use
  `app/security_runtime.py` launch helpers only.
- Capture targets must be public HTTPS :443 on the review host allowlist;
  private, loopback, link-local, `.local`/`.corp`/`.lan`, and non-443 ports
  are blocked so local/admin networks are never scanned.
- HITL capture may open a headed browser so a human can complete Cloudflare,
  consent, or authorized login gates. Never automate bypass of those controls.
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

```bash
python3 -m app.install  # library install: venv, deps, Chromium (no sudo)
python3 run.py          # any OS (calls app.install.bootstrap)
./run.sh                # macOS / Linux
run.bat                 # Windows
.venv/bin/python -m pytest
.venv/bin/python -m app.headless https://example.com --json-summary --package /tmp/h.zip
```

## Recovery

At session start, read `AGENTS.md`, `PROJECT_STATE.md`, `TASKS.md`, and
`docs\DECISIONS.md`; inspect `git status` if available; then resume the first
unfinished checkbox in `TASKS.md`. Before stopping, update all recovery files
with changed files, exact tests run, results, limitations, and next action.
