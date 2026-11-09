from io import BytesIO
from xml.sax.saxutils import escape

import cv2
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from .documents import png


def render_report(record, report, pages):
    result = BytesIO()
    doc = SimpleDocTemplate(result, title=f"VERIFEX | {record['id']}", author="VERIFEX",
                            invariant=True, leftMargin=50, rightMargin=50, topMargin=45, bottomMargin=45)
    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=27, leading=31, textColor=colors.HexColor("#172642"))
    section = ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=13, leading=17,
                             textColor=colors.HexColor("#176a79"), spaceBefore=13, spaceAfter=6, keepWithNext=True)
    normal = ParagraphStyle("body", fontName="Helvetica", fontSize=9.8, leading=14, spaceAfter=6)
    content = [Paragraph("VERIFEX | Forensic report", title), Spacer(1, 12)]

    def line(value):
        content.append(Paragraph(escape(str(value)), normal))

    def heading(value):
        content.append(Paragraph(escape(value), section))

    line(f"Analysis {record['id']}  |  {record['created_at']}")
    line(f"Source file: {record['filename']}")
    heading(f"Assessment: {report['outcome'].replace('_', ' ').title()}")
    line(report["explanation"]["summary"])
    heading("Cryptographic integrity")
    for key in ("record_status", "issuer", "certificate_ref", "uploaded_sha256", "registered_sha256", "sha256_match",
                "record_signature_valid", "signature_valid", "revoked_at"):
        if key in report["crypto"]:
            line(f"{key.replace('_', ' ').title()}: {report['crypto'][key]}")
    heading("Extracted fields and comparison")
    if not report["fields"]:
        line("No labeled fields could be extracted.")
    for field, value in report["fields"].items():
        line(f"{field.replace('_', ' ').title()}: {value['value']} (page {value['page']})")
    for difference in report["differences"]:
        line(f"{difference['label']}: {difference['original'] or 'unreadable'} → {difference['uploaded'] or 'unreadable'}")
    heading("Custom AI forgery detection")
    custom = report["custom_model"]
    line(f"{custom['name']} | {custom['version']} | {custom['predicted_class']} | score {custom['risk_score']}" if custom["status"] == "complete"
         else custom.get("detail", "Model unavailable."))
    heading("Visual observations")
    findings = [*report["opencv"], *(report.get("gemini") or {}).get("observations", []), *custom.get("regions", [])]
    differences = [item for summary in report["comparison"] for item in summary["regions"]]
    for finding in [*findings, *differences]:
        line(f"Page {finding['page']} | {finding.get('kind', 'Gemini')}: {finding['finding']}")
    if not findings and not differences:
        line("No visual regions were marked by the engines that ran.")
    for index, page in enumerate(pages, start=1):
        marked = [item for item in [*findings, *differences] if item["page"] == index and item.get("box")]
        if not marked:
            continue
        image = page.image.copy()
        height, width = image.shape[:2]
        for item in marked:
            x0, y0, x1, y1 = item["box"]
            color = (190, 88, 176) if item.get("kind") == "custom_model" else (42, 83, 225)
            cv2.rectangle(image, (int(x0*width), int(y0*height)), (int(x1*width), int(y1*height)), color, 3)
        scale = min(6.6 * inch / width, 3.6 * inch / height)
        heading(f"Marked review regions | page {index}")
        content.append(Image(BytesIO(png(image)), width=width * scale, height=height * scale, hAlign="LEFT"))
    heading(f"Forensic explanation | {report['explanation']['source']}")
    line(report["explanation"]["detailed"])
    line(report["explanation"]["recommendation"])
    heading("Engine provenance and limitations")
    for name, info in report["engines"].items():
        line(f"{name}: {info['status']} {info.get('model') or info.get('detail') or ''}")
    for limitation in [*report["limitations"], *report["warnings"], custom.get("limitations", "")]:
        if limitation:
            line(limitation)
    line("The accompanying detached Ed25519 signature covers the exact PDF bytes.")
    doc.build(content)
    return result.getvalue()
