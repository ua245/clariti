from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.fetch.browser_capture import CaptureResult, CaptureShot
from app.fetch.network_policy import NetworkPolicyError, allowlist_for_website
from app.main import create_app


HOST = "127.0.0.1:8765"
ORIGIN = f"http://{HOST}"
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def client_for(path: Path) -> TestClient:
    return TestClient(create_app(path, allowed_host=HOST), base_url=ORIGIN)


def headers(client: TestClient) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": client.cookies["clariti_csrf"]}


def test_allowlist_includes_www_twin() -> None:
    assert allowlist_for_website("https://example.com/path") == {
        "example.com",
        "www.example.com",
    }


def test_capture_requires_confirmation(tmp_path: Path) -> None:
    with client_for(tmp_path / "clariti.sqlite3") as client:
        client.get("/")
        review_id = client.post(
            "/api/reviews",
            headers=headers(client),
            json={
                "website": "https://example.com",
                "scope": "Synthetic",
                "selected_checklist_ids": ["privacy-link-present"],
            },
        ).json()["review_id"]
        denied = client.post(
            f"/api/reviews/{review_id}/capture",
            headers=headers(client),
            json={"confirmed": False},
        )
        assert denied.status_code == 422


def test_capture_stores_summary_and_screenshots(tmp_path: Path) -> None:
    fake = CaptureResult(
        final_url="https://example.com/",
        page_title="Example",
        summary_text="Automated privacy-indicator scan\n\nfound privacy-link",
        shots=[
            CaptureShot(
                label="initial-viewport",
                png_bytes=TINY_PNG,
                source_url="https://example.com/",
                note="Initial viewport",
            )
        ],
    )
    with client_for(tmp_path / "clariti.sqlite3") as client:
        client.get("/")
        review_id = client.post(
            "/api/reviews",
            headers=headers(client),
            json={
                "website": "https://example.com",
                "scope": "Synthetic",
                "selected_checklist_ids": ["privacy-link-present"],
            },
        ).json()["review_id"]
        with patch(
            "app.main.capture_privacy_indicators",
            new=AsyncMock(return_value=fake),
        ):
            response = client.post(
                f"/api/reviews/{review_id}/capture",
                headers=headers(client),
                json={"confirmed": True},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["screenshot_count"] == 1
        assert len(body["evidence_ids"]) == 2
        review = client.get(f"/api/reviews/{review_id}").json()
        methods = {item["capture_method"] for item in review["evidence"]}
        assert methods == {"rendered"}


def test_private_ip_rejected() -> None:
    try:
        from app.fetch.network_policy import validate_public_https_url

        validate_public_https_url("https://127.0.0.1/", {"127.0.0.1"})
        raised = False
    except NetworkPolicyError:
        raised = True
    assert raised
