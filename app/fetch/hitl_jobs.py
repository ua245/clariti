"""In-process HITL capture job registry (localhost only, no cookie persistence)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from app.fetch.browser_capture import HitlCaptureSession
from app.fetch.site_capture import HitlSitemapSession

HitlKind = Literal["indicators", "sitemap"]


@dataclass
class HitlJob:
    review_id: str
    website: str
    session: Any
    kind: HitlKind = "indicators"
    task: asyncio.Task[None] | None = None
    evidence_payload: dict[str, object] | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def snapshot(self) -> dict[str, object]:
        data = self.session.snapshot()
        data["review_id"] = self.review_id
        data["website"] = self.website
        data["kind"] = self.kind
        if self.evidence_payload is not None:
            data["evidence_ids"] = self.evidence_payload.get("evidence_ids")
            data["screenshot_count"] = self.evidence_payload.get("screenshot_count")
            data["page_text_count"] = self.evidence_payload.get("page_text_count")
            data["sitemap_url_count"] = self.evidence_payload.get("sitemap_url_count")
            data["final_url"] = self.evidence_payload.get("final_url")
            data["page_title"] = self.evidence_payload.get("page_title")
            data["limitations"] = self.evidence_payload.get("limitations")
        return data


class HitlJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, HitlJob] = {}
        self._lock = asyncio.Lock()
        self._session_factory = HitlCaptureSession
        self._sitemap_factory = HitlSitemapSession

    def set_session_factory(self, factory: Any) -> None:
        """Test hook to inject a fake homepage HITL session class."""
        self._session_factory = factory

    def set_sitemap_factory(self, factory: Any) -> None:
        """Test hook to inject a fake sitemap HITL session class."""
        self._sitemap_factory = factory

    async def start(
        self, review_id: str, website: str, *, kind: HitlKind = "indicators"
    ) -> HitlJob:
        async with self._lock:
            existing = self._jobs.get(review_id)
            if existing is not None and existing.session.status in {
                "starting",
                "waiting_for_human",
                "scanning",
            }:
                raise RuntimeError(
                    "A human-assisted capture is already running for this review."
                )
            if existing is not None and existing.task and not existing.task.done():
                existing.session.request_cancel()
                try:
                    await asyncio.wait_for(existing.task, timeout=5)
                except (asyncio.TimeoutError, Exception):
                    existing.task.cancel()
            factory = self._sitemap_factory if kind == "sitemap" else self._session_factory
            session = factory(website)
            job = HitlJob(review_id=review_id, website=website, session=session, kind=kind)
            job.task = asyncio.create_task(self._run_job(job))
            self._jobs[review_id] = job
        # Wait until the session is interactive or terminal.
        for _ in range(400):
            if job.session.status != "starting":
                break
            await asyncio.sleep(0.05)
        return job

    async def _run_job(self, job: HitlJob) -> None:
        try:
            await job.session.run()
        except Exception:
            # session.run already records failure status/error
            return

    def get(self, review_id: str) -> HitlJob | None:
        return self._jobs.get(review_id)

    async def continue_job(self, review_id: str) -> HitlJob:
        job = self._jobs.get(review_id)
        if job is None:
            raise KeyError("No human-assisted capture job for this review.")
        if job.session.status != "waiting_for_human":
            raise RuntimeError(
                f"Capture job is not waiting for human input (status={job.session.status})."
            )
        job.session.request_continue()
        # Sitemap crawls can take several minutes across many pages / re-pauses.
        limit = 36_000 if job.kind == "sitemap" else 1_200
        saw_progress = False
        for _ in range(limit):
            status = job.session.status
            if status in {"completed", "failed", "cancelled"}:
                break
            if status == "scanning":
                saw_progress = True
            elif status == "waiting_for_human" and saw_progress:
                # Challenge reappeared mid-crawl; UI should Continue again.
                break
            await asyncio.sleep(0.05)
        return job

    async def cancel(self, review_id: str) -> HitlJob | None:
        job = self._jobs.get(review_id)
        if job is None:
            return None
        job.session.request_cancel()
        if job.task and not job.task.done():
            try:
                await asyncio.wait_for(job.task, timeout=10)
            except (asyncio.TimeoutError, Exception):
                job.task.cancel()
        if job.session.status not in {"completed", "failed", "cancelled"}:
            job.session.status = "cancelled"
        return job

    def clear(self, review_id: str) -> None:
        self._jobs.pop(review_id, None)
