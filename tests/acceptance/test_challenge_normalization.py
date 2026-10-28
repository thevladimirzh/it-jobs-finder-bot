"""Acceptance-тесты S96–S98 — классификация challenge-страниц (§9.4 редакция 2).

Контракт (decisions §9.4 редакция 2, решение арбитра 28.10.2026, F-22):
- тело нормализуется перед матчингом: HTML-комментарии снимаются (незакрытый —
  до конца), entity декодируются (``&nbsp;``, ``&#45;``), регистр и разделители
  игнорируются — разорванный маркер ``sm<!--x-->art-captcha`` всё равно
  матчится (S97);
- сильные маркеры (ddos-guard, qrator, smart-captcha, «just a moment») дают
  ``SourceBlocked`` ТОЛЬКО в структурных позициях: ``<script>``/``<link>``/
  cookie-атрибуты/``<title>`` (S94 — test_live_markup.py);
- видимый текст (включая карточки вакансий: вакансия «Qrator», фраза «just a
  moment», встроенный JSON-состояние hh.ru) НИКОГДА не блокирует (S96);
- слабые маркеры («captcha»/«access denied») — только в ``<title>``/``<h1>`` (S98).

«Детект маркеров во всём теле ответа / в первых 4096 байтах» — редакция 1
контракта, УСТАРЕЛА (ложные срабатывания на легитимном контенте → постоянная
потеря источника); текущий контракт — нормализация тела + структурные позиции.

Чёрный ящик: публичное API ``app.collectors`` (api.md §6) и
``app.services.collect.run_collect`` (api.md §10); сеть — FakeClient (R41),
часы инжектируются параметром ``now`` (как в test_live_markup.py). Точные
строки алертов — brief §6.1 (``fakes.alert_line``); теги рисков —
``tests/features/collection_normalization.feature`` (@S96..@S98; риски реестра
— R81, см. docs/qa/acceptance-map.md).

Контрольные страницы строятся инлайн по ЖИВЫМ маркерам разметки 28.10.2026
(``data-qa``-ключи hh.ru, как S92/S95 в test_live_markup.py) — управляемые
граничные входы, а не «фикстуры на глаз»: репрезентативные фикстуры
``tests/data/`` — только из живых образцов (решений §9.2).

Дискриминация (тест «не проходит слишком рано»): S96 красен при любом
матчинге маркеров по видимому тексту (редакция 1 «во всём теле»); S97 красен
без нормализации тела (комментарии/entity/регистр); S98+S96 закрепляют границу
слабых маркеров (``<title>``/``<h1>`` — да, JSON-состояние/описание — нет).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fakes import (
    SOURCE_HABR,
    SOURCE_HH,
    FakeAlertSink,
    FakeClient,
    FakeResponse,
    InMemoryRepo,
    alert_line,
    habr_list_page,
)
from support import load_attr

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)

HH_TITLE_1 = "Младший Python-разработчик"
HH_TITLE_2 = "Управляющий аналитик"
HH_COMPANY_1 = "Работодатель 1"
HH_COMPANY_2 = "Работодатель 2"

BLOCKED = "блокировка/капча"
PARSE_ERROR = "ошибка разбора разметки"

# --- S96 (Examples): маркер вне разрешённой позиции не блокирует ---------------
S96_CASES = [
    ("Qrator", "заголовок вакансии"),
    ("just a moment", "описание вакансии"),
    ("qrator", "видимый текст страницы"),
    ("captcha", "описание вакансии"),
    ("access denied", "видимый текст страницы"),
    ("captcha", "JSON-состояние в <script>"),
]

# --- S97 (Examples): разорванный/переиначенный маркер детектится ---------------
# (строка Examples без пояснения в скобках, позиция — реалистичная структурная
# позиция живой challenge-страницы; каждая строка Examples — своя позиция).
S97_CASES = [
    # marker (raw)             | position        | title                    | head-фрагмент
    (
        "SmartCaptcha",
        "cookie-атрибут",
        "Проверка доступа",
        '<div data-cookie="SmartCaptcha=1"></div>',
    ),
    (
        "sm<!--x-->art-captcha",
        "<script>",
        "Проверка доступа",
        '<script>window.challenge_state = "sm<!--x-->art-captcha";</script>',
    ),
    ("just&nbsp;a&nbsp;moment", "<title>", "just&nbsp;a&nbsp;moment", ""),
    (
        "ddos&#45;guard",
        "<link>",
        "Проверка доступа",
        '<link rel="preload" href="https://cdn.example/ddos&#45;guard.js">',
    ),
]

# --- S98 (Examples): слабые маркеры — только <title>/<h1> ---------------------
S98_CASES = [
    ("captcha", "<title>"),
    ("access denied", "<title>"),
    ("captcha", "<h1>"),
    ("access denied", "<h1>"),
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


# --- Живые маркеры hh.ru (28.10.2026) для контрольных страниц -----------------


def _hh_card(title: str, company: str, href: str, *, description: str = "") -> str:
    """Карточка hh.ru по живым маркерам 28.10.2026 (article[data-qa^=...])."""
    desc = f'<div data-qa="vacancy-description">{description}</div>' if description else ""
    return (
        '<article data-qa="vacancy-serp__vacancy" class="magritte-card">'
        f'<a data-qa="serp-item__title" tabindex="0" href="{href}" target="_blank">'
        f'<span data-qa="serp-item__title-text">{title}</span></a>'
        f'<span data-qa="vacancy-serp__vacancy-employer-text">{company}</span>'
        f"{desc}"
        "</article>"
    )


def _hh_page(
    *cards: str,
    title: str = "Работа и вакансии",
    head_extra: str = "",
    body_extra: str = "",
) -> str:
    """Страница выдачи hh.ru с живым контейнером ``vacancy-serp__results``."""
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
        f"<title>{title}</title>{head_extra}"
        "</head><body>"
        f"{body_extra}"
        '<div data-qa="vacancy-serp__results">' + "".join(cards) + "</div></body></html>"
    )


def _regular_cards() -> tuple[str, str]:
    """Две обычные (не промо) карточки с валидными полями."""
    return (
        _hh_card(HH_TITLE_1, HH_COMPANY_1, "https://hh.ru/vacancy/138031041"),
        _hh_card(HH_TITLE_2, HH_COMPANY_2, "https://hh.ru/vacancy/138862394"),
    )


def _page_with_marker_at(marker: str, position: str) -> str:
    """S96: валидные карточки + маркер в неразрешённой позиции (Given)."""
    first, second = _regular_cards()
    if position == "заголовок вакансии":
        first = _hh_card(f"{HH_TITLE_1}: {marker}", HH_COMPANY_1, "https://hh.ru/vacancy/138031041")
        return _hh_page(first, second)
    if position == "описание вакансии":
        first = _hh_card(
            HH_TITLE_1,
            HH_COMPANY_1,
            "https://hh.ru/vacancy/138031041",
            description=f"Обязанности: поддержка сервисов. {marker}",
        )
        return _hh_page(first, second)
    if position == "видимый текст страницы":
        return _hh_page(first, second, body_extra=f"<p>{marker}</p>")
    if position == "JSON-состояние в <script>":
        return _hh_page(
            first,
            second,
            head_extra=f'<script>window.__INITIAL_STATE__ = {{"state": "{marker}"}};</script>',
        )
    raise AssertionError(f"@S96: неизвестная позиция {position!r}")


# --- S96 (@R81): маркер вне разрешённой позиции не блокирует сбор -------------


@pytest.mark.parametrize(("marker", "position"), S96_CASES)
async def test_s96_marker_outside_structural_position_never_blocks(
    marker: str, position: str
) -> None:
    """@S96: маркер challenge в видимом тексте/заголовке/описании/JSON-состоянии
    НЕ даёт SourceBlocked: вакансии возвращаются и сохраняются, алертов нет."""
    source_blocked = load_attr("app.collectors", "SourceBlocked")
    page = _page_with_marker_at(marker, position)
    client = FakeClient.for_sources(
        hh=FakeResponse(text=page),
        habr=FakeResponse(text=habr_list_page()),
    )
    try:
        vacancies = await _collector(SOURCE_HH).collect(client, now=NOW)
    except source_blocked as exc:  # noqa: B014 - фиксация запрещённого исключения
        pytest.fail(
            f"@S96[{marker} / {position}]: маркер вне структурной позиции дал "
            f"SourceBlocked (ложное срабатывание, потеря источника): {exc!r}"
        )
    assert len(vacancies) == 2, (
        f"@S96[{marker} / {position}]: коллектор вернул не 2 вакансии: {vacancies!r}"
    )

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HH].status == "ok", f"@S96[{marker} / {position}]: отчёт: {reports!r}"
    assert by_source[SOURCE_HH].added == 2, f"@S96[{marker} / {position}]: отчёт: {reports!r}"
    saved = [vacancy for vacancy in repo.vacancies if vacancy.source == SOURCE_HH]
    assert sorted(vacancy.title for vacancy in saved) == sorted(
        [vacancies[0].title, vacancies[1].title]
    ), f"@S96[{marker} / {position}]: карточки не сохранены в кэш: {repo.vacancies!r}"
    assert alerts.texts == [], (
        f"@S96[{marker} / {position}]: алерты на легитимном контенте: {alerts.texts!r}"
    )


# --- S97 (@R81): разорванный/переиначенный маркер детектится -----------------


@pytest.mark.parametrize(("marker", "position", "title", "head_extra"), S97_CASES)
async def test_s97_obfuscated_challenge_marker_still_detected(
    marker: str, position: str, title: str, head_extra: str
) -> None:
    """@S97: маркер, разорванный комментарием/entity или переиначенный регистром,
    всё равно классифицируется как SourceBlocked (нормализация тела, F-22 «а»):
    алерт «блокировка/капча» (ровно один), «ошибка разбора разметки» не уходит."""
    source_blocked = load_attr("app.collectors", "SourceBlocked")
    page = _hh_page(*_regular_cards(), title=title, head_extra=head_extra)
    client = FakeClient.for_sources(
        hh=FakeResponse(text=page),
        habr=FakeResponse(text=habr_list_page()),
    )
    with pytest.raises(source_blocked):
        await _collector(SOURCE_HH).collect(client, now=NOW)

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HH].status == "blocked", f"@S97[{marker}]: отчёт: {reports!r}"
    assert by_source[SOURCE_HH].alert == alert_line(SOURCE_HH, BLOCKED), (
        f"@S97[{marker}]: алерт в отчёте: {by_source[SOURCE_HH].alert!r}"
    )
    assert alerts.texts == [alert_line(SOURCE_HH, BLOCKED)], (
        f"@S97[{marker} / {position}]: алерты: {alerts.texts!r}"
    )
    assert alert_line(SOURCE_HH, PARSE_ERROR) not in alerts.texts, (
        f"@S97[{marker}]: обход детекта классифицирован как битая разметка: {alerts.texts!r}"
    )


# --- S98 (@R81): слабые маркеры — только <title>/<h1> ------------------------


@pytest.mark.parametrize(("marker", "position"), S98_CASES)
async def test_s98_weak_marker_blocks_only_in_title_or_h1(marker: str, position: str) -> None:
    """@S98: «captcha»/«access denied» в <title>/<h1> → SourceBlocked + алерт
    «блокировка/капча» (шаблон brief §6.1), даже при валидных карточках."""
    source_blocked = load_attr("app.collectors", "SourceBlocked")
    title = marker if position == "<title>" else "Проверка доступа"
    body_extra = f"<h1>{marker}</h1>" if position == "<h1>" else ""
    page = _hh_page(*_regular_cards(), title=title, body_extra=body_extra)
    client = FakeClient.for_sources(
        hh=FakeResponse(text=page),
        habr=FakeResponse(text=habr_list_page()),
    )
    with pytest.raises(source_blocked):
        await _collector(SOURCE_HH).collect(client, now=NOW)

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HH].status == "blocked", f"@S98[{marker} / {position}]: {reports!r}"
    assert alerts.texts == [alert_line(SOURCE_HH, BLOCKED)], (
        f"@S98[{marker} / {position}]: алерты: {alerts.texts!r}"
    )
    assert by_source[SOURCE_HABR].status == "ok", (
        f"@S98[{marker} / {position}]: сбор Habr Career пострадал: {reports!r}"
    )
