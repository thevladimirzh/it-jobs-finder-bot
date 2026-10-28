"""Недоверенный HTML источников (TB-1) против НОВЫХ путей разбора I-3 (28.10.2026).

Итерация I-3 переписала парсеры коллекторов под живую разметку (`CardLayout`,
`parse_listing`, `raise_if_blocked`, промо-отсечка, `published_at` из атрибута).
Эти тесты закрепляют гарантии безопасности именно на новых путях: недоверенный
HTML источника не даёт HTML-инъекцию в Telegram-вывод (SEC-01/SEC-05),
опасные схемы URL не переживают канонизацию (SEC-02/SEC-12), challenge-страницы
классифицируются как `SourceBlocked`, а «captcha» в JSON/script/comment — нет
(S94, U-COL-12 на security-уровне), даты из атрибутов не ломают разбор (D5/S93),
гигантские страницы разбираются за линейное время (SEC-09).

Дефекты ревью I-3 (F-20..F-25, `docs/security/report.md` §10) исправлены
(I-3-fix, software-engineer). Контракт challenge-детекта — decisions §9.4
**редакция 2** (решение арбитра 28.10, F-22): нормализация тела (а), сильные
маркеры только в структурных позициях (`<script>`/`<link>`/
cookie-атрибуты/`<title>`) (б), слабые — только в
`<title>`/`<h1>` (г), видимый текст никогда не блокирует (в), HTTP 403/429 →
`SourceBlocked` (д); F-25 — allowlist хостов (чужой хост — молча, как промо;
decisions §9.7 D7). Редакция 1 §9.4 («маркеры во всём теле») устарела.
Тесты SEC-09/SEC-12 ниже обновлены под этот контракт 28.10.2026.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hypothesis import given, settings
from hypothesis import strategies as st
from support import (
    HTML_PAYLOADS,
    assert_no_raw_markup,
    found_tags,
    load_attr,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

ALLOWED_ERRORS = ("ParseError", "SourceBlocked", "EmptyResult", "SourceUnavailable")


# ---------------------------------------------------------------------------
# Синтетические карточки ВСЕХ четырёх схем разбора (живые + legacy маркеры)
# ---------------------------------------------------------------------------


def _hh_live_page(title: str, company: str, href: str = "/vacancy/1") -> str:
    return (
        '<div data-qa="vacancy-serp__results">'
        '<article data-qa="vacancy-serp__vacancy">'
        f'<a data-qa="serp-item__title" href="{href}">{title}</a>'
        f'<span data-qa="vacancy-serp__vacancy-employer-text">{company}</span>'
        '<data value="100000">100 000</data> <data value="RUB">\u20bd</data>'
        "</article></div>"
    )


def _hh_legacy_page(title: str, company: str, href: str = "https://hh.ru/vacancy/1") -> str:
    return (
        '<div data-qa="vacancy-serp">'
        '<div data-qa="vacancy-serp-item">'
        f'<a data-qa="vacancy-title" href="{href}">{title}</a>'
        f'<div data-qa="vacancy-company">{company}</div>'
        '<div data-qa="vacancy-salary">\u043e\u0442 150 000 \u20bd</div>'
        '<div data-qa="vacancy-description">python</div>'
        '<time datetime="2026-03-14T09:00:00+03:00"></time>'
        "</div></div>"
    )


def _habr_live_page(
    title: str,
    company: str,
    href: str = "/vacancies/1/vacancy",
    published: str = "2026-10-27T09:00:00+00:00",
) -> str:
    return (
        "<div data-vacancy-list>"
        '<div class="vacancy-card">'
        f'<a class="vacancy-card__title-link" href="{href}">{title}</a>'
        f'<div class="vacancy-card__company"><a>{company}</a></div>'
        '<div class="vacancy-card__salary"><div class="basic-salary">100 000 \u20bd</div></div>'
        f'<time class="basic-date" datetime="{published}">\u0432\u0447\u0435\u0440\u0430</time>'
        "</div></div>"
    )


def _habr_legacy_page(title: str, company: str, href: str = "/vacancies/100") -> str:
    return (
        '<div class="vacancies-list">'
        '<article class="vacancy-card">'
        f'<a class="vacancy-card__title" data-qa="vacancy-title" href="{href}">{title}</a>'
        f'<div class="vacancy-card__company" data-qa="vacancy-company">{company}</div>'
        '<div class="vacancy-card__salary" data-qa="vacancy-salary">\u043e\u0442 250 000 \u20bd</div>'  # noqa: E501
        '<div class="vacancy-card__description" data-qa="vacancy-description">go</div>'
        '<time datetime="2026-03-13T12:00:00+03:00"></time>'
        "</article></div>"
    )


def _layout(source: str) -> tuple[Any, str]:
    """(CardLayout, base_url) для источника: живая схема с legacy-fallback."""
    if source == "hh.ru":
        return load_attr("app.collectors.hh", "LAYOUT"), load_attr("app.collectors.hh", "BASE_URL")
    return load_attr("app.collectors.habr", "LAYOUT"), load_attr("app.collectors.habr", "BASE_URL")


def _legacy_layout(source: str) -> tuple[Any, str]:
    legacy_layout = load_attr("app.collectors.base", "legacy_layout")
    if source == "hh.ru":
        return legacy_layout(
            'data-qa="vacancy-serp"', 'data-qa="vacancy-serp-item"'
        ), "https://hh.ru"
    return legacy_layout(
        'class="vacancies-list"', 'class="vacancy-card"'
    ), "https://career.habr.com"


PAGES = {
    ("hh.ru", "live"): _hh_live_page,
    ("hh.ru", "legacy"): _hh_legacy_page,
    ("Habr Career", "live"): _habr_live_page,
    ("Habr Career", "legacy"): _habr_legacy_page,
}


async def _parse(html_text: str, source: str, variant: str) -> list[Any]:
    parse_listing = load_attr("app.collectors.base", "parse_listing")
    layout, base_url = _layout(source) if variant == "live" else _legacy_layout(source)
    return await parse_listing(html_text, source=source, base_url=base_url, layout=layout, now=NOW)


def _parse_sync(html_text: str, source: str, variant: str) -> list[Any]:
    return asyncio.run(_parse(html_text, source, variant))


def _render_card(vacancy: Any, lang: str) -> str:
    render_card = load_attr("app.services.digest", "render_card")
    return render_card(n=1, vacancy=vacancy, lang=lang, now=NOW)


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text
        self.headers: dict[str, str] = {}


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def get(self, url: str, *, headers: Any = None) -> _FakeResponse:
        return self._response


# --- SEC-01 / SEC-05: HTML-инъекция через НОВЫЕ пути разбора -----------------


def test_SEC_01_parsed_fields_never_render_raw_markup() -> None:
    """SEC-01 (новые пути I-3): payload в title/company разметки всех 4 схем
    не даёт сырой Telegram-разметки — рендер только из экранированных полей."""
    for (source, variant), build in PAGES.items():
        for payload in HTML_PAYLOADS:
            # "T"/"C" гарантируют непустые поля: пустой title — честный пропуск
            # карточки по контракту, payload проверяется на рендер-инъекцию
            page = build("T" + payload, "C" + payload)
            try:
                vacancies = _parse_sync(page, source, variant)
            except Exception as exc:  # noqa: BLE001 - допустимы только 4 ошибки контракта
                assert type(exc).__name__ in ALLOWED_ERRORS, (
                    f"SEC-01: {type(exc).__name__} из parse_listing "
                    f"({source}/{variant}, payload={payload!r}) — вне контракта api.md §6"
                )
                continue
            assert vacancies, f"SEC-01: карточка потеряна ({source}/{variant}, {payload!r})"
            for vacancy in vacancies:
                for lang in ("ru", "en"):
                    text = _render_card(vacancy, lang)
                    assert_no_raw_markup(
                        text, f"SEC-01 рендер {source}/{variant} lang={lang} payload={payload!r}"
                    )
                    assert set(found_tags(text)) <= {"b"}, (
                        f"SEC-01: теги {found_tags(text)} из payload {payload!r}: {text!r}"
                    )
                    assert text.count("<b>") == 1, f"SEC-01: не один <b>: {text!r}"


def test_SEC_01_parsed_url_never_contains_markup_or_dangerous_schemes() -> None:
    """SEC-01/SEC-02 (новые пути I-3): href из недоверенной разметки после
    канонизации не содержит <>'\"/пробелов/управляющих и опасных схем."""
    hrefs = [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
        '" onmouseover="alert(1)',
        'https://evil.example/"><a href="http://evil.example/">x</a>',
        "https://hh.ru/vacancy/1?x=%3Cscript%3E",
    ]
    for (source, variant), build in PAGES.items():
        for href in hrefs:
            page = build("Title", "Company", href=href)
            try:
                vacancies = _parse_sync(page, source, variant)
            except Exception as exc:  # noqa: BLE001
                assert type(exc).__name__ in ALLOWED_ERRORS, (
                    f"SEC-02: {type(exc).__name__} ({source}/{variant}, href={href!r})"
                )
                continue
            for vacancy in vacancies:
                url = vacancy.url
                for bad_char in ('"', "'", "<", ">", "\x00"):
                    assert bad_char not in url, (
                        f"SEC-02: {bad_char!r} в URL {url!r} (href={href!r})"
                    )
                assert not any(ch.isspace() or ord(ch) < 0x20 for ch in url), (
                    f"SEC-02: пробел/управляющий символ в URL {url!r}"
                )
                lowered = url.lower()
                for scheme in ("javascript:", "data:", "file:", "vbscript:"):
                    assert not lowered.startswith(scheme), f"SEC-02: {scheme} в URL {url!r}"
                text = _render_card(vacancy, "ru")
                assert_no_raw_markup(text, f"SEC-02 рендер с url={url!r}")


# --- SEC-02/SEC-12: промо-отсечка и опасные href ---------------------------


def test_SEC_12_promo_filter_and_dangerous_hrefs_never_reach_digest() -> None:
    """SEC-12 (D6 + F-25): промо-href (adsrv) и карточки с чужим хостом молча
    пропускаются (не в кэше/результате) на живых схемах hh/habr; опасные схемы
    и чужие хосты не дают ссылку в дайджест ни на одной схеме («dangerous hrefs
    never reach digest»). Страница только из промо/чужих карточек → контракт
    §9.5 / решение арбитра (е): `ParseError`, не молчаливый `[]` и не
    `SourceBlocked` (F-25: allowlist хостов закрыл обход промо-фильтра)."""
    hh_live, _ = _layout("hh.ru")
    habr_live, _ = _layout("Habr Career")
    assert hh_live.href_fragment == "/vacancy/"
    assert habr_live.href_fragment == "/vacancies/"
    # F-25: allowlist хостов закреплён конфигурацией схем (хост + его поддомены)
    assert hh_live.allowed_hosts == ("hh.ru",)
    assert set(habr_live.allowed_hosts) == {"career.habr.com", "habr.com"}

    def _hh_card(href: str, title: str = "T", company: str = "C") -> str:
        return (
            _hh_live_page(title, company, href=href)
            .removeprefix('<div data-qa="vacancy-serp__results">')
            .removesuffix("</div>")
        )

    # промо (D6) + чужой хост (F-25) + обычная карточка: в результат попадает
    # только обычная — промо и чужой хост отсекаются молча, без алерта
    mixed = (
        '<div data-qa="vacancy-serp__results">'
        + _hh_card("https://adsrv.hh.ru/click?x=1&url=/vacancy/1", "Promo", "Ads")
        + _hh_card("https://evil.example/vacancy/1", "Evil", "Phish")
        + _hh_card("/vacancy/2")
        + "</div>"
    )
    urls = [v.url for v in _parse_sync(mixed, "hh.ru", "live")]
    assert urls == ["https://hh.ru/vacancy/2"], f"SEC-12: промо/чужой хост прошли отсечку: {urls}"

    # страница ТОЛЬКО из промо — общий контракт §9.5 (ParseError), не молчаливый []
    promo_page = _hh_live_page("T", "C", href="https://adsrv.hh.ru/click?x=1&url=/vacancy/1")
    try:
        vacancies = _parse_sync(promo_page, "hh.ru", "live")
    except Exception as exc:  # noqa: BLE001
        assert type(exc).__name__ == "ParseError", (
            f"SEC-12: {type(exc).__name__} на промо-странице — ждали ParseError (§9.5)"
        )
    else:
        raise AssertionError(
            f"SEC-12: промо-страница молча вернула {[v.url for v in vacancies]} — "
            "по контракту §9.5 ждали ParseError"
        )

    # F-25, (е): страница ТОЛЬКО из чужих карточек → ParseError (диагностика),
    # не тихий [] и не SourceBlocked (ложный алерт «блокировка»)
    for source, variant, build, href in (
        ("hh.ru", "live", _hh_live_page, "https://evil.example/vacancy/1"),
        ("Habr Career", "live", _habr_live_page, "https://evil.example/vacancies/1/vacancy"),
    ):
        try:
            vacancies = _parse_sync(build("T", "C", href=href), source, variant)
        except Exception as exc:  # noqa: BLE001
            assert type(exc).__name__ == "ParseError", (
                f"SEC-12: {type(exc).__name__} на странице только из чужих карточек "
                f"({source}) — ждали ParseError (F-25, (е))"
            )
        else:
            urls = [v.url for v in vacancies]
            raise AssertionError(f"SEC-12: чужой хост прошёл allowlist ({source}): {urls}")

    # опасные href не доходят до дайджеста: чужие хосты (в т.ч. подделка суффикса
    # hh.ru.evil.example и «похожий» evil-hh.ru — не поддомен) и опасные схемы —
    # ни одна карточка результата их не содержит (F-25 + SEC-02)
    dangerous_hrefs = [
        "https://evil.example/vacancy/1",
        "https://hh.ru.evil.example/vacancy/1",
        "https://evil-hh.ru/vacancy/1",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
    ]
    cards = [_hh_card(href, f"T{i}", "C") for i, href in enumerate(dangerous_hrefs)]
    cards.append(_hh_card("/vacancy/2"))
    page = '<div data-qa="vacancy-serp__results">' + "".join(cards) + "</div>"
    vacancies = _parse_sync(page, "hh.ru", "live")
    urls = [v.url for v in vacancies]
    assert urls == ["https://hh.ru/vacancy/2"], f"SEC-12: опасный href в дайджесте: {urls}"
    for vacancy in vacancies:
        host = urlsplit(vacancy.url).hostname or ""
        assert host == "hh.ru" or host.endswith(".hh.ru"), (
            f"SEC-12: хост {host!r} вне allowlist в результате ({vacancy.url!r})"
        )
        assert vacancy.url.startswith("https://"), f"SEC-12: не-https URL {vacancy.url!r}"
        text = _render_card(vacancy, "ru")
        assert_no_raw_markup(text, "SEC-12 рендер после отсечки опасных href")
        assert "<a" not in text, f"SEC-12: карточка создала <a>-тег: {text!r}"


# --- SEC-09: challenge-детект (S94; контракт (б)-(е) — decisions §9.4
#     редакция 2, решение арбитра F-22 28.10) ---


def test_SEC_09_challenge_fixtures_and_status_codes_raise_source_blocked() -> None:
    """SEC-09/S94: challenge-фикстуры и HTTP 403/429 → SourceBlocked до разбора."""
    fetch_page = load_attr("app.collectors.base", "fetch_page")
    source_blocked = load_attr("app.collectors.base", "SourceBlocked")
    for name in ("hh_challenge.html", "habr_challenge.html"):
        body = (DATA_DIR / name).read_text(encoding="utf-8")
        try:
            asyncio.run(fetch_page(_FakeClient(_FakeResponse(200, body)), "https://example.test"))
            raise AssertionError(f"SEC-09: {name} не классифицирована как SourceBlocked")
        except source_blocked:
            pass
    for status in (403, 429):
        try:
            asyncio.run(
                fetch_page(
                    _FakeClient(_FakeResponse(status, "<html>ok</html>")), "https://example.test"
                )
            )
            raise AssertionError(f"SEC-09: HTTP {status} не дал SourceBlocked")
        except source_blocked:
            pass


def test_SEC_09_hidden_captcha_markers_never_block_real_listing() -> None:
    """SEC-09 (S94/U-COL-12): «captcha»/капча-ключи в JSON/script/comment —
    НЕ блокировка: страница hh с JSON-состоянием разбирается нормально."""
    raise_if_blocked = load_attr("app.collectors.base", "raise_if_blocked")
    fetch_page = load_attr("app.collectors.base", "fetch_page")
    page = _hh_live_page("T", "C")
    hidden_variants = [
        '<script>HH-Lux-InitialState={"k":"error.signup.captcha.invalid","captcha":1}</script>',
        "<!-- captcha widget placeholder -->",
        '<script src="https://hh.ru/captcha.js"></script>',
        "<style>.captcha{display:none}</style>",
        "<template>access denied page mock</template>",
    ]
    for fragment in hidden_variants:
        body = fragment + page
        raise_if_blocked(body)  # не должен бросить
        result = asyncio.run(
            fetch_page(_FakeClient(_FakeResponse(200, body)), "https://example.test")
        )
        assert result == body, "SEC-09: fetch_page искажает тело"


def test_SEC_09_visible_block_markers_and_strong_markers_raise_source_blocked() -> None:
    """SEC-09/S94: страница блокировки → `SourceBlocked` (контракт (б)/(г) =
    decisions §9.4 редакция 2, решение арбитра F-22 28.10; имя теста сохранено
    как ID сценария I-3).

    (б) сильные маркеры (ddos-guard/qrator/smart-captcha/«just a moment») —
    только в структурных позициях `<script>`/`<link>`/cookie-атрибуты/`<title>`
    после нормализации (а) — разорванный комментарием/entity маркер матчится;
    (г) слабые «captcha»/«access denied» — только в `<title>`/`<h1>`.
    Негативные контролы (в): видимый текст с маркером (в т.ч. карточка вакансии
    «Qrator», фраза «just a moment») НИКОГДА не даёт `SourceBlocked` —
    ложный блок = постоянная потеря источника."""
    raise_if_blocked = load_attr("app.collectors.base", "raise_if_blocked")
    source_blocked = load_attr("app.collectors.base", "SourceBlocked")

    blocked_bodies = [
        # (г) слабые маркеры — реалистичные заголовочные позиции:
        "<html><head><title>Access Denied</title></head><body></body></html>",
        "<html><body><h1>Access Denied</h1></body></html>",
        "<html><head><title>Please complete the captcha</title></head><body></body></html>",
        "<html><body><h1>please solve the captcha</h1></body></html>",
        # (б) сильные маркеры — структурные позиции:
        '<script src="https://ddos-guard.net/x.js"></script>',
        "<title>Just a moment...</title>",
        '<link rel="stylesheet" href="https://qrator.ru/challenge.css">',
        '<div data-cookie="__qrator_captcha=1">x</div>',
        # (а) нормализация: разорванный комментарием/entity маркер матчится:
        "<title>Smart<!--x-->Captcha</title>",
        "<title>Just a&nbsp;moment...</title>",
        # реалистичная страница блокировки (суть сценария):
        (
            "<html><head><title>Just a moment...</title></head><body>"
            "<p>Проверяем ваш браузер</p>"
            '<script src="https://smart-captcha.ru/captcha.js"></script>'
            "</body></html>"
        ),
    ]
    for body in blocked_bodies:
        try:
            raise_if_blocked(body)
            raise AssertionError(f"SEC-09: {body!r} не классифицирована как SourceBlocked")
        except source_blocked:
            pass

    # (в) видимый текст и непозиционные места — НИКОГДА не SourceBlocked.
    # Старые тела `<p>Access Denied</p>` / `<img alt="Captcha">` /
    # `<p>Please complete the captcha</p>` теперь ЖИВУТ ЗДЕСЬ: после решения
    # арбитра они не являются страницей блокировки ((г)/(в) — не их позиции).
    unblocked_bodies = [
        "<p>Access Denied</p>",
        '<img alt="Captcha">',
        "<p>Please complete the captcha</p>",
        # вакансия «Qrator» (реальный работодатель hh) и фраза «just a moment»
        # в тексте карточки — легитимный контент, блок запрещён (в):
        '<article><a href="/vacancy/1">\u0418\u043d\u0436\u0435\u043d\u0435\u0440</a>'
        '<div class="vacancy-company">Qrator</div></article>',
        "<p>\u0432\u0430\u043a\u0430\u043d\u0441\u0438\u044f just a moment "
        "\u043d\u0430\u0437\u0430\u0434 (ddos-guard "
        "\u0438\u043d\u0436\u0435\u043d\u0435\u0440)</p>",
        # (г): <h2> не входит в зону слабых маркеров (только <title>/<h1>):
        "<h2>Access Denied</h2>",
        # (б): <h1> — не структурная позиция сильных маркеров, текст видимый (в):
        "<h1>Just a moment...</h1>",
        # (а): комментарий снимается нормализацией — маркер в нём не считается:
        "<!-- ddos-guard -->",
    ]
    for body in unblocked_bodies:
        try:
            raise_if_blocked(body)
        except source_blocked:
            raise AssertionError(
                f"SEC-09: ложный SourceBlocked на {body!r} (запрещено контрактом (в))"
            ) from None


# --- SEC-09 (D5/S93): published_at из атрибута ------------------------------


def test_SEC_09_future_publication_date_clamps_to_today() -> None:
    """SEC-09 (D5/S93): «дата из будущего» не даёт отрицательного возраста и
    не ломает рендер (format_age: будущее → «сегодня»/today)."""
    format_age = load_attr("app.services.digest", "format_age")
    i18n_t = load_attr("app.i18n", "t")
    page = _habr_live_page("T", "C", published="9999-12-31T23:59:59+00:00")
    vacancies = _parse_sync(page, "Habr Career", "live")
    assert vacancies, "SEC-09: карточка с будущей датой потеряна"
    published = vacancies[0].published_at
    assert published.tzinfo is not None, "SEC-09: published_at без tz"
    for lang in ("ru", "en"):
        age = format_age(published, NOW, lang)
        assert age == i18n_t("age.today", lang), (
            f"SEC-09: возраст из будущей даты {published.isoformat()} = {age!r}"
        )


# --- P-SEC-08 / P-SEC-09 (hypothesis, фиксированный seed) -------------------


@settings(derandomize=True, max_examples=100, deadline=None)
@given(payload=st.text(max_size=200), href=st.text(max_size=200))
def test_P_SEC_08_untrusted_markup_parse_renders_safely(payload: str, href: str) -> None:
    """P-SEC-08: произвольный текст в полях/href живой разметки → разбор даёт
    либо ≥1 безопасную вакансию, либо ровно одно из 4 исключений контракта."""
    collector_error = load_attr("app.collectors.base", "CollectorError")
    page = _hh_live_page(payload or "T", payload or "C", href=href or "/vacancy/1")
    try:
        vacancies = _parse_sync(page, "hh.ru", "live")
    except collector_error:
        return
    assert vacancies, "P-SEC-08: пустой список мимо контракта api.md §6"
    for vacancy in vacancies:
        for bad_char in ('"', "'", "<", ">", "\x00"):
            assert bad_char not in vacancy.url, f"P-SEC-08: {bad_char!r} в URL {vacancy.url!r}"
        text = _render_card(vacancy, "ru")
        assert_no_raw_markup(text, f"P-SEC-08 рендер payload={payload!r}")
        assert set(found_tags(text)) <= {"b"}, f"P-SEC-08: теги {found_tags(text)}"


@settings(derandomize=True, max_examples=100, deadline=None)
@given(raw=st.text(max_size=60))
def test_P_SEC_09_publication_date_attribute_never_crashes(raw: str) -> None:
    """P-SEC-09: произвольное значение datetime-атрибута → разбор не падает,
    published_at всегда tz-aware (мусорная дата → момент сбора, D5)."""
    page = _habr_live_page("T", "C", published=raw)
    try:
        vacancies = _parse_sync(page, "Habr Career", "live")
    except Exception as exc:  # noqa: BLE001 - допустимы только 4 ошибки контракта
        assert type(exc).__name__ in ALLOWED_ERRORS, (
            f"P-SEC-09: {type(exc).__name__} на datetime={raw!r} — вне контракта api.md §6"
        )
        return
    assert vacancies, "P-SEC-09: карточка потеряна"
    for vacancy in vacancies:
        assert vacancy.published_at.tzinfo is not None, (
            f"P-SEC-09: naive published_at {vacancy.published_at!r} (datetime={raw!r})"
        )


# --- SEC-09: гигантские входы (1.6 МБ живой выдачи) -------------------------


def test_SEC_09_large_listing_parses_within_budget() -> None:
    """SEC-09: живая выдача ~1.6 МБ (fixture ×21) разбирается за линейное время
    (замер I-3: 25 мс; бюджет 5 с — запас на медленный CI)."""
    base = (DATA_DIR / "hh_live_list.html").read_text(encoding="utf-8")
    body = base * 21
    assert len(body) > 1_600_000, f"SEC-09: фикстура не выросла до 1.6 МБ ({len(body)})"
    started = time.perf_counter()
    vacancies = _parse_sync(body, "hh.ru", "live")
    elapsed = time.perf_counter() - started
    assert len(vacancies) == 105, f"SEC-09: потеряно карточек: {len(vacancies)}"
    assert elapsed < 5.0, f"SEC-09: разбор 1.6 МБ занял {elapsed:.2f}s (бюджет 5s)"


def test_SEC_09_giant_fields_stay_bounded_in_render() -> None:
    """SEC-09: гигантские title/company из источника не дают сообщение >4096
    и не ломают рендер (обрезка title/company, DigestError не нужен)."""
    huge = "x" * 500_000
    page = _hh_live_page(huge, huge)
    vacancies = _parse_sync(page, "hh.ru", "live")
    assert vacancies, "SEC-09: карточка с гигантскими полями потеряна"
    message_limit = load_attr("app.services.digest", "MESSAGE_LIMIT")
    text = _render_card(vacancies[0], "ru")
    assert len(text) <= message_limit, f"SEC-09: карточка {len(text)} символов > {message_limit}"
    assert len(vacancies[0].company) <= 101, (
        f"SEC-09: company не обрезана: {len(vacancies[0].company)}"
    )
    assert_no_raw_markup(text, "SEC-09 гигантские поля")
