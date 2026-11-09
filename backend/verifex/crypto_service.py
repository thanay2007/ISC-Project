import hashlib
import hmac
import json
import secrets
from base64 import urlsafe_b64encode
from io import BytesIO

import qrcode
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def verify(public_key: str, data: bytes, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)).verify(bytes.fromhex(signature), data)
    except (InvalidSignature, ValueError):
        return False
    return True


class Vault:
    def __init__(self, encryption_key: bytes, app_secret: str):
        self.cipher = AESGCM(encryption_key)
        self.secret = app_secret.encode()
        self.report_key = Ed25519PrivateKey.from_private_bytes(
            hmac.digest(self.secret, b"verifex/report-key/v1", "sha256")
        )

    def seal(self, data: bytes, context: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self.cipher.encrypt(nonce, data, context.encode())

    def open(self, blob: bytes, context: str) -> bytes:
        return self.cipher.decrypt(blob[:12], blob[12:], context.encode())

    def token_hash(self, token: str) -> str:
        return hmac.new(self.secret, token.encode(), "sha256").hexdigest()

    def issuer_keys(self, user_id: str) -> tuple[bytes, str]:
        key = Ed25519PrivateKey.generate()
        return self.seal(key.private_bytes_raw(), f"issuer:{user_id}"), key.public_key().public_bytes_raw().hex()

    def issuer_sign(self, user_id: str, secret_key: bytes, payload: bytes) -> str:
        key = Ed25519PrivateKey.from_private_bytes(self.open(secret_key, f"issuer:{user_id}"))
        return key.sign(payload).hex()

    def report_sign(self, pdf: bytes) -> str:
        return self.report_key.sign(pdf).hex()

    @property
    def report_public_key(self) -> str:
        return self.report_key.public_key().public_bytes_raw().hex()


def certificate_payload(ref: str, issuer_id: str, issuer_name: str, digest: str, issued_at: str) -> bytes:
    return canonical({
        "type": "verifex-certificate-v1", "ref": ref, "issuer": issuer_id,
        "issuer_name": issuer_name, "sha256": digest, "issued_at": issued_at,
    })


def qr_png(url: str) -> bytes:
    stream = BytesIO()
    qrcode.make(url).save(stream, format="PNG")
    return stream.getvalue()


def png_data_url(png: bytes) -> str:
    return "data:image/png;base64," + urlsafe_b64encode(png).decode().replace("-", "+").replace("_", "/")
