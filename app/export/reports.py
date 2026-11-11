import csv
import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def safe_csv(value: object) -> str:
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def csv_report(review: dict[str, object], final: bool) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Report status", "FINAL" if final else "DRAFT"])
    writer.writerow(["Review ID", safe_csv(review["review_id"])])
    writer.writerow(["Website", safe_csv(review["website"])])
    writer.writerow(["Checklist version", safe_csv(review["checklist_version"])])
    writer.writerow(["Checklist ID", "Status", "Reason", "Evidence IDs"])
    findings = (review.get("latest_companion_import") or {}).get("findings", [])
    for finding in findings:
        writer.writerow([
            safe_csv(finding["checklist_id"]), safe_csv(finding["status"]),
            safe_csv(finding["reason"]), safe_csv(", ".join(finding["evidence_ids"])),
        ])
    return output.getvalue().encode("utf-8-sig")


def pdf_report(review: dict[str, object], final: bool) -> bytes:
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"{'FINAL' if final else 'DRAFT'} Privacy Review Report", styles["Title"]),
        Paragraph(escape(f"Review: {review['review_id']}"), styles["BodyText"]),
        Paragraph(escape(f"Website: {review['website']}"), styles["BodyText"]),
        Paragraph("Draft evidence-based findings. Human review and Legal/Privacy review where appropriate are required.", styles["BodyText"]),
        Spacer(1, 12),
    ]
    for finding in (review.get("latest_companion_import") or {}).get("findings", []):
        story.append(Paragraph(escape(f"{finding['checklist_id']}: {finding['status']}"), styles["Heading3"]))
        story.append(Paragraph(escape(finding["reason"]), styles["BodyText"]))
    document.build(story)
    return output.getvalue()
