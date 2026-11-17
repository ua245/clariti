"""Clariti install/bootstrap library (venv, deps, Playwright Chromium).

No sudo / playwright install-deps. Safe to call from run.py or:

  python3 -m app.install
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.config import PLAYWRIGHT_BROWSERS_DIR, ROOT_DIR

ROOT = ROOT_DIR
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
MARKER = VENV / "requirements.txt"
BROWSER_MARKER = VENV / "playwright-chromium.ok"
PLAYWRIGHT_BROWSERS = PLAYWRIGHT_BROWSERS_DIR


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def browser_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """User-writable browser cache; never requires install-deps / sudo."""
    env = dict(base or os.environ)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS)
    return env


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.check_call(command, cwd=ROOT, env=env or browser_env())


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
    if MARKER.is_file() and REQUIREMENTS.is_file() and REQUIREMENTS.read_bytes() == MARKER.read_bytes():
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
    """Download Chromium into .playwright/ only. Never runs install-deps (sudo)."""
    if BROWSER_MARKER.is_file() and PLAYWRIGHT_BROWSERS.is_dir():
        return
    print("Installing Chromium for website capture (one-time, user-local)...")
    PLAYWRIGHT_BROWSERS.mkdir(parents=True, exist_ok=True)
    # Intentionally omit --with-deps / install-deps: those need admin rights.
    run([str(python), "-m", "playwright", "install", "chromium"])
    try:
        run(
            [
                str(python),
                "-c",
                "from playwright.sync_api import sync_playwright\n"
                "from app.security_runtime import chromium_launch_kwargs\n"
                "with sync_playwright() as p:\n"
                "    b = p.chromium.launch(**chromium_launch_kwargs(headless=True))\n"
                "    b.close()\n"
                "print('chromium-ok')\n",
            ]
        )
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            "Chromium downloaded but failed to launch. Clariti does not use "
            "sudo or Playwright install-deps. Install the usual Chromium shared "
            "libraries for your OS as a normal user (or ask an admin once), "
            "then re-run python3 -m app.install."
        ) from error
    BROWSER_MARKER.write_text("chromium\n", encoding="utf-8")


def bootstrap() -> Path:
    """Ensure venv + requirements + Chromium. Returns venv python path."""
    from app.security_runtime import assert_loopback_only_host, assert_unprivileged_process

    assert_unprivileged_process(context="Clariti install")
    assert_loopback_only_host()
    python = ensure_venv()
    ensure_requirements(python)
    ensure_browser(python)
    return python


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Install Clariti dependencies and Playwright Chromium "
            "(no sudo / no install-deps / no admin)."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify install markers; exit non-zero if incomplete.",
    )
    args = parser.parse_args(argv)
    try:
        if args.check:
            python = venv_python()
            ok = (
                python.is_file()
                and MARKER.is_file()
                and BROWSER_MARKER.is_file()
                and PLAYWRIGHT_BROWSERS.is_dir()
            )
            if not ok:
                raise SystemExit("Clariti install is incomplete. Run: python3 -m app.install")
            print("Clariti install OK")
            return
        bootstrap()
        print("Clariti install complete (venv, requirements, Chromium).")
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            "Clariti install failed. "
            "Verify Python 3.10+, network access for package installation, "
            "and that Playwright can download Chromium without admin rights."
        ) from error


if __name__ == "__main__":
    main()
