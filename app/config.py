"""Настройки приложения (api.md §1): pydantic-settings, читает env и ``.env``.

Требования безопасности (docs/security/threat-model.md §5.5, SEC-07/SEC-08):
- ``admin_id`` парсится строго в ``int`` (мусор не превращается в «админа»);
- ``repr``/``str`` настроек не показывают значение ``bot_token`` и пароль из DSN;
- текст ошибок конфигурации не содержит значений секретов.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MASKED = "***"


class Settings(BaseSettings):
    """Конфигурация процесса: секреты — только из env (R30, SEC-08)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    admin_id: int
    database_url: str
    test_database_url: str = "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs_test"
    collect_interval_minutes: int = 60
    digest_size_default: int = 10
    digest_catchup_minutes: int = 180  # догоняющее окно, 3 ч
    retention_days: int = 30
    cleanup_time: str = "04:15"  # HH:MM, UTC
    http_timeout_seconds: float = 15.0

    @field_validator("admin_id")
    @classmethod
    def _admin_id_is_strict_int(cls, value: Any) -> int:
        """Строгий int: bool/дроби/мусор не могут стать идентификатором админа."""
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("admin_id must be an integer")
        return value

    @field_validator("test_database_url")
    @classmethod
    def _test_db_only(cls, value: str) -> str:
        return validate_test_database_url(value)

    def __repr__(self) -> str:
        fields = ", ".join(
            (
                f"bot_token={_MASKED!r}",
                f"admin_id={self.admin_id!r}",
                f"database_url={mask_dsn(self.database_url)!r}",
                f"test_database_url={mask_dsn(self.test_database_url)!r}",
                f"collect_interval_minutes={self.collect_interval_minutes!r}",
                f"digest_size_default={self.digest_size_default!r}",
                f"digest_catchup_minutes={self.digest_catchup_minutes!r}",
                f"retention_days={self.retention_days!r}",
                f"cleanup_time={self.cleanup_time!r}",
                f"http_timeout_seconds={self.http_timeout_seconds!r}",
            )
        )
        return f"Settings({fields})"

    def __str__(self) -> str:
        return self.__repr__()


def mask_dsn(url: str) -> str:
    """DSN с маскированным паролем userinfo (F-12, SEC-08); само значение не меняется."""
    try:
        parts = urlsplit(url)
        netloc = parts.netloc
        if "@" in netloc:
            userinfo, host = netloc.rsplit("@", 1)
            if ":" in userinfo:
                userinfo = userinfo.split(":", 1)[0] + ":" + _MASKED
            netloc = f"{userinfo}@{host}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:  # noqa: BLE001 - repr не должен падать ни на каком DSN
        return _MASKED


def validate_test_database_url(url: str) -> str:
    """Возвращает ``url``, если имя тестовой БД оканчивается на ``_test`` (R29).

    Исключения: ``ValueError`` — рабочая БД в тестах запрещена.
    """
    if not isinstance(url, str) or not url:
        raise ValueError("test database URL must be a non-empty string")
    name = urlsplit(url).path.rsplit("/", 1)[-1]
    if not name.endswith("_test"):
        raise ValueError(
            "test database name must end with _test "
            f"(got {name!r}); refusing to run against a non-test database"
        )
    return url


settings = Settings()
