import re
import secrets
from datetime import timedelta
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, or_, select

from .db import Event, Session, User, now, timestamp

COOKIE = "verifex_session"
SESSION_SECONDS = 12 * 3600
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


def new_session(request, response, db, user):
    token = secrets.token_urlsafe(32)
    vault = request.app.state.vault
    db.execute(delete(Session).where(Session.expires_at <= now()))
    existing = request.cookies.get(COOKIE, "")
    if existing:
        db.execute(delete(Session).where(Session.token == vault.token_hash(existing)))
    db.add(Session(token=vault.token_hash(token), user_id=user.id,
                   expires_at=now() + timedelta(seconds=SESSION_SECONDS)))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax",
                        secure=request.app.state.settings.secure_cookie)


def current_user(request: Request, db=Depends(db_session)):
    token = request.cookies.get(COOKIE, "")
    if not 30 <= len(token) <= 90:
        raise HTTPException(401, "Sign in to continue.")
    session = db.get(Session, request.app.state.vault.token_hash(token))
    if session is None or session.expires_at <= now():
        raise HTTPException(401, "Sign in to continue.")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Sign in to continue.")
    request.state.session_hash = session.token
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


def login_attempt(request, db, credentials):
    ip = network(request)
    subject = request.app.state.vault.token_hash("login:" + credentials.email)
    window = now() - timedelta(minutes=15)
    with LOGIN_LOCK:
        attempts = db.scalar(select(func.count()).select_from(Event).where(
            Event.kind == "login_failed", Event.created_at >= window,
            or_(Event.subject == subject, Event.network == ip)))
        if attempts >= 6:
            raise HTTPException(429, "Too many failed sign-ins. Try again in 15 minutes.", headers={"Retry-After": "900"})
        user = db.scalar(select(User).where(User.email == credentials.email))
        try:
            correct = PASSWORDS.verify(user.password if user else DUMMY, credentials.password)
        except VerificationError:
            correct = False
        if not correct or user is None:
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
