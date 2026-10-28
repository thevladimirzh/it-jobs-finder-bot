"""Выборка дайджеста (api.md §11): at-most-once доставка (Q2, R3).

Отметка о доставке ставится при формировании дайджеста (decisions §5.1):
``claim_slot`` + ``mark_delivered`` — повторный вызов для того же слота
возвращает ``None``; слот ``day`` можно передать явно (check_schedules).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.domain.profile import Profile, profile_from_jsonb
from app.filters.rules import UserTweaks
from app.services.slots import local_day, make_slot_key


@dataclass(frozen=True)
class DigestItem:
    """Карточка дайджеста со сквозным номером ``n`` (с 1)."""

    n: int
    vacancy: Any


@dataclass(frozen=True)
class Selection:
    """Выбранный выпуск: карточки + ключ занятого слота."""

    items: list[DigestItem]
    slot_key: str


async def select_digest(
    *,
    repo: Any,
    user: Any,
    now: datetime,
    limit: int | None = None,
    day: date | None = None,
) -> Selection | None:
    """Недоставленные вакансии под подписку; ``None`` — пусто/слот отработан."""
    if limit is not None and not 1 <= limit <= 50:
        raise ValueError("digest limit must be within 1..50")
    profile = profile_of(user)
    size = limit if limit is not None else profile.digest_size
    if not 1 <= size <= 50:
        raise ValueError("digest size must be within 1..50")
    tweaks = UserTweaks(
        min_salary_rub=profile.min_salary_rub,
        work_format=profile.work_format,
        stop_words=list(profile.stop_words),
    )
    candidates = await repo.select_candidates(
        user_id=user.id,
        preset_slugs=list(profile.presets),
        tweaks=tweaks,
        limit=size,
    )
    if not candidates:
        return None
    key = make_slot_key(user.id, profile.schedule, day or local_day(profile.schedule, now))
    claimed = await repo.claim_slot(user_id=user.id, slot_key=key)
    if not claimed:
        return None
    await repo.mark_delivered(
        user_id=user.id, vacancy_ids=[row.id for row in candidates], slot_key=key
    )
    return Selection(
        items=[DigestItem(n=index, vacancy=row) for index, row in enumerate(candidates, 1)],
        slot_key=key,
    )


def profile_of(user: Any) -> Profile:
    """Профиль из строки пользователя (JSONB-словарь или ``Profile``)."""
    raw = getattr(user, "profile", None)
    if isinstance(raw, Profile):
        return raw
    if isinstance(raw, Mapping):
        return profile_from_jsonb(dict(raw))
    raise ValueError("user profile is missing or broken")
