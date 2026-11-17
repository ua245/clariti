"""Runtime guards so Clariti never needs or triggers device-admin policies.

Clariti must:
- run as a normal (non-admin / non-root) user
- bind only to loopback
- never call sudo / playwright install-deps
- avoid Chromium flags that disable the sandbox or probe private LAN access
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.config import HOST, PLAYWRIGHT_BROWSERS_DIR, ROOT_DIR

# Chromium args chosen to stay user-local and reduce OS/MDM/firewall prompts.
# Never include --no-sandbox / --disable-setuid-sandbox (admin & policy red flags).
SAFE_CHROMIUM_ARGS: tuple[str, ...] = (
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backing-store-limit",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-component-extensions-with-background-pages",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-domain-reliability",
    "--disable-hang-monitor",
    "--disable-ipc-flooding-protection",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-renderer-backgrounding",
    "--disable-sync",
    "--metrics-recording-only",
    "--no-first-run",
    "--no-default-browser-check",
    "--password-store=basic",
    "--use-mock-keychain",
    "--disable-features="
    "TranslateUI,AudioServiceOutOfProcess,"
    "PrivateNetworkAccessPermissionPrompt,"
    "LocalNetworkAccessPermissions,"
    "LocalNetworkAccessChecks,"
    "InterestFeedContentSuggestions,"
    "AutoExpandDetailsElement",
)

FORBIDDEN_CHROMIUM_ARGS: tuple[str, ...] = (
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--allow-insecure-localhost",
    "--remote-debugging-address=0.0.0.0",
)


def is_elevated_admin() -> bool:
    """True if the process has OS admin/root privileges."""
    if os.name == "nt":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            return False
    geteuid = getattr(os, "geteuid", None)
    return bool(callable(geteuid) and geteuid() == 0)


def assert_unprivileged_process(*, context: str = "Clariti") -> None:
    """Refuse to run when elevated — avoids admin-policy / MDM interactions."""
    if is_elevated_admin():
        raise SystemExit(
            f"{context} must run as a normal user, not Administrator/root. "
            "Elevated runs can trigger device-admin and firewall policy controls. "
            "Re-run without sudo / 'Run as administrator'."
        )


def assert_loopback_only_host(host: str = HOST) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            f"Clariti refuses non-loopback bind host {host!r}. "
            "Only 127.0.0.1/localhost are allowed so public/private network "
            "firewall profiles are not triggered."
        )


def playwright_user_data_dir() -> Path:
    path = ROOT_DIR / ".playwright-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def chromium_launch_kwargs(*, headless: bool) -> dict[str, object]:
    """Shared Playwright Chromium launch options (no admin, no LAN probing)."""
    assert_unprivileged_process(context="Playwright Chromium launch")
    args = list(SAFE_CHROMIUM_ARGS)
    for forbidden in FORBIDDEN_CHROMIUM_ARGS:
        if any(forbidden in arg for arg in args):
            raise RuntimeError(f"Forbidden Chromium arg present: {forbidden}")
    kwargs: dict[str, object] = {
        "headless": headless,
        "args": args,
        "chromium_sandbox": True,
        "handle_sighup": True,
        "handle_sigint": True,
        "handle_sigterm": True,
    }
    # Persistent user profile under the project (never system-wide).
    # Playwright uses user_data_dir via launch_persistent_context; for launch()
    # we still point env / downloads to project-local paths.
    return kwargs


def browser_context_kwargs() -> dict[str, object]:
    return {
        "viewport": {"width": 1280, "height": 800},
        "java_script_enabled": True,
        "ignore_https_errors": False,
        "accept_downloads": False,
        "bypass_csp": False,
        "offline": False,
        # Do not grant geolocation, notifications, camera, mic, clipboard, etc.
        "permissions": [],
        "service_workers": "block",
    }


def ensure_user_browser_env() -> None:
    """Force project-local browser cache; never system Playwright paths."""
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and PLAYWRIGHT_BROWSERS_DIR.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_DIR)
    # Discourage Chromium from using system keyrings / elevated helpers.
    os.environ.setdefault("PLAYWRIGHT_SKIP_BROWSER_GC", "1")


def validate_chromium_args(args: list[str]) -> None:
    lowered = " ".join(args).lower()
    for forbidden in FORBIDDEN_CHROMIUM_ARGS:
        if forbidden.lower() in lowered:
            raise ValueError(f"Chromium arg {forbidden!r} is forbidden (admin/policy risk).")


def runtime_banner() -> str:
    return (
        f"Clariti runtime: user={os.getenv('USER') or os.getenv('USERNAME') or 'unknown'} "
        f"elevated={is_elevated_admin()} bind={HOST} "
        f"browsers={os.environ.get('PLAYWRIGHT_BROWSERS_PATH', PLAYWRIGHT_BROWSERS_DIR)}"
    )


def bootstrap_security_checks() -> None:
    assert_unprivileged_process()
    assert_loopback_only_host()
    ensure_user_browser_env()
    if hasattr(sys.stderr, "write"):
        print(runtime_banner(), flush=True)
