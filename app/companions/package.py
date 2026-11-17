"""Build Companion handoff packages that include screenshots + text evidence."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


def screenshot_attachment_name(evidence_id: str, artifact_path: str | None) -> str:
    suffix = Path(artifact_path or f"{evidence_id}.png").suffix or ".png"
    return f"screenshots/{evidence_id}{suffix}"


def text_attachment_name(evidence_id: str) -> str:
    return f"text/{evidence_id}.txt"


def build_evidence_manifest(evidence: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in evidence:
        evidence_id = str(item["evidence_id"])
        evidence_type = str(item["evidence_type"])
        attachment_name = None
        if evidence_type == "screenshot" and item.get("artifact_path"):
            attachment_name = screenshot_attachment_name(
                evidence_id, str(item["artifact_path"])
            )
        elif evidence_type == "text":
            attachment_name = text_attachment_name(evidence_id)
        rows.append(
            {
                "evidence_id": evidence_id,
                "source_url": item.get("requested_url"),
                "final_url": item.get("final_url"),
                "captured_at_utc": item.get("captured_at_utc"),
                "capture_method": item.get("capture_method"),
                "evidence_type": evidence_type,
                "attachment_name": attachment_name,
                "limitations": item.get("limitations"),
            }
        )
    return rows


def build_screenshot_index(evidence: list[dict[str, object]]) -> list[dict[str, object]]:
    index: list[dict[str, object]] = []
    for item in evidence:
        if item.get("evidence_type") != "screenshot" or not item.get("artifact_path"):
            continue
        evidence_id = str(item["evidence_id"])
        index.append(
            {
                "evidence_id": evidence_id,
                "file": screenshot_attachment_name(
                    evidence_id, str(item["artifact_path"])
                ),
                "source_url": item.get("requested_url"),
                "final_url": item.get("final_url"),
                "limitations": item.get("limitations"),
            }
        )
    return index


def write_handoff_package(
    package_path: Path,
    *,
    prompt: str,
    manifest: dict[str, object],
    evidence: list[dict[str, object]],
    artifact_dir: Path,
) -> Path:
    """Write a zip with prompt, manifest, all screenshots, and text extracts."""
    package_path.parent.mkdir(parents=True, exist_ok=True)
    root = artifact_dir.resolve()
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("prompt.txt", prompt)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr(
            "README.txt",
            (
                "Clariti Companion handoff package\n"
                "================================\n"
                "1. Read prompt.txt (includes Clariti Legal Companion system prompt).\n"
                "2. Upload screenshots/ files with the Companion chat as attachments.\n"
                "3. Use manifest.json evidence_ids when drafting findings.\n"
                "4. Return raw JSON only per response_json_schema.\n"
            ),
        )
        for item in evidence:
            evidence_id = str(item["evidence_id"])
            if item.get("evidence_type") == "screenshot" and item.get("artifact_path"):
                candidate = (artifact_dir / str(item["artifact_path"])).resolve()
                if root not in candidate.parents or not candidate.is_file():
                    continue
                arcname = screenshot_attachment_name(
                    evidence_id, str(item["artifact_path"])
                )
                archive.write(candidate, arcname)
            elif item.get("evidence_type") == "text" and item.get("text_content"):
                archive.writestr(
                    text_attachment_name(evidence_id),
                    str(item["text_content"]),
                )
    return package_path
