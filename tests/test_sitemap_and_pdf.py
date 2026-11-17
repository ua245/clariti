from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.export.reports import pdf_report
from app.fetch.html_text import html_to_evidence_text
from app.fetch.sitemap import parse_sitemap
from app.fetch.sitemap_crawl import SitemapCrawlResult, prioritize_urls
from app.fetch.site_capture import PageTextEvidence, SiteCaptureResult
from app.fetch.browser_capture import CaptureShot
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


def test_parse_sitemap_and_priority() -> None:
    xml = b"""<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/about</loc></url>
      <url><loc>https://example.com/privacy-policy</loc></url>
      <url><loc>https://example.com/</loc></url>
    </urlset>
    """
    urls = parse_sitemap(xml)
    assert urls[0] == "https://example.com/about"
    ordered = prioritize_urls(urls, limit=2)
    assert ordered[0].endswith("/")
    assert "privacy" in ordered[1]


def test_html_to_evidence_text_extracts_privacy_link() -> None:
    html = b"""<html><head><title>Shop</title></head>
    <body><a href="/privacy">Privacy Policy</a><p>Hello</p>
    <script>evil()</script></body></html>"""
    text = html_to_evidence_text(html, source_url="https://example.com/")
    assert "Privacy Policy" in text
    assert "evil()" not in text
    assert "Hello" in text


def test_sitemap_capture_stores_pages_and_screenshots(tmp_path: Path) -> None:
    fake = SiteCaptureResult(
        website="https://example.com",
        sitemap=SitemapCrawlResult(
            website="https://example.com",
            discovered_sitemaps=["https://example.com/sitemap.xml"],
            page_urls=["https://example.com/", "https://example.com/privacy"],
        ),
        pages=[
            PageTextEvidence(
                source_url="https://example.com/privacy",
                final_url="https://example.com/privacy",
                text="Source URL: https://example.com/privacy\nPrivacy Policy text",
                http_status=200,
                limitations="Static extract",
            )
        ],
        shots=[
            CaptureShot(
                label="initial-viewport",
                png_bytes=TINY_PNG,
                source_url="https://example.com/",
                note="Homepage",
            ),
            CaptureShot(
                label="sitemap-page-1",
                png_bytes=TINY_PNG,
                source_url="https://example.com/privacy",
                note="Privacy page",
            ),
        ],
        indicator_summary="found privacy-link",
        page_title="Example",
        final_url="https://example.com/",
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
        with patch("app.main.capture_full_site", new=AsyncMock(return_value=fake)):
            response = client.post(
                f"/api/reviews/{review_id}/capture",
                headers=headers(client),
                json={"confirmed": True, "mode": "sitemap_headless"},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mode"] == "sitemap_headless"
        assert body["screenshot_count"] == 2
        assert body["page_text_count"] == 1
        assert body["sitemap_url_count"] == 2
        review = client.get(f"/api/reviews/{review_id}").json()
        methods = {item["capture_method"] for item in review["evidence"]}
        assert "static" in methods
        assert "rendered" in methods


def test_pdf_embeds_all_screenshots(tmp_path: Path) -> None:
    from PIL import Image as PILImage

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    paths = []
    for index in range(3):
        name = f"shot-{index}.png"
        img = PILImage.new("RGB", (64, 48), color=(40 + index * 40, 90, 160))
        img.save(artifact_dir / name, format="PNG")
        paths.append(name)
    review = {
        "review_id": "review-1",
        "website": "https://example.com",
        "checklist_version": "1.0",
        "effective_findings": [
            {
                "checklist_id": "privacy-link-present",
                "status": "Not verified",
                "reason": "Draft only",
                "observation": "",
                "evidence_ids": [],
            }
        ],
        "evidence": [
            {
                "evidence_id": f"ev-{index}",
                "evidence_type": "screenshot",
                "artifact_path": path,
                "final_url": f"https://example.com/p{index}",
                "requested_url": f"https://example.com/p{index}",
                "limitations": "Synthetic",
                "text_content": None,
            }
            for index, path in enumerate(paths)
        ],
    }
    pdf = pdf_report(review, final=False, artifact_dir=artifact_dir)
    assert pdf.startswith(b"%PDF")
    # Each embedded image adds substantial content vs findings-only PDF.
    assert len(pdf) > 1500
