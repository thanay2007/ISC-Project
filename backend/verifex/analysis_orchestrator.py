import logging
from base64 import b64encode
from math import isfinite
from threading import Event as Signal, Thread

from sqlalchemy import delete, select, update
from sqlalchemy.orm import defer

from . import gemini_service, groq_service
from .crypto_service import canonical, fingerprint
from .db import Analysis, Certificate, Event, now, timestamp
from .documents import decode, png
from .issuance import integrity, matching_record
from .ocr_service import field_agreement, fields_for
from .opencv_service import forensics

LOG = logging.getLogger(__name__)
STAGES = {
    "queued": "Queued for analysis", "render": "Decrypting and rendering document",
    "ocr": "Extracting text and document fields", "forensics": "Measuring visual forensic signals",
    "custom": "Running the custom forgery model", "gemini": "Checking multimodal observations",
    "crypto": "Checking document integrity", "groq": "Preparing the forensic explanation",
    "complete": "Report available", "failed": "Analysis failed",
}
TERMINAL = {"complete", "failed"}
LIMITS = (
    "Scanning, compression, handwriting, and layout can create visual artifacts.",
    "For files without a signed record, the verdict estimates visible alteration from the uploaded pages alone.",
    "Visual confidence describes model support. Gemini can contribute from visible evidence. Issuer verification is a separate check.",
)


def progress(stage, date):
    return {"stage": stage, "label": STAGES[stage], "at": timestamp(date)}


def snapshot(row):
    outcome = published_outcome(row.outcome)
    return {"id": row.id, "filename": row.filename, "mime": row.mime, "stage": row.stage,
            "outcome": outcome, "verdict": verdict_label(outcome),
            "created_at": timestamp(row.created_at), "demo": row.demo,
            "progress": row.progress}


def published_outcome(outcome):
    # Archived reports include old visual-only outcomes.
    return outcome if outcome in {None, "verified", "modified", "revoked", "visual_fake", "visual_original"} else "manual_review"


def verdict_label(outcome):
    if outcome in {"modified", "visual_fake"}:
        return "Fake"
    if outcome in {"verified", "revoked", "visual_original"}:
        return "Original"
    return None


def visual_score(custom, gemini):
    local = custom.get("document_assessment")
    score = None
    if local:
        value, threshold = local["score"], local["threshold"]
        if isfinite(value) and 0 <= value <= 1 and 0 < threshold < 1:
            edited = value * (1 - threshold)
            intact = (1 - value) * threshold
            score = edited / (edited + intact)
    if not gemini:
        return score

    vote = gemini.get("visual_assessment")
    if vote == "likely_edited" and any(
        finding["severity"] == "high" and finding.get("edit_signal") in {
            "altered_text", "pasted_content", "duplicated_region", "content_conflict",
        }
        for finding in gemini.get("observations", [])
    ):
        multiplier = 2.
    elif vote == "no_clear_edit" and not gemini.get("manual_review_recommended"):
        multiplier = .8
    else:
        return score

    # Keep Gemini's influence bounded. An independent observation can settle
    # a borderline case without overriding strong local evidence by itself.
    score = .5 if score is None else score
    return multiplier * score / (1 - score + multiplier * score)


def outcome_for(crypto, custom, gemini=None):
    if crypto["sha256_match"] is True and crypto["signature_valid"]:
        return "revoked" if crypto["record_status"] == "revoked" else "verified"
    if crypto["sha256_match"] is False and crypto["record_signature_valid"]:
        return "modified"
    score = visual_score(custom, gemini)
    if score is None:
        return "manual_review"
    return "visual_fake" if score >= .5 else "visual_original"


def assessment_for(report):
    outcome = report["outcome"]
    if outcome in {"verified", "modified", "revoked"}:
        confidence = 100
    else:
        score = visual_score(report["custom_model"], report.get("gemini"))
        confidence = min(99, round(100 * max(score, 1 - score))) if score is not None else None
    return {"label": verdict_label(outcome), "confidence": confidence}


def local_summary(outcome, forensics, custom):
    lines = {
        "verified": "The uploaded bytes match a trusted issuance record and verify against the issuer’s Ed25519 key.",
        "modified": "The uploaded file differs from the signed issuer record. Resaving or rescanning can also change its fingerprint.",
        "revoked": "The file matches the signed issuer record. The issuer has revoked the certificate.",
        "visual_fake": "The visual assessment found evidence of editing in the uploaded pages.",
        "visual_original": "The visual assessment found limited evidence of editing in the uploaded pages.",
        "manual_review": "This report has no usable authenticity score. Reanalyze the document with the current engines.",
    }
    extra = ""
    if forensics:
        extra += f" OpenCV marked {len(forensics)} visual regions for inspection."
    if custom.get("status") == "complete":
        extra += f" The custom model returned a visual score of {custom['risk_score']:.3f}."
    recommendation = "Check with the issuer if independent confirmation is needed."
    return {"summary": lines[outcome], "detailed": lines[outcome] + extra, "presentation": lines[outcome],
            "recommendation": recommendation, "source": "local"}


def provider_evidence(report):
    evidence = {key: report[key] for key in ("crypto", "opencv", "anomaly", "gemini", "custom_model", "limitations")}
    evidence["assessment"] = assessment_for(report)
    if evidence["gemini"]:
        evidence["gemini"] = {key: value for key, value in evidence["gemini"].items() if key != "comparison_summary"}
    evidence["ocr"] = {"fields": {key: field["value"] for key, field in report["fields"].items()},
                       "gemini_agreement": field_agreement(report["fields"], report["gemini"]),
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
            reference = record.ref if record else None
        mime, pages = decode(data)
        self._stage(job, "ocr")
        lines, engines, warnings = self._text(pages)
        current_fields = fields_for(lines)
        preview = {"page_count": len(pages), "boxes": [{"page": line["page"], "box": line["box"]} for line in lines]}
        self._stage(job, "forensics", preview)
        cv_findings, scores = [], []
        for index, page in enumerate(pages, start=1):
            results, score = forensics(page.image, [item for item in lines if item["page"] == index], index, mime)
            cv_findings.extend(results)
            scores.append(score)
        self._stage(job, "custom")
        custom, layers = self.custom.infer(pages)
        self._stage(job, "gemini")
        gemini, gemini_meta = (gemini_service.analyze(self.settings, pages)
                               if row.external_ai else (None, {"status": "local_only"}))
        if gemini:
            for item in gemini["observations"]:
                region = current_fields.get(item["region"])
                if region and region["page"] == item["page"]:
                    item["box"] = region["box"]
        self._stage(job, "crypto")
        with self.sessions() as db:
            crypto = integrity(db, db.get(Certificate, reference) if reference else None, digest)
        outcome = outcome_for(crypto, custom, gemini)
        report = {"outcome": outcome, "crypto": crypto, "fields": current_fields, "ocr": lines,
                  "page_count": len(pages), "opencv": cv_findings,
                  "anomaly": scores, "custom_model": custom, "gemini": gemini,
                  "limitations": LIMITS, "warnings": sorted(set(warnings))}
        report["model_layers"] = [{name: b64encode(png(image)).decode("ascii") for name, image in layer.items()}
                                  for layer in layers]
        if row.demo and row.filename == "demo-failure.png" and self.custom.metrics.get("failure_case"):
            report["demo_case"] = self.custom.metrics["failure_case"]
        self._stage(job, "groq")
        ai, groq_meta = (groq_service.explain(self.settings, provider_evidence(report))
                         if row.external_ai else (None, {"status": "local_only"}))
        report["engines"] = {"OCR": {"status": "contributed" if lines else "unavailable", "detail": ", ".join(sorted(set(engines)))},
                             "OpenCV": {"status": "contributed"}, "Isolation forest": {"status": "contributed" if any(s is not None for s in scores) else "unavailable"},
                             "Custom model": {"status": custom["status"], "model": custom.get("version")},
                             "Cryptography": {"status": "contributed"}, "Gemini": gemini_meta, "Groq": groq_meta}
        summary = local_summary(outcome, cv_findings, custom)
        report["explanation"] = ({**ai, "summary": summary["summary"], "source": "Groq"} if ai else summary)
        with self.sessions.begin() as db:
            current = db.get(Analysis, job, options=[defer(Analysis.source), defer(Analysis.report)])
            if current is None:
                return
            latest = integrity(db, db.get(Certificate, reference) if reference else None, digest)
            if latest != crypto:
                outcome = outcome_for(latest, custom, gemini)
                report.update(crypto=latest, outcome=outcome,
                              explanation=local_summary(outcome, cv_findings, custom))
            current.certificate_ref = reference
            current.outcome = outcome
            current.report = self.vault.seal(canonical(report), f"report:{job}")
            current.partial = None
            current.stage = "complete"
            current.progress = current.progress + [progress("complete", now())]
            if verdict_label(outcome) == "Fake":
                detail = "Signed record fingerprint mismatch" if outcome == "modified" else "Visual model flagged editing"
                db.add(Event(actor_id=current.owner_id, subject=job, kind="suspicious_upload", detail=detail))

    def _text(self, pages):
        lines, engines, warnings = [], [], []
        for index, page in enumerate(pages, start=1):
            extracted, engine, details = self.ocr.extract(page)
            lines.extend({**line, "page": index} for line in extracted)
            engines.append(engine)
            warnings.extend(details)
        return lines, engines, warnings
