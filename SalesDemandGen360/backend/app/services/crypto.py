"""Credential encryption.

Three rules from CLAUDE.md, implemented here rather than trusted to callers:

1. Credentials are encrypted at rest.
2. The API never returns a full value — only ``last_four``.
3. No credential is ever written to a log, a prompt, or an audit payload.

Rule 3 is why ``SecretValue`` exists. A plain ``str`` holding an API key will
eventually end up in an f-string, a log line, or an exception message. This type
raises on ``str()`` and ``repr()``, so that mistake fails loudly in a test rather
than quietly in production logs.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class CredentialError(RuntimeError):
    """Raised when a credential cannot be decrypted."""


class SecretValue:
    """A string that refuses to be printed.

    Read it deliberately via ``.reveal()``. Anything else — logging, string
    interpolation, an exception repr — gets a redacted marker.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    @property
    def last_four(self) -> str:
        return self._value[-4:] if len(self._value) >= 4 else ""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return "<redacted>"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "SecretValue(<redacted>)"

    def __format__(self, spec: str) -> str:  # pragma: no cover - trivial
        return "<redacted>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretValue):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)


def _fernet() -> Fernet:
    """Derive the encryption key from SECRET_KEY.

    A derived key means one secret in the environment rather than two, and the
    SHA-256 digest guarantees the 32 bytes Fernet requires regardless of how
    long the configured secret is.
    """
    secret = get_settings().secret_key
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> bytes:
    if not value:
        raise ValueError("refusing to encrypt an empty credential")
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt(blob: bytes) -> SecretValue:
    try:
        return SecretValue(_fernet().decrypt(blob).decode("utf-8"))
    except InvalidToken as exc:
        # Never include the blob or the key in the message.
        raise CredentialError(
            "credential could not be decrypted — SECRET_KEY may have changed"
        ) from exc


def last_four(value: str) -> str:
    return value[-4:] if len(value) >= 4 else ""
