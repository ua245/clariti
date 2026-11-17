import asyncio
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


def create_review(client: TestClient) -> str:
    return client.post(
        "/api/reviews",
        headers=headers(client),
        json={
            "website": "https://example.com",
            "scope": "Synthetic",
            "selected_checklist_ids": ["privacy-link-present"],
        },
    ).json()["review_id"]


class FakeHitlSession:
    """Playwright-free HITL session for API lifecycle tests."""

    def __init__(self, website: str) -> None:
        self.website = website
        self.status = "starting"
        self.hint = (
            "Complete any Cloudflare, consent, or login steps in this browser "
            "window, then click Continue in Clariti."
        )
        self.error = None
        self.result = None
        self.site_result = None
        self.page_url = website.rstrip("/") + "/"
        self.page_title = "Example Domain"
        self._continue = asyncio.Event()
        self._cancel = asyncio.Event()

    def snapshot(self) -> dict[str, object]:
        return {
            "status": self.status,
            "hint": self.hint,
            "error": self.error,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "has_result": self.result is not None,
        }

    def request_continue(self) -> None:
        self._continue.set()

    def request_cancel(self) -> None:
        self._cancel.set()

    async def run(self) -> None:
        self.status = "waiting_for_human"
        while True:
            cont_task = asyncio.create_task(self._continue.wait())
            cancel_task = asyncio.create_task(self._cancel.wait())
            done, pending = await asyncio.wait(
                {cont_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if cancel_task in done:
                self.status = "cancelled"
                return
            self._continue.clear()
            self.status = "scanning"
            self.result = CaptureResult(
                final_url=self.page_url,
                page_title=self.page_title,
                summary_text=(
                    "Human-assisted privacy-indicator scan\n\n"
                    "HITL: reviewer completed interactive gates\n"
                    "found privacy-link"
                ),
                shots=[
                    CaptureShot(
                        label="initial-viewport",
                        png_bytes=TINY_PNG,
                        source_url=self.page_url,
                        note="Initial viewport",
                    )
                ],
                limitations=(
                    "Human-assisted headed capture. The reviewer completed any "
                    "Cloudflare, consent, or login gates themselves."
                ),
            )
            self.status = "completed"
            return


class FakeSitemapHitlSession(FakeHitlSession):
    async def run(self) -> None:
        from app.fetch.site_capture import PageTextEvidence, SiteCaptureResult
        from app.fetch.sitemap_crawl import SitemapCrawlResult

        self.status = "waiting_for_human"
        while True:
            cont_task = asyncio.create_task(self._continue.wait())
            cancel_task = asyncio.create_task(self._cancel.wait())
            done, pending = await asyncio.wait(
                {cont_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if cancel_task in done:
                self.status = "cancelled"
                return
            self._continue.clear()
            self.status = "scanning"
            self.site_result = SiteCaptureResult(
                website=self.website,
                sitemap=SitemapCrawlResult(
                    website=self.website,
                    discovered_sitemaps=["https://example.com/sitemap.xml"],
                    page_urls=[self.page_url, "https://example.com/privacy"],
                ),
                pages=[
                    PageTextEvidence(
                        source_url=self.page_url,
                        final_url=self.page_url,
                        text="Privacy Policy",
                        http_status=200,
                        limitations="Synthetic",
                    )
                ],
                shots=[
                    CaptureShot(
                        label="initial-viewport",
                        png_bytes=TINY_PNG,
                        source_url=self.page_url,
                        note="Homepage",
                    )
                ],
                indicator_summary="found privacy-link",
                page_title=self.page_title,
                final_url=self.page_url,
                limitations="Human-assisted headed sitemap capture.",
            )
            self.result = CaptureResult(
                final_url=self.page_url,
                page_title=self.page_title,
                summary_text=self.site_result.overview_text(),
                shots=self.site_result.shots,
                limitations=self.site_result.limitations,
            )
            self.status = "completed"
            return


def test_allowlist_includes_www_twin() -> None:
    assert allowlist_for_website("https://example.com/path") == {
        "example.com",
        "www.example.com",
    }


def test_capture_requires_confirmation(tmp_path: Path) -> None:
    with client_for(tmp_path / "clariti.sqlite3") as client:
        client.get("/")
        review_id = create_review(client)
        denied = client.post(
            f"/api/reviews/{review_id}/capture",
            headers=headers(client),
            json={"confirmed": False},
        )
        assert denied.status_code == 422


def test_hitl_requires_confirmation(tmp_path: Path) -> None:
    with client_for(tmp_path / "clariti.sqlite3") as client:
        client.get("/")
        review_id = create_review(client)
        denied = client.post(
            f"/api/reviews/{review_id}/capture",
            headers=headers(client),
            json={"confirmed": False, "mode": "hitl"},
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
        review_id = create_review(client)
        with patch(
            "app.main.capture_privacy_indicators",
            new=AsyncMock(return_value=fake),
        ):
            response = client.post(
                f"/api/reviews/{review_id}/capture",
                headers=headers(client),
                json={"confirmed": True, "mode": "headless"},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["screenshot_count"] == 1
        assert body["mode"] == "headless"
        assert len(body["evidence_ids"]) == 2
        review = client.get(f"/api/reviews/{review_id}").json()
        methods = {item["capture_method"] for item in review["evidence"]}
        assert methods == {"rendered"}


def test_hitl_lifecycle_continue_stores_evidence(tmp_path: Path) -> None:
    with client_for(tmp_path / "clariti.sqlite3") as client:
        client.app.state.hitl_jobs.set_session_factory(FakeHitlSession)
        client.get("/")
        review_id = create_review(client)

        started = client.post(
            f"/api/reviews/{review_id}/capture",
            headers=headers(client),
            json={"confirmed": True, "mode": "hitl"},
        )
        assert started.status_code == 200, started.text
        body = started.json()
        assert body["mode"] == "hitl"
        assert body["status"] == "waiting_for_human"
        assert "does not bypass" in body["message"].lower()

        status = client.get(f"/api/reviews/{review_id}/capture/status").json()
        assert status["status"] == "waiting_for_human"

        continued = client.post(
            f"/api/reviews/{review_id}/capture/continue",
            headers=headers(client),
        )
        assert continued.status_code == 200, continued.text
        done = continued.json()
        assert done["status"] == "completed"
        assert done["screenshot_count"] == 1
        assert len(done["evidence_ids"]) == 2

        idle = client.get(f"/api/reviews/{review_id}/capture/status").json()
        assert idle["status"] == "idle"

        review = client.get(f"/api/reviews/{review_id}").json()
        assert any("Human-assisted" in (item["limitations"] or "") for item in review["evidence"])


def test_sitemap_hitl_lifecycle_stores_site_evidence(tmp_path: Path) -> None:
    with client_for(tmp_path / "clariti.sqlite3") as client:
        client.app.state.hitl_jobs.set_sitemap_factory(FakeSitemapHitlSession)
        client.get("/")
        review_id = create_review(client)

        started = client.post(
            f"/api/reviews/{review_id}/capture",
            headers=headers(client),
            json={"confirmed": True, "mode": "sitemap"},
        )
        assert started.status_code == 200, started.text
        body = started.json()
        assert body["mode"] == "sitemap"
        assert body["kind"] == "sitemap"
        assert body["status"] == "waiting_for_human"

        continued = client.post(
            f"/api/reviews/{review_id}/capture/continue",
            headers=headers(client),
        )
        assert continued.status_code == 200, continued.text
        done = continued.json()
        assert done["status"] == "completed"
        assert done["mode"] == "sitemap"
        assert done["screenshot_count"] == 1
        assert done["page_text_count"] == 1
        assert done["sitemap_url_count"] == 2


def test_hitl_cancel_clears_job(tmp_path: Path) -> None:
    with client_for(tmp_path / "clariti.sqlite3") as client:
        client.app.state.hitl_jobs.set_session_factory(FakeHitlSession)
        client.get("/")
        review_id = create_review(client)

        started = client.post(
            f"/api/reviews/{review_id}/capture",
            headers=headers(client),
            json={"confirmed": True, "mode": "hitl"},
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "waiting_for_human"

        cancelled = client.post(
            f"/api/reviews/{review_id}/capture/cancel",
            headers=headers(client),
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"

        idle = client.get(f"/api/reviews/{review_id}/capture/status").json()
        assert idle["status"] == "idle"


def test_private_ip_rejected() -> None:
    try:
        from app.fetch.network_policy import validate_public_https_url

        validate_public_https_url("https://127.0.0.1/", {"127.0.0.1"})
        raised = False
    except NetworkPolicyError:
        raised = True
    assert raised
