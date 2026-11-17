from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
ARTIFACT_DIR = DATA_DIR / "artifacts"
DATABASE_PATH = DATA_DIR / "clariti.sqlite3"
STATIC_DIR = Path(__file__).resolve().parent / "ui" / "static"
# Project-local Playwright browsers (user-writable; no sudo / install-deps).
PLAYWRIGHT_BROWSERS_DIR = ROOT_DIR / ".playwright"

DEFAULT_COMPANION_NAME = "Clariti Web Evidence Reviewer"
DEFAULT_COMPANION_URL = (
    "https://gpt.loreal.net/dk/clariti_web_evidence_reviewer-0dfd5ceee8"
)
CHECKLIST_VERSION = "1.0"
HOST = "127.0.0.1"
PORT = 8765
ALLOWED_HOST = f"{HOST}:{PORT}"
