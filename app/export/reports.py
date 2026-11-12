import csv
import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def safe_csv(value: object) -> str:
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def effective_findings(review: dict[str, object]) -> list[dict[str, object]]:
    """Companion drafts overlaid with later reviewer edits (latest edit wins)."""
    imported = review.get("latest_companion_import") or {}
    findings: dict[str, dict[str, object]] = {}
    for finding in imported.get("findings", []):
        findings[str(finding["checklist_id"])] = dict(finding)
    for edit in review.get("reviewer_edits") or []:
        checklist_id = str(edit["checklist_id"])
        base = findings.get(checklist_id, {})
        findings[checklist_id] = {
            **base,
            "checklist_id": checklist_id,
            "status": edit["status"],
            "observation": edit.get("notes") or base.get("observation", ""),
            "reason": edit["reason"],
            "evidence_ids": list(edit.get("evidence_ids") or []),
            "missing_evidence": list(base.get("missing_evidence") or []),
            "suggested_action": base.get("suggested_action", ""),
            "requires_internal_review": bool(base.get("requires_internal_review", False)),
            "reviewer_edited": True,
        }
    return list(findings.values())


def csv_report(review: dict[str, object], final: bool) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Report status", "FINAL" if final else "DRAFT"])
    writer.writerow(["Review ID", safe_csv(review["review_id"])])
    writer.writerow(["Website", safe_csv(review["website"])])
    writer.writerow(["Checklist version", safe_csv(review["checklist_version"])])
    writer.writerow(["Checklist ID", "Status", "Reason", "Evidence IDs"])
    findings = review.get("effective_findings")
    if findings is None:
        findings = effective_findings(review)
    for finding in findings:
        writer.writerow(
            [
                safe_csv(finding["checklist_id"]),
                safe_csv(finding["status"]),
                safe_csv(finding["reason"]),
                safe_csv(", ".join(finding.get("evidence_ids") or [])),
            ]
        )
    return output.getvalue().encode("utf-8-sig")


def pdf_report(review: dict[str, object], final: bool) -> bytes:
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(
            f"{'FINAL' if final else 'DRAFT'} Privacy Review Report",
            styles["Title"],
        ),
        Paragraph(escape(f"Review: {review['review_id']}"), styles["BodyText"]),
        Paragraph(escape(f"Website: {review['website']}"), styles["BodyText"]),
        Paragraph(
            "Draft evidence-based findings. Human review and Legal/Privacy "
            "review where appropriate are required.",
            styles["BodyText"],
        ),
        Spacer(1, 12),
    ]
    findings = review.get("effective_findings")
    if findings is None:
        findings = effective_findings(review)
    for finding in findings:
        story.append(
            Paragraph(
                escape(f"{finding['checklist_id']}: {finding['status']}"),
                styles["Heading3"],
            )
        )
        story.append(Paragraph(escape(str(finding["reason"])), styles["BodyText"]))
    document.build(story)
    return output.getvalue()
