from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from src.database.base import Base
from src.models import User
from src.services.password_security import (
    COMPROMISED_PASSWORD_CHECKING_ENABLED,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    password_needs_rehash,
    validate_password,
    verify_password,
)


@pytest.fixture
def engine():
    database_engine = create_engine("sqlite://")

    @event.listens_for(database_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


def test_hashes_are_salted_and_password_verification_is_correct() -> None:
    password = "a secure passphrase"
    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash
    assert first_hash.startswith("$argon2id$")
    assert verify_password(password, first_hash)
    assert not verify_password("a different passphrase", first_hash)
    assert password_needs_rehash(first_hash) is False


def test_malformed_hash_is_rejected_safely() -> None:
    assert verify_password("a secure passphrase", "not-an-argon2-hash") is False
    assert password_needs_rehash("not-an-argon2-hash") is False


@pytest.mark.parametrize("password", ["", "short"])
def test_empty_and_short_passwords_are_rejected(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password(password)
    with pytest.raises(PasswordPolicyError):
        hash_password(password)


def test_password_policy_minimum_boundary_and_long_passphrases() -> None:
    assert MIN_PASSWORD_LENGTH == 12
    validate_password("x" * MIN_PASSWORD_LENGTH)
    validate_password("x" * 64)
    validate_password("x" * MAX_PASSWORD_LENGTH)
    assert verify_password("x" * MAX_PASSWORD_LENGTH, hash_password("x" * MAX_PASSWORD_LENGTH))

    with pytest.raises(PasswordPolicyError):
        validate_password("x" * (MIN_PASSWORD_LENGTH - 1))
    with pytest.raises(PasswordPolicyError):
        validate_password("x" * (MAX_PASSWORD_LENGTH + 1))


def test_unicode_passwords_are_hashed_as_supplied() -> None:
    password = "mélange 🔐 café passphrase"
    encoded_hash = hash_password(password)

    assert verify_password(password, encoded_hash)
    assert not verify_password("me\u0301lange 🔐 café passphrase", encoded_hash)


def test_passwords_have_no_composition_rules_or_remote_compromise_lookup() -> None:
    assert validate_password("simple lowercase phrase") is None
    assert COMPROMISED_PASSWORD_CHECKING_ENABLED is False
    validate_password("passwordpassword")


def test_only_encoded_hash_is_persisted(engine) -> None:
    password = "persisted secure passphrase"
    encoded_hash = hash_password(password)
    user = User(
        user_id="USR-PASSWORD-TEST",
        email="password.test@example.invalid",
        display_name="Password Test",
        password_hash=encoded_hash,
        status="ACTIVE",
    )
    with Session(engine) as session, session.begin():
        session.add(user)
        session.flush()
        persisted = session.get(User, user.user_id)
        assert persisted is not None
        assert persisted.password_hash == encoded_hash
        assert password not in persisted.password_hash
