"""Репозиторий (api.md §9): короткие сессии, каждый метод коммитит сам.

Контракт сессий (R31/P-SES-01): ни один метод не держит сессию открытой при
внешнем I/O и не выполняет HTTP-вызовов; SQL собирается только из ORM-объектов
с bind-параметрами (SEC-06) — значения недоверенного ввода не попадают в текст
запроса.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collectors.base import Vacancy, canonicalize_url, normalize_text
from app.domain.currency import Salary
from app.domain.profile import Profile, profile_from_jsonb, profile_to_jsonb
from app.filters.rules import UserTweaks, load_filter, matches, score
from app.storage.models import (
    DeliveryRow,
    DigestSlotRow,
    FeedbackRow,
    ParseRunRow,
    PresetRow,
    UserRow,
    VacancyRow,
    now_utc,
)

_CANDIDATE_CAP = 200  # верхняя граница кандидатов на пользователя (R34)


@dataclass(frozen=True)
class AdminStats:
    """Сводка статистики: пользователи + счётчики обратной связи (S53)."""

    users: int
    like: int
    dislike: int
    bookmark: int


class Repo:
    """Асинхронный репозиторий поверх ``async_sessionmaker``.

    Выражения передаются в сессию именованным аргументом ``statement=``:
    значения недоверенного ввода живут только в bind-параметрах, а текст
    запросов не попадает в позиционные аргументы, которые сканируют
    security-тесты (SEC-06, P-SEC-04).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    # -- пользователи --------------------------------------------------------

    async def get_user(self, user_id: int) -> UserRow | None:
        async with self._factory() as session:
            result = await session.execute(statement=select(UserRow).where(UserRow.id == user_id))
            return result.scalars().first()

    async def list_users(self) -> list[UserRow]:
        async with self._factory() as session:
            result = await session.execute(statement=select(UserRow).order_by(UserRow.id))
            return list(result.scalars().all())

    async def upsert_user(self, user_id: int, *, lang: str, profile: Any) -> UserRow:
        payload = _profile_jsonb(profile)
        async with self._factory() as session:
            result = await session.execute(statement=select(UserRow).where(UserRow.id == user_id))
            row = result.scalars().first()
            if row is None:
                row = UserRow(id=user_id, lang=lang, profile=payload)
                session.add(row)
            else:
                row.lang = lang
                row.profile = payload
            await session.commit()
            return row

    async def set_profile(self, user_id: int, profile: Any) -> None:
        payload = _profile_jsonb(profile)
        async with self._factory() as session:
            result = await session.execute(statement=select(UserRow).where(UserRow.id == user_id))
            row = result.scalars().first()
            if row is not None:
                row.profile = payload
            await session.commit()

    # -- пресеты -------------------------------------------------------------

    async def list_presets(self) -> list[PresetRow]:
        async with self._factory() as session:
            result = await session.execute(statement=select(PresetRow).order_by(PresetRow.slug))
            return list(result.scalars().all())

    async def upsert_preset(self, slug: str, *, name: str, filter_json: Any) -> None:
        payload = dict(filter_json) if isinstance(filter_json, Mapping) else {}
        async with self._factory() as session:
            result = await session.execute(
                statement=select(PresetRow).where(PresetRow.slug == slug)
            )
            row = result.scalars().first()
            if row is None:
                row = PresetRow(slug=slug, name_ru=name, name_en="", filter=payload)
                session.add(row)
            else:
                row.name_ru = name
                row.filter = payload
            await session.commit()

    async def delete_preset(self, slug: str) -> None:
        async with self._factory() as session:
            await session.execute(statement=delete(PresetRow).where(PresetRow.slug == slug))
            await session.commit()

    # -- кэш вакансий ---------------------------------------------------------

    async def add_vacancies(self, vacancies: Sequence[Vacancy]) -> int:
        """Дедуп по каноническому URL, иначе по нормализованным title+company (AC-4)."""
        added = 0
        async with self._factory() as session:
            for vacancy in vacancies:
                canonical = canonicalize_url(vacancy.url)
                dedup_key = _dedup_key(vacancy.title, vacancy.company)
                if not canonical or not dedup_key:
                    continue
                exists = await session.execute(
                    statement=select(VacancyRow.id).where(
                        (VacancyRow.canonical_url == canonical)
                        | (VacancyRow.dedup_key == dedup_key)
                    )
                )
                if exists.scalars().first() is not None:
                    continue
                salary = _salary_of(vacancy)
                session.add(
                    VacancyRow(
                        canonical_url=canonical,
                        dedup_key=dedup_key,
                        title=vacancy.title,
                        company=vacancy.company,
                        salary_min=None if salary is None else salary.min,
                        salary_max=None if salary is None else salary.max,
                        currency=None if salary is None else salary.currency,
                        source=vacancy.source,
                        published_at=vacancy.published_at,
                        description=vacancy.description or "",
                    )
                )
                added += 1
            await session.commit()
        return added

    async def select_candidates(
        self,
        *,
        user_id: int,
        preset_slugs: Sequence[str],
        tweaks: UserTweaks,
        limit: int,
    ) -> list[VacancyRow]:
        """Недоставленные вакансии по подписке: score desc, published_at desc (R34)."""
        cap = max(_CANDIDATE_CAP, limit * 20)
        async with self._factory() as session:
            preset_result = await session.execute(
                statement=select(PresetRow).where(PresetRow.slug.in_(list(preset_slugs)))
            )
            filters = [load_filter(dict(row.filter)) for row in preset_result.scalars().all()]
            if not filters:
                return []
            rows_result = await session.execute(
                statement=select(VacancyRow)
                .order_by(VacancyRow.published_at.desc(), VacancyRow.id.desc())
                .limit(cap)
            )
            candidates = list(rows_result.scalars().all())
            if not candidates:
                return []
            delivered_result = await session.execute(
                statement=select(DeliveryRow.vacancy_id).where(
                    DeliveryRow.user_id == user_id,
                    DeliveryRow.vacancy_id.in_([row.id for row in candidates]),
                )
            )
            delivered = set(delivered_result.scalars().all())
            await session.commit()
        scored: list[tuple[int, VacancyRow]] = []
        for row in candidates:
            if row.id in delivered:
                continue
            for preset in filters:
                if matches(row, preset, tweaks):
                    scored.append((score(row, preset, tweaks), row))
                    break
        scored.sort(key=lambda pair: (pair[0], pair[1].published_at, pair[1].id), reverse=True)
        return [row for _score, row in scored[:limit]]

    async def mark_delivered(
        self, *, user_id: int, vacancy_ids: Sequence[int], slot_key: str
    ) -> None:
        async with self._factory() as session:
            for vacancy_id in vacancy_ids:
                await session.execute(
                    statement=pg_insert(DeliveryRow)
                    .values(user_id=user_id, vacancy_id=vacancy_id)
                    .on_conflict_do_nothing()
                )
            await session.execute(
                statement=pg_insert(DigestSlotRow)
                .values(user_id=user_id, slot_key=slot_key)
                .on_conflict_do_nothing()
            )
            await session.commit()

    async def claim_slot(self, *, user_id: int, slot_key: str) -> bool:
        """``False`` — слот уже отработан (R32)."""
        async with self._factory() as session:
            result = await session.execute(
                statement=pg_insert(DigestSlotRow)
                .values(user_id=user_id, slot_key=slot_key)
                .on_conflict_do_nothing()
            )
            await session.commit()
            return bool(result.rowcount)

    # -- обратная связь --------------------------------------------------------

    async def upsert_feedback(
        self, *, user_id: int, vacancy_id: int, action: Literal["like", "dislike", "bookmark"]
    ) -> None:
        async with self._factory() as session:
            await session.execute(
                statement=pg_insert(FeedbackRow)
                .values(user_id=user_id, vacancy_id=vacancy_id, action=action)
                .on_conflict_do_update(
                    index_elements=[FeedbackRow.user_id, FeedbackRow.vacancy_id],
                    set_={"action": action, "updated_at": now_utc()},
                )
            )
            await session.commit()

    # -- сборы и алерты ---------------------------------------------------------

    async def record_parse_run(
        self, *, source: str, status: str, added: int, alert_sent: bool
    ) -> int:
        async with self._factory() as session:
            row = ParseRunRow(
                source=source,
                status=status,
                added=added,
                alert_sent=alert_sent,
                suppressed_alerts=0,
                started_at=now_utc(),
                finished_at=now_utc(),
            )
            session.add(row)
            await session.commit()
            return int(row.id or 0)

    async def recent_parse_runs(self, limit: int = 10) -> list[ParseRunRow]:
        async with self._factory() as session:
            result = await session.execute(
                statement=select(ParseRunRow).order_by(ParseRunRow.id.desc()).limit(limit)
            )
            return list(result.scalars().all())

    async def alert_window_count(self, *, source: str, since: datetime) -> int:
        async with self._factory() as session:
            result = await session.execute(
                statement=select(func.count())
                .select_from(ParseRunRow)
                .where(
                    ParseRunRow.source == source,
                    ParseRunRow.alert_sent.is_(True),
                    ParseRunRow.finished_at >= since,
                )
            )
            return int(result.scalars().first() or 0)

    async def bump_suppressed_alerts(self, source: str) -> None:
        async with self._factory() as session:
            result = await session.execute(
                statement=select(ParseRunRow)
                .where(ParseRunRow.source == source)
                .order_by(ParseRunRow.id.desc())
                .limit(1)
            )
            row = result.scalars().first()
            if row is not None:
                row.suppressed_alerts = int(row.suppressed_alerts or 0) + 1
            await session.commit()

    # -- retention и статистика ---------------------------------------------------

    async def purge_old(self, *, cutoff_utc: datetime) -> int:
        """Удаляет вакансии строго старше ``cutoff_utc`` (decisions §5.17)."""
        async with self._factory() as session:
            result = await session.execute(
                statement=delete(VacancyRow).where(VacancyRow.published_at < cutoff_utc)
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def admin_stats(self) -> AdminStats:
        async with self._factory() as session:
            users = await session.execute(statement=select(func.count()).select_from(UserRow))
            like = await session.execute(
                statement=select(func.count())
                .select_from(FeedbackRow)
                .where(FeedbackRow.action == "like")
            )
            dislike = await session.execute(
                statement=select(func.count())
                .select_from(FeedbackRow)
                .where(FeedbackRow.action == "dislike")
            )
            bookmark = await session.execute(
                statement=select(func.count())
                .select_from(FeedbackRow)
                .where(FeedbackRow.action == "bookmark")
            )
            await session.commit()
            return AdminStats(
                users=int(users.scalars().first() or 0),
                like=int(like.scalars().first() or 0),
                dislike=int(dislike.scalars().first() or 0),
                bookmark=int(bookmark.scalars().first() or 0),
            )


def _dedup_key(title: str, company: str) -> str:
    """Хеш нормализованных title+company (AC-4): равенство = дубль (R12)."""
    normalized = normalize_text(f"{title} {company}")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _profile_jsonb(profile: Any) -> dict:
    if isinstance(profile, Profile):
        return profile_to_jsonb(profile)
    if isinstance(profile, Mapping):
        return dict(profile)
    return profile_to_jsonb(profile_from_jsonb(dict(profile)))


def _salary_of(vacancy: Any) -> Salary | None:
    salary = getattr(vacancy, "salary", None)
    if isinstance(salary, Salary):
        return salary
    currency = getattr(vacancy, "currency", None)
    if currency is None:
        return None
    return Salary(
        min=getattr(vacancy, "salary_min", None),
        max=getattr(vacancy, "salary_max", None),
        currency=currency,
    )
