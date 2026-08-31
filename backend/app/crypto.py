"""Fernet encryption helpers for the GitHub PAT.

The PAT is encrypted at rest in Postgres and is never logged or returned by
any endpoint — only a ``pat_set: bool`` flag is exposed (see routers/settings.py).
``ENCRYPTION_KEY`` must be a valid Fernet key (generate with
``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``).
Missing/invalid keys raise only when an encrypt/decrypt is attempted, so the
app can still boot and serve ``/api/health`` without one.
"""

from __future__ import annotations

from cryptography.fernet import Fernet

from app.config import get_settings


def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set; cannot encrypt/decrypt the GitHub PAT. "
            "Generate one with: python -c "
            '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext secret, returning a URL-safe token string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`."""
    return _fernet().decrypt(token.encode()).decode()
