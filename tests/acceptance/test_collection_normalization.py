"""Acceptance-тесты сценариев S8–S18 — сбор и нормализация вакансий.

Чёрный ящик: публичное API ``app.collectors`` (api.md §6) и
``app.services.collect.run_collect`` (api.md §10) с FakeClient вместо сети (R41).
Точные строки алертов — brief §6.1 (fakes.alert_line). Теги рисков —
tests/features/collection_normalization.feature.

S15: «проблемные фикстуры» моделируются текстовыми артефактами, которые парсер
получает из HTTP-ответа (коллекторы файлы не читают): отсутствие файла → пустое
тело, пустой файл → пробелы, cp1251 → mojibake, BOM → «\\ufeff» + мусор.
S16: нормализация зарплаты проверяется по контракту ``parse_salary`` (api.md §4):
HTML-структура источника спекой не зафиксирована, а результат нормализации —
ровно её предмет. S18: путь текста через ``esc`` + рендер (обрезка {title}).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest
from fakes import (
    BROKEN_MARKUP_HTML,
    CAPTCHA_HTML,
    PERMISSIVE_FILTER,
    SOURCE_HABR,
    SOURCE_HH,
    FakeAlertSink,
    FakeClient,
    FakeResponse,
    InMemoryRepo,
    alert_line,
    habr_list_page,
    hh_empty_page,
    hh_list_page,
    make_tweaks,
    make_vacancy,
    real_repo,
)
from support import app_settings, assert_no_raw_markup, load_attr

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)

FIXTURE_ARTIFACTS = {
    "отсутствующий файл": "",  # файла нет — данных нет вовсе
    "пустой файл": " \n\t ",  # файл есть, но пустой
    "файл в кодировке cp1251": "Р РµР·СЋРјРµ Р·Р°СЂРїР»Р°С‚С‹ РїСЂРѕРіСЂР°РјРјРёСЃС‚Р°",
    "UTF-8 файл с BOM": "\ufeff" + BROKEN_MARKUP_HTML,
}

SALARY_CASES = [
    ("от 150 000 ₽", (150000, None, "RUB")),
    ("до $2000", (None, 2000, "USD")),
    ("100 000 \u2013 200 000 ₽", (100000, 200000, "RUB")),
    ("от 200 000 до 100 000 ₽", (100000, 200000, "RUB")),
    ("от 0 ₽", None),
    ("от -5 000 ₽", None),
    ("от 150\u00a0000 ₽", (150000, None, "RUB")),
    ("от 1,5 млн ₽", (1500000, None, "RUB")),
    ("3000 GBP", (3000, None, "GBP")),
    ("от 99999999999999999999 ₽", None),
    ("мусор", None),
]


def _collector(name: str):
    build_collectors = load_attr("app.collectors", "build_collectors")
    for collector in build_collectors():
        if collector.name == name:
            return collector
    raise AssertionError(f"коллектор с именем {name!r} не найден в build_collectors()")


async def _run_collect(client: FakeClient, repo, alerts) -> list:
    run_collect = load_attr("app.services.collect", "run_collect")
    return await run_collect(client=client, repo=repo, alerts=alerts, now=NOW)


# --- S8 (@R2 @R40): коллекторы дают нормализованные вакансии -----------------


async def test_s08_normalizes_fixture_vacancies() -> None:
    """@S8: из HTML-фикстур — вакансии с полями, каноническим URL, без алертов."""
    canonicalize_url = load_attr("app.collectors", "canonicalize_url")
    client = FakeClient.for_sources(
        hh=FakeResponse(text=hh_list_page()),
        habr=FakeResponse(text=habr_list_page()),
    )
    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)

    assert alerts.texts == [], f"@S8: алерты на валидных страницах: {alerts.texts!r}"
    assert all(report.alert is None for report in reports), f"@S8: алерт в отчёте: {reports!r}"
    assert all(report.status == "ok" for report in reports), f"@S8: статусы сбора: {reports!r}"
    assert repo.vacancies, "@S8: из валидных фикстур не сохранено ни одной вакансии"
    for vacancy in repo.vacancies:
        assert isinstance(vacancy.title, str) and vacancy.title.strip(), f"@S8: title {vacancy!r}"
        assert isinstance(vacancy.company, str) and vacancy.company.strip(), (
            f"@S8: company {vacancy!r}"
        )
        assert hasattr(vacancy, "salary"), f"@S8: нет поля salary {vacancy!r}"
        assert vacancy.source in {SOURCE_HH, SOURCE_HABR}, f"@S8: источник {vacancy.source!r}"
        assert vacancy.published_at is not None and vacancy.published_at.tzinfo is not None, (
            f"@S8: published_at не tz-aware: {vacancy!r}"
        )
        assert canonicalize_url(vacancy.url) == vacancy.url, (
            f"@S8: URL не канонический (схема/хост/без UTM и хвостового '/'): {vacancy.url!r}"
        )


# --- S9 (@R2): битая разметка → ParseError + алерт ----------------------------


async def test_s09_broken_markup_raises_parse_error_with_alert() -> None:
    """@S9: неожиданная вёрстка hh.ru → ParseError, алерт, сбор Habr Career идёт."""
    parse_error = load_attr("app.collectors", "ParseError")
    client = FakeClient.for_sources(
        hh=FakeResponse(text=BROKEN_MARKUP_HTML),
        habr=FakeResponse(text=habr_list_page()),
    )
    with pytest.raises(parse_error):
        await _collector(SOURCE_HH).collect(client)

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HH].status == "parse_error", f"@S9: отчёт hh.ru: {reports!r}"
    assert by_source[SOURCE_HH].alert == alert_line(SOURCE_HH, "ошибка разбора разметки")
    assert by_source[SOURCE_HABR].status == "ok", (
        f"@S9: сбор Habr Career не продолжился: {reports!r}"
    )
    assert alerts.texts == [alert_line(SOURCE_HH, "ошибка разбора разметки")], (
        f"@S9: алерты: {alerts.texts!r}"
    )


# --- S10 (@R1): блокировка/капча → SourceBlocked + алерт ----------------------


async def test_s10_blocked_source_raises_source_blocked_with_alert() -> None:
    """@S10: 403 с капчей Habr Career → SourceBlocked, алерт, сбор hh.ru идёт."""
    source_blocked = load_attr("app.collectors", "SourceBlocked")
    client = FakeClient.for_sources(
        hh=FakeResponse(text=hh_list_page()),
        habr=FakeResponse(text=CAPTCHA_HTML, status_code=403),
    )
    with pytest.raises(source_blocked):
        await _collector(SOURCE_HABR).collect(client)

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HABR].status == "blocked", f"@S10: отчёт Habr Career: {reports!r}"
    assert by_source[SOURCE_HABR].alert == alert_line(SOURCE_HABR, "блокировка/капча")
    assert by_source[SOURCE_HH].status == "ok", f"@S10: сбор hh.ru не продолжился: {reports!r}"
    assert alerts.texts == [alert_line(SOURCE_HABR, "блокировка/капча")], (
        f"@S10: алерты: {alerts.texts!r}"
    )


# --- S11 (@R40 @R2): пустой разбор → EmptyResult + алерт ----------------------


async def test_s11_empty_parse_raises_empty_result_with_alert() -> None:
    """@S11: валидная страница без карточек → EmptyResult, алерт, кэш не пополняется."""
    empty_result = load_attr("app.collectors", "EmptyResult")
    client = FakeClient.for_sources(
        hh=FakeResponse(text=hh_empty_page()),
        habr=FakeResponse(text=habr_list_page()),
    )
    with pytest.raises(empty_result):
        await _collector(SOURCE_HH).collect(client)

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HH].status == "empty", f"@S11: отчёт hh.ru: {reports!r}"
    assert by_source[SOURCE_HH].alert == alert_line(SOURCE_HH, "пустой разбор")
    assert by_source[SOURCE_HH].added == 0, f"@S11: пустой сбор что-то добавил: {reports!r}"
    assert all(v.source != SOURCE_HH for v in repo.vacancies), (
        f"@S11: в кэш попали вакансии пустого разбора: {repo.vacancies!r}"
    )
    assert alerts.texts == [alert_line(SOURCE_HH, "пустой разбор")], (
        f"@S11: алерты: {alerts.texts!r}"
    )


# --- S12 (@R1 @R35): источник недоступен → алерт, кэш пригоден ----------------


async def test_s12_unavailable_source_alerts_and_cache_stays_usable() -> None:
    """@S12: таймаут hh.ru → SourceUnavailable, алерт, кэш остаётся пригодным."""
    source_unavailable = load_attr("app.collectors", "SourceUnavailable")
    client = FakeClient.for_sources(
        hh=TimeoutError("connection timed out"),
        habr=FakeResponse(text=habr_list_page()),
    )
    with pytest.raises(source_unavailable):
        await _collector(SOURCE_HH).collect(client)

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HH].status == "unavailable", f"@S12: отчёт hh.ru: {reports!r}"
    assert by_source[SOURCE_HH].alert == alert_line(SOURCE_HH, "источник недоступен")
    assert alerts.texts == [alert_line(SOURCE_HH, "источник недоступен")], (
        f"@S12: алерты: {alerts.texts!r}"
    )
    rows = await repo.select_candidates(
        user_id=1, preset_slugs=["python-backend"], tweaks=make_tweaks(), limit=10
    )
    assert isinstance(rows, list), f"@S12: кэш непригоден для дайджеста: {rows!r}"


# --- S13 (@R12): дубли по каноническому URL ----------------------------------


@pytest.mark.parametrize(
    "variant",
    [
        "https://hh.ru/vacancy/123",
        "https://hh.ru/vacancy/123/",
        "http://hh.ru/vacancy/123?utm_source=test",
        "https://HH.RU/vacancy/123",
    ],
)
async def test_s13_duplicate_canonical_url_saved_once(variant: str) -> None:
    """@S13: варианты URL одной вакансии канонически равны и не плодят записей."""
    canonicalize_url = load_attr("app.collectors", "canonicalize_url")
    canonical = "https://hh.ru/vacancy/123"
    assert canonicalize_url(variant) == canonicalize_url(canonical), (
        f"@S13: канонические URL различаются: {variant!r}"
    )
    async with real_repo() as db:
        assert await db.repo.add_vacancies([make_vacancy(url=canonical)]) == 1
        assert await db.repo.add_vacancies([make_vacancy(url=variant)]) == 0, (
            f"@S13: дубль {variant!r} сохранён повторно"
        )
        await db.repo.upsert_preset(
            "python-backend", name="Python Backend", filter_json=PERMISSIVE_FILTER
        )
        rows = await db.repo.select_candidates(
            user_id=1, preset_slugs=["python-backend"], tweaks=make_tweaks(), limit=10
        )
        assert len(rows) == 1, f"@S13: в кэше не ровно одна запись: {rows!r}"


# --- S14 (@R12): дубли по нормализованным заголовку и компании ----------------


async def test_s14_duplicate_by_title_and_company_saved_once() -> None:
    """@S14: разные URL/регистр/пунктуация одного оффера → одна запись в кэше."""
    async with real_repo() as db:
        assert (
            await db.repo.add_vacancies(
                [
                    make_vacancy(
                        title="Python Developer",
                        company="ООО «Ромашка»",
                        url="https://hh.ru/vacancy/123",
                        source=SOURCE_HH,
                    )
                ]
            )
            == 1
        )
        assert (
            await db.repo.add_vacancies(
                [
                    make_vacancy(
                        title="  python   developer ",
                        company="ООО Ромашка",
                        url="https://career.habr.com/vacancies/1000",
                        source=SOURCE_HABR,
                    )
                ]
            )
            == 0
        ), "@S14: дубль по заголовку+компании сохранён повторно"
        await db.repo.upsert_preset(
            "python-backend", name="Python Backend", filter_json=PERMISSIVE_FILTER
        )
        rows = await db.repo.select_candidates(
            user_id=1, preset_slugs=["python-backend"], tweaks=make_tweaks(), limit=10
        )
        assert len(rows) == 1, f"@S14: дайджест получил бы обе версии: {rows!r}"


# --- S15 (@R28 @R2): проблемные фикстуры → ParseError, не падение -------------


@pytest.mark.parametrize("fixture", sorted(FIXTURE_ARTIFACTS))
async def test_s15_broken_fixture_artifacts_raise_parse_error(fixture: str) -> None:
    """@S15: артефакты файлов фикстур приводят к ParseError, а не к крашу теста."""
    parse_error = load_attr("app.collectors", "ParseError")
    client = FakeClient.for_sources(hh=FakeResponse(text=FIXTURE_ARTIFACTS[fixture]))
    with pytest.raises(parse_error):  # любое иное исключение провалит тест
        await _collector(SOURCE_HH).collect(client)


# --- S16 (@R22): граничные значения зарплаты ---------------------------------


@pytest.mark.parametrize(("raw", "expected"), SALARY_CASES)
async def test_s16_salary_boundary_values_normalized(raw: str, expected) -> None:
    """@S16: нормализация зарплаты без падений; min/max/currency как в Examples."""
    parse_salary = load_attr("app.domain.currency", "parse_salary")
    result = parse_salary(raw)
    if expected is None:
        assert result is None, f"@S16: {raw!r} должна нормализоваться в None, получено {result!r}"
        return
    minimum, maximum, currency = expected
    assert result is not None, f"@S16: {raw!r} не разобрана"
    assert (result.min, result.max, result.currency) == (minimum, maximum, currency), (
        f"@S16: {raw!r} → {(result.min, result.max, result.currency)}, ожидалось {expected}"
    )


# --- S17 (@R35 @R31): тяжёлая страница не блокирует event loop ---------------


async def test_s17_heavy_page_parse_keeps_event_loop_responsive() -> None:
    """@S17: разбор многомегабайтной страницы не блокирует бота и укладывается в таймаут."""
    page = hh_list_page()
    heavy = (page + "\n") * max(1, 3_000_000 // max(len(page), 1))
    client = FakeClient.for_sources(hh=FakeResponse(text=heavy))
    collector = _collector(SOURCE_HH)

    progress: list[float] = []
    snapshots: list[int] = []
    client.on_request = lambda _url: snapshots.append(len(progress))

    async def ticker() -> None:
        while True:
            progress.append(time.perf_counter())
            await asyncio.sleep(0.001)

    ticker_task = asyncio.create_task(ticker())
    started = time.perf_counter()
    try:
        await collector.collect(client)
    except Exception as exc:  # noqa: BLE001 - различаем ParseError и «падение»
        parse_error = load_attr("app.collectors", "ParseError")
        assert isinstance(exc, parse_error), f"@S17: тяжёлая страница уронила парсер: {exc!r}"
    elapsed = time.perf_counter() - started
    ticker_task.cancel()

    timeout = app_settings().http_timeout_seconds
    assert elapsed <= timeout, f"@S17: разбор {elapsed:.1f}s уложился не в таймаут {timeout}s"
    ticks_during_parse = len(progress) - (snapshots[-1] if snapshots else 0)
    assert ticks_during_parse >= 3, (
        f"@S17: event loop был заблокирован разбором (прогресс фоновых задач "
        f"во время разбора: {ticks_during_parse}) — бот не отвечал на команды"
    )


# --- S18 (@R25 @R7): гигантский внешний текст не ломает нормализацию ----------


async def test_s18_huge_hostile_text_survives_render_path() -> None:
    """@S18: ~1 МБ мусора (NUL, RTL, суррогаты) в тексте — без крашей и обхода esc."""
    render_card = load_attr("app.services.digest", "render_card")
    esc = load_attr("app.textutil", "esc")
    hostile = ("A\udc00\u202e\x00<B>&" * 80_000)[:1_000_000]
    vacancy = make_vacancy(title=hostile, company=hostile[:1000])
    card = render_card(1, vacancy, "ru", NOW)
    assert_no_raw_markup(card, "@S18 карточка")
    escaped_title = esc(hostile)
    assert len(escaped_title) > 1000, "@S18: esc потерял данные гигантского текста"
    inner = card.split("\n", 1)[0].removeprefix("1. <b>").removesuffix("</b>")
    assert len(inner) <= 200, f"@S18: заголовок не обрезан до разумного размера: {len(inner)}"
    assert inner.endswith("\u2026"), f"@S18: обрезка без маркера «…»: {inner[-10:]!r}"
