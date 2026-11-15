from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, LargeBinary, String, Text, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds") + "Z"


def identifier() -> str:
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    google_subject: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    clerk_subject: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    password: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), default="verifier")
    signing_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    public_key: Mapped[str | None] = mapped_column(String(64))


class Session(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Certificate(Base):
    __tablename__ = "certificates"
    ref: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    issuer_name: Mapped[str] = mapped_column(String(120))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[str] = mapped_column(String(128))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    original: Mapped[bytes] = mapped_column(LargeBinary)
    private_metadata: Mapped[bytes | None] = mapped_column(LargeBinary)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    certificate_ref: Mapped[str | None] = mapped_column(ForeignKey("certificates.ref"))
    compare_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    external_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    filename: Mapped[str] = mapped_column(String(160))
    mime: Mapped[str] = mapped_column(String(40))
    source: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    stage: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    outcome: Mapped[str | None] = mapped_column(String(32))
    report: Mapped[bytes | None] = mapped_column(LargeBinary)
    partial: Mapped[bytes | None] = mapped_column(LargeBinary)
    progress: Mapped[list] = mapped_column(JSON, default=list)


class Event(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    actor_id: Mapped[str | None] = mapped_column(String(32), index=True)
    subject: Mapped[str | None] = mapped_column(String(64), index=True)
    network: Mapped[str | None] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    detail: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


def normalize_database_url(value: str) -> URL:
    if not value.strip():
        raise ValueError("Set DATABASE_URL in .env using the Supabase Session pooler connection string.")
    try:
        url = make_url(value.strip())
    except (ArgumentError, ValueError):
        raise ValueError("DATABASE_URL must be a valid PostgreSQL or SQLite connection string.") from None

    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() not in {"postgresql", "sqlite"}:
        raise ValueError("DATABASE_URL must be a PostgreSQL or SQLite connection string.")

    if (url.host or "").lower().endswith((".supabase.co", ".pooler.supabase.com")):
        if url.drivername != "postgresql+psycopg" or url.port not in {None, 5432}:
            raise ValueError("Use the Supabase Session pooler or Direct connection on port 5432 with psycopg.")
        if url.query.get("sslmode", "require") not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("Supabase DATABASE_URL requires sslmode=require or certificate verification.")
        url = url.update_query_dict({"sslmode": url.query.get("sslmode", "require"),
                                     "connect_timeout": url.query.get("connect_timeout", "10")})
    return url


def connect(url: str):
    parsed = normalize_database_url(url)
    sqlite = parsed.get_backend_name() == "sqlite"
    if sqlite and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(parsed, pool_pre_ping=True)
    if sqlite:
        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
