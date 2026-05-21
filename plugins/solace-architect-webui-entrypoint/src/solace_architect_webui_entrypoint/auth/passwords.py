"""Argon2id-based password hashing.

argon2-cffi is OWASP-recommended for new applications. We use the library's
defaults (which match OWASP Argon2id minimums) and rely on the hash string
to embed all parameters needed for verification — meaning future parameter
tuning won't break existing user logins.
"""

from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash, VerificationError


_hasher = PasswordHasher()

# Minimum password rules — kept simple; tune later if needed.
_MIN_LENGTH = 8
_PASSWORD_RE = re.compile(r"\S")   # at least one non-whitespace char


def validate_password_strength(password: str) -> tuple[bool, str | None]:
    """Cheap baseline check. Returns (ok, error_message)."""
    if not isinstance(password, str):
        return False, "password must be a string"
    if len(password) < _MIN_LENGTH:
        return False, f"password must be at least {_MIN_LENGTH} characters"
    if not _PASSWORD_RE.search(password):
        return False, "password cannot be empty / whitespace-only"
    return True, None


def hash_password(password: str) -> str:
    """Hash a plaintext password with argon2id. Raises ValueError on weak passwords."""
    ok, err = validate_password_strength(password)
    if not ok:
        raise ValueError(err)
    return _hasher.hash(password)


def verify_password(stored_hash: str, candidate: str) -> bool:
    """Constant-time verification. Returns True if password matches."""
    try:
        _hasher.verify(stored_hash, candidate)
        return True
    except (VerifyMismatchError, InvalidHash, VerificationError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True if the hash uses parameters older than argon2-cffi's current defaults."""
    return _hasher.check_needs_rehash(stored_hash)
