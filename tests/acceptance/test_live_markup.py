"""Acceptance-тесты сценариев S90–S95 — живая разметка источников (I-3).

Прод-баг I-3: коллекторы hh.ru и Habr Career бросали ``ParseError`` в проде —
вёрстка источников сменилась, а тестовые фикстуры были синтетическими и
самосогласованы с парсером (корень: политика фикстур решений §9.2). Чёрный ящик:
публичное API ``app.collectors`` (api.md §6) и ``app.services.collect.run_collect``
(api.md §10); сеть — FakeClient (R41), часы инжектируются параметром ``now``
(как в test_collection_normalization/test_retention). Точные строки алертов —
brief §6.1 (``fakes.alert_line``); теги рисков —
``tests/features/collection_normalization.feature`` (@S90..@S95, R74..R78).

Фикстуры (создаёт software-engineer из живых образцов 28.10.2026, решений §9.2;
шапка файла: URL выдачи + дата съёмки + что санитизировано):
- ``tests/data/hh_live_list.html``, ``tests/data/habr_live_list.html`` —
  санитизированная живая выдача (S90, S91, S93);
- ``tests/data/hh_challenge.html``, ``tests/data/habr_challenge.html`` — живые
  challenge-образцы (маркеры ddos-guard / qrator; smart-captcha / «Just a moment»
  живых образцов нет — H2 «challenge с прод-IP» отклонена). Используются в кейсах
  S94 [ddos-guard] и S94 [qrator] соответственно.
Отсутствие фикстуры — внятный ``NotImplementedYet`` (``fakes.fixture_text``).
Старые синтетические фикстуры ``tests/data/*_list.html`` остаются регрессионными
данными нормализации (решений §9.2) и используются здесь как валидный ввод
«второго» источника.

Дизайн S92/S95: контрольные страницы строятся инлайн по ЖИВЫМ маркерам разметки
28.10.2026 (``data-qa``-ключи hh.ru, фрагменты DOM из образца) — это управляемые
негативные/граничные входы по образцу S15/S18, а не «фикстуры на глаз»:
репрезентативные фикстуры в ``tests/data/`` — только из живых образцов (§9.2).

S90 (пометка, решение арбитра 28.10): ожидание «min=100000, max=150000,
currency=RUB» взято дословно из фактов живой разметки; на образце 28.10 такая
зарплата есть ТОЛЬКО у промо-карточки (adsrv.hh.ru/click, «Финансовый менеджер»),
которую D6/S92 велит пропускать → ``hh_live_list.html`` обязан содержать обычную
(не промо) карточку с зарплатой «100 000 – 150 000 ₽», иначе шаг S90 невыполним
(gap см. в docs/qa/acceptance-map.md, owner BA/software-engineer).

S94 (уточнение фикстуры 28.10, решение арбитра F-22): маркер challenge несёт
РЕАЛИСТИЧНАЯ структурная позиция живой challenge-страницы (``CHALLENGE_STRUCTURES``:
``<script>`` с challenge-конфигом ddos-guard, cookie ``__qrator_captcha`` qrator,
``<script>``/cookie smart-captcha, ``<title>Just a moment...`` Cloudflare — живые
проверки: ddos-guard ставит ``window.ddos_guard_challenge`` в ``<script>``,
qrator — cookie ``__qrator_captcha``). Маркер в видимом тексте НЕПРИГОДЕН: видимый
текст карточек вакансий никогда не триггерит ``SourceBlocked`` (иначе потеря
источника на вакансии «Qrator», F-22). Padding в ``_challenge_page`` оставляет
маркер за пределами первых 4096 байт тела — реализм живой challenge-страницы
(маркер challenge-конфига/cookie несётся не в первых байтах); контракт детекта —
решения §9.4 РЕДАКЦИЯ 2 (нормализация тела + сильные маркеры только в
структурных позициях); устаревшая редакция 1 «детект маркеров во всём теле
ответа» перекрыта (ложные срабатывания на легитимном контенте). Поведение
редакции 2 закрепляют S96..S98 — ``test_challenge_normalization.py``.

S95: контейнер страницы помечен И старым (``data-qa="vacancy-serp"`), И новым
(``data-qa="vacancy-serp__results"``) маркерами (fallback-цепочка): страница
обязана быть узнаваемой «скелетом» для любой ветки парсера — иначе тест ловил бы
не границу решений §9.5 («карточки есть, но не разобраны» → ``ParseError``, а не
``EmptyResult``), а простое «скелет не найден».
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest
from fakes import (
    CARD_SEPARATOR,
    SOURCE_HABR,
    SOURCE_HH,
    FakeAlertSink,
    FakeClient,
    FakeResponse,
    InMemoryRepo,
    alert_line,
    expected_age_line,
    fixture_text,
    habr_list_page,
    hh_list_page,
    make_vacancy,
)
from support import load_attr

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)  # момент сбора «T» (инъекция часов)

SALARY_REASON_NOTE = "за месяц, до вычета налогов"
# Живая разметка зарплаты hh.ru (образец 28.10.2026): <data value="...">...</data>.
HH_SALARY_100_150 = (
    '<data value="100000">100 000</data> – '
    '<data value="150000">150 000</data><data value="RUB">₽</data> ' + SALARY_REASON_NOTE
)
HH_SALARY_120_000 = (
    '<data value="120000">120 000</data><data value="RUB">₽</data> ' + SALARY_REASON_NOTE
)

HH_TITLE_REGULAR_1 = "Младший Python-разработчик"
HH_TITLE_REGULAR_2 = "Управляющий аналитик"
HH_TITLE_PROMO = "Финансовый менеджер / Финансовый аналитик"

# Маркеры challenge-защиты (решения §9.4; строки Examples @S94).
CHALLENGE_MARKERS = ("ddos-guard", "qrator", "smart-captcha", "Just a moment")
# Живые challenge-образцы: маркер → (источник, фикстура) — проверяются в кейсах S94.
CHALLENGE_LIVE_SAMPLES = {
    "ddos-guard": (SOURCE_HH, "hh_challenge.html"),
    "qrator": (SOURCE_HABR, "habr_challenge.html"),
}


def _collector(name: str):
    build_collectors = load_attr("app.collectors", "build_collectors")
    for collector in build_collectors():
        if collector.name == name:
            return collector
    raise AssertionError(f"коллектор с именем {name!r} не найден в build_collectors()")


async def _run_collect(client: FakeClient, repo, alerts, now: datetime = NOW) -> list:
    run_collect = load_attr("app.services.collect", "run_collect")
    return await run_collect(client=client, repo=repo, alerts=alerts, now=now)


def _norm(raw: str) -> str:
    """Нормализация текста для сравнения заголовков (без двойных пробелов)."""
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", raw)).split())


# --- Живые маркеры hh.ru (28.10.2026) для инлайн-страниц S92/S95 --------------


def _hh_card(title: str, company: str, href: str, salary: str = "", *, promo: bool = False) -> str:
    """Карточка hh.ru по живым маркерам 28.10.2026 (article[data-qa^=...])."""
    qa = "vacancy-serp__vacancy vacancy-serp-item_clickme" if promo else "vacancy-serp__vacancy"
    return (
        f'<article data-qa="{qa}" class="magritte-card">'
        f'<a data-qa="serp-item__title" tabindex="0" href="{href}" target="_blank">'
        f'<span data-qa="serp-item__title-text">{title}</span></a>'
        f'<span data-qa="vacancy-serp__vacancy-employer-text">{company}</span>'
        f"<div>{salary}</div>"
        "</article>"
    )


def _hh_page(*cards: str) -> str:
    """Страница выдачи hh.ru с живым контейнером ``vacancy-serp__results``."""
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
        "<title>Работа и вакансии</title></head><body>"
        '<div data-qa="vacancy-serp__results">' + "".join(cards) + "</div></body></html>"
    )


# Реалистичные структурные позиции маркеров challenge-защиты (решение арбитра
# F-22; живые проверки 28.10.2026: ddos-guard ставит window.ddos_guard_challenge
# в <script>, qrator — cookie __qrator_captcha; см. U-COL-16 и живые образцы
# tests/data/{hh,habr}_challenge.html). Сильные маркеры триггерят SourceBlocked
# только в <script>/<link>/cookie-атрибутах/<title>; видимый текст карточек
# вакансий маркеров не несёт и блокировку не триггерит никогда (F-22).
CHALLENGE_STRUCTURES = {
    "ddos-guard": '<script>window.ddos_guard_challenge = {"token": "x"};</script>',
    "qrator": '<script>document.cookie = "__qrator_captcha=1; path=/;";</script>',
    "smart-captcha": '<script src="https://smart-captcha.ru/api.js" async></script>'
    '<div data-cookie="smart-captcha-token=1"></div>',
    "Just a moment": "",  # маркер несёт сам <title> страницы (Cloudflare)
}


def _challenge_page(marker: str) -> str:
    """Challenge-страница: маркер в реалистичной структурной позиции (F-22) и
    ЗА пределами первых 4096 байт тела (padding живой страницы; контракт
    детекта — решения §9.4 редакция 2 «нормализация + структурные позиции»,
    редакция 1 «во всём теле» устарела)."""
    padding = "<!-- " + "x" * 5_000 + " -->"
    title = "Just a moment..." if marker == "Just a moment" else "Проверка доступа"
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
        f"{padding}<title>{title}</title>{CHALLENGE_STRUCTURES[marker]}"
        "</head><body><h1>Проверка доступа</h1></body></html>"
    )


# --- S90 (@R74): живая разметка hh.ru разбирается в нормализованные вакансии ---


async def test_s90_live_hh_markup_parses_into_vacancies() -> None:
    """@S90: санитизированная живая выдача hh.ru → вакансии, канонические URL, без алертов.

    Ожидание зарплаты «100 000 – 150 000 ₽» → min=100000, max=150000, currency=RUB
    — дословно из фактов живой разметки 28.10 (см. шапку модуля про промо-карточку).
    """
    client = FakeClient.for_sources(
        hh=FakeResponse(text=fixture_text("hh_live_list.html")),
        habr=FakeResponse(text=habr_list_page()),
    )
    canonicalize_url = load_attr("app.collectors", "canonicalize_url")
    vacancies = await _collector(SOURCE_HH).collect(client)

    assert vacancies, "@S90: живая выдача hh.ru не дала ни одной вакансии"
    for vacancy in vacancies:
        assert vacancy.title and vacancy.title.strip(), f"@S90: пустой заголовок {vacancy!r}"
        assert vacancy.company and vacancy.company.strip(), f"@S90: пустая компания {vacancy!r}"
        assert vacancy.source == SOURCE_HH, f"@S90: источник {vacancy.source!r}"
        assert canonicalize_url(vacancy.url) == vacancy.url, (
            f"@S90: URL не канонический: {vacancy.url!r}"
        )
    assert any(
        vacancy.salary is not None
        and (vacancy.salary.min, vacancy.salary.max, vacancy.salary.currency)
        == (100000, 150000, "RUB")
        for vacancy in vacancies
    ), (
        "@S90: зарплата «100 000 – 150 000 ₽» не нормализовалась в "
        "min=100000, max=150000, currency=RUB (см. шапку модуля: фикстура должна "
        "содержать обычную карточку с этой зарплатой)"
    )

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HH].status == "ok", f"@S90: отчёт hh.ru: {reports!r}"
    assert alerts.texts == [], f"@S90: алерты на живой выдаче: {alerts.texts!r}"


# --- S91 (@R74): живая разметка Habr Career, включая карточку без зарплаты -----


@dataclass(frozen=True)
class _HabrCard:
    """Оракул карточки из фикстуры (маркеры живой разметки 28.10.2026)."""

    title: str
    href: str
    salary_text: str
    published_at: datetime


def _habr_fixture_cards(fixture: str) -> list[_HabrCard]:
    """Независимый оракул карточек Habr Career из фикстуры (значения, не разбор)."""
    starts = [m.start() for m in re.finditer(r'<div class="vacancy-card[ "]', fixture)]
    cards: list[_HabrCard] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(fixture)
        block = fixture[start:end]
        title_match = re.search(
            r'vacancy-card__title-link"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.S
        )
        time_match = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        if title_match is None or time_match is None:
            continue
        salary_match = re.search(r"basic-salary[^>]*>(.*?)</div>", block, re.S)
        cards.append(
            _HabrCard(
                title=_norm(title_match.group(2)),
                href=title_match.group(1),
                salary_text=_norm(salary_match.group(1)) if salary_match else "",
                published_at=datetime.fromisoformat(time_match.group(1)),
            )
        )
    return cards


async def test_s91_live_habr_markup_parses_including_card_without_salary() -> None:
    """@S91: живая разметка Habr Career: обе вакансии, salary=None у карточки без зарплаты,
    относительная ссылка → канонический URL с хостом career.habr.com,
    published_at берётся из даты карточки источника, без алертов."""
    fixture = fixture_text("habr_live_list.html")
    cards = _habr_fixture_cards(fixture)
    with_salary = [card for card in cards if card.salary_text]
    without_salary = [card for card in cards if not card.salary_text]
    assert with_salary and without_salary, (
        "@S91: фикстура должна содержать карточку с зарплатой и карточку без зарплаты (Given)"
    )

    client = FakeClient.for_sources(
        hh=FakeResponse(text=hh_list_page()),
        habr=FakeResponse(text=fixture),
    )
    canonicalize_url = load_attr("app.collectors", "canonicalize_url")
    vacancies = await _collector(SOURCE_HABR).collect(client)
    assert vacancies, "@S91: живая выдача Habr Career не дала ни одной вакансии"

    by_title = {_norm(vacancy.title): vacancy for vacancy in vacancies}
    card_paid, card_free = with_salary[0], without_salary[0]
    assert card_free.title in by_title, f"@S91: карточка без зарплаты не возвращена: {card_free!r}"
    assert card_paid.title in by_title, f"@S91: карточка с зарплатой не возвращена: {card_paid!r}"
    assert by_title[card_free.title].salary is None, (
        f"@S91: у карточки без зарплаты salary не None: {by_title[card_free.title]!r}"
    )
    assert by_title[card_paid.title].salary is not None, (
        f"@S91: у карточки с зарплатой salary is None: {by_title[card_paid.title]!r}"
    )

    fixture_paths = {card.href for card in cards}
    fixture_dates = {card.published_at for card in cards}
    for vacancy in vacancies:
        parts = urlsplit(vacancy.url)
        assert parts.netloc == "career.habr.com", (
            f"@S91: относительная ссылка не разрешена в career.habr.com: {vacancy.url!r}"
        )
        assert parts.path in fixture_paths, f"@S91: URL не из ссылки карточки: {vacancy.url!r}"
        assert canonicalize_url(vacancy.url) == vacancy.url, (
            f"@S91: URL не канонический: {vacancy.url!r}"
        )
        assert vacancy.published_at in fixture_dates, (
            f"@S91: published_at не из даты карточки источника: {vacancy!r}"
        )
    assert by_title[card_paid.title].published_at == card_paid.published_at, (
        f"@S91: дата карточки с зарплатой искажена: {by_title[card_paid.title]!r}"
    )
    assert by_title[card_free.title].published_at == card_free.published_at, (
        f"@S91: дата карточки без зарплаты искажена: {by_title[card_free.title]!r}"
    )

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HABR].status == "ok", f"@S91: отчёт Habr Career: {reports!r}"
    assert alerts.texts == [], f"@S91: алерты на живой выдаче: {alerts.texts!r}"


# --- S92 (@R75): промо-карточка hh.ru пропускается и не попадает в кэш --------


async def test_s92_promo_card_skipped_and_not_cached() -> None:
    """@S92: промо-карточка (adsrv.hh.ru/click, не /vacancy/) — мимо кэша и дедупа, без алерта."""
    page = _hh_page(
        _hh_card(
            HH_TITLE_REGULAR_1,
            "Работодатель 1",
            "https://hh.ru/vacancy/138031041?query=python&amp;hhtmFrom=vacancy_search_list",
            HH_SALARY_100_150,
        ),
        _hh_card(
            HH_TITLE_REGULAR_2,
            "Работодатель 2",
            "https://hh.ru/vacancy/138862394",
            HH_SALARY_120_000,
        ),
        _hh_card(
            HH_TITLE_PROMO,
            "Рекламный работодатель",
            "https://adsrv.hh.ru/click?b=2262371&amp;place=35&amp;meta=Ec-H0oLXyVANfkY7lsppZr"
            "&amp;clickType=link_to_vacancy&amp;j=1",
            HH_SALARY_100_150,
            promo=True,
        ),
    )
    client = FakeClient.for_sources(
        hh=FakeResponse(text=page),
        habr=FakeResponse(text=habr_list_page()),
    )
    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}

    assert by_source[SOURCE_HH].status == "ok", f"@S92: отчёт hh.ru: {reports!r}"
    assert by_source[SOURCE_HH].added == 2, f"@S92: в кэш добавлено не 2 карточки: {reports!r}"
    assert sorted(
        vacancy.title for vacancy in repo.vacancies if vacancy.source == SOURCE_HH
    ) == sorted([HH_TITLE_REGULAR_1, HH_TITLE_REGULAR_2]), (
        f"@S92: в кэше hh.ru не ровно две обычные вакансии: {repo.vacancies!r}"
    )
    assert HH_TITLE_PROMO not in [vacancy.title for vacancy in repo.vacancies], (
        f"@S92: промо-карточка сохранена: {repo.vacancies!r}"
    )
    assert all("adsrv" not in vacancy.url for vacancy in repo.vacancies), (
        f"@S92: в кэш попал URL промо-карточки: {repo.vacancies!r}"
    )
    assert alerts.texts == [], f"@S92: алерты при промо-карточке: {alerts.texts!r}"

    # Промо не участвует в дедупликации: её ключ (title+company) не «сожжён» —
    # настоящая вакансия с теми же заголовком и компанией сохраняется.
    added = await repo.add_vacancies(
        [make_vacancy(title=HH_TITLE_PROMO, company="Рекламный работодатель")]
    )
    assert added == 1, (
        "@S92: промо-карточка участвовала в дедупликации и заблокировала "
        f"настоящую вакансию с тем же заголовком/компанией (added={added})"
    )


# --- S93 (@R76): нет даты публикации — published_at = момент сбора, «сегодня» --


async def test_s93_missing_publish_date_falls_back_to_collection_time() -> None:
    """@S93: у hh.ru нет дат в выдаче → published_at = момент сбора T, карточки не
    отбрасываются, возраст в дайджесте «сегодня» (RU) и «today» (EN)."""
    fixture = fixture_text("hh_live_list.html")
    expected_count = len(
        re.findall(r'data-qa="serp-item__title"[^>]*href="[^"]*?/vacancy/', fixture)
    )
    assert expected_count > 0, "@S93: в живой фикстуре нет обычных карточек hh.ru"

    client = FakeClient.for_sources(
        hh=FakeResponse(text=fixture),
        habr=FakeResponse(text=habr_list_page()),
    )
    repo, alerts = InMemoryRepo(), FakeAlertSink()
    await _run_collect(client, repo, alerts, now=NOW)  # сбор «в момент T»

    hh_vacancies = [vacancy for vacancy in repo.vacancies if vacancy.source == SOURCE_HH]
    assert hh_vacancies, "@S93: карточки без даты отброшены полностью"
    assert len(hh_vacancies) == expected_count, (
        f"@S93: карточки отброшены из-за отсутствия даты: {len(hh_vacancies)} из "
        f"{expected_count} обычных карточек фикстуры"
    )
    format_age = load_attr("app.services.digest", "format_age")
    render_card = load_attr("app.services.digest", "render_card")
    for vacancy in hh_vacancies:
        assert vacancy.published_at == NOW, (
            f"@S93: published_at {vacancy.published_at!r} != момент сбора {NOW!r}"
        )
        age_ru = format_age(vacancy.published_at, NOW, "ru")
        age_en = format_age(vacancy.published_at, NOW, "en")
        assert age_ru == expected_age_line(lang="ru", full_days=0) == "сегодня", (
            f"@S93: возраст RU {age_ru!r} != «сегодня»"
        )
        assert age_en == expected_age_line(lang="en", full_days=0) == "today", (
            f"@S93: возраст EN {age_en!r} != «today»"
        )
    card = render_card(1, hh_vacancies[0], "ru", NOW)
    assert f"{CARD_SEPARATOR} сегодня" in card, (
        f"@S93: в карточке дайджеста нет возраста «сегодня»:\n{card!r}"
    )


# --- S94 (@R77): challenge-страница → блокировка, а не битая разметка ---------


@pytest.mark.parametrize("marker", CHALLENGE_MARKERS)
async def test_s94_challenge_marker_classified_as_blocked(marker: str) -> None:
    """@S94: маркер challenge-защиты → SourceBlocked, алерт «блокировка/капча»;
    алерт «ошибка разбора разметки» не отправляется. Маркер несёт реалистичная
    структурная позиция живой challenge-страницы (CHALLENGE_STRUCTURES, F-22) —
    видимый текст карточек вакансий SourceBlocked не триггерит никогда.
    Для ddos-guard/qrator дополнительно проверяется живой challenge-образец
    источника (фикстуры hh_challenge.html / habr_challenge.html); для
    smart-captcha/«Just a moment» живых образцов нет (H2 отклонена) — кейс
    маркерный."""
    source_blocked = load_attr("app.collectors", "SourceBlocked")
    client = FakeClient.for_sources(
        hh=FakeResponse(text=_challenge_page(marker)),
        habr=FakeResponse(text=habr_list_page()),
    )
    with pytest.raises(source_blocked):
        await _collector(SOURCE_HH).collect(client)

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HH].status == "blocked", f"@S94[{marker}]: отчёт: {reports!r}"
    assert by_source[SOURCE_HH].alert == alert_line(SOURCE_HH, "блокировка/капча"), (
        f"@S94[{marker}]: алерт в отчёте: {by_source[SOURCE_HH].alert!r}"
    )
    assert alerts.texts == [alert_line(SOURCE_HH, "блокировка/капча")], (
        f"@S94[{marker}]: алерты: {alerts.texts!r}"
    )
    assert alert_line(SOURCE_HH, "ошибка разбора разметки") not in alerts.texts, (
        f"@S94[{marker}]: challenge классифицирован как битая разметка: {alerts.texts!r}"
    )

    live_sample = CHALLENGE_LIVE_SAMPLES.get(marker)
    if live_sample is not None:
        source, filename = live_sample
        page = fixture_text(filename)
        live_client = (
            FakeClient.for_sources(hh=FakeResponse(text=page))
            if source == SOURCE_HH
            else FakeClient.for_sources(habr=FakeResponse(text=page))
        )
        with pytest.raises(source_blocked):
            await _collector(source).collect(live_client)


# --- S95 (@R78): скелет есть, карточки не разобраны — ParseError, не EmptyResult


async def test_s95_unparseable_cards_with_skeleton_raise_parse_error() -> None:
    """@S95: контейнер выдачи есть, карточки есть, но ни одна не содержит
    обязательных полей → ParseError («ошибка разбора разметки»), а не EmptyResult
    («пустой разбор»); в кэш ничего не попадает (решения §9.5)."""
    page = _hh_page(
        # Контейнер помечен и старым маркером (fallback-цепочка, см. шапку модуля).
        '<div data-qa="vacancy-serp"></div>'
        '<article data-qa="vacancy-serp__vacancy"><span>Карточка без заголовка</span></article>'
        '<article data-qa="vacancy-serp__vacancy">'
        '<a data-qa="serp-item__title" href="https://hh.ru/vacancy/1">Карточка без компании</a>'
        "</article>"
    )
    parse_error = load_attr("app.collectors", "ParseError")
    empty_result = load_attr("app.collectors", "EmptyResult")
    client = FakeClient.for_sources(
        hh=FakeResponse(text=page),
        habr=FakeResponse(text=habr_list_page()),
    )
    try:
        await _collector(SOURCE_HH).collect(client)
    except empty_result as exc:  # noqa: B014 - исключения не связаны; явная фиксация границы
        pytest.fail(f"@S95: неразобранные карточки классифицированы как EmptyResult: {exc!r}")
    except parse_error:
        pass
    else:
        pytest.fail("@S95: неразобранные карточки не дали ParseError")

    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(client, repo, alerts)
    by_source = {report.source: report for report in reports}
    assert by_source[SOURCE_HH].status == "parse_error", f"@S95: отчёт: {reports!r}"
    assert alerts.texts == [alert_line(SOURCE_HH, "ошибка разбора разметки")], (
        f"@S95: алерты: {alerts.texts!r}"
    )
    assert alert_line(SOURCE_HH, "пустой разбор") not in alerts.texts, (
        f"@S95: вместо ошибки разбора пришёл «пустой разбор»: {alerts.texts!r}"
    )
    assert by_source[SOURCE_HH].added == 0, f"@S95: в кэш что-то добавлено: {reports!r}"
    assert all(vacancy.source != SOURCE_HH for vacancy in repo.vacancies), (
        f"@S95: в кэш попали вакансии неразборной страницы: {repo.vacancies!r}"
    )
