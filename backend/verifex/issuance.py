import hmac
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from sqlalchemy import select

from .crypto_service import canonical, certificate_payload, fingerprint, verify
from .db import Certificate, User, identifier, now, timestamp


def register(db, vault, user, data, demo=False, metadata=None):
    if not user.signing_key or not user.public_key:
        raise ValueError("Issuer has no trusted signing key")
    ref, issued, digest = identifier(), now(), fingerprint(data)
    signature = vault.issuer_sign(user.id, user.signing_key,
                                 certificate_payload(ref, user.id, user.name, digest, timestamp(issued)))
    record = Certificate(ref=ref, issuer_id=user.id, issuer_name=user.name, fingerprint=digest,
                         signature=signature, issued_at=issued,
                         original=vault.seal(data, f"certificate:{ref}"), demo=demo,
                         private_metadata=vault.seal(canonical(metadata), f"certificate-meta:{ref}") if metadata else None)
    db.add(record)
    return record


def integrity(db, record, digest=None):
    if not record:
        return {"record_status": "unknown", "record_signature_valid": None, "signature_valid": None,
                "sha256_match": None, "certificate_ref": None, "uploaded_sha256": digest}
    issuer = db.get(User, record.issuer_id)
    key = issuer.public_key if issuer else None
    issued = timestamp(record.issued_at)
    payload = certificate_payload(record.ref, record.issuer_id, record.issuer_name, record.fingerprint, issued)
    record_valid = bool(key and verify(key, payload, record.signature))
    matched = hmac.compare_digest(digest, record.fingerprint) if digest is not None else None
    document_valid = bool(key and verify(
        key, certificate_payload(record.ref, record.issuer_id, record.issuer_name, digest, issued), record.signature
    )) if digest is not None else None
    status = "revoked" if record.revoked_at else "invalid_record" if not record_valid else "registered"
    return {"record_status": status, "record_signature_valid": record_valid, "signature_valid": document_valid,
            "sha256_match": matched, "certificate_ref": record.ref, "uploaded_sha256": digest,
            "registered_sha256": record.fingerprint, "issuer": record.issuer_name, "issued_at": issued,
            "revoked_at": timestamp(record.revoked_at) if record.revoked_at else None,
            "issuer_public_key": key, "record_signature": record.signature}


def matching_record(db, digest):
    return db.scalar(select(Certificate).where(Certificate.fingerprint == digest)
                     .order_by(Certificate.revoked_at.is_not(None), Certificate.issued_at.desc(), Certificate.ref))


def demo_pdf(scenario):
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(900, 620), invariant=True)
    pdf.setFillColor(HexColor("#fbf7e9"))
    pdf.rect(0, 0, 900, 620, fill=1, stroke=0)
    for offset, color, weight in ((24, "#1b3057", 3), (34, "#b78c4c", 1)):
        pdf.setStrokeColor(HexColor(color))
        pdf.setLineWidth(weight)
        pdf.rect(offset, offset, 900-2*offset, 620-2*offset, fill=0)
    pdf.setFillColor(HexColor("#192b4c"))
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawCentredString(450, 544, "Q U I L L S P I R E   /   F I C T I O N A L   I N S T I T U T E")
    pdf.setFont("Times-Bold", 53)
    pdf.drawCentredString(450, 473, "Certificate of Merit")
    pdf.setFont("Helvetica", 14)
    pdf.drawCentredString(450, 430, "VERIFEX DEMONSTRATION  |  SYNTHETIC ACADEMIC RECORD")
    pdf.setStrokeColor(HexColor("#b78c4c"))
    pdf.line(99, 405, 800, 405)
    fields = [
        ("Student name", "Arlen Cloudfell" if scenario != "unknown" else "Nima Quillridge"),
        ("Institution", "Quillspire Fictional Institute"),
        ("Certificate ID", "VX-DEMO-1001" if scenario != "unknown" else "VX-UNREGISTERED-42"),
        ("Roll number", "R-24681"), ("Course", "Applied Cryptography"),
        ("Grade", "A+" if scenario == "modified" else "B"),
        ("Marks", "71"), ("Issue date", "2026-03-11"),
        ("Signatory", "Synthetic Registrar"),
    ]
    for index, (label, value) in enumerate(fields):
        y = 371 - 28 * index
        pdf.setFont("Helvetica", 18)
        pdf.setFillColor(HexColor("#192b4c"))
        if label == "Grade" and scenario == "modified":
            pdf.drawString(103, y, "Grade:")
            pdf.setFillColor(HexColor("#e7e0ca"))
            pdf.rect(160, y-4, 45, 25, fill=1, stroke=0)
            pdf.setFillColor(HexColor("#354459"))
            pdf.setFont("Times-Bold", 20)
            pdf.drawString(166, y+1, value)
        else:
            pdf.drawString(103, y, f"{label}: {value}")
    pdf.setStrokeColor(HexColor("#b78c4c"))
    for radius in (45, 37):
        pdf.circle(737, 180, radius)
    pdf.setFont("Times-Bold", 24)
    pdf.drawCentredString(737, 173, "VX")
    pdf.setFont("Helvetica", 11)
    pdf.drawCentredString(450, 68, "FICTIONAL SAMPLE  •  FOR DEMONSTRATION ONLY")
    pdf.showPage()
    pdf.save()
    return stream.getvalue()
