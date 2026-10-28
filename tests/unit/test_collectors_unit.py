"""Юнит-тесты коллекторов и дедупликации (U-COL-02..06, U-COL-09..13, U-DED-01).

Владелец: software-engineer. Без БД и сети: парсеры, ошибки источников,
канонизация/нормализация (R2, R12, R28, R35, R40), живая разметка источников
(R74..R78, I-3): новые маркеры с fallback на старые, промо-карточки (D6),
`published_at` = момент сбора без даты (D5), challenge → SourceBlocked (§9.4),
граница ParseError/EmptyResult (§9.5).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from app.collectors import (
    EmptyResult,
    ParseError,
    SourceBlocked,
    SourceUnavailable,
    build_collectors,
    canonicalize_url,
    normalize_text,
)
from app.collectors.base import parse_cards

HH_PAGE = """
<div data-qa="vacancy-serp">
  <div class="vacancy-serp-item" data-qa="vacancy-serp-item">
    <a data-qa="vacancy-title" href="https://hh.ru/vacancy/1?utm_source=x">Python Developer</a>
    <div data-qa="vacancy-company">Ромашка</div>
    <div data-qa="vacancy-salary">от 150 000 ₽</div>
    <time datetime="2026-03-14T09:00:00+03:00"></time>
  </div>
</div>
"""


class _Resp:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.headers: dict[str, str] = {}


class _Client:
    def __init__(self, payload: _Resp | Exception) -> None:
        self.payload = payload

    async def get(self, url: str, *, headers=None):  # noqa: ANN001, ANN202
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _hh_collector():
    return next(c for c in build_collectors() if c.name == "hh.ru")


def _habr_collector():
    return next(c for c in build_collectors() if c.name == "Habr Career")


# --- U-COL-02 (R2): валидная вёрстка разбирается, битая → ParseError ----------


def test_u_col02_valid_markup_parses_and_broken_raises_parse_error() -> None:
    vacancies = asyncio.run(_hh_collector().collect(_Client(_Resp(HH_PAGE))))
    assert [v.title for v in vacancies] == ["Python Developer"]
    assert vacancies[0].url == "https://hh.ru/vacancy/1"
    with pytest.raises(ParseError):
        asyncio.run(_hh_collector().collect(_Client(_Resp("<html><p>не та вёрстка</p></html>"))))


# --- U-COL-03 (R1): блокировка/капча → SourceBlocked --------------------------


def test_u_col03_blocked_source_raises_source_blocked() -> None:
    """U-COL-03 (R1): блокировка/капча → SourceBlocked.

    I-3-fix (F-22, решение арбитра): слабые маркеры капчи триггерят блокировку
    только в <title>/<h1> (страница-заголовок), сильные — только в структурных
    позициях; видимый текст больше не классифицируется как блокировка (вакансия
    про captcha не должна лишать источник) — см. U-COL-16.
    """
    with pytest.raises(SourceBlocked):
        asyncio.run(_hh_collector().collect(_Client(_Resp("captcha", status_code=403))))
    with pytest.raises(SourceBlocked):
        asyncio.run(_hh_collector().collect(_Client(_Resp("<h1>please solve the captcha</h1>"))))


# --- U-COL-04 (R40): пустой разбор не возвращается молча ----------------------


def test_u_col04_empty_page_raises_empty_result_never_empty_list() -> None:
    page = '<div data-qa="vacancy-serp">ничего нет</div>'
    with pytest.raises(EmptyResult):
        asyncio.run(_hh_collector().collect(_Client(_Resp(page))))


# --- U-COL-05 (R28): артефакты фикстур → ошибка источника, не падение ---------


@pytest.mark.parametrize(
    "body",
    ["", " \n\t ", "\ufeff<html>мусор</html>", "Р РµР·СЋРјРµ", "x" * 10_000],
)
def test_u_col05_fixture_artifacts_raise_collector_error(body: str) -> None:
    with pytest.raises((ParseError, EmptyResult, SourceBlocked, SourceUnavailable)):
        asyncio.run(_hh_collector().collect(_Client(_Resp(body))))


# --- U-COL-06 (R35): тяжёлая страница не блокирует event loop -----------------


def test_u_col06_heavy_page_parses_and_yields_to_event_loop() -> None:
    heavy = (HH_PAGE + "\n") * 2000
    ticks: list[int] = []

    async def ticker() -> None:
        while True:
            ticks.append(1)
            await asyncio.sleep(0)

    async def go() -> int:
        task = asyncio.create_task(ticker())
        started = time.perf_counter()
        vacancies = await _hh_collector().collect(_Client(_Resp(heavy)))
        elapsed = time.perf_counter() - started
        task.cancel()
        assert elapsed < 15, f"разбор тяжёлой страницы {elapsed:.1f}s"
        assert len(ticks) >= 3, "event loop был заблокирован разбором"
        return len(vacancies)

    assert asyncio.run(go()) == 2000


# --- U-COL-07/08 (QA §6.10, R24): «остальные поля короткие» при нормализации --


def test_u_col07_giant_company_and_description_clamped_at_parse() -> None:
    def page_with(company: str, description: str) -> str:
        return (
            '<div data-qa="vacancy-serp">'
            '<div class="vacancy-serp-item" data-qa="vacancy-serp-item">'
            '<a data-qa="vacancy-title" href="https://hh.ru/vacancy/1">Python Developer</a>'
            f'<div data-qa="vacancy-company">{company}</div>'
            f'<div data-qa="vacancy-description">{description}</div>'
            '<div data-qa="vacancy-salary">от 150 000 \u20bd</div>'
            '<time datetime="2026-03-14T09:00:00+03:00"></time>'
            "</div></div>"
        )

    def parse(text: str):
        return asyncio.run(
            parse_cards(
                text,
                source="hh.ru",
                base_url="https://hh.ru",
                container_marker='data-qa="vacancy-serp"',
                card_marker='data-qa="vacancy-serp-item"',
            )
        )

    giant = "\u041a" * 5000
    vacancy = parse(page_with(giant, giant))[0]
    assert len(vacancy.company) <= 100, f"U-COL-07: company длиной {len(vacancy.company)}"
    assert vacancy.company.endswith("\u2026"), "U-COL-07: обрезка company без «…»"
    assert len(vacancy.description) <= 100, (
        f"U-COL-07: description длиной {len(vacancy.description)}"
    )
    assert vacancy.description.endswith("\u2026"), "U-COL-07: обрезка description без «…»"

    # короткие поля не трогаются (без «…» и потерь)
    short = parse(page_with("Ромашка", "python django postgres"))[0]
    assert short.company == "Ромашка", f"U-COL-07: короткий company искажён: {short.company!r}"
    assert short.description == "python django postgres", (
        f"U-COL-07: короткий description искажён: {short.description!r}"
    )

    # карточка с гигантским company разрешимо короткая — без DigestError (QA §6.10)
    from app.services.digest import render_card, render_digest

    now = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)

    class _Item:
        n = 1

        def __init__(self, vacancy: object) -> None:
            self.vacancy = vacancy

    card = render_card(1, vacancy, "ru", now)
    assert len(card) < 4096, f"U-COL-07: карточка не разрешимо короткая: {len(card)}"
    parts = render_digest([_Item(vacancy)], lang="ru", now=now, on_date=now.date())
    assert all(len(part) <= 4096 for part in parts), "U-COL-07: часть дайджеста > 4096"


@settings(derandomize=True, max_examples=150, deadline=None)
@given(st.text(max_size=300))
def test_u_col08_clamp_bounds_property(raw: str) -> None:
    """U-COL-08: обрезка поля тотальна: ≤100, префикс сохранён, «…» только при обрезке."""
    from app.collectors.base import clamp_text

    clamped = clamp_text(raw)
    assert len(clamped) <= 100, f"U-COL-08: {len(clamped)} символов после clamp_text"
    if len(raw) <= 100:
        assert clamped == raw, f"U-COL-08: короткий текст искажён: {raw!r} -> {clamped!r}"
    else:
        assert clamped.endswith("\u2026"), f"U-COL-08: обрезка без «…»: {clamped[-5:]!r}"
        assert clamped[:-1] == raw[:99], "U-COL-08: префикс исходного текста потерян"


# --- U-DED-01 (R12): канонизация/нормализация идемпотентны ---------------------


def test_u_ded01_canonical_url_and_normalize_text_invariants() -> None:
    assert canonicalize_url("http://hh.ru/vacancy/9/?utm_source=x") == "https://hh.ru/vacancy/9"
    assert normalize_text("  Python   Developer ") == normalize_text("python developer")
    for raw in ("мусор", "https://a.b/c", '" onmouseover="x', "javascript:alert(1)"):
        canonical = canonicalize_url(raw)
        assert canonicalize_url(canonical) == canonical
        assert not any(ch.isspace() for ch in canonical)
    # карточка с одинаковыми title+company дедуплицируется независимо от URL
    block = HH_PAGE.replace("https://hh.ru/vacancy/1?utm_source=x", "https://career.habr.com/x/1")
    first = asyncio.run(
        parse_cards(
            HH_PAGE,
            source="hh.ru",
            base_url="https://hh.ru",
            container_marker='data-qa="vacancy-serp"',
            card_marker='data-qa="vacancy-serp-item"',
        )
    )
    second = asyncio.run(
        parse_cards(
            block,
            source="Habr Career",
            base_url="https://career.habr.com",
            container_marker='data-qa="vacancy-serp"',
            card_marker='data-qa="vacancy-serp-item"',
        )
    )
    assert normalize_text(f"{first[0].title} {first[0].company}") == normalize_text(
        f"{second[0].title} {second[0].company}"
    )


# --- U-COL-09..13 (R74..R78): живая разметка источников (I-3, 28.10.2026) ------
#
# Маркеры — дословно из живых образцов 28.10.2026 (решения §9): hh.ru
# `article[data-qa^="vacancy-serp__vacancy"]`, `a[data-qa="serp-item__title"]`,
# `span[data-qa="vacancy-serp__vacancy-employer-text"]`, зарплата `<data value=...>`;
# Habr Career `div.vacancy-card`, `a.vacancy-card__title-link`,
# `div.vacancy-card__company a`, `div.vacancy-card__salary .basic-salary`,
# `time.basic-date[datetime]`. Старые маркеры остаются fallback-цепочкой.

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)

HH_LIVE_SALARY_RANGE = (
    '<data value="100000">100 000</data> \u2013 '
    '<data value="150000">150 000 </data><data value="RUB">\u20bd</data> '
    "<!-- -->за месяц, <!-- -->до вычета налогов"
)
HH_LIVE_SALARY_FROM = (
    '<data value="120000">120 000</data> <data value="RUB">\u20bd</data> '
    "<!-- -->за месяц, <!-- -->до вычета налогов"
)
HH_STATE_TEMPLATE = (
    '<template style="display:none" id="HH-Lux-InitialState">'
    "{&#34;error.signup.captcha.invalid&#34;:&#34;Пожалуйста, подтвердите, "
    "что вы не робот&#34;,&#34;error.vacancy.archive.accessDenied&#34;:"
    "&#34;Недостаточно прав&#34;}"
    "</template>"
)


def _hh_live_card(
    title: str = "Младший Python-разработчик",
    company: str = "Ромашка",
    href: str = "https://hh.ru/vacancy/2?query=python&amp;hhtmFrom=vacancy_search_list",
    salary: str = HH_LIVE_SALARY_RANGE,
    *,
    promo: bool = False,
) -> str:
    """Карточка hh.ru по живым маркерам 28.10.2026 (без даты публикации в выдаче)."""
    qa = "vacancy-serp__vacancy vacancy-serp-item_clickme" if promo else "vacancy-serp__vacancy"
    return (
        f'<article data-qa="{qa}" class="magritte-card">'
        f'<a class="magritte-link" data-qa="serp-item__title" tabindex="0" href="{href}" '
        'target="_blank">'
        f'<span data-qa="serp-item__title-text">{title}</span></a>'
        f'<span data-qa="vacancy-serp__vacancy-employer-text">{company}</span>'
        f"<div>{salary}</div>"
        "</article>"
    )


def _hh_live_page(*cards: str, state: str = "") -> str:
    """Страница выдачи hh.ru: живой контейнер + карточки (+ скрытое JSON-состояние)."""
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"></head><body>'
        f"{state}"
        '<div data-qa="vacancy-serp__results">' + "".join(cards) + "</div></body></html>"
    )


def _habr_live_card(
    title: str,
    company: str,
    href: str = "/vacancies/1000168771",
    salary: str = "",
    moment: str = "2026-10-28T05:52:23+03:00",
) -> str:
    """Карточка Habr Career по живым маркерам 28.10.2026 (div.vacancy-card)."""
    cls = "vacancy-card" if salary else "vacancy-card vacancy-card--bp"
    return (
        f'<div class="{cls}">'
        f'<a aria-label="{title}" class="vacancy-card__backdrop-link" href="{href}"></a>'
        '<div class="vacancy-card__inner">'
        f'<div class="vacancy-card__date"><time class="basic-date" datetime="{moment}">'
        "28 октября</time></div>"
        '<div class="vacancy-card__info">'
        f'<div class="vacancy-card__company"><a class="link-comp" href="/companies/x">'
        f"{company}</a></div>"
        f'<div class="vacancy-card__title"><a class="vacancy-card__title-link" href="{href}">'
        f"{title}</a></div>"
        f"{salary}"
        "</div></div></div>"
    )


def _habr_live_page(*cards: str) -> str:
    """Страница выдачи Habr Career: живой контейнер ``data-vacancy-list``."""
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"></head><body>'
        '<div data-vacancy-list="">'
        + "".join(
            '<div class="section-box section-box--appearance-marked">'
            '<div class="basic-section basic-section--appearance-vacancy-card">'
            f"{card}</div></div>"
            for card in cards
        )
        + "</div></body></html>"
    )


# --- U-COL-09 (R74): живые маркеры hh.ru разбираются, старые — fallback ---------


def test_u_col09_live_hh_markup_parses_with_new_markers() -> None:
    """U-COL-09: article[data-qa^=vacancy-serp__vacancy] + serp-item__title +
    employer-text + зарплата из <data value> разбираются; URL канонический."""
    vacancies = asyncio.run(
        _hh_collector().collect(_Client(_Resp(_hh_live_page(_hh_live_card()))), now=NOW)
    )
    assert [v.title for v in vacancies] == ["Младший Python-разработчик"]
    vacancy = vacancies[0]
    assert vacancy.company == "Ромашка", f"U-COL-09: company {vacancy.company!r}"
    assert (vacancy.salary.min, vacancy.salary.max, vacancy.salary.currency) == (
        100000,
        150000,
        "RUB",
    ), f"U-COL-09: зарплата из <data value> {vacancy.salary!r}"
    assert vacancy.url == "https://hh.ru/vacancy/2?hhtmFrom=vacancy_search_list&query=python", (
        f"U-COL-09: канонический URL {vacancy.url!r} (&amp; в href должен разворачиваться)"
    )
    assert canonicalize_url(vacancy.url) == vacancy.url, (
        f"U-COL-09: URL не каноничен {vacancy.url!r}"
    )


def test_u_col09_legacy_markers_still_parse_via_fallback() -> None:
    """U-COL-09: старые синтетические маркеры остаются рабочими (fallback-цепочка)."""
    vacancies = asyncio.run(_hh_collector().collect(_Client(_Resp(HH_PAGE)), now=NOW))
    assert [v.title for v in vacancies] == ["Python Developer"], (
        f"U-COL-09: старые маркеры сломаны: {[v.title for v in vacancies]!r}"
    )


def test_u_col09_salary_from_single_data_value_and_text_fallback() -> None:
    """U-COL-09: одиночное <data value> → min; без <data> зарплата берётся из текста."""
    single = _hh_live_card(
        title="Управляющий аналитик", company="ПАО Банк", salary=HH_LIVE_SALARY_FROM
    )
    vacancies = asyncio.run(_hh_collector().collect(_Client(_Resp(_hh_live_page(single))), now=NOW))
    assert (vacancies[0].salary.min, vacancies[0].salary.max) == (120000, None), (
        f"U-COL-09: одиночное значение {vacancies[0].salary!r}"
    )
    text_only = _hh_live_card(
        title="QA Engineer",
        company="Kaktus",
        salary='<span data-qa="vacancy-salary">от 150 000 \u20bd</span>',
    )
    vacancies = asyncio.run(
        _hh_collector().collect(_Client(_Resp(_hh_live_page(text_only))), now=NOW)
    )
    assert (vacancies[0].salary.min, vacancies[0].salary.max, vacancies[0].salary.currency) == (
        150000,
        None,
        "RUB",
    ), f"U-COL-09: текстовый fallback зарплаты {vacancies[0].salary!r}"


@settings(derandomize=True, max_examples=200, deadline=None)
@given(
    first=st.integers(min_value=1, max_value=10**9),
    second=st.integers(min_value=1, max_value=10**9),
    currency=st.sampled_from(["RUB", "USD", "EUR"]),
    dashed=st.booleans(),
)
def test_u_col09_salary_data_values_bounds_property(
    first: int, second: int, currency: str, dashed: bool
) -> None:
    """U-COL-09 (P): <data value> тотальны: границы отсортированы, валюта сохранена."""
    sign = {"RUB": "\u20bd", "USD": "$", "EUR": "\u20ac"}[currency]
    if dashed:
        markup = (
            f'<data value="{first}">{first}</data> \u2013 '
            f'<data value="{second}">{second}</data><data value="{currency}">{sign}</data>'
        )
    else:
        markup = f'<data value="{first}">{first}</data> <data value="{currency}">{sign}</data>'
    page = _hh_live_page(_hh_live_card(salary=markup))
    vacancies = asyncio.run(_hh_collector().collect(_Client(_Resp(page)), now=NOW))
    salary = vacancies[0].salary
    assert salary is not None, f"U-COL-09: зарплата не разобрана: {markup!r}"
    assert salary.currency == currency, f"U-COL-09: валюта {salary.currency!r} != {currency!r}"
    if dashed:
        assert (salary.min, salary.max) == (
            min(first, second),
            max(first, second),
        ), f"U-COL-09: границы {salary!r} не отсортированы для {markup!r}"
    else:
        assert (salary.min, salary.max) == (first, None), f"U-COL-09: {salary!r} != {(first, None)}"


# --- U-COL-10 (R75): промо-карточки пропускаются молча (D6) ---------------------


def test_u_col10_promo_cards_skipped_silently() -> None:
    """U-COL-10: href заголовка не на /vacancy/ → карточка пропускается без ошибки;
    страница только из промо-карточек — общий контракт §9.5 (ParseError, не «тишина»)."""
    promo = _hh_live_card(
        title="Финансовый менеджер",
        company="Рекламный работодатель",
        href="https://adsrv.hh.ru/click?b=2262371&amp;place=35&amp;clickType=link_to_vacancy&amp;j=1",
        promo=True,
    )
    vacancies = asyncio.run(
        _hh_collector().collect(_Client(_Resp(_hh_live_page(_hh_live_card(), promo))), now=NOW)
    )
    assert [v.title for v in vacancies] == ["Младший Python-разработчик"], (
        f"U-COL-10: промо-карточка не пропущена: {[v.title for v in vacancies]!r}"
    )
    assert all("adsrv" not in v.url for v in vacancies), f"U-COL-10: adsrv в URL: {vacancies!r}"
    with pytest.raises(ParseError):
        asyncio.run(_hh_collector().collect(_Client(_Resp(_hh_live_page(promo))), now=NOW))


# --- U-COL-11 (R76): нет даты публикации → момент сбора (D5) --------------------


def test_u_col11_missing_publish_date_falls_back_to_collection_time() -> None:
    """U-COL-11: у hh.ru нет даты в выдаче → published_at == now (D5), карточка не
    отбрасывается; дата источника (когда она есть) имеет приоритет."""
    collected = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
    vacancies = asyncio.run(
        _hh_collector().collect(_Client(_Resp(_hh_live_page(_hh_live_card()))), now=collected)
    )
    assert vacancies[0].published_at == collected, (
        f"U-COL-11: published_at {vacancies[0].published_at!r} != момент сбора {collected!r}"
    )
    later = datetime(2026, 3, 15, 9, 0, tzinfo=UTC)
    vacancies = asyncio.run(
        _hh_collector().collect(_Client(_Resp(_hh_live_page(_hh_live_card()))), now=later)
    )
    assert vacancies[0].published_at == later, "U-COL-11: now не прокинут в published_at"
    dated = HH_PAGE  # старая разметка с <time datetime="..."> — дата источника в приоритете
    vacancies = asyncio.run(_hh_collector().collect(_Client(_Resp(dated)), now=later))
    assert vacancies[0].published_at == datetime(2026, 3, 14, 6, 0, tzinfo=UTC), (
        f"U-COL-11: дата источника заменена моментом сбора: {vacancies[0].published_at!r}"
    )


# --- U-COL-12 (R77): challenge → SourceBlocked, «captcha» в JSON — не ложный ----


@pytest.mark.parametrize("marker", ["ddos-guard", "qrator", "smart-captcha", "Just a moment"])
def test_u_col12_challenge_marker_beyond_first_4kb_blocks_source(marker: str) -> None:
    """U-COL-12: маркер challenge-защиты в структурной позиции (<script>) за
    пределами первых 4096 байт → SourceBlocked (детект во всём теле, до разбора
    карточек). I-3-fix (F-22): маркер только в видимом тексте блокировку не даёт —
    новый контракт закреплён в U-COL-16 (было — «во всём теле», решения §9.4)."""
    padding = "<!-- " + "x" * 5_000 + " -->"
    page = f"<html><body>{padding}<script>window.marker = '{marker}';</script></body></html>"
    with pytest.raises(SourceBlocked):
        asyncio.run(_hh_collector().collect(_Client(_Resp(page))))


def test_u_col12_captcha_in_embedded_state_json_is_not_a_block() -> None:
    """U-COL-12: «captcha»/«accessDenied» в скрытом JSON-состоянии hh (template) —
    не блокировка; слабый маркер капчи блокирует только в <title>/<h1> (F-22, (г))."""
    vacancies = asyncio.run(
        _hh_collector().collect(
            _Client(_Resp(_hh_live_page(_hh_live_card(), state=HH_STATE_TEMPLATE))), now=NOW
        )
    )
    assert vacancies, "U-COL-12: ложный срабатывание на JSON-состоянии hh"
    with pytest.raises(SourceBlocked):
        heading = "<html><head><title>please solve the captcha</title></head><body></body></html>"
        asyncio.run(_hh_collector().collect(_Client(_Resp(heading))))


# --- U-COL-13 (R78): граница ParseError/EmptyResult + живая разметка Habr ------


def test_u_col13_unparseable_cards_raise_parse_error_not_empty_result() -> None:
    """U-COL-13: скелет есть, карточки есть, но не разобраны → ParseError; валидная
    страница без карточек → EmptyResult (§9.5, S95/S11)."""
    broken = _hh_live_page(
        '<article data-qa="vacancy-serp__vacancy"><span>Карточка без заголовка</span></article>',
        '<article data-qa="vacancy-serp__vacancy">'
        '<a data-qa="serp-item__title" href="https://hh.ru/vacancy/1">Без компании</a></article>',
    )
    with pytest.raises(ParseError) as excinfo:
        asyncio.run(_hh_collector().collect(_Client(_Resp(broken)), now=NOW))
    assert not isinstance(excinfo.value, EmptyResult), "U-COL-13: EmptyResult вместо ParseError"
    with pytest.raises(EmptyResult):
        asyncio.run(_hh_collector().collect(_Client(_Resp(_hh_live_page())), now=NOW))


def test_u_col13_live_habr_markup_parses_including_card_without_salary() -> None:
    """U-COL-13: div.vacancy-card / title-link / company a / basic-salary / basic-date:
    относительный href → career.habr.com, дата из time.basic-date, salary=None без зарплаты."""
    paid = _habr_live_card(
        "Frontend-разработчик",
        "ELEMENTAREE",
        href="/vacancies/1000169548",
        salary=(
            '<div class="vacancy-card__salary"><div class="basic-salary">'
            "от 170 000 \u20bd</div></div>"
        ),
        moment="2026-10-28T08:47:07+03:00",
    )
    free = _habr_live_card(
        "Rust Developer",
        "Bell Integrator",
        href="/vacancies/1000169404",
        moment="2026-10-28T09:12:55+03:00",
    )
    # момент сбора — после дат карточек (F-23: далёкое будущее > now + сутки
    # отбрасывается к моменту сбора; здесь даты источника — в прошлом)
    collected_at = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    vacancies = asyncio.run(
        _habr_collector().collect(_Client(_Resp(_habr_live_page(paid, free))), now=collected_at)
    )
    by_title = {v.title: v for v in vacancies}
    assert set(by_title) == {"Frontend-разработчик", "Rust Developer"}, (
        f"U-COL-13: заголовки {sorted(by_title)!r}"
    )
    assert by_title["Frontend-разработчик"].salary is not None, "U-COL-13: зарплата не разобрана"
    assert by_title["Rust Developer"].salary is None, "U-COL-13: выдумана зарплата без basic-salary"
    assert by_title["Rust Developer"].url == "https://career.habr.com/vacancies/1000169404", (
        f"U-COL-13: относительная ссылка {by_title['Rust Developer'].url!r}"
    )
    assert by_title["Frontend-разработчик"].published_at == datetime.fromisoformat(
        "2026-10-28T08:47:07+03:00"
    ), f"U-COL-13: дата карточки {by_title['Frontend-разработчик'].published_at!r}"
    assert by_title["Rust Developer"].company == "Bell Integrator", (
        f"U-COL-13: компания {by_title['Rust Developer'].company!r}"
    )
