from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.database.base import Base
from src.models import User
from src.services.access_token_service import (
    ACCESS_TOKEN_ALGORITHM,
    ACCESS_TOKEN_LIFETIME_SECONDS,
    AccessTokenConfigurationError,
    AccessTokenService,
    AuthenticatedUserContext,
    InvalidAccessToken,
    REQUIRED_ACCESS_TOKEN_CLAIMS,
)

ISSUER = "https://issuer.example.invalid"
AUDIENCE = "recruitment-api-test"


@pytest.fixture(scope="module")
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def token_service(tmp_path, key_pair) -> AccessTokenService:
    private_key, public_key = key_pair
    private_path = tmp_path / "jwt-private.pem"
    public_path = tmp_path / "jwt-public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    settings = Settings.from_env(
        {
            "JWT_ISSUER": ISSUER,
            "JWT_AUDIENCE": AUDIENCE,
            "JWT_PRIVATE_KEY_PATH": str(private_path),
            "JWT_PUBLIC_KEY_PATH": str(public_path),
        }
    )
    return AccessTokenService(settings)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _active_user(session: Session, *, status: str = "ACTIVE", token_version: int = 4) -> User:
    password_hash = None if status == "PENDING_ACTIVATION" else "$argon2id$test-only"
    user = User(
        user_id="USR-JWT-TEST",
        email="jwt.test@example.invalid",
        display_name="JWT Test User",
        status=status,
        password_hash=password_hash,
        token_version=token_version,
    )
    session.add(user)
    session.flush()
    return user


def _claims(
    *,
    now: int | None = None,
    **overrides: object,
) -> dict[str, object]:
    issued_at = int(datetime.now(timezone.utc).timestamp()) if now is None else now
    claims: dict[str, object] = {
        "sub": "USR-JWT-TEST",
        "jti": str(uuid4()),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": issued_at,
        "exp": issued_at + ACCESS_TOKEN_LIFETIME_SECONDS,
        "token_version": 4,
    }
    claims.update(overrides)
    return claims


def _signed_token(
    private_key,
    claims: dict[str, object],
    *,
    algorithm: str = ACCESS_TOKEN_ALGORITHM,
) -> str:
    return jwt.encode(claims, private_key, algorithm=algorithm)


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _hmac_token_with_public_key_as_secret(public_key, claims: dict[str, object]) -> str:
    header = _base64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    payload = _base64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signature = hmac.new(public_pem, signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_base64url(signature)}"


def test_token_creation_has_approved_claims_lifetime_and_no_sensitive_data(
    token_service: AccessTokenService,
    session: Session,
) -> None:
    user = _active_user(session)

    first = token_service.create_access_token(session, user)
    second = token_service.create_access_token(session, user)
    claims = jwt.decode(
        first.encoded_token,
        options={"verify_signature": False, "verify_exp": False, "verify_aud": False},
    )

    assert first.token_type == "Bearer"
    assert first.expires_in == ACCESS_TOKEN_LIFETIME_SECONDS == 600
    assert claims["sub"] == user.user_id
    assert claims["jti"]
    assert claims["iss"] == ISSUER
    assert claims["aud"] == AUDIENCE
    assert claims["token_version"] == user.token_version
    assert claims["exp"] - claims["iat"] == 600
    assert set(claims) == set(REQUIRED_ACCESS_TOKEN_CLAIMS)
    assert claims["jti"] != jwt.decode(
        second.encoded_token,
        options={"verify_signature": False, "verify_exp": False, "verify_aud": False},
    )["jti"]
    assert user.email not in claims.values()
    assert user.display_name not in claims.values()
    assert user.password_hash not in claims.values()
    assert jwt.get_unverified_header(first.encoded_token)["alg"] == "RS256"

    context = token_service.verify_access_token(session, first.encoded_token)
    assert context == AuthenticatedUserContext(
        user_id=user.user_id,
        token_id=claims["jti"],
        token_version=user.token_version,
    )


def test_invalid_or_missing_key_configuration_fails_closed(tmp_path) -> None:
    with pytest.raises(AccessTokenConfigurationError, match="configuration is invalid"):
        AccessTokenService(Settings.from_env({}))

    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_text("not a private key", encoding="utf-8")
    public_path.write_text("not a public key", encoding="utf-8")
    settings = Settings.from_env(
        {
            "JWT_ISSUER": ISSUER,
            "JWT_AUDIENCE": AUDIENCE,
            "JWT_PRIVATE_KEY_PATH": str(private_path),
            "JWT_PUBLIC_KEY_PATH": str(public_path),
        }
    )
    with pytest.raises(AccessTokenConfigurationError) as error:
        AccessTokenService(settings)
    assert "not a private key" not in str(error.value)


def test_mismatched_signing_and_verification_keys_are_rejected(
    tmp_path,
    key_pair,
) -> None:
    private_key, _ = key_pair
    other_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        other_private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    settings = Settings.from_env(
        {
            "JWT_ISSUER": ISSUER,
            "JWT_AUDIENCE": AUDIENCE,
            "JWT_PRIVATE_KEY_PATH": str(private_path),
            "JWT_PUBLIC_KEY_PATH": str(public_path),
        }
    )
    with pytest.raises(AccessTokenConfigurationError):
        AccessTokenService(settings)


def test_valid_signature_and_wrong_signing_key(
    token_service: AccessTokenService,
    session: Session,
    key_pair,
) -> None:
    _active_user(session)
    private_key, _ = key_pair
    token = _signed_token(private_key, _claims())
    assert token_service.verify_access_token(session, token).user_id == "USR-JWT-TEST"

    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(InvalidAccessToken):
        token_service.verify_access_token(session, _signed_token(wrong_key, _claims()))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(iss="https://wrong-issuer.example.invalid"),
        lambda value: value.update(aud="wrong-audience"),
        lambda value: value.pop("sub"),
        lambda value: value.update(sub=""),
        lambda value: value.update(sub="x" * 81),
        lambda value: value.pop("jti"),
        lambda value: value.update(jti="not-a-uuid"),
        lambda value: value.pop("iat"),
        lambda value: value.update(iat="not-an-integer"),
        lambda value: value.pop("exp"),
        lambda value: value.update(exp="not-an-integer"),
        lambda value: value.pop("token_version"),
        lambda value: value.update(token_version=True),
        lambda value: value.update(token_version=0),
    ],
)
def test_required_claim_validation_rejects_bad_claims(
    token_service: AccessTokenService,
    session: Session,
    key_pair,
    mutate,
) -> None:
    _active_user(session)
    claims = _claims()
    mutate(claims)

    with pytest.raises(InvalidAccessToken):
        token_service.verify_access_token(session, _signed_token(key_pair[0], claims))


def test_expired_future_issued_and_overlong_tokens_are_rejected(
    token_service: AccessTokenService,
    session: Session,
    key_pair,
) -> None:
    _active_user(session)
    now = int(datetime.now(timezone.utc).timestamp())
    invalid_claims = [
        _claims(now=now - 700),
        _claims(now=now + 31),
        _claims(now=now, exp=now + 601),
        _claims(now=now, exp=now),
    ]

    for claims in invalid_claims:
        with pytest.raises(InvalidAccessToken):
            token_service.verify_access_token(session, _signed_token(key_pair[0], claims))


def test_bad_signature_and_tampered_payload_are_rejected(
    token_service: AccessTokenService,
    session: Session,
    key_pair,
) -> None:
    _active_user(session)
    token = _signed_token(key_pair[0], _claims())
    header, payload, signature = token.split(".")
    altered_payload = _base64url(
        json.dumps(_claims(sub="USR-TAMPERED"), separators=(",", ":")).encode("utf-8")
    )
    tampered_payload = f"{header}.{altered_payload}.{signature}"
    altered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered_signature = f"{header}.{payload}.{altered_signature}"

    for invalid_token in (tampered_payload, tampered_signature):
        with pytest.raises(InvalidAccessToken):
            token_service.verify_access_token(session, invalid_token)


def test_algorithm_allowlist_rejects_none_unsupported_and_hmac_confusion(
    token_service: AccessTokenService,
    session: Session,
    key_pair,
) -> None:
    _active_user(session)
    claims = _claims()
    private_key, public_key = key_pair
    none_token = jwt.encode(claims, key="", algorithm="none")
    unsupported_token = _signed_token(private_key, claims, algorithm="RS512")
    hmac_token = _hmac_token_with_public_key_as_secret(public_key, claims)

    for invalid_token in (none_token, unsupported_token, hmac_token):
        with pytest.raises(InvalidAccessToken):
            token_service.verify_access_token(session, invalid_token)


@pytest.mark.parametrize("status", ["PENDING_ACTIVATION", "LOCKED", "DISABLED"])
def test_non_active_accounts_cannot_create_or_verify_tokens(
    token_service: AccessTokenService,
    session: Session,
    key_pair,
    status: str,
) -> None:
    user = _active_user(session, status=status)
    with pytest.raises(InvalidAccessToken):
        token_service.create_access_token(session, user)
    with pytest.raises(InvalidAccessToken):
        token_service.verify_access_token(
            session,
            _signed_token(key_pair[0], _claims()),
        )


def test_missing_user_and_outdated_token_version_are_rejected(
    token_service: AccessTokenService,
    session: Session,
    key_pair,
) -> None:
    claims = _claims(sub="USR-MISSING")
    with pytest.raises(InvalidAccessToken):
        token_service.verify_access_token(session, _signed_token(key_pair[0], claims))

    user = _active_user(session)
    token = token_service.create_access_token(session, user)
    user.token_version += 1
    session.flush()
    with pytest.raises(InvalidAccessToken):
        token_service.verify_access_token(session, token.encoded_token)


def test_invalid_token_errors_do_not_disclose_account_state(
    token_service: AccessTokenService,
    session: Session,
    key_pair,
) -> None:
    with pytest.raises(InvalidAccessToken) as missing_error:
        token_service.verify_access_token(
            session,
            _signed_token(key_pair[0], _claims(sub="USR-NOT-FOUND")),
        )
    _active_user(session, status="DISABLED")
    with pytest.raises(InvalidAccessToken) as disabled_error:
        token_service.verify_access_token(
            session,
            _signed_token(key_pair[0], _claims()),
        )
    assert str(missing_error.value) == str(disabled_error.value)
