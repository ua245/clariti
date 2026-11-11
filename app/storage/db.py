import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.checklist.models import ChecklistTemplate
from app.config import (
    DATABASE_PATH,
    DEFAULT_COMPANION_NAME,
    DEFAULT_COMPANION_URL,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path
        self.artifact_dir = path.parent / "artifacts"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self, template: ChecklistTemplate) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checklist_templates (
                    version TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id TEXT PRIMARY KEY,
                    website TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    checklist_version TEXT NOT NULL,
                    selected_checklist_ids_json TEXT NOT NULL,
                    checklist_snapshot_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL REFERENCES reviews(review_id),
                    requested_url TEXT,
                    final_url TEXT,
                    captured_at_utc TEXT NOT NULL,
                    capture_method TEXT NOT NULL CHECK(
                        capture_method IN ('manual', 'static', 'rendered')
                    ),
                    evidence_type TEXT NOT NULL,
                    text_content TEXT,
                    artifact_path TEXT,
                    sha256 TEXT,
                    http_status INTEGER,
                    limitations TEXT NOT NULL,
                    redaction_status TEXT NOT NULL CHECK(
                        redaction_status IN ('not_reviewed', 'reviewed', 'redacted')
                    ),
                    original_evidence_id TEXT REFERENCES evidence(evidence_id)
                );
                CREATE TABLE IF NOT EXISTS handoff_batches (
                    batch_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL REFERENCES reviews(review_id),
                    checklist_version TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS companion_imports (
                    import_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES handoff_batches(batch_id),
                    review_id TEXT NOT NULL REFERENCES reviews(review_id),
                    raw_response TEXT NOT NULL,
                    findings_json TEXT NOT NULL,
                    imported_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviewer_edits (
                    edit_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL REFERENCES reviews(review_id),
                    checklist_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL REFERENCES reviews(review_id),
                    reviewer_name TEXT NOT NULL,
                    review_revision INTEGER NOT NULL,
                    approved_at_utc TEXT NOT NULL
                );
                """
            )
            review_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(reviews)")
            }
            if "selected_checklist_ids_json" not in review_columns:
                connection.execute(
                    """
                    ALTER TABLE reviews ADD COLUMN selected_checklist_ids_json
                    TEXT NOT NULL DEFAULT '[]'
                    """
                )
            if "revision" not in review_columns:
                connection.execute(
                    "ALTER TABLE reviews ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
                )
            for key, value in {
                "companion_name": DEFAULT_COMPANION_NAME,
                "companion_url": DEFAULT_COMPANION_URL,
                "active_checklist_version": template.version,
            }.items():
                connection.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                    (key, value),
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO checklist_templates(version, payload_json, created_at_utc)
                VALUES (?, ?, ?)
                """,
                (template.version, template.model_dump_json(), utc_now()),
            )

    def get_settings(self) -> dict[str, str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM settings WHERE key IN (?, ?, ?)",
                ("companion_name", "companion_url", "active_checklist_version"),
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def update_settings(self, name: str, url: str) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO settings(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                [("companion_name", name), ("companion_url", url)],
            )

    def reset_settings(self) -> None:
        self.update_settings(DEFAULT_COMPANION_NAME, DEFAULT_COMPANION_URL)

    def get_active_template(self) -> ChecklistTemplate:
        version = self.get_settings()["active_checklist_version"]
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM checklist_templates WHERE version = ?",
                (version,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Active checklist template is missing.")
        return ChecklistTemplate.model_validate_json(row["payload_json"])

    def add_template(self, template: ChecklistTemplate) -> None:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM checklist_templates WHERE version = ?",
                (template.version,),
            ).fetchone()
            if existing is not None:
                raise ValueError("Checklist version already exists and is immutable.")
            connection.execute(
                """
                INSERT INTO checklist_templates(version, payload_json, created_at_utc)
                VALUES (?, ?, ?)
                """,
                (template.version, template.model_dump_json(), utc_now()),
            )
            connection.execute(
                """
                INSERT INTO settings(key, value) VALUES ('active_checklist_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (template.version,),
            )

    def create_review(
        self,
        review_id: str,
        website: str,
        scope: str,
        template: ChecklistTemplate,
        selected_checklist_ids: list[str],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reviews(
                    review_id, website, scope, checklist_version, selected_checklist_ids_json,
                    checklist_snapshot_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    website,
                    scope,
                    template.version,
                    json.dumps(selected_checklist_ids),
                    template.model_dump_json(),
                    utc_now(),
                ),
            )

    def list_reviews(self) -> list[dict[str, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT review_id, website, scope, checklist_version, created_at_utc
                FROM reviews ORDER BY created_at_utc DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_review(self, review_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reviews WHERE review_id = ?", (review_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["selected_checklist_ids"] = json.loads(
            result.pop("selected_checklist_ids_json")
        )
        result["checklist_snapshot"] = json.loads(result.pop("checklist_snapshot_json"))
        return result

    def create_evidence(self, values: dict[str, object]) -> None:
        columns = (
            "evidence_id", "review_id", "requested_url", "final_url",
            "captured_at_utc", "capture_method", "evidence_type", "text_content",
            "artifact_path", "sha256", "http_status", "limitations",
            "redaction_status", "original_evidence_id",
        )
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO evidence({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )
            connection.execute(
                "UPDATE reviews SET revision = revision + 1 WHERE review_id = ?",
                (values["review_id"],),
            )

    def list_evidence(self, review_id: str) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT evidence_id, requested_url, final_url, captured_at_utc,
                    capture_method, evidence_type, text_content, artifact_path, sha256,
                    http_status, limitations, redaction_status, original_evidence_id
                FROM evidence WHERE review_id = ? ORDER BY captured_at_utc DESC
                """,
                (review_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_handoff_batch(
        self, batch_id: str, review_id: str, checklist_version: str,
        evidence_ids: list[str], manifest: dict[str, object], prompt: str
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO handoff_batches(
                    batch_id, review_id, checklist_version, evidence_ids_json,
                    manifest_json, prompt_text, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id, review_id, checklist_version, json.dumps(evidence_ids),
                    json.dumps(manifest), prompt, utc_now(),
                ),
            )

    def get_handoff_batch(self, batch_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM handoff_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["evidence_ids"] = json.loads(result.pop("evidence_ids_json"))
        result["manifest"] = json.loads(result.pop("manifest_json"))
        return result

    def create_companion_import(
        self, import_id: str, batch_id: str, review_id: str, raw_response: str,
        findings: list[dict[str, object]]
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO companion_imports(
                    import_id, batch_id, review_id, raw_response, findings_json, imported_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (import_id, batch_id, review_id, raw_response, json.dumps(findings), utc_now()),
            )
            connection.execute(
                "UPDATE reviews SET revision = revision + 1 WHERE review_id = ?",
                (review_id,),
            )

    def latest_companion_import(self, review_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT import_id, batch_id, findings_json, imported_at_utc
                FROM companion_imports WHERE review_id = ?
                ORDER BY imported_at_utc DESC LIMIT 1
                """,
                (review_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["findings"] = json.loads(result.pop("findings_json"))
        return result

    def create_reviewer_edit(
        self, edit_id: str, review_id: str, checklist_id: str, status: str, notes: str,
        reason: str, evidence_ids: list[str]
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reviewer_edits(
                    edit_id, review_id, checklist_id, status, notes, reason,
                    evidence_ids_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (edit_id, review_id, checklist_id, status, notes, reason,
                 json.dumps(evidence_ids), utc_now()),
            )
            connection.execute(
                "UPDATE reviews SET revision = revision + 1 WHERE review_id = ?",
                (review_id,),
            )

    def list_reviewer_edits(self, review_id: str) -> list[dict[str, object]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT edit_id, checklist_id, status, notes, reason, evidence_ids_json,
                    created_at_utc FROM reviewer_edits WHERE review_id = ?
                ORDER BY created_at_utc
                """,
                (review_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence_ids"] = json.loads(item.pop("evidence_ids_json"))
            result.append(item)
        return result

    def create_approval(self, approval_id: str, review_id: str, reviewer_name: str, revision: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO approvals(
                    approval_id, review_id, reviewer_name, review_revision, approved_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (approval_id, review_id, reviewer_name, revision, utc_now()),
            )

    def current_approval(self, review_id: str, revision: int) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT approval_id, reviewer_name, review_revision, approved_at_utc
                FROM approvals WHERE review_id = ? AND review_revision = ?
                ORDER BY approved_at_utc DESC LIMIT 1
                """,
                (review_id, revision),
            ).fetchone()
        return dict(row) if row else None
