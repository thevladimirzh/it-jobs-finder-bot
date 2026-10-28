"""Acceptance-тесты S99–S101 — allowlist хостов URL вакансии (decisions §9.7, D7).

Контракт (решение арбитра 28.10.2026, F-25 / CWE-601):
- URL карточки обязан вести на хост источника или его поддомен: hh.ru —
  ``hh.ru`` и поддомены; Habr Career — ``career.habr.com`` и ``habr.com`` с
  поддоменами (S101); проверка — после канонизации URL;
- чужой хост → карточка пропускается МОЛЧА, как промо (D6): в кэш не попадает,
  в дедупликации не участвует, алерта не вызывает (S99) — отдельная
  наблюдаемая категория «чужой хост» не вводится;
- страница, где ВСЕ карточки ведут на чужие хосты (путь ``/vacancy/`` сохранён
  — промо-фильтр D6 пройден) → ``ParseError`` по общему контракту §9.5
  («карточки есть, ни одна не разобрана»), а не молчаливый пустой сбор (S100);
- правила независимы: ``adsrv.hh.ru`` — поддомен ``hh.ru`` (allowlist проходит),
  но отсекается промо-правилом D6 (S92).

Чёрный ящик: публичное API ``app.collectors`` (api.md §6) и
``app.services.collect.run_collect`` (api.md §10); сеть — FakeClient (R41),
часы — параметр ``now``. Точные строки алертов — brief §6.1
(``fakes.alert_line``); теги рисков —
``tests/features/collection_normalization.feature`` (@S99..@S101; риски реестра
— R84, см. docs/qa/acceptance-map.md).

Контрольные страницы строятся инлайн по ЖИВЫМ маркерам разметки 28.10.2026
(data-qa-ключи hh.ru, ``vacancy-card``-маркеры Habr Career, как S92/S95 в
test_live_markup.py) — управляемые граничные входы, а не «фикстуры на глаз»
(фикстуры tests/data/ — только живые образцов, решений §9.2). Второй источник
получает валидную фикстуру ``tests/data/``; «в кэш попадают только две
обычные вакансии» читается по источнику Given (прецедент — S92, §7 карты).
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

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
    hh_list_page,
    make_vacancy,
)
from support import load_attr

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)

REG_TITLE_1 = "Младший Python-разработчик"
REG_TITLE_2 = "Управляющий аналитик"
REG_COMPANY_1 = "Работодатель 1"
REG_COMPANY_2 = "Работодатель 2"
# Карточка-ловушка: уникальные заголовок/компания — ключ дедупа не должен быть
# «сожжён» пропущенной карточкой (как у промо в S92).
FOREIGN_TITLE = "Вакансия-ловушка с чужого хоста"
FOREIGN_COMPANY = "ООО Фишинг"

PARSE_ERROR = "ошибка разбора разметки"

# --- S99 (Examples): чужой хост → пропуск молча -------------------------------
S99_CASES = [
    (SOURCE_HH, "https://evil.example/vacancy/1"),
    (SOURCE_HH, "https://career.habr.com/vacancy/1"),
    (SOURCE_HABR, "https://evil.example/vacancies/1"),
    (SOURCE_HABR, "https://hh.ru/vacancies/1"),
]

# --- S101 (Examples): поддомен источника разрешён -----------------------------
S101_CASES = [
    (SOURCE_HH, "https://spb.hh.ru/vacancy/1"),
    (SOURCE_HABR, "https://habr.com/vacancies/1"),
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


# --- Живые маркеры разметки (28.10.2026) для контрольных страниц --------------


def _hh_card(title: str, company: str, href: str) -> str:
    """Карточка hh.ru по живым маркерам 28.10.2026 (article[data-qa^=...])."""
    return (
        '<article data-qa="vacancy-serp__vacancy" class="magritte-card">'
        f'<a data-qa="serp-item__title" tabindex="0" href="{href}" target="_blank">'
        f'<span data-qa="serp-item__title-text">{title}</span></a>'
        f'<span data-qa="vacancy-serp__vacancy-employer-text">{company}</span>'
        "</article>"
    )


def _hh_page(*cards: str) -> str:
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
        "<title>Работа и вакансии</title></head><body>"
        '<div data-qa="vacancy-serp__results">' + "".join(cards) + "</div></body></html>"
    )


def _habr_card(title: str, company: str, href: str) -> str:
    """Карточка Habr Career по живым маркерам 28.10.2026 (div.vacancy-card)."""
    return (
        '<div class="vacancy-card">'
        f'<a class="vacancy-card__title-link" href="{href}">{title}</a>'
        '<div class="vacancy-card__company">'
        f'<a href="https://career.habr.com/companies/example">{company}</a></div>'
        '<time class="basic-date" datetime="2026-03-14T10:00:00+03:00"></time>'
        "</div>"
    )


def _habr_page(*cards: str) -> str:
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
        "<title>Вакансии</title></head><body>"
        '<div class="vacancies-list" data-vacancy-list>' + "".join(cards) + "</div></body></html>"
    )


def _source_page(source: str, cards: list[tuple[str, str, str]]) -> str:
    """Страница источника ``source`` с карточками (title, company, href)."""
    if source == SOURCE_HH:
        return _hh_page(*[_hh_card(*card) for card in cards])
    if source == SOURCE_HABR:
        return _habr_page(*[_habr_card(*card) for card in cards])
    raise AssertionError(f"неизвестный источник {source!r}")


def _fixture_page(source: str) -> str:
    """Валидная фикстура источника ``source`` (tests/data/, живые образцы)."""
    return hh_list_page() if source == SOURCE_HH else habr_list_page()


# --- S99 (@R84): карточка с чужим хостом пропускается молча -------------------


@pytest.mark.parametrize(("source", "foreign_url"), S99_CASES)
async def test_s99_foreign_host_card_skipped_silently(source: str, foreign_url: str) -> None:
    """@S99: карточка с URL на чужой хост мимо кэша и дедупликации, без алерта;
    в кэш попадают только две обычные вакансии источника (прецедент S92)."""
    page = _source_page(
        source,
        [
            (REG_TITLE_1, REG_COMPANY_1, _regular_href(source, 1)),
            (REG_TITLE_2, REG_COMPANY_2, _regular_href(source, 2)),
            (FOREIGN_TITLE, FOREIGN_COMPANY, foreign_url),
        ],
    )
    client = FakeClient.for_sources(
        hh=FakeResponse(text=page if source == SOURCE_HH else _fixture_page(SOURCE_HH)),
        habr=FakeResponse(text=page if source == SOURCE_HABR else _fixture_page(SOURCE_HABR)),
    )
    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}

    assert by_source[source].status == "ok", f"@S99[{source} / {foreign_url}]: {reports!r}"
    assert by_source[source].added == 2, (
        f"@S99[{source} / {foreign_url}]: в кэш добавлено не 2 карточки: {reports!r}"
    )
    saved = [vacancy for vacancy in repo.vacancies if vacancy.source == source]
    assert sorted(vacancy.title for vacancy in saved) == sorted([REG_TITLE_1, REG_TITLE_2]), (
        f"@S99[{source} / {foreign_url}]: в кэше не ровно две обычные вакансии: {repo.vacancies!r}"
    )
    assert FOREIGN_TITLE not in [vacancy.title for vacancy in repo.vacancies], (
        f"@S99[{source} / {foreign_url}]: карточка с чужим хостом сохранена: {repo.vacancies!r}"
    )
    assert all(
        urlsplit(vacancy.url).hostname != urlsplit(foreign_url).hostname for vacancy in saved
    ), f"@S99[{source} / {foreign_url}]: в кэш попал чужой хост: {repo.vacancies!r}"
    assert alerts.texts == [], (
        f"@S99[{source} / {foreign_url}]: алерты при чужом хосте: {alerts.texts!r}"
    )

    # Чужой хост не участвует в дедупликации: его ключ (title+company) не
    # «сожжён» — настоящая вакансия с теми же заголовком и компанией сохраняется.
    added = await repo.add_vacancies([make_vacancy(title=FOREIGN_TITLE, company=FOREIGN_COMPANY)])
    assert added == 1, (
        f"@S99[{source} / {foreign_url}]: пропущенная карточка участвовала в "
        f"дедупликации и заблокировала вакансию с тем же заголовком/компанией (added={added})"
    )


def _regular_href(source: str, index: int) -> str:
    if source == SOURCE_HH:
        return f"https://hh.ru/vacancy/13803104{index}"
    return f"/vacancies/92700{index}"  # относительная ссылка → career.habr.com


# --- S100 (@R84): страница только из чужих хостов → ParseError ---------------


async def test_s100_only_foreign_host_cards_raise_parse_error() -> None:
    """@S100: все карточки ведут на чужие хосты (путь /vacancy/ сохранён —
    промо-фильтр D6 пройден) → ParseError («ошибка разбора разметки»), а не
    молчаливый пустой сбор; в кэш ничего не попадает (§9.5)."""
    page = _hh_page(
        _hh_card(FOREIGN_TITLE, FOREIGN_COMPANY, "https://evil.example/vacancy/1"),
        _hh_card(FOREIGN_TITLE + " 2", FOREIGN_COMPANY, "https://career.habr.com/vacancy/2"),
    )
    parse_error = load_attr("app.collectors", "ParseError")
    empty_result = load_attr("app.collectors", "EmptyResult")
    client = FakeClient.for_sources(
        hh=FakeResponse(text=page),
        habr=FakeResponse(text=habr_list_page()),
    )
    try:
        await _collector(SOURCE_HH).collect(client, now=NOW)
    except empty_result as exc:  # noqa: B014 - исключения не связаны; граница §9.5
        pytest.fail(f"@S100: карточки с чужими хостами классифицированы как EmptyResult: {exc!r}")
    except parse_error:
        pass
    else:
        pytest.fail("@S100: страница только из чужих хостов не дала ParseError")

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HH].status == "parse_error", f"@S100: отчёт: {reports!r}"
    assert by_source[SOURCE_HH].added == 0, f"@S100: в кэш что-то добавлено: {reports!r}"
    assert alerts.texts == [alert_line(SOURCE_HH, PARSE_ERROR)], f"@S100: алерты: {alerts.texts!r}"
    assert all(vacancy.source != SOURCE_HH for vacancy in repo.vacancies), (
        f"@S100: в кэш попали вакансии страницы из чужих хостов: {repo.vacancies!r}"
    )


# --- S101 (@R84): поддомен источника разрешён --------------------------------


@pytest.mark.parametrize(("source", "url"), S101_CASES)
async def test_s101_subdomain_card_url_allowed(source: str, url: str) -> None:
    """@S101: URL карточки на хост источника или его поддомен (spb.hh.ru,
    habr.com) сохраняется в кэш с каноническим URL, без алертов."""
    page = _source_page(source, [(REG_TITLE_1, REG_COMPANY_1, url)])
    client = FakeClient.for_sources(
        hh=FakeResponse(text=page if source == SOURCE_HH else _fixture_page(SOURCE_HH)),
        habr=FakeResponse(text=page if source == SOURCE_HABR else _fixture_page(SOURCE_HABR)),
    )
    canonicalize_url = load_attr("app.collectors", "canonicalize_url")
    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}

    assert by_source[source].status == "ok", f"@S101[{source} / {url}]: {reports!r}"
    assert by_source[source].added == 1, f"@S101[{source} / {url}]: {reports!r}"
    matching = [
        vacancy for vacancy in repo.vacancies if vacancy.source == source and vacancy.url == url
    ]
    assert matching, (
        f"@S101[{source} / {url}]: карточка с поддоменом не сохранена: {repo.vacancies!r}"
    )
    assert canonicalize_url(matching[0].url) == url, (
        f"@S101[{source} / {url}]: URL не канонический: {matching[0].url!r}"
    )
    assert alerts.texts == [], f"@S101[{source} / {url}]: алерты: {alerts.texts!r}"
