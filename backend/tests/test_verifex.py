import json
import time
from base64 import urlsafe_b64encode
from dataclasses import replace
from secrets import token_bytes, token_urlsafe

import cv2
import numpy as np
import pymupdf
import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.verifex import gemini_service, groq_service
from backend.verifex.config import Settings
from backend.verifex.crypto_service import Vault, fingerprint, verify
from backend.verifex.documents import decode
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


def queued(client, scenario, consent=False):
    response = client.post(f"/api/demo/{scenario}", json={"external_ai": consent}, headers=WRITE)
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
    assert result["engines"]["Gemini"]["status"] == "consent_required"
    assert result["explanation"]["source"] == "local"
    if result["custom_model"]["status"] == "complete":
        overlay = client.get(f"/api/analyses/{job}/pages/1?layer=heatmap")
        assert overlay.status_code == 200 and overlay.content.startswith(b"\x89PNG")
        assert "model_layers" not in result
    events = client.get(f"/api/analyses/{job}/events").text
    assert "Extracting text" in events and '"stage": "complete"' in events
    unknown = finished(client, queued(client, "unknown", consent=True))["result"]
    assert unknown["outcome"] in {"unverified", "manual_review", "suspicious"}
    assert unknown["crypto"]["record_status"] == "unknown"
    assert unknown["engines"]["Groq"]["status"] == "not_configured"
    assert unknown["explanation"]["source"] == "local"
    modified_job = queued(client, "modified")
    changed = finished(client, modified_job)["result"]
    assert changed["outcome"] == "modified"
    assert changed["crypto"]["record_signature_valid"]
    assert changed["crypto"]["sha256_match"] is False and changed["crypto"]["signature_valid"] is False
    assert next(item for item in changed["differences"] if item["field"] == "grade")["uploaded"] == "A+"
    layer = client.get(f"/api/analyses/{modified_job}/pages/1?layer=difference")
    assert layer.status_code == 200 and layer.content.startswith(b"\x89PNG")
    reply = client.post(f"/api/analyses/{modified_job}/assistant", json={"question": "Which fields changed?"}, headers=WRITE)
    assert "Grade: B" in reply.json()["answer"]
    report = client.get(f"/api/analyses/{modified_job}/report.pdf")
    with pymupdf.open(stream=report.content, filetype="pdf") as pdf:
        assert "Forensic report" in pdf[0].get_text()
    sig = client.get(f"/api/analyses/{modified_job}/report.pdf?signature=true").text.strip()
    for pdf, expected in ((report.content, True), (report.content + b"changed", False)):
        result = client.post("/api/reports/verify", files=pdf_file(pdf), data={"signature": sig}, headers=WRITE)
        assert result.json()["signature_valid"] is expected
    client.post("/api/auth/logout", json={}, headers=WRITE)
    signup(client, "other")
    assert client.get(f"/api/analyses/{modified_job}").status_code == 403
    assert client.get(f"/api/analyses/{modified_job}/report.pdf").status_code == 403


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
    assert body["version"].startswith("synthetic-unet-v1+")
    assert body["inference_ms"] > 0
    performance = client.get("/api/ai/model-performance").json()
    assert performance["evaluation"]["test"]["count"] == 300
    failure = finished(client, queued(client, "failure"))["result"]
    assert failure["demo_case"]["label"] != failure["demo_case"]["prediction"]
    assert failure["crypto"]["sha256_match"] is (failure["demo_case"]["label"] == 0)
