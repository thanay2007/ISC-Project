import json
import time
from base64 import urlsafe_b64encode
from dataclasses import replace
from io import BytesIO
from secrets import token_bytes, token_urlsafe

import cv2
import numpy as np
import pymupdf
import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from reportlab.pdfgen import canvas

from backend.verifex import gemini_service, groq_service
from backend.verifex.analysis_orchestrator import assessment_for, outcome_for
from backend.verifex.config import Settings
from backend.verifex.crypto_service import Vault, canonical, fingerprint, verify
from backend.verifex.db import Analysis
from backend.verifex.documents import Page, decode
from backend.verifex.gemini_service import GeminiResult
from backend.verifex.groq_service import Explanation
from backend.verifex.issuance import demo_pdf
from backend.verifex.main import create_app
from backend.verifex.ocr_service import OCR, compare_fields, fields_for
from backend.verifex.opencv_service import compare_images

WRITE = {"X-Verifex-Request": "1"}
PASSWORD = "local-test-password!"


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}",
                    app_secret=token_urlsafe(48), encryption_key=urlsafe_b64encode(token_bytes(32)).decode(),
                    public_url="http://testserver", secure_cookie=False, demo_enabled=True,
                    ocr_engine="pdf", gemini_key="", gemini_model="", groq_key="", groq_model="",
                    clerk_publishable_key="", clerk_secret_key="",
                    admin_email="admin@example.test", admin_password=PASSWORD)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as browser:
        yield browser


def signup(client, name):
    result = client.post("/api/auth/register", json={
        "name": name, "email": f"{name}@example.test", "password": PASSWORD,
    }, headers=WRITE)
    assert result.status_code == 201, result.text
    assert "HttpOnly" in result.headers["Set-Cookie"]
    assert result.json()["role"] == "verifier"
    return result.json()


def queued(client, scenario):
    response = client.post(f"/api/demo/{scenario}", json={}, headers=WRITE)
    assert response.status_code == 202, response.text
    return response.json()["id"]


def finished(client, job):
    for _ in range(200):
        response = client.get(f"/api/analyses/{job}")
        assert response.status_code == 200, response.text
        state = response.json()
        if state["stage"] in {"complete", "failed"}:
            assert state["stage"] == "complete", state
            return state
        time.sleep(.05)
    pytest.fail("Analysis never reached a terminal state")


def pdf_file(data):
    return {"file": ("certificate.pdf", data, "application/pdf")}


def test_guest_workspace_is_private_and_cannot_use_admin_routes(client):
    assert client.post("/api/auth/guest", json={}).status_code == 403
    response = client.post("/api/auth/guest", json={}, headers=WRITE)
    assert response.status_code == 200
    guest = response.json()
    assert guest["role"] == "guest"
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert client.post("/api/auth/guest", json={}, headers=WRITE).json()["id"] == guest["id"]
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/certificates").status_code == 403
    job = queued(client, "unknown")
    assert client.get(f"/api/analyses/{job}").status_code == 200

    client.cookies.clear()
    other = client.post("/api/auth/guest", json={}, headers=WRITE).json()
    assert other["id"] != guest["id"]
    assert client.get("/api/analyses").json() == []
    assert client.get(f"/api/analyses/{job}").status_code == 403


def test_local_admin_login(settings):
    from base64 import b64encode

    publishable_key = "pk_test_" + b64encode(b"test.clerk.accounts.dev$").decode()
    local = replace(settings, public_url="http://localhost:3000", clerk_publishable_key=publishable_key,
                    clerk_secret_key="test-secret")
    credentials = {"username": "admin", "password": "admin123"}
    endpoint = "/api/auth/admin/login"
    with TestClient(create_app(local), client=("127.0.0.1", 50000)) as browser:
        browser.cookies.set("__session", "unused-clerk-cookie")
        assert browser.post(endpoint, json={**credentials, "password": "wrong"}, headers=WRITE).status_code == 401
        result = browser.post(endpoint, json=credentials, headers=WRITE)
        assert result.status_code == 200
        assert "HttpOnly" in result.headers["Set-Cookie"]
        assert browser.get("/api/admin/users").status_code == 200
        browser.post("/api/auth/logout", json={}, headers=WRITE)
        browser.cookies.delete("__session")
        assert browser.get("/api/admin/users").status_code == 401

    with TestClient(create_app(local), client=("192.0.2.1", 50000)) as browser:
        assert browser.post(endpoint, json=credentials, headers=WRITE).status_code == 404
    with TestClient(create_app(settings), client=("127.0.0.1", 50000)) as browser:
        assert browser.post(endpoint, json=credentials, headers=WRITE).status_code == 404


def test_cryptographic_primitives():
    vault = Vault(token_bytes(32), token_urlsafe(48))
    assert fingerprint(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    sealed = vault.seal(b"original", "certificate:A")
    assert sealed != vault.seal(b"original", "certificate:A")
    assert vault.open(sealed, "certificate:A") == b"original"
    with pytest.raises(InvalidTag):
        vault.open(sealed, "certificate:B")
    with pytest.raises(InvalidTag):
        vault.open(sealed[:-1] + bytes([sealed[-1] ^ 1]), "certificate:A")
    secret, public = vault.issuer_keys("issuer")
    signature = vault.issuer_sign("issuer", secret, b"credential")
    assert verify(public, b"credential", signature)
    assert not verify(public, b"credential!", signature)


def test_real_pdf_text_and_pixel_comparison():
    mime, before = decode(demo_pdf("genuine"))
    _, after = decode(demo_pdf("modified"))
    assert mime == "application/pdf"
    ocr = OCR("pdf")
    lines_a, engine, _ = ocr.extract(before[0])
    lines_b, _, _ = ocr.extract(after[0])
    assert engine == "PDF text layer"
    fields_a, fields_b = (fields_for([{**line, "page": 1} for line in lines]) for lines in (lines_a, lines_b))
    assert fields_a["student_name"]["value"] == "Arlen Cloudfell"
    difference = next(item for item in compare_fields(fields_a, fields_b) if item["field"] == "grade")
    assert difference["original"] == "B"
    assert difference["uploaded"] == "A+"
    identical, _ = compare_images(before[0].image, before[0].image, 1)
    assert identical["changed_fraction"] == 0
    changed, layer = compare_images(before[0].image, after[0].image, 1)
    assert 0 < changed["changed_fraction"] < .02
    assert changed["regions"] and layer[:, :, 3].any()


def test_provider_response_schemas():
    response = GeminiResult.model_validate_json(json.dumps({
        "document_type": "certificate", "extracted_fields": {"grade": "B"},
        "observations": [{"region": "grade", "page": 1, "severity": "medium", "finding": "Different text baseline"}],
        "manual_review_recommended": True,
    }))
    assert response.extracted_fields.grade == "B"
    with pytest.raises(ValidationError):
        GeminiResult.model_validate_json('{"observations":[{"region":"arbitrary coordinates"}]}')
    assert Explanation.model_validate_json(
        '{"summary":"Recorded","detailed":"Recorded","presentation":"Recorded","recommendation":"Review"}'
    ).summary == "Recorded"
    with pytest.raises(ValidationError):
        Explanation.model_validate_json('{"summary":"Missing evidence"}')


def test_provider_failure_paths(settings, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise TimeoutError
    monkeypatch.setattr(gemini_service.genai, "Client", unavailable)
    monkeypatch.setattr(groq_service, "Groq", unavailable)
    configured = replace(settings, gemini_key="test", gemini_model="test-model", groq_key="test", groq_model="test-model")
    assert gemini_service.analyze(configured, [])[1]["status"] == "failed"
    assert groq_service.explain(configured, {})[1]["status"] == "failed"


def test_demo_access_and_local_report(client):
    assert client.get("/api/analyses").status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@b.test", "password": "x"}).status_code == 403
    assert client.post("/api/auth/login", json={"email": "a@b.test", "password": "x"},
                       headers={**WRITE, "Origin": "https://different.test"}).status_code == 403
    signup(client, "verifier")
    reference = client.get("/api/demo").json()["restricted_ref"]
    denied = client.get(f"/api/certificates/{reference}/original")
    assert denied.status_code == 403
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/security").json()["counts"]["access_denied"] == 2
    job = queued(client, "genuine")
    state = finished(client, job)
    result = state["result"]
    assert result["outcome"] == "verified"
    assert result["crypto"]["sha256_match"] and result["crypto"]["signature_valid"]
    assert result["engines"]["Gemini"]["status"] == "not_configured"
    assert result["assessment"] == {"label": "Original", "confidence": 100}
    assert result["explanation"]["source"] == "local"
    if result["custom_model"]["status"] == "complete":
        overlay = client.get(f"/api/analyses/{job}/pages/1?layer=heatmap")
        assert overlay.status_code == 200 and overlay.content.startswith(b"\x89PNG")
        assert "model_layers" not in result
    events = client.get(f"/api/analyses/{job}/events").text
    assert "Extracting text" in events and '"stage": "complete"' in events
    unknown = finished(client, queued(client, "unknown"))["result"]
    assert unknown["assessment"]["label"] in {"Fake", "Original"}
    assert 50 <= unknown["assessment"]["confidence"] < 100
    assert unknown["crypto"]["record_status"] == "unknown"
    assert unknown["engines"]["Groq"]["status"] == "not_configured"
    assert unknown["explanation"]["source"] == "local"
    modified_job = queued(client, "modified")
    changed = finished(client, modified_job)["result"]
    assert changed["outcome"] == "modified"
    assert changed["assessment"] == {"label": "Fake", "confidence": 100}
    assert changed["crypto"]["record_signature_valid"]
    assert changed["crypto"]["sha256_match"] is False and changed["crypto"]["signature_valid"] is False
    assert changed["fields"]["grade"]["value"] == "A+"
    assert "comparison" not in changed and "original_ocr" not in changed
    layer = client.get(f"/api/analyses/{modified_job}/pages/1?layer=difference")
    assert layer.status_code == 422
    reply = client.post(f"/api/analyses/{modified_job}/assistant", json={"question": "Which fields were extracted?"}, headers=WRITE)
    assert "Grade: A+" in reply.json()["answer"]
    report = client.get(f"/api/analyses/{modified_job}/report.pdf")
    with pymupdf.open(stream=report.content, filetype="pdf") as pdf:
        assert "Forensic report" in pdf[0].get_text()
        assert "Assessment: Fake | 100/100 confidence" in pdf[0].get_text()
    sig = client.get(f"/api/analyses/{modified_job}/report.pdf?signature=true").text.strip()
    for pdf, expected in ((report.content, True), (report.content + b"changed", False)):
        result = client.post("/api/reports/verify", files=pdf_file(pdf), data={"signature": sig}, headers=WRITE)
        assert result.json()["signature_valid"] is expected
    client.post("/api/auth/logout", json={}, headers=WRITE)
    signup(client, "other")
    assert client.get(f"/api/analyses/{modified_job}").status_code == 403
    assert client.post(f"/api/analyses/{modified_job}/reanalyze", json={}, headers=WRITE).status_code == 403
    assert client.get(f"/api/analyses/{modified_job}/report.pdf").status_code == 403


def test_upload_checks_image_bytes_and_accepts_still_webp(client):
    signup(client, "image-upload")
    image = Image.new("RGB", (50, 40), "white")
    headers = WRITE
    for format_name in ("WEBP", "BMP"):
        stream = BytesIO()
        image.save(stream, format_name)
        response = client.post("/api/analyses", files={"file": ("document.png", stream.getvalue(), "image/png")},
                               headers=headers)
        if format_name == "WEBP":
            assert response.status_code == 202
            assert response.json()["mime"] == "image/webp"
        else:
            assert response.status_code == 422
            assert "BMP image" in response.json()["detail"]

    animated = BytesIO()
    image.save(animated, "PNG", save_all=True, append_images=[Image.new("RGB", image.size, "black")], duration=100)
    response = client.post("/api/analyses", files={"file": ("animated.png", animated.getvalue(), "image/png")},
                           headers=headers)
    assert response.status_code == 422
    assert "multiple frames" in response.json()["detail"]


def test_utility_bill_analysis_uses_both_providers_automatically(client, monkeypatch):

    data = BytesIO()
    bill = canvas.Canvas(data)
    for index, line in enumerate(("Electricity Bill", "Account number: 123456", "Amount due: 250.00",
                                  "Due date: 12 December 2026", "Service address: 10 Example Street")):
        bill.drawString(72, 750 - index * 29, line)
    bill.save()
    files = {"file": ("electricity-bill.pdf", data.getvalue(), "application/pdf")}
    assert client.post("/api/auth/guest", json={}, headers=WRITE).status_code == 200
    assert client.post("/api/analyses", files=files, headers=WRITE).status_code == 403
    signup(client, "billtester")

    calls = []
    gemini_observations = []

    def gemini(_settings, pages):
        assert len(pages) == 1
        calls.append("Gemini")
        return {"document_type": "Electricity bill", "extracted_fields": {"amount_due": "250.00"},
                "observations": gemini_observations, "visual_assessment": "likely_edited" if gemini_observations else "inconclusive",
                "additional_fields": [{"label": "Meter reading", "value": "1250 kWh"}]}, {"status": "contributed"}

    def groq(_settings, evidence, schema=Explanation, question=None):
        assert evidence["ocr"]["fields"]["account_number"] == "123456"
        assert evidence["gemini"]["document_type"] == "Electricity bill"
        assert evidence["assessment"]["label"] == ("Fake" if gemini_observations else "Original")
        assert evidence["ocr"]["gemini_agreement"] == {"amount_due": True}
        if question:
            calls.append("Groq assistant")
            return {"answer": "The electricity bill totals 250.00."}, {"status": "contributed"}
        calls.append("Groq")
        return dict.fromkeys(("summary", "detailed", "presentation", "recommendation"), "Electricity bill findings."), {"status": "contributed"}

    monkeypatch.setattr(gemini_service, "analyze", gemini)
    monkeypatch.setattr(groq_service, "explain", groq)
    monkeypatch.setattr(client.app.state.custom, "infer", lambda _: ({
        "status": "complete", "name": "Fixture model", "version": "test",
        "predicted_class": "visual_tamper_signal", "risk_score": .4725, "threshold": .4644,
        "document_assessment": {"score": .45, "threshold": .55},
    }, []))
    submitted = client.post("/api/analyses", files=files, data={"external_ai": "false"}, headers=WRITE)
    assert submitted.status_code == 202
    job = submitted.json()["id"]
    state = finished(client, job)
    result = state["result"]
    assert result["fields"]["amount_due"]["value"] == "250.00"
    assert result["crypto"]["record_status"] == "unknown"
    assert state["verdict"] == result["assessment"]["label"]
    assert result["assessment"] == {"label": "Original", "confidence": 60}
    assert result["field_agreement"] == {"amount_due": True}
    assert result["custom_model"]["predicted_class"] == "visual_tamper_signal"
    assert "limited evidence" in result["explanation"]["summary"]

    # Simulate a report saved with the old threshold-based decision.
    with client.app.state.sessions.begin() as db:
        row = db.get(Analysis, job)
        vault = client.app.state.vault
        saved = json.loads(vault.open(row.report, f"report:{job}"))
        saved["outcome"] = row.outcome = "fake"
        del saved["custom_model"]["document_assessment"]
        saved["explanation"]["summary"] = "Fake at 51/100 confidence"
        row.report = vault.seal(canonical(saved), f"report:{job}")
    archived = client.get(f"/api/analyses/{job}").json()
    assert archived["verdict"] is None
    assert archived["result"]["assessment"] == {"label": None, "confidence": None}
    assert "no usable authenticity score" in archived["result"]["explanation"]["summary"]
    pdf_response = client.get(f"/api/analyses/{job}/report.pdf")
    with pymupdf.open(stream=pdf_response.content, filetype="pdf") as pdf:
        assert "Assessment unavailable" in pdf[0].get_text()
        assert "51/100" not in pdf[0].get_text()
    history = client.get("/api/analyses").json()
    assert history[0]["verdict"] is None
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["counts"]["original"] == 0
    assert dashboard["counts"]["fake"] == 0
    gemini_observations.append({"page": 1, "region": "amount_due", "severity": "high",
                                "edit_signal": "altered_text", "finding": "The amount has mismatched inserted digits."})
    retry = client.post(f"/api/analyses/{job}/reanalyze", json={}, headers=WRITE)
    assert retry.status_code == 202
    new_job = retry.json()["id"]
    assert job != new_job
    checked = finished(client, new_job)
    assert checked["verdict"] == "Fake"
    assert checked["result"]["crypto"]["uploaded_sha256"] == result["crypto"]["uploaded_sha256"]
    reply = client.post(f"/api/analyses/{new_job}/assistant", json={"question": "What is the total?"}, headers=WRITE)
    assert reply.json()["source"] == "Groq"
    assert calls == ["Gemini", "Groq", "Gemini", "Groq", "Groq assistant"]


def test_low_confidence_scan_retries_ocr(monkeypatch):
    ocr = OCR("auto")
    ocr.paddle = object()
    calls = []
    box = [0., 0., 1., .2]

    def recognize(image):
        calls.append(image)
        return ([{"text": "Acc 00012", "confidence": .48, "box": box}] if len(calls) == 1 else
                [{"text": "Account number: 00012", "confidence": .96, "box": box}])

    monkeypatch.setattr(ocr, "_paddle_lines", recognize)
    image = np.full((80, 100, 3), 200, dtype=np.uint8)
    lines, engine, _ = ocr.extract(Page(image, []))
    assert len(calls) == 2 and not np.array_equal(calls[0], calls[1])
    assert engine == "PaddleOCR"
    assert lines[0]["text"] == "Account number: 00012"


def test_standalone_visual_assessment_can_flag_an_edit():
    crypto = {"record_status": "unknown", "sha256_match": None, "signature_valid": None,
              "record_signature_valid": None}
    custom = {"document_assessment": {"score": .9, "threshold": .6}}
    outcome = outcome_for(crypto, custom)
    assert outcome == "visual_fake"
    assert assessment_for({"outcome": outcome, "custom_model": custom}) == {"label": "Fake", "confidence": 86}
    assert outcome_for(crypto, custom, {"visual_assessment": "no_clear_edit"}) == "visual_fake"
    ambiguous = {"visual_assessment": "likely_edited", "observations": [{"severity": "high", "edit_signal": "none"}]}
    assert outcome_for(crypto, {}, ambiguous) == "manual_review"
    concrete = {"visual_assessment": "likely_edited", "observations": [{"severity": "high", "edit_signal": "pasted_content"}]}
    assert outcome_for(crypto, {}, concrete) == "visual_fake"
    verified = {**crypto, "record_status": "registered", "sha256_match": True, "signature_valid": True}
    assert outcome_for(verified, custom, concrete) == "verified"


def test_issuance_revocation_and_qr(client):
    signup(client, "verifier")
    login = client.post("/api/auth/login", json={"email": "admin@example.test", "password": PASSWORD}, headers=WRITE)
    assert login.json()["role"] == "admin"
    people = client.get("/api/admin/users").json()
    candidate = next(item for item in people if item["email"] == "verifier@example.test")
    promoted = client.post(f"/api/admin/users/{candidate['id']}/role", json={"role": "institution"}, headers=WRITE)
    assert promoted.json()["role"] == "institution"
    client.post("/api/auth/login", json={"email": "verifier@example.test", "password": PASSWORD}, headers=WRITE)
    data = demo_pdf("unknown")
    issued = client.post("/api/certificates", files=pdf_file(data), data={"student_name": "Fictional Student"}, headers=WRITE)
    assert issued.status_code == 201, issued.text
    reference = issued.json()["certificate_ref"]
    url = f"/api/verify/{reference}"
    assert client.get("/api/certificates").json()[0]["private_metadata"]["student_name"] == "Fictional Student"
    assert "private_metadata" not in client.get(url).json()
    assert client.get(url).json()["record_signature_valid"]
    qr = client.get(url + "/qr.png")
    raster = cv2.imdecode(np.frombuffer(qr.content, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert cv2.QRCodeDetector().detectAndDecode(raster)[0] == f"http://testserver/verify/{reference}"
    result = client.post(url, files=pdf_file(data), headers=WRITE).json()
    assert result["signature_valid"] and result["sha256_match"]
    assert client.post(f"/api/certificates/{reference}/revoke", json={}, headers=WRITE).json()["record_status"] == "revoked"
    assert client.get(url).json()["record_status"] == "revoked"
    assert client.post("/api/certificates", files=pdf_file(b"wrong bytes"), headers=WRITE).status_code == 422


def test_rate_limit_and_validation(client):
    for _ in range(6):
        response = client.post("/api/auth/login", json={"email": "blocked@example.test", "password": "bad"}, headers=WRITE)
        assert response.status_code == 401
    assert client.post("/api/auth/login", json={"email": "blocked@example.test", "password": "bad"}, headers=WRITE).status_code == 429
    result = client.post("/api/auth/register", json={"email": "not an email", "password": "private", "name": "Tester"}, headers=WRITE)
    assert result.status_code == 422
    assert "private" not in result.text


def test_model_artifact_inference(client):
    signup(client, "modeltester")
    result = client.post("/api/ai/custom-forgery-detection", files=pdf_file(demo_pdf("modified")), headers=WRITE)
    assert result.status_code == 200
    if not client.get("/api/health").json()["model_loaded"]:
        pytest.skip("Optional PyTorch runtime is unavailable")
    body = result.json()
    assert body["status"] == "complete"
    assert 0 <= body["risk_score"] <= 1
    assert 0 <= body["document_assessment"]["score"] <= 1
    assert 0 < body["document_assessment"]["threshold"] < 1
    assert body["version"].startswith("mixed-unet-v3+")
    assert body["inference_ms"] > 0
    performance = client.get("/api/ai/model-performance").json()
    assert performance["evaluation"]["test"]["count"] == 3059
    assert performance["evaluation"]["groups"]["doctamper"]["false_positive_rate"] is None
    failure = finished(client, queued(client, "failure"))["result"]
    assert failure["demo_case"]["label"] != failure["demo_case"]["prediction"]
    assert failure["crypto"]["sha256_match"] is (failure["demo_case"]["label"] == 0)
