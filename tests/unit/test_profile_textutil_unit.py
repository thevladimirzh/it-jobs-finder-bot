"""Юнит-тесты профиля, конфигурации и экранирования.

U-UX-01 (валидация ввода), U-CFG-01 (неполная конфигурация env),
U-TEX-01/02/03 (esc/esc_attr, гигантский текст, обязательность esc).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from datetime import time as dt_time
from zoneinfo import ZoneInfo

import pydantic
import pytest

from app.config import Settings, validate_test_database_url
from app.domain.profile import (
    Profile,
    Schedule,
    parse_hhmm,
    parse_tz,
    profile_from_jsonb,
    profile_to_jsonb,
)
from app.textutil import esc, esc_attr

SETTINGS_KWARGS = {
    "_env_file": None,
    "bot_token": "1000000000:" + "T" * 35,
    "database_url": "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs",
}


# --- U-UX-01 (R15): строгие парсеры времени и таймзоны -----------------------


def test_u_ux01_strict_time_and_timezone_parsers() -> None:
    assert parse_hhmm("09:30") == dt_time(9, 30)
    for bad in ("25:00", "09:60", "9:30", "0930", "09:30\n", "", "0а:30", "０９:３０"):
        with pytest.raises(ValueError):
            parse_hhmm(bad)
    assert parse_tz("Europe/Moscow") == ZoneInfo("Europe/Moscow")
    assert parse_tz("UTC+3") == timezone(timedelta(hours=3))
    assert parse_tz("UTC-5") == timezone(-timedelta(hours=5))
    for bad in ("Mars/Olymp", "UTC+99", "../etc/passwd", "/etc/passwd", "Europe//Moscow", "\x00"):
        with pytest.raises(ValueError):
            parse_tz(bad)


# --- U-UX-01b: round-trip профиля и строгий разбор JSONB ---------------------


def test_u_ux01b_profile_jsonb_round_trip_and_strict_parsing() -> None:
    profile = Profile(
        lang="en",
        presets=["python-backend", "qa"],
        min_salary_rub=150000,
        work_format="удалённо",
        stop_words=["junior"],
        digest_size=50,
        schedule=Schedule(dt_time(9, 30), "Europe/Moscow"),
    )
    assert profile_from_jsonb(profile_to_jsonb(profile)) == profile
    for broken in ({}, {"lang": "ru"}):
        with pytest.raises(ValueError):
            profile_from_jsonb(broken)  # type: ignore[arg-type]
    broken_size = dict(profile_to_jsonb(profile), digest_size=0)
    with pytest.raises(ValueError):
        profile_from_jsonb(broken_size)


# --- U-CFG-01 (R30): неполная конфигурация env падает явно --------------------


def test_u_cfg01_missing_bot_token_fails_explicitly(monkeypatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with pytest.raises(pydantic.ValidationError) as excinfo:
        Settings(**{k: v for k, v in SETTINGS_KWARGS.items() if k != "bot_token"})
    assert "bot_token" in str(excinfo.value)
    with pytest.raises(ValueError):
        validate_test_database_url("postgresql+asyncpg://jobs:jobs@localhost:5432/jobs_prod")
    test_url = "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs_test"
    assert validate_test_database_url(test_url) == test_url


# --- U-CFG-02 (F-12, SEC-08): repr/str не показывают пароль из DSN -----------


def test_u_cfg02_repr_masks_database_password() -> None:
    secret = "Sup3r" + "Secret" + "DbPass" + "w0rd"
    settings = Settings(
        **{
            **SETTINGS_KWARGS,
            "admin_id": 1000,
            "database_url": f"postgresql+asyncpg://jobs:{secret}@db:5432/jobs",
            "test_database_url": f"postgresql+asyncpg://jobs:{secret}@db:5432/jobs_test",
        }
    )
    for rendered in (repr(settings), str(settings), f"{settings!r}"):
        assert secret not in rendered, f"U-CFG-02: пароль DSN в строке настроек: {rendered[:120]!r}"
        assert "jobs:***@" in rendered, f"U-CFG-02: DSN не замаскирован: {rendered[:120]!r}"
    # значение при этом не меняется (использование подключения сохраняется)
    assert settings.database_url.endswith(f":{secret}@db:5432/jobs")
    assert secret in settings.database_url and secret in settings.test_database_url


# --- U-TEX-01/02/03 (R7, R25, R38) -------------------------------------------


def test_u_tex01_esc_is_total_and_reversible() -> None:
    for raw in ("<script>alert(1)</script>", "a&b", "\x00\u202e\udc00"):
        out = esc(raw)
        assert "<" not in out and ">" not in out
        assert "&lt;" in out or "<" not in raw
    assert esc_attr('a"b<c>') == "a&quot;b&lt;c&gt;"


def test_u_tex02_huge_hostile_text_never_crashes() -> None:
    hostile = ("A\udc00\u202e\x00<B>&" * 80_000)[:1_000_000]
    out = esc(hostile)
    assert len(out) > 1_000_000  # данные не потеряны
    assert "<" not in out and ">" not in out
    assert '"' not in esc_attr(hostile)


def test_u_tex03_render_paths_escape_external_text() -> None:
    """U-TEX-03 (R38): рендер-пути не пропускают чужую разметку."""
    from app.collectors.base import Vacancy
    from app.services.digest import render_card, render_empty, render_header

    now = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
    vacancy = Vacancy(
        title="<script>x</script>",
        company="<b>Co</b> & «Ромашка»",
        salary=None,
        url="https://hh.ru/vacancy/1",
        source="hh.ru",
        published_at=now,
    )
    text = render_card(1, vacancy, "ru", now)
    assert text.count("<b>") == text.count("</b>") == 1
    assert "&lt;script&gt;" in text
    assert "<script>" not in text
    for out in (render_empty("ru"), render_header(1, now.date(), "en")):
        assert "<script" not in out
