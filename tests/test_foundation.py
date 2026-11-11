from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


HOST = "127.0.0.1:8765"
ORIGIN = f"http://{HOST}"


def new_client(database_path: Path) -> TestClient:
    return TestClient(create_app(database_path, allowed_host=HOST), base_url=ORIGIN)


def csrf_headers() -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": ""}


def state_headers(client: TestClient) -> dict[str, str]:
    headers = csrf_headers()
    headers["X-CSRF-Token"] = client.cookies["clariti_csrf"]
    return headers


def create_review(client: TestClient, website: str = "https://example.com") -> str:
    client.get("/")
    response = client.post(
        "/api/reviews",
        headers=state_headers(client),
        json={
            "website": website,
            "scope": "Synthetic review scope",
            "selected_checklist_ids": ["privacy-link-present"],
        },
    )
    assert response.status_code == 200
    return response.json()["review_id"]


def test_companion_settings_survive_restart_and_reset_is_explicit(tmp_path: Path) -> None:
    database_path = tmp_path / "clariti.sqlite3"
    with new_client(database_path) as client:
        client.get("/")
        saved = client.post(
            "/api/settings",
            headers=state_headers(client),
            json={"name": "Custom reviewer", "url": "https://reviewer.example/path"},
        )
        assert saved.status_code == 200
        assert saved.json()["companion_name"] == "Custom reviewer"

    with new_client(database_path) as restarted:
        boot = restarted.get("/api/bootstrap")
        assert boot.json()["settings"]["companion_url"] == "https://reviewer.example/path"
        restarted.get("/")
        reset = restarted.post("/api/settings/reset", headers=state_headers(restarted))
        assert reset.status_code == 200
        assert reset.json()["companion_name"] == "Clariti Web Evidence Reviewer"


def test_review_keeps_immutable_checklist_snapshot(tmp_path: Path) -> None:
    with new_client(tmp_path / "clariti.sqlite3") as client:
        first_review = create_review(client)
        template = client.get("/api/bootstrap").json()["template"]
        template["version"] = "1.1"
        template["items"][0]["question"] = "Changed template question"
        saved = client.post(
            "/api/checklist-templates",
            headers=state_headers(client),
            json=template,
        )
        assert saved.status_code == 200
        second_review = create_review(client, "https://second.example")

        first = client.get(f"/api/reviews/{first_review}").json()
        second = client.get(f"/api/reviews/{second_review}").json()
        assert first["checklist_snapshot"]["version"] == "1.0"
        assert first["selected_checklist_ids"] == ["privacy-link-present"]
        assert first["checklist_snapshot"]["items"][0]["question"] != "Changed template question"
        assert second["checklist_snapshot"]["version"] == "1.1"


def test_evidence_stays_in_its_review_and_html_remains_data(tmp_path: Path) -> None:
    with new_client(tmp_path / "clariti.sqlite3") as client:
        first_review = create_review(client)
        second_review = create_review(client, "https://second.example")
        payload = {
            "text": '<img src=x onerror="alert(1)"> Privacy link',
            "source_url": "https://example.com/privacy",
            "limitations": "Synthetic evidence",
        }
        added = client.post(
            f"/api/reviews/{first_review}/evidence/text",
            headers=state_headers(client),
            json=payload,
        )
        assert added.status_code == 200
        first = client.get(f"/api/reviews/{first_review}").json()
        second = client.get(f"/api/reviews/{second_review}").json()
        assert first["evidence"][0]["text_content"] == payload["text"]
        assert second["evidence"] == []
        assert "textContent = item.text_content" in (
            Path("app/ui/static/app.js").read_text(encoding="utf-8")
        )
        assert "innerHTML" not in Path("app/ui/static/app.js").read_text(encoding="utf-8")


def test_state_changes_require_expected_origin_and_csrf(tmp_path: Path) -> None:
    with new_client(tmp_path / "clariti.sqlite3") as client:
        client.get("/")
        response = client.post(
            "/api/reviews",
            json={
                "website": "https://example.com",
                "scope": "scope",
                "selected_checklist_ids": ["privacy-link-present"],
            },
        )
        assert response.status_code == 403


def test_companion_url_rejects_embedded_credentials(tmp_path: Path) -> None:
    with new_client(tmp_path / "clariti.sqlite3") as client:
        client.get("/")
        response = client.post(
            "/api/settings",
            headers=state_headers(client),
            json={
                "name": "Reviewer",
                "url": "https://user:password@reviewer.example/path",
            },
        )
        assert response.status_code == 422
        response = client.post(
            "/api/reviews",
            headers={"Origin": "https://attacker.example", "X-CSRF-Token": "bad"},
            json={
                "website": "https://example.com",
                "scope": "scope",
                "selected_checklist_ids": ["privacy-link-present"],
            },
        )
        assert response.status_code == 403


def test_screenshot_requires_review_confirmation(tmp_path: Path) -> None:
    with new_client(tmp_path / "clariti.sqlite3") as client:
        review_id = create_review(client)
        response = client.post(
            f"/api/reviews/{review_id}/evidence/screenshot",
            headers=state_headers(client),
            files={"screenshot": ("sample.png", b"\x89PNG\r\n\x1a\nimage", "image/png")},
            data={"reviewed_confirmation": "false"},
        )
        assert response.status_code == 422
