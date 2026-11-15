import re
from base64 import urlsafe_b64decode
from functools import lru_cache

import jwt
import requests
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import User, identifier


@lru_cache(maxsize=4)
def verifier(publishable_key):
    match = re.fullmatch(r"pk_(?:test|live)_([A-Za-z0-9_=-]+)", publishable_key)
    if not match:
        raise ValueError("Invalid CLERK_PUBLISHABLE_KEY")
    encoded = match[1]
    domain = urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("ascii")
    if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\$", domain):
        raise ValueError("Invalid Clerk Frontend API domain")
    issuer = f"https://{domain[:-1]}"
    return issuer, jwt.PyJWKClient(issuer + "/.well-known/jwks.json", timeout=5)


def verify_session(settings, token):
    origin, keys = verifier(settings.clerk_publishable_key)
    try:
        if len(token) > 8192 or jwt.get_unverified_header(token).get("alg") != "RS256":
            raise jwt.InvalidTokenError()
        key = keys.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], issuer=origin,
                            options={"require": ["iss", "exp", "nbf", "sub", "sid", "azp"], "verify_aud": False})
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, "Could not reach Clerk to verify the session.") from None
    except jwt.PyJWTError:
        raise HTTPException(401, "Your Clerk session could not be verified.") from None
    if (claims["azp"] != settings.public_url.rstrip("/") or claims.get("sts", "active") != "active"
            or not re.fullmatch(r"user_[A-Za-z0-9]{1,240}", claims["sub"])
            or not isinstance(claims["sid"], str) or not claims["sid"].startswith("sess_")):
        raise HTTPException(401, "Your Clerk session could not be verified.")
    return claims


def load_profile(settings, subject):
    try:
        response = requests.get(f"https://api.clerk.com/v1/users/{subject}", timeout=8, allow_redirects=False,
                                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"})
        response.raise_for_status()
        profile = response.json()
    except (requests.RequestException, ValueError):
        raise HTTPException(503, "Could not load your Clerk account.") from None
    if profile.get("id") != subject or profile.get("banned") or profile.get("locked"):
        raise HTTPException(403, "This Clerk account cannot use the workspace.")
    return profile


def resolve_user(settings, vault, db, subject, unusable_password):
    linked = select(User).where(User.clerk_subject == subject)
    user = db.scalar(linked)
    if user is not None:
        return user
    profile = load_profile(settings, subject)
    primary = next((item for item in profile.get("email_addresses", [])
                    if item.get("id") == profile.get("primary_email_address_id")), {})
    email = (primary.get("email_address") or "").strip().lower()
    if (len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
            or email.endswith("@verifex.invalid") or (primary.get("verification") or {}).get("status") != "verified"):
        raise HTTPException(403, "Verify your primary email address in Clerk to use the workspace.")

    google_ids = {account.get("provider_user_id") for account in profile.get("external_accounts", [])
                  if account.get("provider") in {"google", "oauth_google"}
                  and (account.get("verification") or {}).get("status") == "verified"}
    user = db.scalar(select(User).where(User.email == email))
    if user and (user.clerk_subject or not (user.google_subject and user.google_subject in google_ids)):
        raise HTTPException(409, "This email already belongs to a VERIFEX account. Contact your administrator to link it.")
    if user is None:
        name = " ".join(profile.get(field) or "" for field in ("first_name", "last_name")).strip()
        user = User(id=identifier(), email=email, name=name[:120] or email.split("@", 1)[0][:120],
                    password=unusable_password, role="verifier")
        db.add(user)
    user.clerk_subject = subject
    if email == settings.admin_email and user.role != "admin":
        user.role = "admin"
        if not user.signing_key:
            user.signing_key, user.public_key = vault.issuer_keys(user.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        user = db.scalar(linked)
        if user is None:
            raise HTTPException(409, "This account could not be linked. Contact your administrator.") from None
    return user
