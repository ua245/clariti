import csv
import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer


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


def _fit_image(path: Path, max_width: float, max_height: float) -> Image:
    # Normalize via Pillow so truncated/odd PNGs from captures still embed.
    from PIL import Image as PILImage

    with PILImage.open(path) as opened:
        rgb = opened.convert("RGB")
        buffer = io.BytesIO()
        rgb.save(buffer, format="PNG")
        buffer.seek(0)
        image = Image(buffer)
    width = float(image.imageWidth)
    height = float(image.imageHeight)
    if width <= 0 or height <= 0:
        image.drawWidth = max_width
        image.drawHeight = max_height / 2
        return image
    scale = min(max_width / width, max_height / height, 1.0)
    image.drawWidth = width * scale
    image.drawHeight = height * scale
    return image


def pdf_report(
    review: dict[str, object],
    final: bool,
    *,
    artifact_dir: Path | None = None,
) -> bytes:
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
        observation = finding.get("observation")
        if observation:
            story.append(Paragraph(escape(str(observation)), styles["BodyText"]))

    evidence = list(review.get("evidence") or [])
    screenshots = [
        item
        for item in evidence
        if item.get("evidence_type") == "screenshot" and item.get("artifact_path")
    ]
    if screenshots and artifact_dir is not None:
        story.append(PageBreak())
        story.append(Paragraph("Screenshot evidence", styles["Heading2"]))
        story.append(
            Paragraph(
                escape(
                    f"Embedding {len(screenshots)} screenshot(s). Images are capture-time "
                    "UI evidence only and do not prove tracking or notice completeness."
                ),
                styles["BodyText"],
            )
        )
        root = artifact_dir.resolve()
        max_width = 6.5 * inch
        max_height = 8.0 * inch
        for index, item in enumerate(screenshots):
            rel = str(item["artifact_path"])
            candidate = (artifact_dir / rel).resolve()
            if root not in candidate.parents or not candidate.is_file():
                story.append(
                    Paragraph(
                        escape(f"Missing artifact for {item.get('evidence_id')}"),
                        styles["BodyText"],
                    )
                )
                continue
            caption = (
                f"{item.get('evidence_id')} · {item.get('final_url') or item.get('requested_url') or ''}"
            )
            story.append(Spacer(1, 8))
            story.append(Paragraph(escape(caption), styles["Heading3"]))
            if item.get("limitations"):
                story.append(
                    Paragraph(escape(str(item["limitations"])), styles["BodyText"])
                )
            try:
                story.append(_fit_image(candidate, max_width, max_height))
            except Exception:
                story.append(
                    Paragraph(
                        escape(f"Could not embed image for {item.get('evidence_id')}"),
                        styles["BodyText"],
                    )
                )
            # Keep large reports readable: page break between screenshots.
            if index < len(screenshots) - 1:
                story.append(PageBreak())

    text_items = [
        item for item in evidence if item.get("evidence_type") == "text" and item.get("text_content")
    ]
    if text_items:
        story.append(PageBreak())
        story.append(Paragraph("Text evidence excerpts", styles["Heading2"]))
        for item in text_items[:40]:
            story.append(
                Paragraph(
                    escape(f"{item.get('evidence_id')} · {item.get('final_url') or item.get('requested_url') or ''}"),
                    styles["Heading3"],
                )
            )
            excerpt = str(item["text_content"])[:4000]
            story.append(Paragraph(escape(excerpt).replace("\n", "<br/>"), styles["BodyText"]))
            story.append(Spacer(1, 8))

    document.build(story)
    return output.getvalue()
