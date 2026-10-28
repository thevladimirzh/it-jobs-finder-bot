"""E2E: гварды БД, конкурентность, производительность, миграции, обратная связь.

Обязательства acceptance-map §4: E2E-GUARD-01 (R29), E2E-CONC-01 (R31),
E2E-CONC-02 (R32), E2E-PERF-01 (R34), E2E-PERF-02 (R35), E2E-MIG-01 (R37),
E2E-BTN-01 (R5). Тесты пропускаются, если PostgreSQL недоступен (AC-1).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from datetime import time as dt_time
from pathlib import Path

import pytest
from fixtures import postgres_available
from helpers import PERMISSIVE_FILTER, REPO_ROOT, BotHarness

from app.config import settings as app_settings
from app.config import validate_test_database_url
from app.domain.profile import Profile, Schedule, profile_to_jsonb
from app.storage.db import build_engine, build_session_factory
from app.storage.models import Base
from app.storage.repo import Repo

pytestmark = pytest.mark.skipif(
    not postgres_available(), reason="PostgreSQL недоступен — e2e пропущены"
)

NOW = datetime(2026, 6, 15, 7, 30, tzinfo=UTC)


@asynccontextmanager
async def _db() -> AsyncIterator[tuple[Repo, object]]:
    """Чистая тестовая БД + реальный Repo."""
    engine = build_engine(validate_test_database_url(app_settings.test_database_url))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        yield Repo(build_session_factory(engine)), engine
    finally:
        await engine.dispose()


class _Vacancy:
    _next = 0

    def __init__(self, title: str, company: str = "Romashka", **values: object) -> None:
        _Vacancy._next += 1
        self.title = title
        self.company = company
        self.salary = None
        self.url = f"https://hh.ru/vacancy/e2e-{_Vacancy._next}"
        self.source = "hh.ru"
        self.published_at = datetime(2026, 6, 14, 9, 0, tzinfo=UTC)
        self.description = ""
        self.__dict__.update(values)


class _Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_html(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    def texts_for(self, user_id: int) -> list[str]:
        return [text for chat, text in self.sent if chat == user_id]


class _Throttle:
    async def wait(self) -> None:
        return None


# --- E2E-GUARD-01 (R29): тестовая БД только с суффиксом _test ----------------


def test_e2e_guard01_only_test_database_is_accepted() -> None:
    with pytest.raises(ValueError):
        validate_test_database_url("postgresql+asyncpg://jobs:jobs@localhost:5432/jobs")
    assert validate_test_database_url(app_settings.test_database_url).endswith("_test")


# --- E2E-CONC-01 (R31): сессии БД не удерживаются при HTTP -------------------


def test_e2e_conc01_no_db_session_held_during_http() -> None:
    from app.services.collect import run_collect

    class _Result:
        rowcount = 0

        def __await__(self):
            async def _done():
                return self

            return _done().__await__()

        def scalars(self):
            return self

        def all(self):
            return []

        def first(self):
            return None

    class _Session(_Result):
        def __init__(self) -> None:
            self.closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            self.closed = True
            return False

        async def close(self):
            self.closed = True

        async def commit(self):
            return None

        def add(self, obj):
            return None

        def __getattr__(self, name):
            def _recorded(*args, **kwargs):
                return _Result()

            return _recorded

    class _Factory:
        def __init__(self) -> None:
            self.sessions: list[_Session] = []

        def __call__(self, *args, **kwargs):
            session = _Session()
            self.sessions.append(session)
            return session

    class _Client:
        def __init__(self, factory: _Factory) -> None:
            self.factory = factory

        async def get(self, url, *, headers=None):  # noqa: ANN001, ANN202
            assert all(s.closed for s in self.factory.sessions), "сессия БД удерживается при HTTP"

            class _Resp:
                text = ""
                status_code = 200
                headers: dict[str, str] = {}

            return _Resp()

    class _Alerts:
        async def send_admin(self, text: str) -> None:
            return None

    factory = _Factory()
    repo = Repo(factory)

    async def go() -> None:
        await run_collect(client=_Client(factory), repo=repo, alerts=_Alerts(), now=NOW)

    asyncio.run(go())
    assert factory.sessions, "сессии не открывались — проверка R31 вакуумна"
    assert all(session.closed for session in factory.sessions)


# --- E2E-CONC-02 (R32): слот отрабатывает один раз при гонке -----------------


def test_e2e_conc02_concurrent_slot_processing_sends_once() -> None:
    from app.services.scheduler import check_schedules

    async def go() -> tuple[_Sender, Repo]:
        async with _db() as (repo, _engine):
            profile = Profile(
                lang="ru",
                presets=["python-backend"],
                digest_size=10,
                schedule=Schedule(dt_time(9, 30), "Europe/Moscow"),
            )
            for user_id in (1, 2, 3):
                await repo.upsert_user(user_id, lang="ru", profile=profile_to_jsonb(profile))
            await repo.upsert_preset(
                "python-backend", name="Python Backend", filter_json=PERMISSIVE_FILTER
            )
            await repo.add_vacancies([_Vacancy(f"Vacancy {n}") for n in range(5)])
            sender = _Sender()
            await asyncio.gather(
                *[
                    check_schedules(
                        repo=repo,
                        sender=sender,
                        throttle=_Throttle(),
                        now=datetime(2026, 6, 15, 6, 30, tzinfo=UTC),
                    )
                    for _ in range(3)
                ]
            )
            return sender, repo

    sender, _repo = asyncio.run(go())
    for user_id in (1, 2, 3):
        assert len(sender.texts_for(user_id)) == 1, f"пользователь {user_id}: {sender.sent!r}"


# --- E2E-PERF-01 (R34): digest-job укладывается в минуту на масштабе ---------


def test_e2e_perf01_digest_job_within_minute_at_scale() -> None:
    from sqlalchemy import insert

    from app.services.scheduler import check_schedules

    async def go() -> float:
        async with _db() as (repo, engine):
            await repo.upsert_preset(
                "python-backend", name="Python Backend", filter_json=PERMISSIVE_FILTER
            )
            profile = Profile(
                lang="ru",
                presets=["python-backend"],
                digest_size=10,
                schedule=Schedule(dt_time(9, 30), "Europe/Moscow"),
            )
            payload = profile_to_jsonb(profile)
            vacancies_table = Base.metadata.tables["vacancies"]
            users_table = Base.metadata.tables["users"]
            async with engine.begin() as conn:
                rows = [
                    {
                        "canonical_url": f"https://hh.ru/vacancy/perf-{i}",
                        "dedup_key": f"perf-{i}",
                        "title": f"Python Developer {i}",
                        "company": f"Company {i}",
                        "salary_min": None,
                        "salary_max": None,
                        "currency": None,
                        "source": "hh.ru",
                        "published_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
                        "description": "python",
                        "created_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
                    }
                    for i in range(20_000)
                ]
                for start in range(0, len(rows), 5_000):
                    await conn.execute(insert(vacancies_table), rows[start : start + 5_000])
                users = [
                    {
                        "id": 20_000 + i,
                        "lang": "ru",
                        "profile": payload,
                        "created_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
                    }
                    for i in range(200)
                ]
                await conn.execute(insert(users_table), users)
            sender = _Sender()
            started = time.perf_counter()
            await check_schedules(
                repo=repo,
                sender=sender,
                throttle=_Throttle(),
                now=datetime(2026, 6, 15, 6, 30, tzinfo=UTC),
            )
            elapsed = time.perf_counter() - started
            assert len(sender.sent) >= 1, "дайджесты не отправлены"
            return elapsed

    assert asyncio.run(go()) < 60, "digest-job не уложился в минуту на масштабе 20k/200"


# --- E2E-PERF-02 (R35): тяжёлая страница не блокирует бота -------------------


def test_e2e_perf02_heavy_page_parse_keeps_loop_responsive() -> None:
    from app.collectors.base import parse_cards

    page = (REPO_ROOT / "tests" / "data" / "hh_list.html").read_text(encoding="utf-8")
    heavy = (page + "\n") * 1500
    ticks: list[int] = []

    async def ticker() -> None:
        while True:
            ticks.append(1)
            await asyncio.sleep(0)

    async def go() -> int:
        task = asyncio.create_task(ticker())
        started = time.perf_counter()
        vacancies = await parse_cards(
            heavy,
            source="hh.ru",
            base_url="https://hh.ru",
            container_marker='data-qa="vacancy-serp"',
            card_marker='data-qa="vacancy-serp-item"',
        )
        elapsed = time.perf_counter() - started
        task.cancel()
        assert elapsed < app_settings.http_timeout_seconds, f"разбор {elapsed:.1f}s"
        assert len(ticks) >= 3, "event loop блокировался разбором тяжёлой страницы"
        return len(vacancies)

    assert asyncio.run(go()) >= 1


# --- E2E-MIG-01 (R37): alembic upgrade head на чистой БД ---------------------


def test_e2e_mig01_alembic_upgrade_on_clean_db() -> None:
    url = validate_test_database_url(app_settings.test_database_url)
    engine = build_engine(url)

    async def reset() -> None:
        from sqlalchemy import text

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        await engine.dispose()

    asyncio.run(reset())
    env = {**os.environ, "DATABASE_URL": url}
    alembic_bin = Path(sys.executable).parent / "alembic"
    proc = subprocess.run(
        [str(alembic_bin), "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"alembic upgrade head упал: {proc.stderr}"

    async def check() -> int:

        engine2 = build_engine(url)
        factory = build_session_factory(engine2)
        repo = Repo(factory)
        presets = await repo.list_presets()
        await engine2.dispose()
        return len(presets)

    assert asyncio.run(check()) == 7, "сид-миграция создала не 7 пресетов"


# --- E2E-BTN-01 (R5): команды обратной связи end-to-end ----------------------


def test_e2e_btn01_feedback_commands_end_to_end() -> None:
    async def go() -> tuple[list[str], list[str], list[str]]:
        async with BotHarness() as harness:
            # I-2 (decisions §8): онбординг кнопками — текстовый ввод «lang:ru»
            # и slug-пресета упразднён; время HH:MM остаётся текстом.
            await harness.send("/start", user_id=9001)
            await harness.press("dlg:lang:ru", user_id=9001)
            await harness.press("dlg:preset:python-backend", user_id=9001)
            await harness.press("dlg:preset:done", user_id=9001)
            await harness.press("dlg:format:any", user_id=9001)
            await harness.press("dlg:tz:msk", user_id=9001)
            await harness.send("09:30", user_id=9001)
            await harness.press("dlg:size:10", user_id=9001)
            await harness.seed_vacancies([_Vacancy(f"Python Developer {n}") for n in (1, 2, 3)])
            assert await harness.deliver_digest(user_id=9001), "дайджест не доставлен"
            like = await harness.send("/like 2", user_id=9001)
            bad = await harness.send("/like 99", user_id=9001)
            bookmark = await harness.send("/bookmark 1", user_id=9001)
            return like, bad, bookmark

    like, bad, bookmark = asyncio.run(go())
    assert like == ["\U0001f44d Учтено"]
    assert bad == [
        "Не понял номер. Отправьте номер карточки из последнего дайджеста (например: /like 3)."
    ]
    assert bookmark == ["\U0001f516 Сохранено"]
