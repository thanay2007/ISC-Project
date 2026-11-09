import os
from base64 import urlsafe_b64decode
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL") or f"sqlite:///{ROOT / '.verifex' / 'verifex.sqlite3'}")
    app_secret: str = field(default_factory=lambda: os.getenv("APP_SECRET_KEY", ""))
    encryption_key: str = field(default_factory=lambda: os.getenv("ENCRYPTION_KEY", ""))
    public_url: str = field(default_factory=lambda: os.getenv("PUBLIC_URL", "http://localhost:3000"))
    secure_cookie: bool = field(default_factory=lambda: os.getenv("COOKIE_SECURE", "false").lower() == "true")
    demo_enabled: bool = field(default_factory=lambda: os.getenv("DEMO_ENABLED", "false").lower() == "true")
    gemini_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", ""))
    groq_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", ""))
    ocr_engine: str = field(default_factory=lambda: os.getenv("OCR_ENGINE", "auto"))
    tesseract_cmd: str = field(default_factory=lambda: os.getenv("TESSERACT_CMD", ""))
    admin_email: str = field(default_factory=lambda: os.getenv("ADMIN_EMAIL", "").strip().lower())
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))

    def validate(self) -> bytes:
        key = urlsafe_b64decode(self.encryption_key)
        if len(self.app_secret) < 32 or len(key) != 32:
            raise ValueError("Generate an .env with python backend/setup_env.py")
        origin = urlparse(self.public_url)
        if origin.scheme not in {"http", "https"} or not origin.netloc or origin.path not in {"", "/"} or origin.username or origin.query or origin.fragment:
            raise ValueError("PUBLIC_URL must be an HTTP(S) origin")
        if self.secure_cookie and origin.scheme != "https":
            raise ValueError("COOKIE_SECURE requires an HTTPS public origin")
        return key
