"""Профиль пользователя и расписание (api.md §5).

``profile_from_jsonb`` строгий: любой битый вход — только ``ValueError``
(SEC-13/P-SEC-02); ``parse_tz`` отклоняет пути (SEC-14) и любой мусор
(P-UX-01). Свойство: ``profile_from_jsonb(profile_to_jsonb(p)) == p``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, timedelta, timezone
from datetime import time as dt_time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.i18n import Lang

_HHMM_RE = re.compile(r"([0-9]{2}):([0-9]{2})")
_UTC_OFFSET_RE = re.compile(r"UTC([+-])([0-9]{1,2})")
_IANA_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+)*")
_INT64_MAX = 2**63 - 1

REQUIRED_KEYS = (
    "lang",
    "presets",
    "min_salary_rub",
    "work_format",
    "stop_words",
    "digest_size",
    "schedule",
)


@dataclass(frozen=True)
class Schedule:
    """Время дайджеста в таймзоне пользователя (IANA или ``UTC±N``)."""

    local_time: dt_time
    tz: str


@dataclass(frozen=True)
class Profile:
    """Настройки подписки; ``schedule is None`` → дайджест не отправляется (AC-18)."""

    lang: Lang
    presets: list[str] = field(default_factory=list)
    min_salary_rub: int | None = None
    work_format: str | None = None
    stop_words: list[str] = field(default_factory=list)
    digest_size: int = 10
    schedule: Schedule | None = None


def parse_hhmm(raw: str) -> dt_time:
    """Строгий ``HH:MM`` (ASCII-цифры, без хвостовых пробелов); иначе ``ValueError``."""
    if not isinstance(raw, str):
        raise ValueError("time must be a string")
    match = _HHMM_RE.fullmatch(raw)
    if match is None:
        raise ValueError("time must look like HH:MM")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("time must be within 00:00-23:59")
    return dt_time(hour, minute)


def parse_tz(raw: str) -> ZoneInfo | timezone:
    """IANA-ключ или ``UTC±N``; путь/мусор — ``ValueError`` (SEC-14)."""
    if not isinstance(raw, str) or not raw:
        raise ValueError("timezone must be a non-empty string")
    offset = _UTC_OFFSET_RE.fullmatch(raw)
    if offset is not None:
        hours = int(offset.group(2))
        if hours > 14:
            raise ValueError("UTC offset out of range")
        delta = timedelta(hours=hours)
        return timezone(-delta if offset.group(1) == "-" else delta)
    if raw == "UTC":
        return UTC
    if _IANA_RE.fullmatch(raw) is None:
        raise ValueError("timezone must be an IANA key or UTC±N")
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ValueError(f"unknown timezone: {raw!r}") from exc


def profile_to_jsonb(profile: Profile) -> dict[str, Any]:
    """JSONB-представление профиля (round-trip с :func:`profile_from_jsonb`)."""
    schedule: dict[str, str] | None = None
    if profile.schedule is not None:
        schedule = {
            "local_time": profile.schedule.local_time.strftime("%H:%M"),
            "tz": profile.schedule.tz,
        }
    return {
        "lang": profile.lang,
        "presets": list(profile.presets),
        "min_salary_rub": profile.min_salary_rub,
        "work_format": profile.work_format,
        "stop_words": list(profile.stop_words),
        "digest_size": profile.digest_size,
        "schedule": schedule,
    }


def profile_from_jsonb(data: Mapping[str, Any]) -> Profile:
    """Строгий разбор JSONB; битые данные — только ``ValueError`` (SEC-13)."""
    if not isinstance(data, Mapping):
        raise ValueError("profile must be a mapping")
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise ValueError(f"profile is missing keys: {missing}")
    try:
        return _build_profile(data)
    except ValueError:
        raise
    except (TypeError, AttributeError, OverflowError) as exc:
        raise ValueError(f"broken profile data: {exc}") from exc


def _build_profile(data: Mapping[str, Any]) -> Profile:
    lang = data["lang"]
    if lang not in ("ru", "en"):
        raise ValueError("profile.lang must be 'ru' or 'en'")
    presets = _str_list(data["presets"], "presets")
    stop_words = _str_list(data["stop_words"], "stop_words")
    min_salary_rub = data["min_salary_rub"]
    if min_salary_rub is not None and (
        isinstance(min_salary_rub, bool)
        or not isinstance(min_salary_rub, int)
        or not 0 <= min_salary_rub <= _INT64_MAX
    ):
        raise ValueError("profile.min_salary_rub must be an integer or None")
    work_format = data["work_format"]
    if work_format is not None and not isinstance(work_format, str):
        raise ValueError("profile.work_format must be a string or None")
    digest_size = data["digest_size"]
    if (
        isinstance(digest_size, bool)
        or not isinstance(digest_size, int)
        or not 1 <= digest_size <= 50
    ):
        raise ValueError("profile.digest_size must be an integer in 1..50")
    schedule = _parse_schedule(data["schedule"])
    return Profile(
        lang=lang,
        presets=presets,
        min_salary_rub=min_salary_rub,
        work_format=work_format,
        stop_words=stop_words,
        digest_size=digest_size,
        schedule=schedule,
    )


def _str_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"profile.{name} must be a list of strings")
    return list(value)


def _parse_schedule(value: Any) -> Schedule | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("profile.schedule must be a mapping or None")
    if "local_time" not in value or "tz" not in value:
        raise ValueError("profile.schedule needs local_time and tz")
    local_time = parse_hhmm(value["local_time"]) if isinstance(value["local_time"], str) else None
    if local_time is None:
        raise ValueError("profile.schedule.local_time must be HH:MM")
    tz_name = value["tz"]
    if not isinstance(tz_name, str):
        raise ValueError("profile.schedule.tz must be a string")
    parse_tz(tz_name)  # валидация; хранится исходная строка
    return Schedule(local_time=local_time, tz=tz_name)
