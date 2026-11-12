import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


HOST = "127.0.0.1:8765"
ORIGIN = f"http://{HOST}"


def client_for(path: Path) -> TestClient:
    return TestClient(create_app(path, allowed_host=HOST), base_url=ORIGIN)


def headers(client: TestClient) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": client.cookies["clariti_csrf"]}


def seeded_review(client: TestClient) -> tuple[str, str, str]:
    client.get("/")
    review_id = client.post(
        "/api/reviews",
        headers=headers(client),
        json={
            "website": "https://example.com",
            "scope": "Synthetic scope",
            "selected_checklist_ids": ["privacy-link-present"],
        },
    ).json()["review_id"]
    evidence_id = client.post(
        f"/api/reviews/{review_id}/evidence/text",
        headers=headers(client),
        json={"text": "Privacy link: Privacy", "limitations": "Synthetic"},
    ).json()["evidence_id"]
    batch_id = client.post(
        f"/api/reviews/{review_id}/handoffs",
        headers=headers(client),
        json={"evidence_ids": [evidence_id], "evidence_review_confirmed": True},
    ).json()["batch_id"]
    payload = {
        "schema_version": "1.0",
        "review_id": review_id,
        "batch_id": batch_id,
        "checklist_version": "1.0",
        "summary": "Synthetic evidence review.",
        "findings": [
            {
                "checklist_id": "privacy-link-present",
                "status": "Pass",
                "evidence_ids": [evidence_id],
                "observation": "Labelled link appears in supplied text.",
                "reason": "Evidence supports link presence only.",
                "missing_evidence": [],
                "suggested_action": "No action suggested.",
                "requires_internal_review": False,
            }
        ],
        "limitations": ["Synthetic evidence only."],
        "review_notice": "Draft evidence review; human review required.",
    }
    imported = client.post(
        f"/api/handoffs/{batch_id}/imports",
        headers=headers(client),
        json={"response_text": json.dumps(payload)},
    )
    assert imported.status_code == 200
    return review_id, evidence_id, batch_id


def test_exports_include_findings_and_reviewer_edits(tmp_path: Path) -> None:
    with client_for(tmp_path / "clariti.sqlite3") as client:
        review_id, evidence_id, _ = seeded_review(client)
        draft = client.get(f"/api/reviews/{review_id}/exports/csv")
        assert draft.status_code == 200
        assert "privacy-link-present" in draft.text
        assert "Pass" in draft.text

        edited = client.post(
            f"/api/reviews/{review_id}/edits",
            headers=headers(client),
            json={
                "checklist_id": "privacy-link-present",
                "status": "Partial",
                "notes": "Needs clearer screenshot.",
                "reason": "Text alone is weak for prominence claims.",
                "evidence_ids": [evidence_id],
            },
        )
        assert edited.status_code == 200

        review = client.get(f"/api/reviews/{review_id}").json()
        assert review["effective_findings"][0]["status"] == "Partial"
        assert review["current_approval"] is None

        csv_after_edit = client.get(f"/api/reviews/{review_id}/exports/csv")
        assert "Partial" in csv_after_edit.text

        final_blocked = client.get(f"/api/reviews/{review_id}/exports/csv?final=true")
        assert final_blocked.status_code == 422

        approved = client.post(
            f"/api/reviews/{review_id}/approvals",
            headers=headers(client),
            json={"reviewer_name": "Ada Reviewer"},
        )
        assert approved.status_code == 200
        final_ok = client.get(f"/api/reviews/{review_id}/exports/pdf?final=true")
        assert final_ok.status_code == 200
        assert final_ok.headers["content-type"].startswith("application/pdf")


def test_ui_keeps_findings_renderer_top_level() -> None:
    source = Path("app/ui/static/app.js").read_text(encoding="utf-8")
    assert "function renderFindings(review)" in source
    assert "textContent = item.text_content" in source
    assert "innerHTML" not in source
