"""Acceptance-тесты сценариев S61–S62 — retention (очистка старых вакансий).

Чёрный ящик: ``app.services.scheduler.run_cleanup`` (api.md §14) поверх
реального ``Repo`` на тестовой БД: удаление — фактическое (AC-11). Решение
decisions §5.17: удаляется строго старше now − RETENTION_DAYS (ровно 30 дней
остаётся до следующего запуска); недоставленные удаляются так же (R19).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fakes import (
    PERMISSIVE_FILTER,
    PRESET_NAMES_RU,
    SOURCE_HH,
    make_tweaks,
    make_vacancy,
    real_repo,
)
from support import load_attr

NOW = datetime(2026, 6, 15, 4, 15, tzinfo=UTC)  # CLEANUP_TIME 04:15 UTC


def _vacancy(title: str, age_days: int) -> object:
    return make_vacancy(
        title=title,
        company="Romashka",
        url=f"https://hh.ru/vacancy/{title}",
        source=SOURCE_HH,
        published_at=NOW - timedelta(days=age_days),
    )


async def _cached_titles(db) -> set[str]:
    rows = await db.repo.select_candidates(
        user_id=1,
        preset_slugs=["python-backend"],
        tweaks=make_tweaks(),
        limit=100,
    )
    return {row.title for row in rows}


# --- S61 (@R19): очистка строго старше 30 дней по крону ----------------------


async def test_s61_cleanup_removes_strictly_older_than_30_days() -> None:
    """@S61: 31 день — удалена; ровно 30 дней — остаётся до следующего запуска."""
    run_cleanup = load_attr("app.services.scheduler", "run_cleanup")
    async with real_repo() as db:
        await db.repo.upsert_preset(
            "python-backend", name=PRESET_NAMES_RU["python-backend"], filter_json=PERMISSIVE_FILTER
        )
        await db.repo.add_vacancies(
            [
                _vacancy("старая", 31),
                _vacancy("граница", 30),
                _vacancy("свежая", 5),
            ]
        )
        removed = await run_cleanup(repo=db.repo, now=NOW)
        assert removed == 1, f"@S61: удалено {removed}, ожидалась ровно 1 (31 день)"
        titles = await _cached_titles(db)
        assert titles == {"граница", "свежая"}, f"@S61: в кэше остались {titles}"


# --- S62 (@R19): недоставленные вакансии тоже удаляются ----------------------


async def test_s62_cleanup_removes_undelivered_vacancies() -> None:
    """@S62: «дыры» в подборке принимаются: недоставленная старая вакансия удаляется."""
    run_cleanup = load_attr("app.services.scheduler", "run_cleanup")
    async with real_repo() as db:
        await db.repo.upsert_preset(
            "python-backend", name=PRESET_NAMES_RU["python-backend"], filter_json=PERMISSIVE_FILTER
        )
        undelivered = _vacancy("пропущенная", 45)
        await db.repo.add_vacancies([undelivered, _vacancy("свежая", 2)])
        titles_before = await _cached_titles(db)
        assert "пропущенная" in titles_before, f"@S62: старая вакансия не в кэше: {titles_before}"

        await run_cleanup(repo=db.repo, now=NOW)
        titles_after = await _cached_titles(db)
        assert "пропущенная" not in titles_after, (
            f"@S62: недоставленная вакансия старше 30 дней не удалена: {titles_after}"
        )
        assert "свежая" in titles_after, f"@S62: свежая вакансия удалена: {titles_after}"
