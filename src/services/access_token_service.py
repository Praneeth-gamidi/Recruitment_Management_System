from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import Session

from src.core.config import Settings, get_settings
from src.models import User
from src.services.account_service import (
    AccountUnavailableError,
    require_active_account,
)

ACCESS_TOKEN_ALGORITHM = "RS256"
ACCESS_TOKEN_LIFETIME_SECONDS = 600
ACCESS_TOKEN_CLOCK_SKEW_SECONDS = 30
INVALID_ACCESS_TOKEN_MESSAGE = "Invalid authentication credentials."
INVALID_JWT_CONFIGURATION_MESSAGE = "JWT service configuration is invalid."
REQUIRED_ACCESS_TOKEN_CLAIMS = (
    "sub",
    "jti",
    "iss",
    "aud",
    "iat",
    "exp",
    "token_version",
)


class InvalidAccessToken(ValueError):
    """Public-safe failure for invalid tokens or unavailable accounts."""


class AccessTokenConfigurationError(RuntimeError):
    """Public-safe failure for incomplete or invalid JWT service configuration."""


@dataclass(frozen=True)
class AccessToken:
    encoded_token: str
    token_type: str
    expires_in: int


@dataclass(frozen=True)
class AuthenticatedUserContext:
    user_id: str
    token_id: str
    token_version: int


class AccessTokenService:
    """Create and verify RS256 access tokens against current account state."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._issuer = self._settings.jwt_issuer
        self._audience = self._settings.jwt_audience
        private_path = self._settings.jwt_private_key_path
        public_path = self._settings.jwt_public_key_path
        if not self._issuer or not self._audience or not private_path or not public_path:
            raise AccessTokenConfigurationError(INVALID_JWT_CONFIGURATION_MESSAGE)

        try:
            private_bytes = Path(private_path).read_bytes()
            public_bytes = Path(public_path).read_bytes()
            self._private_key = serialization.load_pem_private_key(
                private_bytes,
                password=None,
            )
            self._public_key = serialization.load_pem_public_key(public_bytes)
            if not isinstance(self._private_key, rsa.RSAPrivateKey):
                raise ValueError
            if not isinstance(self._public_key, rsa.RSAPublicKey):
                raise ValueError
            if self._private_key.key_size < 2048 or self._public_key.key_size < 2048:
                raise ValueError
            if (
                self._private_key.public_key().public_numbers()
                != self._public_key.public_numbers()
            ):
                raise ValueError
        except (OSError, TypeError, ValueError, UnsupportedAlgorithm):
            raise AccessTokenConfigurationError(
                INVALID_JWT_CONFIGURATION_MESSAGE
            ) from None

    def create_access_token(self, session: Session, user: User) -> AccessToken:
        if not isinstance(user, User) or not user.user_id:
            raise InvalidAccessToken(INVALID_ACCESS_TOKEN_MESSAGE)
        try:
            active_user = require_active_account(session, user.user_id)
        except AccountUnavailableError:
            raise InvalidAccessToken(INVALID_ACCESS_TOKEN_MESSAGE) from None

        issued_at = datetime.now(timezone.utc)
        issued_timestamp = int(issued_at.timestamp())
        expires_timestamp = issued_timestamp + ACCESS_TOKEN_LIFETIME_SECONDS
        claims = {
            "sub": active_user.user_id,
            "jti": str(uuid4()),
            "iss": self._issuer,
            "aud": self._audience,
            "iat": issued_timestamp,
            "exp": expires_timestamp,
            "token_version": active_user.token_version,
        }
        encoded = jwt.encode(
            claims,
            self._private_key,
            algorithm=ACCESS_TOKEN_ALGORITHM,
            headers={"typ": "JWT"},
        )
        return AccessToken(
            encoded_token=encoded,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_LIFETIME_SECONDS,
        )

    def verify_access_token(
        self,
        session: Session,
        encoded_token: str,
    ) -> AuthenticatedUserContext:
        if not isinstance(encoded_token, str) or not encoded_token:
            raise InvalidAccessToken(INVALID_ACCESS_TOKEN_MESSAGE)
        try:
            header = jwt.get_unverified_header(encoded_token)
            if header.get("alg") != ACCESS_TOKEN_ALGORITHM:
                raise InvalidAccessToken(INVALID_ACCESS_TOKEN_MESSAGE)
            claims = jwt.decode(
                encoded_token,
                self._public_key,
                algorithms=[ACCESS_TOKEN_ALGORITHM],
                issuer=self._issuer,
                audience=self._audience,
                leeway=ACCESS_TOKEN_CLOCK_SKEW_SECONDS,
                options={
                    "require": list(REQUIRED_ACCESS_TOKEN_CLAIMS),
                    "verify_iat": True,
                },
            )
        except InvalidAccessToken:
            raise
        except (jwt.PyJWTError, TypeError, ValueError, UnicodeDecodeError, OverflowError):
            raise InvalidAccessToken(INVALID_ACCESS_TOKEN_MESSAGE) from None

        subject = claims.get("sub")
        token_id = claims.get("jti")
        issued_at = claims.get("iat")
        expires_at = claims.get("exp")
        token_version = claims.get("token_version")
        if (
            not isinstance(subject, str)
            or not subject.strip()
            or len(subject) > 80
            or not isinstance(token_id, str)
            or not _is_uuid(token_id)
            or type(issued_at) is not int
            or type(expires_at) is not int
            or type(token_version) is not int
            or token_version < 1
        ):
            raise InvalidAccessToken(INVALID_ACCESS_TOKEN_MESSAGE)

        now = int(datetime.now(timezone.utc).timestamp())
        lifetime = expires_at - issued_at
        if (
            issued_at > now + ACCESS_TOKEN_CLOCK_SKEW_SECONDS
            or expires_at <= now
            or lifetime <= 0
            or lifetime > ACCESS_TOKEN_LIFETIME_SECONDS
        ):
            raise InvalidAccessToken(INVALID_ACCESS_TOKEN_MESSAGE)

        try:
            active_user = require_active_account(session, subject)
        except AccountUnavailableError:
            raise InvalidAccessToken(INVALID_ACCESS_TOKEN_MESSAGE) from None
        if active_user.token_version != token_version:
            raise InvalidAccessToken(INVALID_ACCESS_TOKEN_MESSAGE)

        return AuthenticatedUserContext(
            user_id=active_user.user_id,
            token_id=token_id,
            token_version=active_user.token_version,
        )


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
