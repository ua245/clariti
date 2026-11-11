import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.checklist.service import load_default_template
from app.checklist.models import ChecklistTemplate
from app.companions.manual import ManualCompanionConnector, ResponseValidationError
from app.companions.models import Status
from app.config import (
    ALLOWED_HOST,
    DEFAULT_COMPANION_NAME,
    DEFAULT_COMPANION_URL,
    PORT,
    STATIC_DIR,
)
from app.evidence.service import (
    add_screenshot_evidence,
    add_text_evidence,
    artifact_for_evidence,
)
from app.storage.db import Database
from app.export.reports import csv_report, pdf_report


class CompanionSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website: str = Field(min_length=1, max_length=2048)
    scope: str = Field(min_length=1, max_length=2_000)
    selected_checklist_ids: list[str] = Field(min_length=1, max_length=100)


class TextEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100_000)
    source_url: str | None = Field(default=None, max_length=2048)
    limitations: str = Field(default="", max_length=2_000)


class PrepareHandoffInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    evidence_review_confirmed: bool


class ImportResponseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_text: str = Field(min_length=1, max_length=500_000)


class ReviewerEditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checklist_id: str = Field(min_length=1, max_length=64)
    status: Status
    notes: str = Field(max_length=8_000)
    reason: str = Field(min_length=1, max_length=8_000)
    evidence_ids: list[str] = Field(max_length=100)


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_name: str = Field(min_length=1, max_length=200)


def validate_navigation_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise HTTPException(
            422,
            "Companion URL must be an HTTPS browser-navigation URL without credentials.",
        )
    return value


def create_app(
    database_path: Path | None = None,
    allowed_host: str = ALLOWED_HOST,
) -> FastAPI:
    database = Database(database_path) if database_path else Database()
    database.initialize(load_default_template())
    allowed_origin = f"http://{allowed_host}"

    app = FastAPI(title="Clariti", docs_url=None, redoc_url=None)
    app.state.database = database
    app.state.allowed_host = allowed_host
    connector = ManualCompanionConnector()

    @app.middleware("http")
    async def enforce_local_host(request: Request, call_next):
        if request.headers.get("host") != allowed_host:
            return JSONResponse(
                status_code=400, content={"detail": "Unexpected Host header."}
            )
        return await call_next(request)

    def require_state_change_protection(request: Request) -> None:
        if request.headers.get("host") != allowed_host:
            raise HTTPException(400, "Unexpected Host header.")
        if request.headers.get("origin") != allowed_origin:
            raise HTTPException(403, "Unexpected Origin header.")
        cookie_token = request.cookies.get("clariti_csrf")
        header_token = request.headers.get("x-csrf-token")
        if not cookie_token or not header_token or not secrets.compare_digest(
            cookie_token, header_token
        ):
            raise HTTPException(403, "CSRF token is missing or invalid.")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def index() -> FileResponse:
        response = FileResponse(STATIC_DIR / "index.html")
        response.set_cookie(
            "clariti_csrf",
            secrets.token_urlsafe(32),
            httponly=False,
            samesite="strict",
            secure=False,
        )
        return response

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, object]:
        return {
            "settings": database.get_settings(),
            "template": database.get_active_template().model_dump(mode="json"),
            "reviews": database.list_reviews(),
            "notice": (
                "Draft evidence-based findings. Human review and Legal/Privacy "
                "review where appropriate are required."
            ),
        }

    @app.post("/api/settings")
    def save_settings(payload: CompanionSettingsInput, request: Request) -> dict[str, str]:
        require_state_change_protection(request)
        name = payload.name.strip()
        if not name:
            raise HTTPException(422, "Companion name must not be blank.")
        url = validate_navigation_url(payload.url)
        database.update_settings(name, url)
        return database.get_settings()

    @app.post("/api/settings/reset")
    def reset_settings(request: Request) -> dict[str, str]:
        require_state_change_protection(request)
        database.reset_settings()
        return database.get_settings()

    @app.post("/api/reviews")
    def create_review(payload: ReviewInput, request: Request) -> dict[str, str]:
        require_state_change_protection(request)
        website = validate_navigation_url(payload.website)
        scope = payload.scope.strip()
        if not scope:
            raise HTTPException(422, "Review scope must not be blank.")
        template = database.get_active_template()
        selected_ids = payload.selected_checklist_ids
        available_ids = {item.id for item in template.items}
        if len(selected_ids) != len(set(selected_ids)):
            raise HTTPException(422, "Selected checklist IDs must be unique.")
        unknown_ids = set(selected_ids) - available_ids
        if unknown_ids:
            raise HTTPException(422, "Selected checklist includes an unknown item.")
        review_id = f"review-{uuid4()}"
        database.create_review(
            review_id, website, scope, template, selected_ids
        )
        return {"review_id": review_id}

    @app.post("/api/checklist-templates")
    def add_checklist_template(
        payload: ChecklistTemplate, request: Request
    ) -> dict[str, str]:
        require_state_change_protection(request)
        item_ids = [item.id for item in payload.items]
        if len(item_ids) != len(set(item_ids)):
            raise HTTPException(422, "Checklist item IDs must be unique.")
        try:
            database.add_template(payload)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"version": payload.version}

    @app.get("/api/reviews/{review_id}")
    def get_review(review_id: str) -> dict[str, object]:
        review = database.get_review(review_id)
        if review is None:
            raise HTTPException(404, "Review was not found.")
        review["evidence"] = database.list_evidence(review_id)
        review["latest_companion_import"] = database.latest_companion_import(review_id)
        review["reviewer_edits"] = database.list_reviewer_edits(review_id)
        review["current_approval"] = database.current_approval(
            review_id, int(review["revision"])
        )
        return review

    @app.post("/api/reviews/{review_id}/edits")
    def add_reviewer_edit(
        review_id: str, payload: ReviewerEditInput, request: Request
    ) -> dict[str, str]:
        require_state_change_protection(request)
        review = database.get_review(review_id)
        if review is None:
            raise HTTPException(404, "Review was not found.")
        if payload.checklist_id not in review["selected_checklist_ids"]:
            raise HTTPException(422, "Edit checklist item is not selected for this review.")
        if not payload.reason.strip():
            raise HTTPException(422, "Reviewer edits require a reason.")
        available_evidence = {
            item["evidence_id"] for item in database.list_evidence(review_id)
        }
        if not set(payload.evidence_ids).issubset(available_evidence):
            raise HTTPException(422, "Reviewer edit references evidence outside this review.")
        database.create_reviewer_edit(
            f"edit-{uuid4()}",
            review_id,
            payload.checklist_id,
            payload.status,
            payload.notes,
            payload.reason,
            payload.evidence_ids,
        )
        return {"status": "saved"}

    @app.post("/api/reviews/{review_id}/approvals")
    def approve_review(
        review_id: str, payload: ApprovalInput, request: Request
    ) -> dict[str, object]:
        require_state_change_protection(request)
        review = database.get_review(review_id)
        if review is None:
            raise HTTPException(404, "Review was not found.")
        reviewer_name = payload.reviewer_name.strip()
        if not reviewer_name:
            raise HTTPException(422, "Reviewer display name must not be blank.")
        if database.latest_companion_import(review_id) is None:
            raise HTTPException(422, "Import draft findings before approval.")
        revision = int(review["revision"])
        database.create_approval(f"approval-{uuid4()}", review_id, reviewer_name, revision)
        return {
            "reviewer_name": reviewer_name,
            "review_revision": revision,
            "notice": "Display name is not an authenticated corporate identity.",
        }

    @app.get("/api/reviews/{review_id}/exports/{format_name}")
    def export_review(review_id: str, format_name: str, final: bool = False) -> Response:
        review = database.get_review(review_id)
        if review is None:
            raise HTTPException(404, "Review was not found.")
        if final and database.current_approval(review_id, int(review["revision"])) is None:
            raise HTTPException(422, "Final export requires current sign-off.")
        if format_name == "csv":
            return Response(
                csv_report(review, final), media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{review_id}.csv"'},
            )
        if format_name == "pdf":
            return Response(
                pdf_report(review, final), media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{review_id}.pdf"'},
            )
        raise HTTPException(404, "Export format was not found.")

    @app.post("/api/reviews/{review_id}/handoffs")
    def prepare_handoff(
        review_id: str, payload: PrepareHandoffInput, request: Request
    ) -> dict[str, object]:
        require_state_change_protection(request)
        if not payload.evidence_review_confirmed:
            raise HTTPException(
                422, "Confirm evidence review/redaction before preparing a handoff."
            )
        if len(payload.evidence_ids) != len(set(payload.evidence_ids)):
            raise HTTPException(422, "Selected evidence IDs must be unique.")
        review = database.get_review(review_id)
        if review is None:
            raise HTTPException(404, "Review was not found.")
        all_evidence = database.list_evidence(review_id)
        by_id = {item["evidence_id"]: item for item in all_evidence}
        if any(evidence_id not in by_id for evidence_id in payload.evidence_ids):
            raise HTTPException(422, "Selected evidence does not belong to this review.")
        evidence = [by_id[evidence_id] for evidence_id in payload.evidence_ids]
        if any(item["redaction_status"] not in {"reviewed", "redacted"} for item in evidence):
            raise HTTPException(422, "Each selected evidence item must be reviewed.")
        handoff = connector.prepare_handoff(review, evidence)
        database.create_handoff_batch(
            handoff.batch_id,
            review_id,
            str(review["checklist_version"]),
            payload.evidence_ids,
            handoff.manifest,
            handoff.prompt,
        )
        return {
            "batch_id": handoff.batch_id,
            "prompt": handoff.prompt,
            "manifest": handoff.manifest,
        }

    @app.get("/api/handoffs/{batch_id}")
    def get_handoff(batch_id: str) -> dict[str, object]:
        batch = database.get_handoff_batch(batch_id)
        if batch is None:
            raise HTTPException(404, "Handoff batch was not found.")
        return batch

    @app.get("/api/handoffs/{batch_id}/attachments")
    def get_handoff_attachments(batch_id: str) -> list[dict[str, object]]:
        batch = database.get_handoff_batch(batch_id)
        if batch is None:
            raise HTTPException(404, "Handoff batch was not found.")
        evidence = {
            item["evidence_id"]: item for item in database.list_evidence(str(batch["review_id"]))
        }
        return [
            {
                "evidence_id": evidence[evidence_id]["evidence_id"],
                "evidence_type": evidence[evidence_id]["evidence_type"],
                "text_content": evidence[evidence_id]["text_content"],
                "download_url": (
                    f"/api/evidence/{evidence_id}/artifact"
                    if evidence[evidence_id]["artifact_path"] else None
                ),
            }
            for evidence_id in batch["evidence_ids"]
        ]

    @app.post("/api/handoffs/{batch_id}/imports")
    def import_companion_response(
        batch_id: str, payload: ImportResponseInput, request: Request
    ) -> dict[str, object]:
        require_state_change_protection(request)
        batch = database.get_handoff_batch(batch_id)
        if batch is None:
            raise HTTPException(404, "Handoff batch was not found.")
        review = database.get_review(str(batch["review_id"]))
        if review is None:
            raise HTTPException(404, "Review was not found.")
        try:
            response = connector.import_response(payload.response_text, review, batch)
        except ResponseValidationError as error:
            raise HTTPException(422, str(error)) from error
        import_id = f"import-{uuid4()}"
        database.create_companion_import(
            import_id,
            batch_id,
            str(review["review_id"]),
            payload.response_text,
            [finding.model_dump(mode="json") for finding in response.findings],
        )
        return {
            "import_id": import_id,
            "findings": [finding.model_dump(mode="json") for finding in response.findings],
        }

    @app.post("/api/reviews/{review_id}/evidence/text")
    def add_text(
        review_id: str, payload: TextEvidenceInput, request: Request
    ) -> dict[str, str]:
        require_state_change_protection(request)
        if database.get_review(review_id) is None:
            raise HTTPException(404, "Review was not found.")
        source_url = (
            validate_navigation_url(payload.source_url) if payload.source_url else None
        )
        evidence_id = add_text_evidence(
            database, review_id, payload.text, source_url, payload.limitations.strip()
        )
        return {"evidence_id": evidence_id}

    @app.post("/api/reviews/{review_id}/evidence/screenshot")
    async def add_screenshot(
        review_id: str,
        request: Request,
        screenshot: UploadFile = File(...),
        source_url: str | None = Form(default=None, max_length=2048),
        limitations: str = Form(default="", max_length=2_000),
        reviewed_confirmation: bool = Form(...),
    ) -> dict[str, str]:
        require_state_change_protection(request)
        if database.get_review(review_id) is None:
            raise HTTPException(404, "Review was not found.")
        validated_source_url = (
            validate_navigation_url(source_url) if source_url else None
        )
        evidence_id = await add_screenshot_evidence(
            database,
            review_id,
            screenshot,
            validated_source_url,
            limitations.strip(),
            reviewed_confirmation,
        )
        return {"evidence_id": evidence_id}

    @app.get("/api/evidence/{evidence_id}/artifact")
    def get_artifact(evidence_id: str) -> FileResponse:
        artifact = artifact_for_evidence(database, evidence_id)
        return FileResponse(artifact)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
