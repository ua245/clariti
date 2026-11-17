#!/usr/bin/env python3
"""Cross-platform Clariti launcher (thin wrapper around app.install)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.install import bootstrap, browser_env  # noqa: E402


def main() -> None:
    python = bootstrap()
    print("Starting Clariti at http://127.0.0.1:8765")
    raise SystemExit(
        subprocess.call(
            [str(python), "-m", "app.launch"],
            cwd=ROOT,
            env=browser_env(),
        )
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            "Clariti setup or startup failed. "
            "Verify Python 3.10+, network access for package installation, "
            "and that Playwright can download Chromium without admin rights. "
            "You can also run: python3 -m app.install"
        ) from error
