from base64 import urlsafe_b64encode
from dataclasses import replace
from time import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from backend.tests.test_verifex import WRITE, settings
from backend.verifex import clerk_auth
from backend.verifex.main import create_app


def test_clerk_signup_and_api_permissions(settings, monkeypatch):
    domain = "test.clerk.accounts.dev"
    issuer = f"https://{domain}"
    settings = replace(settings, clerk_publishable_key="pk_test_" + urlsafe_b64encode(f"{domain}$".encode()).decode(),
                       clerk_secret_key="test-secret", admin_email="owner@example.test", admin_password="")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key()))
    monkeypatch.setattr(clerk_auth, "verifier", lambda key: (issuer, keys))
    profiles = []

    def profile(_settings, subject):
        profiles.append(subject)
        email = "owner@example.test" if subject == "user_owner" else "reader@example.test"
        status = "unverified" if subject == "user_unverified" else "verified"
        return {"primary_email_address_id": "email_1", "first_name": "Example",
                "email_addresses": [{"id": "email_1", "email_address": email, "verification": {"status": status}}]}

    monkeypatch.setattr(clerk_auth, "load_profile", profile)

    def token(subject, **overrides):
        claims = {"iss": issuer, "sub": subject, "sid": "sess_example", "azp": settings.public_url,
                  "exp": int(time()) + 60, "nbf": int(time()) - 1, **overrides}
        return jwt.encode(claims, private_key, algorithm="RS256")

    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health").json()
        assert health["clerk_publishable_key"] == settings.clerk_publishable_key
        assert settings.clerk_secret_key not in str(health)
        assert client.post("/api/auth/register", headers=WRITE, json={
            "name": "Example", "email": "legacy@example.test", "password": "sample-password-321",
        }).status_code == 403
        for changes in ({"azp": "https://other.example"}, {"exp": int(time()) - 1}, {"sts": "pending"}):
            client.cookies.set("__session", token("user_reader", **changes))
            assert client.get("/api/auth/me").status_code == 401
        assert profiles == []

        client.cookies.set("__session", token("user_unverified"))
        assert client.get("/api/auth/me").status_code == 403
        client.cookies.set("__session", token("user_reader"))
        reader = client.post("/api/auth/guest", headers=WRITE, json={}).json()
        assert reader["role"] == "verifier"
        assert client.get("/api/auth/me").json()["id"] == reader["id"]
        assert profiles.count("user_reader") == 1
        assert client.get("/api/admin/users").status_code == 403
        job = client.post("/api/demo/unknown", headers=WRITE, json={"external_ai": False}).json()["id"]
        assert client.get(f"/api/analyses/{job}/events").status_code == 200

        client.cookies.set("__session", token("user_collision"))
        assert client.get("/api/auth/me").status_code == 409
        client.cookies.set("__session", token("user_owner"))
        assert client.get("/api/auth/me").json()["role"] == "admin"
        assert client.get("/api/admin/users").status_code == 200
        assert client.get(f"/api/analyses/{job}").status_code == 403
