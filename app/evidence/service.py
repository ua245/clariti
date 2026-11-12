import hashlib
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.storage.db import Database, utc_now

MAX_TEXT_LENGTH = 100_000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
}


def new_evidence_id() -> str:
    return f"ev-{secrets.token_urlsafe(12)}"


def add_text_evidence(
    database: Database,
    review_id: str,
    text: str,
    source_url: str | None,
    limitations: str,
) -> str:
    if not text.strip():
        raise HTTPException(422, "Evidence text must not be empty.")
    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(422, f"Evidence text exceeds {MAX_TEXT_LENGTH} characters.")
    evidence_id = new_evidence_id()
    database.create_evidence(
        {
            "evidence_id": evidence_id,
            "review_id": review_id,
            "requested_url": source_url,
            "final_url": None,
            "captured_at_utc": utc_now(),
            "capture_method": "manual",
            "evidence_type": "text",
            "text_content": text,
            "artifact_path": None,
            "sha256": None,
            "http_status": None,
            "limitations": limitations,
            "redaction_status": "reviewed",
            "original_evidence_id": None,
        }
    )
    return evidence_id


async def add_screenshot_evidence(
    database: Database,
    review_id: str,
    upload: UploadFile,
    source_url: str | None,
    limitations: str,
    reviewed_confirmation: bool,
) -> str:
    if not reviewed_confirmation:
        raise HTTPException(
            422, "Confirm that you reviewed the screenshot before storing it."
        )
    content = await upload.read(MAX_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(422, "Screenshot file must not be empty.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(422, f"Screenshot exceeds {MAX_IMAGE_BYTES} bytes.")
    detected = next(
        (value for signature, value in IMAGE_SIGNATURES.items() if content.startswith(signature)),
        None,
    )
    if detected is None:
        raise HTTPException(422, "Only PNG and JPEG screenshots are accepted.")
    content_type, suffix = detected
    if upload.content_type and upload.content_type != content_type:
        raise HTTPException(422, "Screenshot MIME type does not match file content.")

    evidence_id = new_evidence_id()
    relative_path = f"{evidence_id}{suffix}"
    artifact_path = database.artifact_dir / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(content)
    database.create_evidence(
        {
            "evidence_id": evidence_id,
            "review_id": review_id,
            "requested_url": source_url,
            "final_url": None,
            "captured_at_utc": utc_now(),
            "capture_method": "manual",
            "evidence_type": "screenshot",
            "text_content": None,
            "artifact_path": relative_path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "http_status": None,
            "limitations": limitations,
            "redaction_status": "reviewed",
            "original_evidence_id": None,
        }
    )
    return evidence_id


def add_bytes_screenshot_evidence(
    database: Database,
    review_id: str,
    content: bytes,
    source_url: str | None,
    limitations: str,
    *,
    capture_method: str = "rendered",
    redaction_status: str = "reviewed",
) -> str:
    if not content:
        raise HTTPException(422, "Screenshot file must not be empty.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(422, f"Screenshot exceeds {MAX_IMAGE_BYTES} bytes.")
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(422, "Only PNG screenshots are accepted for automated capture.")
    if capture_method not in {"manual", "static", "rendered"}:
        raise HTTPException(422, "Unsupported capture method.")

    evidence_id = new_evidence_id()
    relative_path = f"{evidence_id}.png"
    artifact_path = database.artifact_dir / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(content)
    database.create_evidence(
        {
            "evidence_id": evidence_id,
            "review_id": review_id,
            "requested_url": source_url,
            "final_url": source_url,
            "captured_at_utc": utc_now(),
            "capture_method": capture_method,
            "evidence_type": "screenshot",
            "text_content": None,
            "artifact_path": relative_path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "http_status": None,
            "limitations": limitations,
            "redaction_status": redaction_status,
            "original_evidence_id": None,
        }
    )
    return evidence_id


def add_rendered_text_evidence(
    database: Database,
    review_id: str,
    text: str,
    source_url: str | None,
    limitations: str,
) -> str:
    if not text.strip():
        raise HTTPException(422, "Evidence text must not be empty.")
    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(422, f"Evidence text exceeds {MAX_TEXT_LENGTH} characters.")
    evidence_id = new_evidence_id()
    database.create_evidence(
        {
            "evidence_id": evidence_id,
            "review_id": review_id,
            "requested_url": source_url,
            "final_url": source_url,
            "captured_at_utc": utc_now(),
            "capture_method": "rendered",
            "evidence_type": "text",
            "text_content": text,
            "artifact_path": None,
            "sha256": None,
            "http_status": None,
            "limitations": limitations,
            "redaction_status": "reviewed",
            "original_evidence_id": None,
        }
    )
    return evidence_id


def artifact_for_evidence(database: Database, evidence_id: str) -> Path:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT artifact_path FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
    if row is None or row["artifact_path"] is None:
        raise HTTPException(404, "Screenshot evidence was not found.")
    candidate = (database.artifact_dir / row["artifact_path"]).resolve()
    root = database.artifact_dir.resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(404, "Screenshot artifact was not found.")
    return candidate
