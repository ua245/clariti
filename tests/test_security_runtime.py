from app.config import HOST
from app.fetch.network_policy import NetworkPolicyError, validate_public_https_url
from app.fetch.site_capture import challenge_message
from app.security_runtime import (
    FORBIDDEN_CHROMIUM_ARGS,
    SAFE_CHROMIUM_ARGS,
    assert_loopback_only_host,
    chromium_launch_kwargs,
    validate_chromium_args,
)


def test_host_is_loopback_only() -> None:
    assert HOST == "127.0.0.1"
    assert_loopback_only_host()


def test_safe_chromium_args_forbid_admin_flags() -> None:
    validate_chromium_args(list(SAFE_CHROMIUM_ARGS))
    for forbidden in FORBIDDEN_CHROMIUM_ARGS:
        assert forbidden not in " ".join(SAFE_CHROMIUM_ARGS)


def test_chromium_launch_kwargs_keep_sandbox() -> None:
    kwargs = chromium_launch_kwargs(headless=True)
    assert kwargs["chromium_sandbox"] is True
    assert kwargs["headless"] is True
    validate_chromium_args(list(kwargs["args"]))  # type: ignore[arg-type]
    joined = " ".join(kwargs["args"])  # type: ignore[arg-type]
    assert "--no-sandbox" not in joined
    assert "PrivateNetworkAccessPermissionPrompt" in joined
    assert "LocalNetworkAccess" in joined


def test_challenge_message_ignores_generic_cloudflare_text() -> None:
    # Regression: generic instructional copy must NOT re-pause every sitemap page.
    assert challenge_message(None) is None
    assert challenge_message("") is None
    assert (
        challenge_message(
            "Complete any Cloudflare, consent, or login steps in this browser window"
        )
        is None
    )
    assert challenge_message("cf_challenge") is not None
    assert "Cloudflare" in (challenge_message("cf_challenge") or "")
    assert challenge_message("login_wall") is not None


def test_blocks_private_and_local_hostnames() -> None:
    allowed = {"example.com", "www.example.com"}
    for url in (
        "https://127.0.0.1/",
        "https://10.0.0.1/",
        "https://192.168.1.1/",
        "https://localhost/",
        "https://printer.local/",
        "https://intranet.corp/",
        "https://example.com:8443/",
    ):
        try:
            validate_public_https_url(url, allowed if "example.com" in url else {url.split("/")[2]})
            raised = False
        except NetworkPolicyError:
            raised = True
        assert raised, url
