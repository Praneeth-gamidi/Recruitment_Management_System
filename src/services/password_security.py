from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, UnsupportedParametersError, VerificationError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024
COMPROMISED_PASSWORD_CHECKING_ENABLED = False

_PASSWORD_HASHER = PasswordHasher()


class PasswordPolicyError(ValueError):
    """Raised when a password does not satisfy the local password policy."""


def validate_password(password: str) -> None:
    """Validate length without trimming, truncating, or normalizing the password.

    Passwords are measured in Unicode code points and hashed as supplied.
    Compromised-password screening is not configured and is not performed.
    """
    if not isinstance(password, str) or not password:
        raise PasswordPolicyError("Password must not be empty.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must contain at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must not exceed {MAX_PASSWORD_LENGTH} characters."
        )


def hash_password(password: str) -> str:
    """Return a salted Argon2id encoded password hash."""
    validate_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password, returning False for invalid or unsupported hashes."""
    if not isinstance(password, str) or not isinstance(encoded_hash, str):
        return False
    try:
        return _PASSWORD_HASHER.verify(encoded_hash, password)
    except (InvalidHashError, UnsupportedParametersError, VerificationError):
        return False


def password_needs_rehash(encoded_hash: str) -> bool:
    """Report whether a valid hash uses parameters older than the current defaults."""
    if not isinstance(encoded_hash, str):
        return False
    try:
        return _PASSWORD_HASHER.check_needs_rehash(encoded_hash)
    except (InvalidHashError, UnsupportedParametersError, VerificationError):
        return False
