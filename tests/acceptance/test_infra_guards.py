"""Acceptance-тесты сценариев S72–S78 — гарантии инфраструктуры и запреты.

Чёрный ящик по публичному API (api.md) и наблюдаемым гарантиям тестовой обвязки.
Запрещённые конструкции (AGENTS.md): рабочая БД из тестов (R29, S72), сеть в
тестах (R41, S73), удержание сессии БД при HTTP (R31, S74), Telegram-текст без
экранирования (R38, S78). S76 — публичная команда ``alembic upgrade head``.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, date, datetime
from datetime import time as dt_time

import pydantic
import pytest
from fakes import (
    PERMISSIVE_FILTER,
    PRESET_NAMES_RU,
    REPO_ROOT,
    SOURCE_HH,
    FakeAlertSink,
    FakeClient,
    FakeResponse,
    FakeSender,
    FakeThrottle,
    ProbeSessionFactory,
    hh_list_page,
    make_digest_item,
    make_profile,
    make_schedule,
    make_vacancy,
    migrated_db,
    open_bot,
    real_repo,
    run_alembic,
    send_text,
)
from support import assert_no_raw_markup, ensure_test_env, found_tags, load_attr

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
ON_DATE = date(2026, 3, 14)
TEST_DB_URL = "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs_test"
PROD_DB_URL = "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs_prod"


# --- S72 (@R29): тестовая БД обязана оканчиваться на _test -------------------


def test_s72_non_test_database_url_rejected_before_any_test() -> None:
    """@S72: запуск с TEST_DATABASE_URL=jobs_prod завершается ошибкой до тестов."""
    ensure_test_env()
    validate = load_attr("app.config", "validate_test_database_url")
    with pytest.raises(ValueError):
        validate(PROD_DB_URL)
    assert validate(TEST_DB_URL) == TEST_DB_URL, "@S72: валидный _test-URL отклонён"

    # «чистая команда тестов» с рабочей БД падает до выполнения тестов
    # (полная команда pytest в подпроцессе ушла бы в рекурсию — запускается
    # чистый прогон smoke-модуля; guard обязан сработать уже на старте).
    env = {**os.environ, "TEST_DATABASE_URL": PROD_DB_URL}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_smoke.py", "-q"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0, f"@S72: прогон с jobs_prod прошёл: {proc.stdout!r}"
    assert "passed" not in proc.stdout, f"@S72: тесты выполнились с рабочей БД: {proc.stdout!r}"


# --- S73 (@R41): тесты не ходят в сеть ---------------------------------------


async def test_s73_collectors_never_open_network_connections(monkeypatch) -> None:
    """@S73: коллекторы работают только через FakeClient; сокет запрещён и падает."""

    def _forbid(*args, **kwargs):
        raise AssertionError("@S73: попытка сетевого соединения из теста (R41)")

    monkeypatch.setattr(socket.socket, "connect", _forbid)
    monkeypatch.setattr(socket, "create_connection", _forbid)

    build_collectors = load_attr("app.collectors", "build_collectors")
    collector_error = load_attr("app.collectors", "CollectorError")
    client = FakeClient.for_sources(hh=FakeResponse(text=hh_list_page()))
    for collector in build_collectors():
        try:
            collected = await collector.collect(client)
        except Exception as exc:  # noqa: BLE001 - допустимы только ошибки источника
            assert isinstance(exc, collector_error), (
                f"@S73: коллектор упал не ошибкой источника: {exc!r}"
            )
        else:
            assert collected, f"@S73: коллектор {collector.name} дал пустой результат молча"
    assert client.calls, "@S73: HTTP не прошёл через FakeClient — проверка вакуумна"


# --- S74 (@R31): сессии БД не удерживаются на время HTTP-вызовов -------------


async def test_s74_db_sessions_not_held_during_http() -> None:
    """@S74: задержанный HTTP не держит сессии; параллельные запросы к БД проходят."""
    run_collect = load_attr("app.services.collect", "run_collect")
    repo_cls = load_attr("app.storage.repo", "Repo")
    probe = ProbeSessionFactory()
    repo = repo_cls(probe)
    client = FakeClient.for_sources(
        hh=FakeResponse(text=hh_list_page()),
        habr=FakeResponse(text=hh_list_page()),
        fallback=FakeResponse(text=hh_list_page()),
    )
    client.delay = 0.05
    client.on_request = lambda url: probe.assert_none_open(f"HTTP-запрос {url[:40]!r}")

    async def parallel_db_tasks() -> None:
        for i in range(10):
            await repo.get_user(i)

    await asyncio.gather(
        run_collect(client=client, repo=repo, alerts=FakeAlertSink(), now=NOW),
        parallel_db_tasks(),
    )
    probe.assert_none_open("после завершения сбора")
    assert probe.sessions, "@S74: сессии не открывались — проверка R31 вакуумна"


# --- S75 (@R34): отбор дайджеста укладывается в минуту -----------------------


async def test_s75_digest_job_finishes_within_a_minute_at_scale() -> None:
    """@S75: ~100k вакансий, 1000 пользователей — job выборки быстрее минуты."""
    from sqlalchemy import insert

    check_schedules = load_attr("app.services.scheduler", "check_schedules")
    profile_to_jsonb = load_attr("app.domain.profile", "profile_to_jsonb")
    async with real_repo() as db:
        await db.repo.upsert_preset(
            "python-backend", name=PRESET_NAMES_RU["python-backend"], filter_json=PERMISSIVE_FILTER
        )
        published = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
        vacancies_table = db.base.metadata.tables["vacancies"]
        users_table = db.base.metadata.tables["users"]
        async with db.engine.begin() as conn:
            vacancy_rows = [
                {
                    "canonical_url": f"https://hh.ru/vacancy/{i}",
                    "dedup_key": f"python developer company{i}",
                    "title": f"Python Developer {i}",
                    "company": f"Company {i}",
                    "salary_min": 100000,
                    "salary_max": None,
                    "currency": "RUB",
                    "source": SOURCE_HH,
                    "published_at": published,
                    "description": "python",
                    "created_at": published,
                }
                for i in range(100_000)
            ]
            for start in range(0, len(vacancy_rows), 10_000):
                await conn.execute(insert(vacancies_table), vacancy_rows[start : start + 10_000])
            profile_json = dict(
                profile_to_jsonb(
                    make_profile(schedule=make_schedule(dt_time(9, 30), "Europe/Moscow"))
                )
            )
            user_rows = [
                {"id": 10_000 + i, "lang": "ru", "profile": profile_json, "created_at": published}
                for i in range(1000)
            ]
            for start in range(0, len(user_rows), 500):
                await conn.execute(insert(users_table), user_rows[start : start + 500])

        sender, throttle = FakeSender(), FakeThrottle()
        started = time.perf_counter()
        await check_schedules(
            repo=db.repo,
            sender=sender,
            throttle=throttle,
            now=datetime(2026, 3, 14, 6, 30, tzinfo=UTC),
        )
        elapsed = time.perf_counter() - started
        assert elapsed < 60, f"@S75: job выборки {elapsed:.1f}s ≥ 60s при 100k/1000"
        assert len(sender.sent) >= 1, f"@S75: дайджесты не отправлены: {sender.sent!r}"


# --- S76 (@R37): миграции на чистой БД + сиды пресетов -----------------------


async def test_s76_alembic_upgrade_on_clean_db_matches_models() -> None:
    """@S76: alembic upgrade head успешно; схема = модели; сид создаёт 7 пресетов."""
    from sqlalchemy import inspect as sa_inspect

    async with migrated_db() as db:
        assert db.migration.returncode == 0, (
            f"@S76: alembic upgrade head завершился ошибкой: {db.migration.stderr}"
        )
        async with db.engine.connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: set(sa_inspect(sync_conn).get_table_names())
            )
        expected = set(db.base.metadata.tables)
        actual = tables - {"alembic_version"}
        assert actual == expected, (
            f"@S76: схема БД != модели: только в БД {sorted(actual - expected)}, "
            f"только в моделях {sorted(expected - actual)}"
        )
        presets = await db.repo.list_presets()
        assert len(presets) == 7, f"@S76: сид-миграция создала {len(presets)} пресетов, не 7"
        assert {preset.slug for preset in presets} == set(PRESET_NAMES_RU), (
            f"@S76: slug-и пресетов: {sorted(preset.slug for preset in presets)}"
        )
        assert run_alembic("current").returncode == 0, "@S76: alembic current падает"


# --- S77 (@R30): неполная конфигурация env → явная ошибка на старте ----------


def test_s77_missing_bot_token_fails_startup_explicitly(monkeypatch, tmp_path) -> None:
    """@S77: без BOT_TOKEN — ошибка конфигурации с именем переменной; без частичного старта."""
    ensure_test_env()
    settings_cls = load_attr("app.config", "Settings")
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    with pytest.raises(pydantic.ValidationError) as excinfo:
        settings_cls(_env_file=None)
    assert "bot_token" in str(excinfo.value), (
        f"@S77: ошибка конфигурации не называет переменную: {excinfo.value}"
    )

    env = {key: value for key, value in os.environ.items() if key != "BOT_TOKEN"}
    env["PYTHONPATH"] = str(REPO_ROOT)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.main"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - диагностика регрессии
        raise AssertionError(
            "@S77: приложение стартовало без BOT_TOKEN вместо ошибки конфигурации"
        ) from exc
    assert proc.returncode != 0, f"@S77: запуск без BOT_TOKEN успешен: {proc.stdout!r}"
    assert "bot_token" in (proc.stdout + proc.stderr).lower(), (
        f"@S77: в ошибке нет имени переменной: {(proc.stdout + proc.stderr)!r}"
    )


# --- S78 (@R38 @R7): весь Telegram-текст проходит через экранирование --------


async def test_s78_all_output_paths_escape_external_text() -> None:
    """@S78: во всех путях вывода внешний текст экранирован; своих тегов ввод не даёт."""
    render_card = load_attr("app.services.digest", "render_card")
    render_digest = load_attr("app.services.digest", "render_digest")
    render_empty = load_attr("app.services.digest", "render_empty")
    render_header = load_attr("app.services.digest", "render_header")

    hostile = make_vacancy(
        title="<script>alert(1)</script> Developer",
        company='ООО "Ромашка" & <b>Co</b>',
        salary=None,
        url="https://hh.ru/vacancy/781",
        source=SOURCE_HH,
        published_at=NOW,
    )
    outputs = {
        "карточка": render_card(1, hostile, "ru", NOW),
        "дайджест": "\n\n".join(
            render_digest([make_digest_item(1, hostile)], lang="ru", now=NOW, on_date=ON_DATE)
        ),
        "пустой дайджест": render_empty("ru"),
        "заголовок": render_header(1, ON_DATE, "ru"),
    }
    for where, text in outputs.items():
        assert_no_raw_markup(text, f"@S78 {where}")
        assert set(found_tags(text)) <= {"b"}, f"@S78 {where}: недопустимые теги в {text!r}"
        assert "<script>" not in text, f"@S78 {where}: чужой тег в тексте: {text!r}"
    assert "&lt;script&gt;" in outputs["карточка"], "@S78: заголовок не экранирован"

    # ответы команд не отражают пользовательский ввод в разметку
    async with open_bot() as h:
        reply = await send_text(h, 1401, "/like <script>alert(1)</script>")
        joined = "\n".join(reply)
        assert "<script>" not in joined, f"@S78: ответ команды несёт чужую разметку: {joined!r}"
        assert_no_raw_markup(joined, "@S78 ответ команды")
