from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, LargeBinary, String, Text, create_engine, event
from sqlalchemy.engine import make_url
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


def connect(url: str):
    parsed = make_url(url)
    sqlite = parsed.get_backend_name() == "sqlite"
    if sqlite and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True)
    if sqlite:
        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
