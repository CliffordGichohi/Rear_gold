from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

TOKEN_FORMAT_VERSION = "v1"
TOKEN_NONCE_BYTES = 12
OAUTH_STATE_NONCE_BYTES = 32


class TokenDecryptionError(ValueError):
    """Raised without exposing ciphertext or key material."""


class OAuthStateError(ValueError):
    """Raised when an OAuth state is absent, altered, mismatched, or stale."""


@dataclass(frozen=True, slots=True)
class OAuthStateManager:
    signing_key: str
    ttl_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.signing_key:
            raise ValueError("OAuth state signing key is required.")
        if not 60 <= self.ttl_seconds <= 900:
            raise ValueError("OAuth state lifetime must be between 60 and 900 seconds.")

    def issue(self, *, now: int | None = None) -> str:
        issued_at = int(time.time() if now is None else now)
        nonce = _encode(secrets.token_bytes(OAUTH_STATE_NONCE_BYTES))
        payload = f"{issued_at}.{nonce}"
        signature = self._signature(payload)
        return f"{payload}.{signature}"

    def validate(
        self,
        state: str | None,
        *,
        cookie_state: str | None,
        now: int | None = None,
    ) -> None:
        if not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
            raise OAuthStateError("OAuth state did not match the initiating browser session.")
        self.validate_cookie(cookie_state, now=now)

    def validate_cookie(
        self,
        cookie_state: str | None,
        *,
        now: int | None = None,
    ) -> None:
        if not cookie_state:
            raise OAuthStateError("OAuth browser state is missing.")
        parts = cookie_state.split(".")
        if len(parts) != 3:
            raise OAuthStateError("OAuth state format is invalid.")
        issued_text, nonce, signature = parts
        try:
            issued_at = int(issued_text)
        except ValueError as exc:
            raise OAuthStateError("OAuth state timestamp is invalid.") from exc
        current = int(time.time() if now is None else now)
        if issued_at > current + 30 or current - issued_at > self.ttl_seconds:
            raise OAuthStateError("OAuth state has expired.")
        if len(nonce) < 32:
            raise OAuthStateError("OAuth state nonce is invalid.")
        expected = self._signature(f"{issued_text}.{nonce}")
        if not hmac.compare_digest(signature, expected):
            raise OAuthStateError("OAuth state signature is invalid.")

    def _signature(self, payload: str) -> str:
        digest = hmac.new(
            self.signing_key.encode("utf-8"),
            payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return _encode(digest)


class TokenCipher:
    """Versioned authenticated encryption for provider tokens at rest."""

    def __init__(self, *, key_material: str, environment: str) -> None:
        if not key_material:
            raise ValueError("Provider token encryption key material is required.")
        if not environment:
            raise ValueError("Provider environment is required.")
        self._key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"gold-market-intelligence/provider-token/v1",
            info=f"ctrader:{environment}".encode(),
        ).derive(key_material.encode("utf-8"))

    def encrypt(self, plaintext: str, *, purpose: str) -> str:
        if not plaintext:
            raise ValueError("A non-empty provider token is required.")
        associated_data = self._associated_data(purpose)
        nonce = secrets.token_bytes(TOKEN_NONCE_BYTES)
        encrypted = AESGCM(self._key).encrypt(
            nonce,
            plaintext.encode("utf-8"),
            associated_data,
        )
        return f"{TOKEN_FORMAT_VERSION}.{_encode(nonce + encrypted)}"

    def decrypt(self, ciphertext: str, *, purpose: str) -> str:
        prefix = f"{TOKEN_FORMAT_VERSION}."
        if not ciphertext.startswith(prefix):
            raise TokenDecryptionError("Unsupported provider-token ciphertext version.")
        try:
            payload = _decode(ciphertext.removeprefix(prefix))
            nonce = payload[:TOKEN_NONCE_BYTES]
            encrypted = payload[TOKEN_NONCE_BYTES:]
            if len(nonce) != TOKEN_NONCE_BYTES or not encrypted:
                raise ValueError
            plaintext = AESGCM(self._key).decrypt(
                nonce,
                encrypted,
                self._associated_data(purpose),
            )
            return plaintext.decode("utf-8")
        except (binascii.Error, InvalidTag, UnicodeDecodeError, ValueError) as exc:
            raise TokenDecryptionError(
                "Provider token could not be authenticated or decrypted."
            ) from exc

    @staticmethod
    def _associated_data(purpose: str) -> bytes:
        if purpose not in {"access", "refresh"}:
            raise ValueError("Provider token purpose must be access or refresh.")
        return f"ctrader:{purpose}:{TOKEN_FORMAT_VERSION}".encode("ascii")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
