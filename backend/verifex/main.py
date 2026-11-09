import asyncio
import json
import logging
from base64 import b64decode
from collections import Counter
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from . import groq_service
from .analysis_orchestrator import STAGES, TERMINAL, Analyzer, local_summary, progress, provider_evidence, snapshot
from .config import ROOT, Settings
from .crypto_service import Vault, fingerprint, qr_png, verify
from backend.app.services.custom_forgery_model import CustomForgeryModel
from .db import Analysis, Certificate, Event, Session, User, connect, identifier, now, timestamp
from .documents import MAX_BYTES, decode, png, read_upload, safe_name, upload_document
from .issuance import demo_pdf, integrity, register
from .migrate import upgrade
from .ocr_service import OCR
from .opencv_service import compare_images
from .reports import render_report
from .security import (COOKIE, PASSWORDS, Login, Registration, audit, current_user, db_session, deny,
                       event_row, login_attempt, network, new_session, require_role, user_info)

LOG = logging.getLogger(__name__)
DB = Annotated[object, Depends(db_session)]
Actor = Annotated[User, Depends(current_user)]
Admin = Annotated[User, Depends(require_role("admin"))]
Issuer = Annotated[User, Depends(require_role("institution", "admin"))]
DEMO_EMAIL = "quillspire-issuer@verifex.invalid"
MODEL_DIR = ROOT / "ml/models"
RESULTS_DIR = ROOT / "ml/results"


def demo_seed(sessions, vault):
    with sessions.begin() as db:
        issuer = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if not issuer:
            issuer = User(id=identifier(), email=DEMO_EMAIL, password=PASSWORDS.hash(identifier() + identifier()),
                          name="Quillspire Fictional Institute", role="institution")
            issuer.signing_key, issuer.public_key = vault.issuer_keys(issuer.id)
            db.add(issuer)
            db.flush()
        fixture = RESULTS_DIR / "failure.png"
        original = RESULTS_DIR / "failure-original.png"
        originals = [demo_pdf("genuine")]
        if fixture.is_file():
            originals.append((original if original.is_file() else fixture).read_bytes())
        for data in originals:
            if not db.scalar(select(Certificate.ref).where(Certificate.demo.is_(True), Certificate.issuer_id == issuer.id,
                                                          Certificate.fingerprint == fingerprint(data))):
                register(db, vault, issuer, data, demo=True)


def add_job(request, db, actor, data, mime, filename, ref=None, comparison=False, consent=False, demo=False):
    open_jobs = db.scalar(select(func.count()).select_from(Analysis).where(
        Analysis.owner_id == actor.id, Analysis.stage.not_in(TERMINAL)))
    if open_jobs >= 4:
        raise HTTPException(429, "Wait for an analysis to finish before adding another.")
    if consent:
        last_hour = db.scalar(select(func.count()).select_from(Analysis).where(
            Analysis.owner_id == actor.id, Analysis.external_ai.is_(True), Analysis.created_at >= now() - timedelta(hours=1)))
        if last_hour >= 12:
            raise HTTPException(429, "The hourly external AI limit has been reached. Local analysis is available.")
    job, date = identifier(), now()
    row = Analysis(id=job, owner_id=actor.id, filename=filename, mime=mime, created_at=date,
                   source=request.app.state.vault.seal(data, f"analysis:{job}"), certificate_ref=ref,
                   compare_allowed=comparison, external_ai=consent, demo=demo, stage="queued",
                   progress=[progress("queued", date)])
    db.add(row)
    audit(db, "analysis_submitted", "Queued for forensic analysis", actor.id, job, network(request))
    db.commit()
    request.app.state.analyzer.wake.set()
    return snapshot(row)


def analysis_owned(request, db, user, job, report=False, source=False):
    options = []
    if not report:
        options.append(defer(Analysis.report))
    if not source:
        options.append(defer(Analysis.source))
    row = db.get(Analysis, job, options=options)
    if not row:
        raise HTTPException(404, "Analysis does not exist.")
    if row.owner_id != user.id:
        deny(request, db, user, row.id, "Attempted to open another user’s analysis")
    return row


def get_report(request, row):
    if row.stage != "complete" or row.report is None:
        raise HTTPException(409, "The analysis report is not ready.")
    return json.loads(request.app.state.vault.open(row.report, f"report:{row.id}"))


def preview_for(request, row):
    return json.loads(request.app.state.vault.open(row.partial, f"partial:{row.id}")) if row.partial else None


def own_certificate(request, db, user, ref):
    record = db.get(Certificate, ref)
    if not record:
        raise HTTPException(404, "Certificate record does not exist.")
    if record.issuer_id != user.id and user.role != "admin":
        deny(request, db, user, record.ref, "Attempted to access a restricted certificate")
    return record


def rate_check(db, actor, kind, count, minutes):
    recent = db.scalar(select(func.count()).select_from(Event).where(
        Event.actor_id == actor.id, Event.kind == kind, Event.created_at >= now() - timedelta(minutes=minutes)))
    if recent >= count:
        raise HTTPException(429, "Request limit reached. Try again later.")


def image_response(value):
    return Response(value, media_type="image/png")


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=750)
    external_ai: bool = False


class Consent(BaseModel):
    external_ai: bool = False


class InstitutionChange(BaseModel):
    role: Literal["institution", "verifier"]


def local_answer(question, report):
    question = question.casefold()
    crypto = report["crypto"]
    if "sha" in question or "hash" in question:
        return ("SHA-256 produces a fingerprint from the exact bytes. Changing even a small part of the document produces "
                f"a different fingerprint. Uploaded digest: {crypto['uploaded_sha256']}. " +
                ("A matching issuance digest was found." if crypto["sha256_match"] else
                 "The selected issuance digest differs." if crypto["sha256_match"] is False else "No issuance digest was available."))
    if "unsigned" in question:
        return "An unsigned certificate can be genuine. Ask the issuer to corroborate it independently."
    if "signature" in question:
        return "Ed25519 checks whether the issuer signed this fingerprint and record metadata. " + report["explanation"]["summary"]
    if any(term in question for term in ("field", "changed", "difference", "grade")):
        changes = [f"{item['label']}: {item['original'] or 'unreadable'} → {item['uploaded'] or 'unreadable'}"
                   for item in report["differences"]]
        return "; ".join(changes) if changes else "No differences between authorized OCR fields were recorded."
    if any(term in question for term in ("visual", "pattern", "opencv")):
        return " ".join(item["finding"] for item in report["opencv"][:5]) or "OpenCV did not mark a visual review region."
    return report["explanation"]["detailed"]


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        engine, sessions = connect(settings.database_url)
        vault = Vault(settings.validate(), settings.app_secret)
        upgrade(engine)
        app.state.sessions, app.state.vault = sessions, vault
        app.state.settings = settings
        if settings.admin_email and settings.admin_password:
            if len(settings.admin_password) < 12 or settings.admin_email == DEMO_EMAIL:
                raise ValueError("Choose a unique ADMIN_EMAIL and an ADMIN_PASSWORD of at least 12 characters.")
            with sessions.begin() as db:
                if not db.scalar(select(User.id).where(User.email == settings.admin_email)):
                    user = User(id=identifier(), email=settings.admin_email, name="VERIFEX Administrator",
                                password=PASSWORDS.hash(settings.admin_password), role="admin")
                    user.signing_key, user.public_key = vault.issuer_keys(user.id)
                    db.add(user)
        if settings.demo_enabled:
            demo_seed(sessions, vault)
        ocr = OCR(settings.ocr_engine, settings.tesseract_cmd)
        custom = CustomForgeryModel(MODEL_DIR, RESULTS_DIR)
        app.state.custom = custom
        app.state.ocr = ocr
        app.state.analyzer = Analyzer(sessions, vault, settings, ocr, custom)
        app.state.analyzer.start()
        # Warm in the background so missing model mirrors never block the landing page.
        ocr.preload()
        try:
            yield
        finally:
            app.state.analyzer.stop()
            engine.dispose()

    app = FastAPI(title="VERIFEX", description="Document forensics, certificate issuance and verification",
                  version="1.0", docs_url="/api/docs", openapi_url="/api/openapi.json",
                  redoc_url=None, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        details = ", ".join(".".join(str(part) for part in issue["loc"] if part != "body") for issue in exc.errors()[:5])
        return JSONResponse({"detail": f"Check the submitted values ({details})."}, status_code=422)

    @app.middleware("http")
    async def security_headers(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("X-Verifex-Request") != "1" or (
                request.headers.get("Origin") and request.headers["Origin"] != settings.public_url.rstrip("/")
            ):
                return JSONResponse({"detail": "Request origin was rejected."}, status_code=403)
            limit = MAX_BYTES + 256 * 1024
            length = request.headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > limit):
                return JSONResponse({"detail": "Request exceeds the upload limit."}, status_code=413)
            if length is None:
                return JSONResponse({"detail": "Content-Length is required for this operation."}, status_code=411)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "private, no-store, no-transform"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/health")
    def health(request: Request):
        return {"status": "ok", "demo_enabled": settings.demo_enabled,
                "model_loaded": request.app.state.custom.model is not None,
                "paddle_status": "ready" if request.app.state.ocr.paddle is not None else
                "warming" if request.app.state.ocr.warming else "unavailable"}

    @app.post("/api/auth/register", status_code=201)
    def register_user(request: Request, response: Response, payload: Registration, db: DB):
        if payload.email.endswith("@verifex.invalid"):
            raise HTTPException(422, "Choose another email address.")
        client_network = network(request)
        registrations = db.scalar(select(func.count()).select_from(Event).where(
            Event.kind == "registered", Event.network == client_network, Event.created_at >= now() - timedelta(hours=1)))
        if registrations >= 12:
            raise HTTPException(429, "Registration limit reached. Try again later.")
        user = User(id=identifier(), email=payload.email, name=payload.name, password=PASSWORDS.hash(payload.password))
        db.add(user)
        audit(db, "registered", "Verifier account created", user.id, network_id=client_network)
        try:
            new_session(request, response, db, user)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "This email is already registered.")
        return user_info(user)

    @app.post("/api/auth/login")
    def login(request: Request, response: Response, payload: Login, db: DB):
        user = login_attempt(request, db, payload)
        audit(db, "login_succeeded", "Signed in", user.id, network_id=network(request))
        new_session(request, response, db, user)
        return user_info(user)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, db: DB):
        token = request.cookies.get(COOKIE)
        if token:
            db.execute(delete(Session).where(Session.token == request.app.state.vault.token_hash(token)))
            db.commit()
        response.delete_cookie(COOKIE, httponly=True, samesite="lax", secure=settings.secure_cookie)
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(actor: Actor):
        return user_info(actor)

    @app.post("/api/analyses", status_code=202)
    def submit(request: Request, actor: Actor, db: DB, file: UploadFile = File(),
               certificate_ref: str = Form("", max_length=32), external_ai: bool = Form(False)):
        record = db.get(Certificate, certificate_ref.strip()) if certificate_ref.strip() else None
        if certificate_ref.strip() and record is None:
            raise HTTPException(404, "Certificate reference does not exist.")
        allowed = bool(record and (record.issuer_id == actor.id or actor.role == "admin"))
        data, mime, _ = upload_document(file)
        return add_job(request, db, actor, data, mime, safe_name(file.filename),
                       ref=record.ref if record else None, comparison=allowed, consent=external_ai)

    @app.get("/api/analyses")
    def history(actor: Actor, db: DB):
        rows = db.scalars(select(Analysis).options(defer(Analysis.source), defer(Analysis.report))
                          .where(Analysis.owner_id == actor.id).order_by(Analysis.created_at.desc()).limit(150))
        return [snapshot(row) for row in rows]

    @app.get("/api/analyses/{job}")
    def get_analysis(request: Request, actor: Actor, db: DB, job: str):
        row = analysis_owned(request, db, actor, job, report=True)
        report = get_report(request, row) if row.stage == "complete" else None
        if report:
            report.pop("model_layers", None)
        return {**snapshot(row), "preview": preview_for(request, row), "result": report}

    @app.get("/api/analyses/{job}/events")
    async def stream(request: Request, actor: Actor, db: DB, job: str):
        analysis_owned(request, db, actor, job)
        db.close()
        sessions = request.app.state.sessions
        session_id = request.state.session_hash

        async def events():
            cursor = 0
            sent_preview = False
            for tick in range(300):
                if await request.is_disconnected():
                    break
                with sessions() as current:
                    active = current.get(Session, session_id)
                    row = current.get(Analysis, job, options=[defer(Analysis.source), defer(Analysis.report)])
                    if not active or active.expires_at <= now() or row is None:
                        break
                    updates = row.progress[cursor:]
                    terminal = row.stage in TERMINAL
                    partial = preview_for(request, row) if not sent_preview else None
                for item in updates:
                    cursor += 1
                    yield f"id: {cursor}\ndata: {json.dumps(item)}\n\n"
                if partial:
                    sent_preview = True
                    yield f"event: preview\ndata: {json.dumps(partial)}\n\n"
                if terminal:
                    break
                if tick % 12 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(.5)
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache, no-transform"})

    @app.get("/api/analyses/{job}/pages/{page}")
    def page_preview(request: Request, actor: Actor, db: DB, job: str, page: int,
                     layer: Literal["uploaded", "original", "difference", "heatmap", "mask", "processed"] = "uploaded"):
        row = analysis_owned(request, db, actor, job, source=layer not in {"heatmap", "mask"})
        vault = request.app.state.vault
        if page < 1:
            raise HTTPException(404, "Page does not exist.")
        if layer in {"mask", "heatmap"}:
            report = get_report(request, row)
            if page > report["page_count"]:
                raise HTTPException(404, "Page does not exist.")
            overlays = report.get("model_layers") or []
            if len(overlays) >= page:
                return image_response(b64decode(overlays[page-1][layer], validate=True))
            model = request.app.state.custom
            if model.model and model.config["version"] == report["custom_model"].get("version"):
                _, source_pages = decode(vault.open(row.source, f"analysis:{job}"))
                _, regenerated = model.infer([source_pages[page-1]])
                return image_response(png(regenerated[0][layer]))
            raise HTTPException(409, "A model overlay is unavailable for this analysis.")
        _, pages = decode(vault.open(row.source, f"analysis:{job}"))
        if layer in {"original", "difference"}:
            if not row.compare_allowed or not row.certificate_ref:
                deny(request, db, actor, row.id, "Attempted to render an unavailable original")
            record = db.get(Certificate, row.certificate_ref)
            originals = decode(vault.open(record.original, f"certificate:{record.ref}"))[1]
            if page > len(originals):
                raise HTTPException(404, "Original page does not exist.")
            if layer == "original":
                return image_response(png(originals[page-1].image))
            if page <= len(pages):
                return image_response(png(compare_images(originals[page-1].image, pages[page-1].image, page)[1]))
        if page > len(pages):
            raise HTTPException(404, "Page does not exist.")
        source = pages[page-1]
        if layer == "processed":
            import cv2
            gray = cv2.cvtColor(source.image, cv2.COLOR_BGR2GRAY)
            return image_response(png(cv2.createCLAHE(2., (8, 8)).apply(gray)))
        return image_response(png(source.image))

    @app.post("/api/ai/custom-forgery-detection")
    def model_detection(request: Request, actor: Actor, db: DB, file: UploadFile = File()):
        rate_check(db, actor, "custom_inference", 25, 10)
        _, _, pages = upload_document(file)
        result, _ = request.app.state.custom.infer(pages)
        audit(db, "custom_inference", result["status"], actor.id, network_id=network(request))
        db.commit()
        return result

    @app.get("/api/ai/model-performance")
    def model_performance(request: Request):
        custom = request.app.state.custom
        return {"deployed": custom.config if custom.model is not None else None, "evaluation": custom.metrics}

    @app.post("/api/analyses/{job}/assistant")
    def assistant(request: Request, actor: Actor, db: DB, job: str, payload: Question):
        row = analysis_owned(request, db, actor, job, report=True)
        report = get_report(request, row)
        answer, meta = None, {"status": "consent_required"}
        if payload.external_ai and row.external_ai:
            rate_check(db, actor, "assistant_external", 20, 60)
            audit(db, "assistant_external", "Requested Groq analysis explanation", actor.id, row.id, network(request))
            db.commit()
            answer, meta = groq_service.explain(settings, provider_evidence(report), groq_service.Answer, payload.question)
        return {"answer": answer["answer"] if answer else local_answer(payload.question, report),
                "source": "Groq" if answer else "local", "engine": meta}

    @app.get("/api/analyses/{job}/report.pdf")
    def download_report(request: Request, actor: Actor, db: DB, job: str, signature: bool = False):
        row = analysis_owned(request, db, actor, job, report=True, source=True)
        report = get_report(request, row)
        vault = request.app.state.vault
        pages = decode(vault.open(row.source, f"analysis:{job}"))[1]
        pdf = render_report(snapshot(row), report, pages)
        signed = vault.report_sign(pdf)
        if signature:
            return Response(signed + "\n", media_type="text/plain", headers={
                "Content-Disposition": f'attachment; filename="verifex-{job}.sig"'})
        return Response(pdf, media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="verifex-{job}.pdf"',
            "X-Report-Signature": signed, "X-Report-Public-Key": vault.report_public_key})

    @app.post("/api/reports/verify")
    def verify_report(request: Request, file: UploadFile = File(), signature: str = Form(max_length=140)):
        data = read_upload(file)
        public = request.app.state.vault.report_public_key
        return {"signature_valid": data.startswith(b"%PDF-") and verify(public, data, signature.strip()),
                "public_key": public, "sha256": fingerprint(data)}

    @app.post("/api/certificates", status_code=201)
    def issue(request: Request, actor: Issuer, db: DB, file: UploadFile = File(),
              student_name: str = Form("", max_length=120), certificate_id: str = Form("", max_length=100),
              course: str = Form("", max_length=150)):
        data, _, _ = upload_document(file)
        metadata = {key: value.strip() for key, value in {"student_name": student_name,
                    "certificate_id": certificate_id, "course": course}.items() if value.strip()}
        record = register(db, request.app.state.vault, actor, data, metadata=metadata)
        audit(db, "certificate_issued", "Registered and signed an original", actor.id, record.ref, network(request))
        db.commit()
        return {**integrity(db, record), "private_metadata": metadata}

    @app.get("/api/certificates")
    def issued(request: Request, actor: Issuer, db: DB):
        query = select(Certificate).options(defer(Certificate.original)).where(Certificate.demo.is_(False))
        if actor.role != "admin":
            query = query.where(Certificate.issuer_id == actor.id)
        vault = request.app.state.vault
        return [{**integrity(db, row), "private_metadata": json.loads(vault.open(row.private_metadata, f"certificate-meta:{row.ref}"))
                 if row.private_metadata else {}} for row in db.scalars(query.order_by(Certificate.issued_at.desc()).limit(150))]

    @app.get("/api/certificates/{ref}/original")
    def certificate_original(request: Request, actor: Actor, db: DB, ref: str):
        record = own_certificate(request, db, actor, ref)
        original = request.app.state.vault.open(record.original, f"certificate:{record.ref}")
        return image_response(png(decode(original)[1][0].image))

    @app.post("/api/certificates/{ref}/revoke")
    def revoke(request: Request, actor: Issuer, db: DB, ref: str):
        record = own_certificate(request, db, actor, ref)
        if record.demo:
            raise HTTPException(409, "Demo issuance records are fixed.")
        if not record.revoked_at:
            record.revoked_at = now()
            audit(db, "certificate_revoked", "Issuer revoked the certificate", actor.id, record.ref, network(request))
            db.commit()
        return integrity(db, record)

    def public_record(db, ref):
        record = db.get(Certificate, ref, options=[defer(Certificate.original)])
        if not record:
            raise HTTPException(404, "No certificate matches this verification reference.")
        return record

    @app.get("/api/verify/{ref}")
    def verify_record(db: DB, ref: str):
        return integrity(db, public_record(db, ref))

    @app.post("/api/verify/{ref}")
    def verify_upload(request: Request, db: DB, ref: str, file: UploadFile = File()):
        record = public_record(db, ref)
        result = integrity(db, record, fingerprint(read_upload(file)))
        audit(db, "public_verification", "Matched file" if result["sha256_match"] else "File fingerprint differs",
              subject=ref, network_id=network(request))
        db.commit()
        return result

    @app.get("/api/verify/{ref}/qr.png")
    def qr(db: DB, ref: str):
        public_record(db, ref)
        return image_response(qr_png(f"{settings.public_url.rstrip('/')}/verify/{ref}"))

    @app.get("/api/dashboard")
    def dashboard(actor: Actor, db: DB):
        rows = db.execute(select(Analysis.id, Analysis.filename, Analysis.outcome, Analysis.stage, Analysis.created_at)
                          .where(Analysis.owner_id == actor.id).order_by(Analysis.created_at.desc())).all()
        counts = Counter(row.outcome for row in rows if row.outcome)
        dates = [(now() - timedelta(days=index)).date().isoformat() for index in reversed(range(7))]
        trends = {day: {"day": day, "analyzed": 0, "verified": 0} for day in dates}
        for row in rows:
            key = row.created_at.date().isoformat()
            if key in trends and row.stage == "complete":
                trends[key]["analyzed"] += 1
                trends[key]["verified"] += int(row.outcome == "verified")
        alerts_query = select(Event).where(Event.kind.in_(["access_denied", "suspicious_upload", "login_failed"]))
        if actor.role != "admin":
            alerts_query = alerts_query.where(Event.actor_id == actor.id)
        alerts = db.scalars(alerts_query.order_by(Event.created_at.desc()).limit(8))
        return {"counts": {"analyzed": sum(counts.values()), **counts,
                           "signature_failures": counts["modified"],
                           "institutions": db.scalar(select(func.count()).select_from(User)
                                                     .where(User.role == "institution", User.email != DEMO_EMAIL))},
                "trends": list(trends.values()),
                "recent": [{**row._asdict(), "created_at": timestamp(row.created_at)} for row in rows[:6]],
                "alerts": [event_row(item) for item in alerts]}

    @app.get("/api/security")
    def security(actor: Actor, db: DB):
        query = select(Event)
        if actor.role != "admin":
            query = query.where(Event.actor_id == actor.id)
        events = list(db.scalars(query.order_by(Event.created_at.desc()).limit(150)))
        counts = Counter(item.kind for item in events)
        failures = Counter(item.network for item in events if item.kind == "login_failed")
        verification = Counter(item.network for item in events if item.kind == "public_verification")
        uploads = Counter(item.actor_id for item in events if item.kind == "suspicious_upload")
        signals = {"repeated_login_sources": sum(v >= 3 for v in failures.values()),
                   "high_verification_sources": sum(v >= 5 for v in verification.values()),
                   "repeated_suspicious_uploaders": sum(v >= 2 for v in uploads.values())}
        return {"events": [event_row(item) for item in events], "counts": counts, "signals": signals}

    @app.post("/api/security/summary")
    def security_summary(request: Request, actor: Admin, db: DB, payload: Consent):
        if not payload.external_ai:
            raise HTTPException(422, "Authorize external processing to request an AI summary.")
        rate_check(db, actor, "security_summary_external", 10, 60)
        evidence = security(actor, db)
        evidence.pop("events")
        audit(db, "security_summary_external", "Requested an aggregate security summary", actor.id,
              network_id=network(request))
        db.commit()
        answer, meta = groq_service.explain(settings, evidence, groq_service.Answer, "Summarize these security event counts.")
        return {"answer": answer["answer"] if answer else "Local totals: " + ", ".join(
            f"{key.replace('_', ' ')} {value}" for key, value in evidence["counts"].items()),
                "source": "Groq" if answer else "local", "engine": meta}

    @app.get("/api/admin/users")
    def users(_actor: Admin, db: DB):
        return [user_info(item) for item in db.scalars(select(User).where(User.email != DEMO_EMAIL).order_by(User.email).limit(250))]

    @app.post("/api/admin/users/{user_id}/role")
    def change_role(request: Request, actor: Admin, db: DB, user_id: str, payload: InstitutionChange):
        user = db.get(User, user_id)
        if not user or user.email == DEMO_EMAIL or user.role == "admin":
            raise HTTPException(404, "A manageable account was not found.")
        if user.role != payload.role:
            if payload.role == "institution" and not user.signing_key:
                user.signing_key, user.public_key = request.app.state.vault.issuer_keys(user.id)
            user.role = payload.role
            audit(db, "role_changed", f"Role changed to {payload.role}", actor.id, user.id, network(request))
            db.commit()
        return user_info(user)

    def demo_record(db):
        if not settings.demo_enabled:
            raise HTTPException(404, "The demo lab is disabled.")
        return db.scalar(select(Certificate).where(Certificate.demo.is_(True),
                                                    Certificate.fingerprint == fingerprint(demo_pdf("genuine"))).limit(1))

    @app.get("/api/demo")
    def demo_info(actor: Actor, db: DB):
        record = demo_record(db)
        return {"restricted_ref": record.ref, "actor_role": actor.role, "stages": STAGES,
                "failure_case": (RESULTS_DIR / "failure.png").is_file()}

    @app.post("/api/demo/{scenario}", status_code=202)
    def run_demo(request: Request, actor: Actor, db: DB,
                 scenario: Literal["genuine", "modified", "unknown", "failure", "reset"], payload: Consent):
        record = demo_record(db)
        if scenario == "reset":
            db.execute(delete(Analysis).where(Analysis.owner_id == actor.id, Analysis.demo.is_(True)))
            audit(db, "demo_reset", "Cleared demo runs for this account", actor.id, network_id=network(request))
            db.commit()
            return {"ok": True}
        if scenario == "failure":
            if not (RESULTS_DIR / "failure.png").is_file():
                raise HTTPException(404, "A recorded model failure case is unavailable.")
            data, mime = (RESULTS_DIR / "failure.png").read_bytes(), "image/png"
            fixture = RESULTS_DIR / "failure-original.png"
            digest = fingerprint(fixture.read_bytes() if fixture.is_file() else data)
            record = db.scalar(select(Certificate).where(Certificate.demo.is_(True), Certificate.fingerprint == digest))
        else:
            data, mime = demo_pdf(scenario), "application/pdf"
        compare = record is not None and scenario in {"genuine", "modified", "failure"}
        return add_job(request, db, actor, data, mime, f"demo-{scenario}." + ("png" if scenario == "failure" else "pdf"),
                       ref=record.ref if compare else None, comparison=compare, consent=payload.external_ai, demo=True)

    return app


app = create_app()
