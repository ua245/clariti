#!/usr/bin/env python3
"""Cross-platform Clariti launcher.

Creates a project-local virtual environment if needed, installs pinned
dependencies when requirements change, ensures Chromium for website capture,
then starts the local app.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
MARKER = VENV / "requirements.txt"
BROWSER_MARKER = VENV / "playwright-chromium.ok"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.check_call(command, cwd=ROOT)


def ensure_venv() -> Path:
    python = venv_python()
    if python.is_file():
        return python

    print("Creating project-local virtual environment...")
    uv = shutil.which("uv")
    if uv:
        run([uv, "venv", str(VENV)])
    else:
        run([sys.executable, "-m", "venv", str(VENV)])
    if not python.is_file():
        raise SystemExit(
            "Could not create a virtual environment. Install Python 3.10+ "
            "with the venv module, or install uv (https://github.com/astral-sh/uv)."
        )
    return python


def ensure_requirements(python: Path) -> None:
    needs_install = True
    if MARKER.is_file() and REQUIREMENTS.read_bytes() == MARKER.read_bytes():
        needs_install = False
    if not needs_install:
        return

    print("Installing pinned requirements...")
    uv = shutil.which("uv")
    if uv:
        run([uv, "pip", "install", "-r", str(REQUIREMENTS), "--python", str(python)])
    else:
        run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(REQUIREMENTS),
            ]
        )
    MARKER.write_bytes(REQUIREMENTS.read_bytes())
    if BROWSER_MARKER.exists():
        BROWSER_MARKER.unlink()


def ensure_browser(python: Path) -> None:
    if BROWSER_MARKER.is_file():
        return
    print("Installing Chromium for website capture (one-time)...")
    run([str(python), "-m", "playwright", "install", "chromium"])
    BROWSER_MARKER.write_text("chromium\n", encoding="utf-8")


def main() -> None:
    python = ensure_venv()
    ensure_requirements(python)
    ensure_browser(python)
    print("Starting Clariti at http://127.0.0.1:8765")
    raise SystemExit(subprocess.call([str(python), "-m", "app.launch"], cwd=ROOT))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            "Clariti setup or startup failed. "
            "Verify Python 3.10+, network access for package installation, "
            "and that Playwright can download Chromium."
        ) from error
