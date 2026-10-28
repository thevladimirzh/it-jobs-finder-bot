"""Слоты расписания (api.md §14): локальное время, DST, ключи слотов."""

from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import time as dt_time

from app.domain.profile import Schedule, parse_tz


def local_slot(schedule: Schedule, day: date) -> datetime:
    """Слот в таймзоне пользователя; «дыра» DST — первый существующий момент (R6).

    Для несуществующего локального времени (перевод часов вперёд) слот
    сдвигается на первый существующий момент после «дыры» (acceptance-map §6.6:
    допустим и 03:00, и сдвиг самой даты — 03:30).
    """
    tz = parse_tz(schedule.tz)
    naive = datetime.combine(day, schedule.local_time or dt_time(0, 0))
    slot = naive.replace(tzinfo=tz)
    normalized = slot.astimezone(UTC).astimezone(tz)
    if normalized.replace(tzinfo=None) != naive:
        return normalized  # «дыра» DST: первый существующий момент
    return slot


def slot_key(user_id: int, schedule: Schedule, day: date) -> str:
    """Ключ слота: одно наступление в сутки, без дублей при overlap (R32)."""
    return make_slot_key(user_id, schedule, day)


def make_slot_key(user_id: int, schedule: Schedule | None, day: date) -> str:
    if schedule is None:
        stamp = "none"
        tz_name = "UTC"
    else:
        stamp = schedule.local_time.strftime("%H:%M")
        tz_name = schedule.tz
    return f"{user_id}|{tz_name}|{stamp}|{day.isoformat()}"


def local_day(schedule: Schedule | None, now: datetime) -> date:
    """Локальная дата слота для момента ``now`` (UTC-день, если расписания нет)."""
    if schedule is None:
        return now.date()
    tz = parse_tz(schedule.tz)
    return now.astimezone(tz).date()
