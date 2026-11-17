import json
import re
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.companions.models import CompanionResponse
from app.companions.package import (
    build_evidence_manifest,
    build_screenshot_index,
    write_handoff_package,
)
from app.companions.system_prompt import build_companion_prompt

MAX_RESPONSE_BYTES = 500_000
FENCE = re.compile(r"\A```json\s*\r?\n(.*)\r?\n```\s*\Z", re.DOTALL)


class ResponseValidationError(ValueError):
    """Actionable invalid-response error."""


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ResponseValidationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_response(raw: str) -> CompanionResponse:
    if not raw or len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ResponseValidationError("Response exceeds the 500000-byte limit.")
    match = FENCE.fullmatch(raw.strip())
    if raw.strip().startswith("```") and match is None:
        raise ResponseValidationError("Use raw JSON or exactly one ```json fenced object.")
    payload = match.group(1) if match else raw.strip()
    try:
        decoded = json.loads(payload, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise ResponseValidationError(f"Invalid JSON: {error.msg}.") from error
    try:
        return CompanionResponse.model_validate(decoded)
    except ValidationError as error:
        messages = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
        raise ResponseValidationError(f"Response contract error: {messages}") from error


@dataclass(frozen=True)
class Handoff:
    batch_id: str
    prompt: str
    manifest: dict[str, object]
    package_path: Path | None = None
    screenshot_count: int = 0


class CompanionConnector(ABC):
    @abstractmethod
    def prepare_handoff(
        self,
        review: dict[str, object],
        evidence: list[dict[str, object]],
        *,
        artifact_dir: Path | None = None,
        package_dir: Path | None = None,
    ) -> Handoff:
        raise NotImplementedError

    @abstractmethod
    def validate_response(
        self, raw: str, review: dict[str, object], batch: dict[str, object]
    ) -> CompanionResponse:
        raise NotImplementedError

    @abstractmethod
    def import_response(
        self, raw: str, review: dict[str, object], batch: dict[str, object]
    ) -> CompanionResponse:
        raise NotImplementedError


class ManualCompanionConnector(CompanionConnector):
    def prepare_handoff(
        self,
        review: dict[str, object],
        evidence: list[dict[str, object]],
        *,
        artifact_dir: Path | None = None,
        package_dir: Path | None = None,
    ) -> Handoff:
        batch_id = f"batch-{secrets.token_urlsafe(12)}"
        screenshots = build_screenshot_index(evidence)
        evidence_manifest = build_evidence_manifest(evidence)
        package_name = f"{batch_id}.zip"
        manifest = {
            "schema_version": "1.0",
            "review_id": review["review_id"],
            "batch_id": batch_id,
            "checklist_version": review["checklist_version"],
            "website": review["website"],
            "scope": review["scope"],
            "selected_checklist_items": review["selected_checklist_ids"],
            "evidence_manifest": evidence_manifest,
            "screenshots": screenshots,
            "screenshot_count": len(screenshots),
            "attachment_bundle": package_name,
            "attachment_instructions": (
                "Upload every file under screenshots/ from the handoff zip together "
                "with this prompt. Screenshot files are part of the evidence package."
            ),
            "capture_limitations": [
                item["limitations"] for item in evidence if item.get("limitations")
            ],
            "response_json_schema": CompanionResponse.model_json_schema(),
        }
        prompt = build_companion_prompt(manifest)
        if screenshots:
            prompt += (
                "\n\n---\nSCREENSHOT ATTACHMENTS\n---\n"
                f"This handoff includes {len(screenshots)} screenshot file(s) in "
                f"`{package_name}` under screenshots/. Upload those image files with "
                "the Companion turn. Do not invent screenshots that are not listed:\n"
                + "\n".join(
                    f"- {row['evidence_id']}: {row['file']} "
                    f"({row.get('final_url') or row.get('source_url') or 'no url'})"
                    for row in screenshots
                )
            )

        package_path: Path | None = None
        if artifact_dir is not None:
            target_dir = package_dir or (artifact_dir / "handoffs")
            package_path = write_handoff_package(
                target_dir / package_name,
                prompt=prompt,
                manifest=manifest,
                evidence=evidence,
                artifact_dir=artifact_dir,
            )
            manifest["attachment_bundle_path"] = str(package_path.name)

        return Handoff(
            batch_id=batch_id,
            prompt=prompt,
            manifest=manifest,
            package_path=package_path,
            screenshot_count=len(screenshots),
        )

    def validate_response(
        self, raw: str, review: dict[str, object], batch: dict[str, object]
    ) -> CompanionResponse:
        response = parse_response(raw)
        for field in ("review_id", "batch_id", "checklist_version"):
            if getattr(response, field) != batch[field]:
                raise ResponseValidationError(f"{field} does not match prepared batch.")
        expected_ids = set(review["selected_checklist_ids"])
        actual_ids = [finding.checklist_id for finding in response.findings]
        if len(actual_ids) != len(set(actual_ids)):
            raise ResponseValidationError("Response contains duplicate checklist IDs.")
        if set(actual_ids) != expected_ids:
            raise ResponseValidationError(
                "Response must contain exactly one finding per selected checklist item."
            )
        evidence_ids = set(batch["evidence_ids"])
        for finding in response.findings:
            unknown = set(finding.evidence_ids) - evidence_ids
            if unknown:
                raise ResponseValidationError(
                    "Response references evidence outside this batch."
                )
            if finding.status in {"Pass", "Fail", "Partial"} and not finding.evidence_ids:
                raise ResponseValidationError(
                    f"{finding.status} finding {finding.checklist_id} requires evidence."
                )
            if not finding.evidence_ids and not finding.reason.strip():
                raise ResponseValidationError(
                    f"Evidence-free finding {finding.checklist_id} needs a reason."
                )
            if finding.status == "Not applicable" and not finding.reason.strip():
                raise ResponseValidationError(
                    "Not applicable finding needs a scope rationale."
                )
        return response

    def import_response(
        self, raw: str, review: dict[str, object], batch: dict[str, object]
    ) -> CompanionResponse:
        return self.validate_response(raw, review, batch)
