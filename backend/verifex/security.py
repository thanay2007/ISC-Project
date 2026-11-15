import re
import secrets
from datetime import timedelta
from ipaddress import ip_address
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, or_, select

from .db import Event, Session, User, now, timestamp
from . import clerk_auth

COOKIE = "verifex_session"
LOCAL_ADMIN_EMAIL = "admin@verifex.invalid"
LOCAL_ADMIN_HASH = "$argon2id$v=19$m=65536,t=2,p=2$WIpwfC28nj18t3HZhHdQuA$morLGRHkZYuvfKKfDFDys31UJrpPQegq8WEFcRmeyRI"
SESSION_SECONDS = 12 * 3600
GUEST_SESSION_SECONDS = 30 * 24 * 3600
PASSWORDS = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
DUMMY = PASSWORDS.hash(secrets.token_urlsafe(32))
LOGIN_LOCK = Lock()


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address.")
        return value


class AdminLogin(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class Registration(Login):
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if len(value.strip()) < 2 or not value.isprintable():
            raise ValueError("Enter a display name.")
        return value.strip()


def db_session(request: Request):
    with request.app.state.sessions() as db:
        yield db


def network(request):
    return request.app.state.vault.token_hash("network:" + (request.client.host if request.client else "unknown"))


def audit(db, kind, detail, actor=None, subject=None, network_id=None):
    db.add(Event(kind=kind, detail=detail, actor_id=actor, subject=subject, network=network_id))


def user_info(user):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


def new_session(request, response, db, user, max_age=SESSION_SECONDS):
    token = secrets.token_urlsafe(32)
    vault = request.app.state.vault
    db.execute(delete(Session).where(Session.expires_at <= now()))
    existing = request.cookies.get(COOKIE, "")
    if existing:
        db.execute(delete(Session).where(Session.token == vault.token_hash(existing)))
    db.add(Session(token=vault.token_hash(token), user_id=user.id,
                   expires_at=now() + timedelta(seconds=max_age)))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=max_age, httponly=True, samesite="lax",
                        secure=request.app.state.settings.secure_cookie)


def local_admin_allowed(request):
    if not request.app.state.settings.local_admin_enabled or not request.client:
        return False
    try:
        return ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def password_session(request, db):
    token = request.cookies.get(COOKIE, "")
    if not 30 <= len(token) <= 90:
        return None
    session = db.get(Session, request.app.state.vault.token_hash(token))
    if session is None or session.expires_at <= now():
        return None
    user = db.get(User, session.user_id)
    if not user or (user.email == LOCAL_ADMIN_EMAIL and not local_admin_allowed(request)):
        return None
    request.state.session_hash = session.token
    return user


def session_user(request, db):
    settings = request.app.state.settings
    user = password_session(request, db)
    if user and user.email == LOCAL_ADMIN_EMAIL:
        return user
    clerk_token = request.cookies.get("__session")
    if settings.clerk_enabled and clerk_token:
        claims = clerk_auth.verify_session(settings, clerk_token)
        user = clerk_auth.resolve_user(settings, request.app.state.vault, db, claims["sub"], DUMMY)
        request.state.session_hash = None
        request.state.clerk_expires_at = claims["exp"]
        return user
    return user


def current_user(request: Request, db=Depends(db_session)):
    user = session_user(request, db)
    if user is None:
        raise HTTPException(401, "Open the workspace to start a session.")
    return user


def require_role(*allowed):
    def check(request: Request, user=Depends(current_user), db=Depends(db_session)):
        if user.role not in allowed:
            deny(request, db, user, None, "Required role was missing")
        return user
    return check


def deny(request, db, user, subject, detail):
    audit(db, "access_denied", detail, actor=user.id, subject=subject, network_id=network(request))
    db.commit()
    raise HTTPException(403, "This resource is restricted.")


def login_attempt(request, db, credentials, *, local_admin=False):
    ip = network(request)
    subject = request.app.state.vault.token_hash("login:" + credentials.email)
    window = now() - timedelta(minutes=15)
    with LOGIN_LOCK:
        attempts = db.scalar(select(func.count()).select_from(Event).where(
            Event.kind == "login_failed", Event.created_at >= window,
            or_(Event.subject == subject, Event.network == ip)))
        if attempts >= 6:
            raise HTTPException(429, "Too many failed sign-ins. Try again in 15 minutes.", headers={"Retry-After": "900"})
        user = None
        if credentials.email != LOCAL_ADMIN_EMAIL or local_admin:
            user = db.scalar(select(User).where(User.email == credentials.email))
        try:
            correct = PASSWORDS.verify(user.password if user else DUMMY, credentials.password)
        except VerificationError:
            correct = False
        if not correct or user is None or user.role == "guest" or user.google_subject is not None or user.clerk_subject is not None:
            audit(db, "login_failed", "Incorrect credentials", subject=subject, network_id=ip)
            db.commit()
            raise HTTPException(401, "Incorrect email or password.")
        if PASSWORDS.check_needs_rehash(user.password):
            user.password = PASSWORDS.hash(credentials.password)
        return user


def event_row(item):
    return {"id": item.id, "actor": item.actor_id, "kind": item.kind, "detail": item.detail,
            "subject": item.subject if item.kind != "login_failed" else None,
            "created_at": timestamp(item.created_at)}
