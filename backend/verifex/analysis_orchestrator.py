import logging
from base64 import b64encode
from threading import Event as Signal, Thread

from sqlalchemy import delete, select, update
from sqlalchemy.orm import defer

from . import gemini_service, groq_service
from .crypto_service import canonical, fingerprint
from .db import Analysis, Certificate, Event, now, timestamp
from .documents import decode, png
from .issuance import integrity, matching_record
from .ocr_service import compare_fields, fields_for
from .opencv_service import compare_images, forensics

LOG = logging.getLogger(__name__)
STAGES = {
    "queued": "Queued for analysis", "render": "Decrypting and rendering document",
    "ocr": "Extracting text and document fields", "forensics": "Measuring visual forensic signals",
    "custom": "Running the custom forgery model", "gemini": "Checking multimodal observations",
    "crypto": "Checking SHA-256 and Ed25519 integrity", "groq": "Preparing the forensic explanation",
    "complete": "Report available", "failed": "Analysis failed",
}
TERMINAL = {"complete", "failed"}
LIMITS = (
    "Visual findings and model scores are review signals. Scanning, resaving and layout can create differences.",
    "An absent issuance record leaves authenticity unknown.",
    "A valid signature establishes the match to a registered issuance record. Revocation is checked independently.",
)


def progress(stage, date):
    return {"stage": stage, "label": STAGES[stage], "at": timestamp(date)}


def snapshot(row):
    return {"id": row.id, "filename": row.filename, "mime": row.mime, "stage": row.stage,
            "outcome": row.outcome, "created_at": timestamp(row.created_at), "demo": row.demo,
            "progress": row.progress}


def outcome_for(crypto, observations, fields, cv_findings, custom, no_text):
    if crypto["record_status"] == "revoked":
        return "revoked"
    if crypto["record_status"] == "invalid_record":
        return "manual_review"
    if crypto["sha256_match"] is True and crypto["signature_valid"]:
        return "verified"
    if crypto["sha256_match"] is False:
        return "modified"
    if any(diff["kind"] == "changed" for diff in fields) or any(
        item["kind"] == "copy_move" for item in cv_findings
    ) or any(item["severity"] == "high" for item in observations):
        return "suspicious"
    if no_text or custom.get("predicted_class") == "visual_tamper_signal":
        return "manual_review"
    return "unverified"


def local_summary(outcome, crypto, differences, forensics, custom):
    lines = {
        "verified": "The uploaded bytes match a trusted issuance record and verify against the issuer’s Ed25519 key.",
        "modified": "The uploaded SHA-256 fingerprint differs from the selected record. The issuer signature does not verify against the uploaded fingerprint.",
        "revoked": "The issuer has revoked this certificate.",
        "suspicious": "The inspection found visual or text differences worth reviewing.",
        "manual_review": "The available evidence calls for manual review.",
        "unverified": "No trusted issuance record matched. Authenticity is unknown.",
    }
    changed = [row["label"] for row in differences if row["kind"] == "changed"]
    extra = f" Extracted values differ for {', '.join(changed)}." if changed else ""
    if forensics:
        extra += f" OpenCV marked {len(forensics)} visual regions for inspection."
    if custom.get("status") == "complete":
        extra += f" The custom model returned a visual score of {custom['risk_score']:.3f}."
    recommendation = "Check the issuer or compare with an authorized original." if outcome != "verified" else "Use the verification link to check current revocation status."
    return {"summary": lines[outcome], "detailed": lines[outcome] + extra, "presentation": lines[outcome],
            "recommendation": recommendation, "source": "local"}


def provider_evidence(report):
    evidence = {key: report[key] for key in ("outcome", "crypto", "differences", "opencv", "anomaly",
                                             "gemini", "gemini_discrepancies", "custom_model", "limitations")}
    evidence["ocr"] = {"fields": {key: field["value"] for key, field in report["fields"].items()},
                       "line_count": len(report["ocr"]), "page_count": report["page_count"]}
    return evidence


class Analyzer:
    def __init__(self, sessions, vault, settings, ocr, custom):
        self.sessions, self.vault, self.settings, self.ocr, self.custom = sessions, vault, settings, ocr, custom
        self.wake = Signal()
        self.stopping = Signal()
        self.thread = Thread(target=self._loop, name="verifex-analysis", daemon=True)

    def start(self):
        with self.sessions.begin() as db:
            # One analysis worker owns this database. Restore work interrupted by shutdown.
            db.execute(update(Analysis).where(Analysis.stage.not_in(TERMINAL | {"queued"}))
                       .values(stage="queued", progress=[], partial=None))
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        self.thread.join()

    def _loop(self):
        while not self.stopping.is_set():
            with self.sessions() as db:
                job = db.scalar(select(Analysis.id).where(Analysis.stage == "queued")
                                .order_by(Analysis.created_at, Analysis.id).limit(1))
            if job:
                try:
                    self.run(job)
                except Exception:
                    LOG.exception("Analysis %s failed", job)
                    self._stage(job, "failed")
                continue
            self.wake.wait(1)
            self.wake.clear()

    def _stage(self, job, stage, preview=None):
        with self.sessions.begin() as db:
            row = db.get(Analysis, job, options=[defer(Analysis.source), defer(Analysis.report)])
            if row is None:
                return False
            row.stage = stage
            row.progress = row.progress + [progress(stage, now())]
            if preview is not None:
                row.partial = self.vault.seal(canonical(preview), f"partial:{job}")
            if stage == "failed":
                row.partial = None
            return True

    def run(self, job):
        if not self._stage(job, "render"):
            return
        with self.sessions() as db:
            row = db.get(Analysis, job)
            if row is None:
                return
            data = self.vault.open(row.source, f"analysis:{job}")
            digest = fingerprint(data)
            record = db.get(Certificate, row.certificate_ref) if row.certificate_ref else matching_record(db, digest)
            original_data = self.vault.open(record.original, f"certificate:{record.ref}") if record and row.compare_allowed else None
            reference = record.ref if record else None
        mime, pages = decode(data)
        original = decode(original_data)[1] if original_data else []
        self._stage(job, "ocr")
        lines, engines, warnings = self._text(pages)
        current_fields = fields_for(lines)
        original_lines = lines if data == original_data else self._text(original)[0]
        original_fields = fields_for(original_lines)
        differences = compare_fields(original_fields, current_fields) if original else []
        preview = {"page_count": len(pages), "boxes": [{"page": line["page"], "box": line["box"]} for line in lines]}
        self._stage(job, "forensics", preview)
        cv_findings, scores, comparisons = [], [], []
        for index, page in enumerate(pages, start=1):
            results, score = forensics(page.image, [item for item in lines if item["page"] == index], index, mime)
            cv_findings.extend(results)
            scores.append(score)
            if index <= len(original):
                summary, _ = compare_images(original[index-1].image, page.image, index)
                comparisons.append({"page": index, **summary})
        self._stage(job, "custom")
        custom, layers = self.custom.infer(pages)
        self._stage(job, "gemini")
        gemini, gemini_meta = (gemini_service.analyze(self.settings, pages, original)
                               if row.external_ai else (None, {"status": "consent_required"}))
        observations, discrepancies = [], []
        if gemini:
            for item in gemini["observations"]:
                region = current_fields.get(item["region"])
                if region and region["page"] == item["page"]:
                    item["box"] = region["box"]
                observations.append(item)
            gemini_fields = {name: {"value": value, "page": None, "box": None}
                             for name, value in gemini["extracted_fields"].items() if value}
            discrepancies = compare_fields(gemini_fields, current_fields)
        self._stage(job, "crypto")
        with self.sessions() as db:
            crypto = integrity(db, db.get(Certificate, reference) if reference else None, digest)
        outcome = outcome_for(crypto, observations, differences, cv_findings, custom, not lines)
        report = {"outcome": outcome, "crypto": crypto, "fields": current_fields, "ocr": lines,
                  "original_fields": original_fields, "original_ocr": original_lines,
                  "differences": differences, "comparison": comparisons,
                  "page_count": len(pages), "original_pages": len(original), "opencv": cv_findings,
                  "anomaly": scores, "custom_model": custom, "gemini": gemini, "gemini_discrepancies": discrepancies,
                  "limitations": LIMITS, "warnings": sorted(set(warnings))}
        report["model_layers"] = [{name: b64encode(png(image)).decode("ascii") for name, image in layer.items()}
                                  for layer in layers]
        if row.demo and row.filename == "demo-failure.png" and self.custom.metrics.get("failure_case"):
            report["demo_case"] = self.custom.metrics["failure_case"]
        self._stage(job, "groq")
        ai, groq_meta = (groq_service.explain(self.settings, provider_evidence(report))
                         if row.external_ai else (None, {"status": "consent_required"}))
        report["engines"] = {"OCR": {"status": "contributed" if lines else "unavailable", "detail": ", ".join(sorted(set(engines)))},
                             "OpenCV": {"status": "contributed"}, "Isolation forest": {"status": "contributed" if any(s is not None for s in scores) else "unavailable"},
                             "Custom model": {"status": custom["status"], "model": custom.get("version")},
                             "Cryptography": {"status": "contributed"}, "Gemini": gemini_meta, "Groq": groq_meta}
        report["explanation"] = ({**ai, "source": "Groq"} if ai else local_summary(outcome, crypto, differences, cv_findings, custom))
        with self.sessions.begin() as db:
            current = db.get(Analysis, job, options=[defer(Analysis.source), defer(Analysis.report)])
            if current is None:
                return
            latest = integrity(db, db.get(Certificate, reference) if reference else None, digest)
            if latest != crypto:
                outcome = outcome_for(latest, observations, differences, cv_findings, custom, not lines)
                report.update(crypto=latest, outcome=outcome,
                              explanation=local_summary(outcome, latest, differences, cv_findings, custom))
            current.certificate_ref = reference
            current.outcome = outcome
            current.report = self.vault.seal(canonical(report), f"report:{job}")
            current.partial = None
            current.stage = "complete"
            current.progress = current.progress + [progress("complete", now())]
            if outcome in {"modified", "suspicious"}:
                db.add(Event(actor_id=current.owner_id, subject=job, kind="suspicious_upload", detail=outcome))

    def _text(self, pages):
        lines, engines, warnings = [], [], []
        for index, page in enumerate(pages, start=1):
            extracted, engine, details = self.ocr.extract(page)
            lines.extend({**line, "page": index} for line in extracted)
            engines.append(engine)
            warnings.extend(details)
        return lines, engines, warnings
