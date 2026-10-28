"""Юнит-тесты ужесточения коллекторов I-3-fix (U-COL-14..19, F-20..F-25).

Владелец: software-engineer. Без БД и сети. Находки security review I-3
(`docs/security/report.md` §10): F-20 (ReDoS на недоверенном HTML), F-21 (крах
`int()` в зарплате), F-22 (детект challenge — решение арбитра), F-23 (дата из
далёкого будущего), F-24 (лимит тела ответа), F-25 (allowlist хостов URL).
Каждый фикс закреплён красным тестом до кода; патологические входы F-20 — с
бюджетом времени (квадратичный regex вылезал секундами/минутами).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.collectors import (
    EmptyResult,
    ParseError,
    SourceBlocked,
    SourceUnavailable,
    build_collectors,
)
from app.collectors.base import CollectorError

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

CONTRACT_ERRORS = (ParseError, EmptyResult, SourceBlocked, SourceUnavailable)


class _Resp:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.headers: dict[str, str] = {}


class _Client:
    def __init__(self, payload: _Resp) -> None:
        self.payload = payload

    async def get(self, url: str, *, headers=None):  # noqa: ANN001, ANN202
        return self.payload


def _hh_collector():
    return next(c for c in build_collectors() if c.name == "hh.ru")


def _habr_collector():
    return next(c for c in build_collectors() if c.name == "Habr Career")


def _hh_card(title: str, company: str, href: str, salary: str = "") -> str:
    """Карточка hh.ru по живым маркерам 28.10.2026."""
    return (
        '<article data-qa="vacancy-serp__vacancy" class="magritte-card">'
        f'<a data-qa="serp-item__title" tabindex="0" href="{href}" target="_blank">'
        f'<span data-qa="serp-item__title-text">{title}</span></a>'
        f'<span data-qa="vacancy-serp__vacancy-employer-text">{company}</span>'
        f"<div>{salary}</div>"
        "</article>"
    )


def _hh_page(*cards: str) -> str:
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"></head><body>'
        '<div data-qa="vacancy-serp__results">' + "".join(cards) + "</div></body></html>"
    )


def _habr_card(title: str, company: str, href: str, published: str) -> str:
    """Карточка Habr Career по живым маркерам 28.10.2026."""
    return (
        '<div class="vacancy-card">'
        f'<a aria-label="{title}" class="vacancy-card__backdrop-link" href="{href}"></a>'
        '<div class="vacancy-card__inner">'
        f'<div class="vacancy-card__date"><time class="basic-date" datetime="{published}">'
        "28 октября</time></div>"
        '<div class="vacancy-card__info">'
        f'<div class="vacancy-card__company"><a class="link-comp" href="/companies/x">'
        f"{company}</a></div>"
        f'<div class="vacancy-card__title"><a class="vacancy-card__title-link" href="{href}">'
        f"{title}</a></div>"
        "</div></div></div>"
    )


def _habr_page(*cards: str) -> str:
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


def _collect_error(collector, body: str) -> type[Exception] | None:
    """Класс ошибки контракта при сборе body; успешный сбор → None."""
    try:
        asyncio.run(collector.collect(_Client(_Resp(body))))
    except CollectorError as exc:
        return type(exc)
    return None


# --- U-COL-14 (F-20, CWE-1333): недоверенный HTML без квадратичного regex -----


def _redos_bodies() -> list[tuple[str, str]]:
    card_head = (
        '<article data-qa="vacancy-serp__vacancy">'
        '<a data-qa="serp-item__title" href="https://hh.ru/vacancy/1">X</a>'
    )
    return [
        # воспроизводитель §10.4: N незакрытых `<!--` без `-->` → O(n²) в _HIDDEN_RE
        ("комментарий без закрытия", "<!--" * 20_000 + "clean"),
        # воспроизводитель §10.4: незакрытые <a data-qa="serp-item__title"> в карточке
        (
            "незакрытые якоря",
            '<div data-qa="vacancy-serp__results"><article data-qa="vacancy-serp__vacancy">'
            + '<a data-qa="serp-item__title">' * 5_000
            + "</article></div>",
        ),
        # воспроизводитель §10.4: поток `<` без `>` → O(n²) в LEGACY_COMPANY_PATTERN
        (
            "поток '<' без '>'",
            '<div data-qa="vacancy-serp__results">'
            + card_head
            + "<" * 20_000
            + '<span data-qa="vacancy-serp__vacancy-employer-text">C</span>'
            "</article></div>",
        ),
    ]


@pytest.mark.parametrize(("name", "body"), _redos_bodies(), ids=[n for n, _ in _redos_bodies()])
def test_u_col14_untrusted_bodies_parse_within_budget(name: str, body: str) -> None:
    """U-COL-14 (F-20): вредоносные тела разбираются за миллисекунды (бюджет 1.0s),
    исключения — только контракта api.md §6; полные размеры воспроизводителя
    (800 КБ комментарий, 20k якорей) замеряются в отчёте I-3-fix."""
    started = time.perf_counter()
    try:
        asyncio.run(_hh_collector().collect(_Client(_Resp(body))))
    except CONTRACT_ERRORS:
        pass  # классификация мусорного тела — любая ошибка контракта
    except Exception as exc:  # noqa: BLE001 - падение вне контракта недопустимо
        raise AssertionError(f"U-COL-14: {type(exc).__name__} вне контракта: {exc}") from exc
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"U-COL-14: «{name}» ({len(body)} символов) занял {elapsed:.2f}s"


# --- U-COL-15 (F-21): зарплата из <data value> не падает на мусорных значениях --


@pytest.mark.parametrize("value", ["\u00b2", "9" * 4301, "12,5", "-5", "\u0663", ""])
def test_u_col15_garbage_data_values_never_crash_salary(value: str) -> None:
    """U-COL-15 (F-21): value из не-десятичных цифр (²), гигантских чисел
    (4301 цифра), дробных/отрицательных/не-ASCII — без ValueError вне контракта
    api.md §6; зарплата таких карточек — None («Зарплата не указана»)."""
    salary = f'<data value="{value}">\u20bd</data> <data value="RUB">\u20bd</data>'
    page = _hh_page(_hh_card("Т", "С", "/vacancy/1", salary=salary))
    try:
        vacancies = asyncio.run(_hh_collector().collect(_Client(_Resp(page)), now=NOW))
    except CONTRACT_ERRORS as exc:
        raise AssertionError(f"U-COL-15: {type(exc).__name__} на value={value!r}") from exc
    except Exception as exc:  # noqa: BLE001 - ValueError и др. вне контракта
        raise AssertionError(f"U-COL-15: {type(exc).__name__} вне контракта: {exc}") from exc
    assert vacancies[0].salary is None, f"U-COL-15: выдумана зарплата из value={value!r}"


@settings(derandomize=True, max_examples=100, deadline=None)
@given(value=st.text(max_size=60))
def test_u_col15_data_value_property_never_crashes(value: str) -> None:
    """U-COL-15 (P): произвольный value в <data> — либо контрактная ошибка,
    либо карточка; зарплата — None или валидный Salary с границами (0, int64]."""
    salary = f'<data value="{value}">x</data> <data value="RUB">\u20bd</data>'
    page = _hh_page(_hh_card("Т", "С", "/vacancy/1", salary=salary))
    try:
        vacancies = asyncio.run(_hh_collector().collect(_Client(_Resp(page)), now=NOW))
    except CollectorError:
        return
    parsed = vacancies[0].salary
    if parsed is not None:
        for bound in (parsed.min, parsed.max):
            if bound is not None:
                assert 0 < bound <= 2**63 - 1, f"U-COL-15: граница {bound} вне (0, int64]"


# --- U-COL-16 (F-22): детект challenge по решению арбитра --------------------


def test_u_col16_split_markers_in_structural_positions_still_block() -> None:
    """U-COL-16 (F-22, «а»): маркер, разорванный комментарием/entity/дефисом,
    после нормализации матчится — в <title>/<script>/cookie-атрибутах блок."""
    blocked_bodies = [
        "<html><head><title>Just a mome<!--x-->nt</title></head><body></body></html>",
        "<html><head><title>Just a&nbsp;moment</title></head><body></body></html>",
        "<html><head><title>SmartCaptcha</title></head><body></body></html>",
        "<html><body><script>window.ddos_guard_challenge = true;</script></body></html>",
        '<html><body><script>document.cookie = "__qrator_captcha=1;";</script></body></html>',
        '<html><body><link rel="stylesheet" href="https://smart-captcha.ru/x.css"></body></html>',
        '<html><body><div data-cookie="__qrator_captcha=1"></div></body></html>',
    ]
    for body in blocked_bodies:
        assert _collect_error(_hh_collector(), body) is SourceBlocked, (
            f"U-COL-16: {body!r} не классифицирован как SourceBlocked"
        )


def test_u_col16_visible_vacancy_text_never_blocks() -> None:
    """U-COL-16 (F-22, «в»): видимый текст (в т.ч. карточек вакансий — «Qrator»,
    «just a moment», «ddos-guard») НИКОГДА не даёт SourceBlocked: ложный блок —
    это постоянная потеря источника (запрещено решением арбитра)."""
    page = _hh_page(
        _hh_card("Just a moment to start", "Qrator", "/vacancy/1"),
        _hh_card("ddos-guard инженер", "SmartCaptcha Labs", "/vacancy/2"),
    )
    vacancies = asyncio.run(_hh_collector().collect(_Client(_Resp(page)), now=NOW))
    assert [v.title for v in vacancies] == ["Just a moment to start", "ddos-guard инженер"], (
        f"U-COL-16: карточки потеряны/заблокированы: {vacancies!r}"
    )
    marker_page = '<html><body><div id="challenge-content">ddos-guard</div></body></html>'
    assert _collect_error(_hh_collector(), marker_page) is ParseError, (
        "U-COL-16: маркер в видимом тексте дал не ParseError"
    )


def test_u_col16_weak_markers_only_in_title_h1() -> None:
    """U-COL-16 (F-22, «г»): слабые «captcha»/«access denied» — только в
    <title>/<h1> после нормализации; в <p>/<img alt>/template/видимом тексте — нет."""
    blocked_bodies = [
        "<html><head><title>please solve the captcha</title></head><body></body></html>",
        "<html><body><h1>Access Denied</h1></body></html>",
    ]
    for body in blocked_bodies:
        assert _collect_error(_hh_collector(), body) is SourceBlocked, (
            f"U-COL-16: {body!r} не классифицирован как SourceBlocked"
        )
    unblocked_bodies = [
        "<html><body><p>Access Denied</p></body></html>",
        '<html><body><img alt="Captcha"></body></html>',
        "<html><body><p>Please complete the captcha</p></body></html>",
        "<html><body>please solve the captcha</body></html>",
        "<html><body><h2>Access Denied</h2></body></html>",
        "<html><body><template>access denied captcha</template></body></html>",
    ]
    for body in unblocked_bodies:
        assert _collect_error(_hh_collector(), body) is not SourceBlocked, (
            f"U-COL-16: ложный SourceBlocked на {body!r}"
        )


def test_u_col16_comment_markers_never_block() -> None:
    """U-COL-16 (F-22, «а»): маркер в комментарии (<!-- ddos-guard -->) — не блок."""
    comment_only = "<html><body><!-- ddos-guard test --></body></html>"
    assert _collect_error(_hh_collector(), comment_only) is not SourceBlocked
    page = "<html><body><!-- qrator -->" + _hh_page(_hh_card("Т", "С", "/vacancy/1"))
    page += "</body></html>"
    vacancies = asyncio.run(_hh_collector().collect(_Client(_Resp(page)), now=NOW))
    assert len(vacancies) == 1, f"U-COL-16: комментарий сломал разбор: {vacancies!r}"


# --- U-COL-17 (F-23): published_at из далёкого будущего -> момент сбора -------


def test_u_col17_far_future_publish_date_falls_back_to_collection_time() -> None:
    """U-COL-17 (F-23): дата > now + сутки (обход retention) и мусорная дата —
    момент сбора (D5); свежая дата и граница «now + сутки» — как в источнике."""
    collected = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    far = ("9999-12-31T23:59:59+00:00", "2026-10-30T09:00:00+00:00", "мусор")
    for published in far:
        page = _habr_page(_habr_card("Т", "С", "/vacancies/1", published))
        vacancies = asyncio.run(_habr_collector().collect(_Client(_Resp(page)), now=collected))
        assert vacancies[0].published_at == collected, (
            f"U-COL-17: {published!r} -> {vacancies[0].published_at!r} != момент сбора"
        )
    fresh = "2026-10-27T09:00:00+00:00"
    page = _habr_page(_habr_card("Т", "С", "/vacancies/1", fresh))
    vacancies = asyncio.run(_habr_collector().collect(_Client(_Resp(page)), now=collected))
    assert vacancies[0].published_at == datetime.fromisoformat(fresh)
    boundary = "2026-10-29T12:00:00+00:00"  # ровно now + сутки — допустимо
    page = _habr_page(_habr_card("Т", "С", "/vacancies/1", boundary))
    vacancies = asyncio.run(_habr_collector().collect(_Client(_Resp(page)), now=collected))
    assert vacancies[0].published_at == datetime.fromisoformat(boundary)
    beyond = "2026-10-29T12:00:01+00:00"  # чуть дальше суток — момент сбора
    page = _habr_page(_habr_card("Т", "С", "/vacancies/1", beyond))
    vacancies = asyncio.run(_habr_collector().collect(_Client(_Resp(page)), now=collected))
    assert vacancies[0].published_at == collected


@settings(derandomize=True, max_examples=100, deadline=None)
@given(raw=st.text(max_size=60))
def test_u_col17_publish_date_property_bounded(raw: str) -> None:
    """U-COL-17 (P): произвольное datetime-значение — без крашей; published_at
    tz-aware и никогда не дальше now + суток (обход retention невозможен)."""
    collected = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    page = _habr_page(_habr_card("Т", "С", "/vacancies/1", raw))
    try:
        vacancies = asyncio.run(_habr_collector().collect(_Client(_Resp(page)), now=collected))
    except CollectorError:
        return
    published = vacancies[0].published_at
    assert published.tzinfo is not None, f"U-COL-17: naive published_at ({raw!r})"
    assert published <= collected + timedelta(days=1), (
        f"U-COL-17: published_at {published!r} > now + сутки (datetime={raw!r})"
    )


# --- U-COL-18 (F-24): лимит тела ответа (отказ, не обрезка) ------------------


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, n: int) -> bytes:  # noqa: ARG002 - интерфейс StreamReader
        return self._chunks.pop(0) if self._chunks else b""


def test_u_col18_response_body_size_capped_with_source_unavailable() -> None:
    """U-COL-18 (F-24): тело > 5 МиБ — отказ SourceUnavailable (обрезанный HTML
    дал бы ложный ParseError); в пределах лимита — тело целиком."""
    http_mod = __import__("app.services.http", fromlist=["read_limited"])
    read_limited = getattr(http_mod, "read_limited", None)
    assert read_limited is not None, "U-COL-18: read_limited не реализован (F-24)"
    limit = http_mod.MAX_BODY_BYTES
    assert limit == 5 * 1024 * 1024, f"U-COL-18: лимит {limit} != 5 МиБ"

    def run(chunks: list[bytes]) -> bytes:
        return asyncio.run(read_limited(_FakeStream(chunks)))

    assert run([b"x" * 64] * 4) == b"x" * 256
    assert run([b"y" * limit]) == b"y" * limit
    with pytest.raises(SourceUnavailable):
        run([b"z" * (1024 * 1024)] * 6)
    with pytest.raises(SourceUnavailable):
        run([b"z" * (limit + 1)])


class _AsyncCM:
    def __init__(self, value: object) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self._value

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeResponse:
    status = 200
    headers = {"Content-Type": "text/html; charset=utf-8"}
    charset = "utf-8"

    def __init__(self, chunks: list[bytes]) -> None:
        self.content = _FakeStream(chunks)


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def get(self, url: str, *, headers: object = None) -> _AsyncCM:  # noqa: ARG002
        return _AsyncCM(self._response)


def test_u_col18_aiohttp_client_enforces_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """U-COL-18: AiohttpClient.get читает тело через ограниченное чтение —
    гигантский ответ источника не буферизуется целиком (усилитель F-20 закрыт)."""
    import app.services.http as http_mod

    response = _FakeResponse([b"<html>ok</html>"])

    def fake_session(**kwargs: object) -> _AsyncCM:  # noqa: ARG001
        return _AsyncCM(_FakeSession(response))

    monkeypatch.setattr(http_mod.aiohttp, "ClientSession", fake_session)
    client = http_mod.AiohttpClient(timeout_seconds=5)
    result = asyncio.run(client.get("https://example.test/"))
    assert result.text == "<html>ok</html>", f"U-COL-18: тело искажено: {result.text!r}"

    response.content = _FakeStream([b"z" * (1024 * 1024)] * 6)
    with pytest.raises(SourceUnavailable):
        asyncio.run(client.get("https://example.test/"))


# --- U-COL-19 (F-25): allowlist хостов URL вакансии --------------------------


def test_u_col19_foreign_host_cards_skipped_like_promo() -> None:
    """U-COL-19 (F-25): чужой хост (фишинг evil.example/vacancy/1, подделка
    hh.ru.evil.com) — карточка пропускается молча, как промо (D6), в результат
    и кэш не попадает; страница только из таких карточек — контракт §9.5."""
    evil_page = _hh_page(_hh_card("Фишинг", "С", "https://evil.example/vacancy/1"))
    assert _collect_error(_hh_collector(), evil_page) is ParseError, (
        "U-COL-19: страница только из чужих хостов дала не ParseError (§9.5)"
    )
    mixed_page = _hh_page(
        _hh_card("Фишинг", "С", "https://evil.example/vacancy/1"),
        _hh_card("Подделка", "С", "https://hh.ru.evil.com/vacancy/3"),
        _hh_card("Настоящая", "С", "/vacancy/2"),
        _hh_card("Субдомен", "С", "https://sub.hh.ru/vacancy/4"),
    )
    vacancies = asyncio.run(_hh_collector().collect(_Client(_Resp(mixed_page)), now=NOW))
    assert [v.url for v in vacancies] == [
        "https://hh.ru/vacancy/2",
        "https://sub.hh.ru/vacancy/4",
    ], f"U-COL-19: allowlist обойдён: {[v.url for v in vacancies]!r}"
    assert all("evil" not in v.url for v in vacancies), "U-COL-19: фишинговый URL в результате"


def test_u_col19_habr_hosts_allowed() -> None:
    """U-COL-19 (F-25): у Habr Career разрешены career.habr.com и habr.com
    (+поддомены), чужой хост — пропуск молча."""
    dates = "2026-10-27T09:00:00+00:00"
    page = _habr_page(
        _habr_card("Карьера", "С", "https://career.habr.com/vacancies/1", dates),
        _habr_card("Хабр", "С", "https://habr.com/vacancies/2", dates),
        _habr_card("Фишинг", "С", "https://evil.example/vacancies/3", dates),
    )
    vacancies = asyncio.run(_habr_collector().collect(_Client(_Resp(page)), now=NOW))
    assert [v.title for v in vacancies] == ["Карьера", "Хабр"], (
        f"U-COL-19: allowlist Habr: {[v.title for v in vacancies]!r}"
    )
