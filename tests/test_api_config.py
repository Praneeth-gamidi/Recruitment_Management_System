from __future__ import annotations

import pytest

from src.core.config import Settings


def test_settings_load_environment_values_and_parse_cors_origins() -> None:
    settings = Settings.from_env(
        {
            "APP_NAME": "Recruitment API test",
            "APP_VERSION": "2.3.4",
            "APP_ENV": "test",
            "APP_HOST": "0.0.0.0",
            "APP_PORT": "8123",
            "LOG_LEVEL": "debug",
            "CORS_ORIGINS": "https://example.test, http://localhost:4321/ ",
        }
    )

    assert settings.app_name == "Recruitment API test"
    assert settings.app_version == "2.3.4"
    assert settings.environment == "test"
    assert settings.host == "0.0.0.0"
    assert settings.port == 8123
    assert settings.log_level == "DEBUG"
    assert settings.cors_origins == ("https://example.test", "http://localhost:4321")
    assert settings.refresh_token_lifetime_days == 7
    assert settings.refresh_token_family_lifetime_days == 30


def test_settings_validate_refresh_token_lifetimes() -> None:
    settings = Settings.from_env(
        {
            "REFRESH_TOKEN_LIFETIME_DAYS": "5",
            "REFRESH_TOKEN_FAMILY_LIFETIME_DAYS": "12",
        }
    )
    assert settings.refresh_token_lifetime_days == 5
    assert settings.refresh_token_family_lifetime_days == 12

    with pytest.raises(ValueError, match="must be integers"):
        Settings.from_env({"REFRESH_TOKEN_LIFETIME_DAYS": "seven"})
    with pytest.raises(ValueError, match="must be positive"):
        Settings.from_env({"REFRESH_TOKEN_LIFETIME_DAYS": "0"})
    with pytest.raises(ValueError, match="must be at least"):
        Settings.from_env(
            {
                "REFRESH_TOKEN_LIFETIME_DAYS": "8",
                "REFRESH_TOKEN_FAMILY_LIFETIME_DAYS": "7",
            }
        )


@pytest.mark.parametrize(
    "values, message",
    [
        ({"CORS_ORIGINS": "*"}, "Invalid CORS origin"),
        ({"CORS_ORIGINS": "https://example.test/api"}, "must not include a path"),
        ({"APP_PORT": "not-a-number"}, "must be an integer"),
        ({"APP_PORT": "70000"}, "between 1 and 65535"),
        ({"LOG_LEVEL": "TRACE"}, "LOG_LEVEL must be"),
    ],
)
def test_settings_reject_invalid_configuration(values: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Settings.from_env(values)
