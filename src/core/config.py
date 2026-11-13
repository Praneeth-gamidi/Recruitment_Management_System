from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    environment: str
    log_level: str
    cors_origins: tuple[str, ...]
    host: str
    port: int
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_private_key_path: str | None = None
    jwt_public_key_path: str | None = None
    refresh_token_lifetime_days: int = 7
    refresh_token_family_lifetime_days: int = 30

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        if environ is None:
            load_dotenv(ROOT_DIR / ".env")
            source = os.environ
        else:
            source = environ

        origins = tuple(
            origin.strip().rstrip("/")
            for origin in source.get(
                "CORS_ORIGINS",
                "http://localhost:3000,http://localhost:8501",
            ).split(",")
            if origin.strip()
        )
        for origin in origins:
            parsed = urlsplit(origin)
            if origin == "*" or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"Invalid CORS origin: {origin!r}")
            if parsed.path or parsed.query or parsed.fragment:
                raise ValueError(f"CORS origins must not include a path or query: {origin!r}")

        log_level = source.get("LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")

        try:
            port = int(source.get("APP_PORT", "8000"))
        except ValueError as exc:
            raise ValueError("APP_PORT must be an integer.") from exc
        if not 1 <= port <= 65535:
            raise ValueError("APP_PORT must be between 1 and 65535.")

        try:
            refresh_token_lifetime_days = int(
                source.get("REFRESH_TOKEN_LIFETIME_DAYS", "7")
            )
            refresh_token_family_lifetime_days = int(
                source.get("REFRESH_TOKEN_FAMILY_LIFETIME_DAYS", "30")
            )
        except ValueError as exc:
            raise ValueError("Refresh-token lifetime settings must be integers.") from exc
        if refresh_token_lifetime_days < 1:
            raise ValueError("REFRESH_TOKEN_LIFETIME_DAYS must be positive.")
        if refresh_token_family_lifetime_days < refresh_token_lifetime_days:
            raise ValueError(
                "REFRESH_TOKEN_FAMILY_LIFETIME_DAYS must be at least "
                "REFRESH_TOKEN_LIFETIME_DAYS."
            )

        return cls(
            app_name=source.get("APP_NAME", "Recruitment Management System API"),
            app_version=source.get("APP_VERSION", "0.1.0"),
            environment=source.get("APP_ENV", "development"),
            log_level=log_level,
            cors_origins=origins,
            host=source.get("APP_HOST", "127.0.0.1"),
            port=port,
            jwt_issuer=source.get("JWT_ISSUER") or None,
            jwt_audience=source.get("JWT_AUDIENCE") or None,
            jwt_private_key_path=source.get("JWT_PRIVATE_KEY_PATH") or None,
            jwt_public_key_path=source.get("JWT_PUBLIC_KEY_PATH") or None,
            refresh_token_lifetime_days=refresh_token_lifetime_days,
            refresh_token_family_lifetime_days=refresh_token_family_lifetime_days,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
