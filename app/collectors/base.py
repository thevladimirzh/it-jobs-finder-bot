"""База коллекторов (api.md §6): типы, ошибки, канонизация и нормализация.

Сетевые вызовы — только через переданный ``client`` (R41); ``collect`` никогда
не возвращает пустой список молча (R40): 0 карточек → ``EmptyResult``,
битая разметка → ``ParseError``, блокировка/капча → ``SourceBlocked``,
сеть/таймаут/5xx → ``SourceUnavailable``.

Разбор списка карточек описывает :class:`CardLayout` — fallback-цепочки маркеров
живой разметки (I-3, 28.10.2026) со старыми маркерами как запасным вариантом:
парсер принимает И старые, И новые маркеры (решения §9).

Безопасность на недоверенном HTML (TB-1, report §10, I-3-fix):
- F-20 (CWE-1333): разбор идёт линейными стадиями (:class:`FieldRule` /
  :class:`CardRule`, скан тегов ``<``…``>``), квадратичных regex ``.*?``/``[^>]*``
  по блокам больше нет;
- F-22: ``raise_if_blocked`` реализует решение арбитра (нормализация тела,
  сильные маркеры — только в структурных позициях ``<script>``/``<link>``/
  cookie-атрибутах/``<title>``, слабые — только в ``<title>``/``<h1>``; видимый
  текст карточек вакансий не триггерит ``SourceBlocked`` никогда);
- F-23: ``published_at`` из атрибута валидируется по диапазону (далёкое будущее
  → момент сбора);
- F-25: URL карточки обязан вести на хост источника (allowlist) — чужой хост
  пропускается молча, как промо-карточка (D6).
"""

from __future__ import annotations

import asyncio
import html
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from app.domain.currency import Salary

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_HTTP_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
_UTC_OFFSET = "+00:00"

FIELD_LIMIT = 100  # гарантия «остальные поля короткие» (QA §6.10, decisions §5.7)

# Маркеры challenge-защиты (F-22, решение арбитра): сильные — только в
# структурных позициях (<script>/<link>/cookie-атрибуты/<title>), слабые —
# только в заголовочных (<title>/<h1>); видимый текст не проверяется вовсе
# (ложный блок на вакансии «Qrator»/фразе «just a moment» запрещён).
_STRONG_MARKERS = ("ddos-guard", "qrator", "smart-captcha", "just a moment")
# Слабые маркеры капчи/отказа: «captcha» во встроенном JSON-состоянии hh.ru
# (словари локализации) блокировкой не является (S94/U-COL-12).
_WEAK_BLOCK_MARKERS = ("captcha", "access denied")
_KEYWORD_FROM_RE = re.compile(r"(?<![а-яa-zё])от(?![а-яa-zё])", re.IGNORECASE)
_KEYWORD_TO_RE = re.compile(r"(?<![а-яa-zё])до(?![а-яa-zё])", re.IGNORECASE)
_CURRENCY_CODE_RE = re.compile(r"[A-Z]{3}")
_CURRENCY_SIGNS = {"\u20bd": "\u20bd", "$": "$", "\u20ac": "\u20ac"}
_DATETIME_RE = r'<time[^>]*datetime="([^"]+)"'
_WS_RE = re.compile(r"\s*")


class CollectorError(Exception):
    """Базовая ошибка источника."""


class ParseError(CollectorError):
    """Битая/неожиданная разметка → алерт «ошибка разбора разметки»."""


class SourceBlocked(CollectorError):
    """Блокировка/капча (403/429) → алерт «блокировка/капча»."""


class EmptyResult(CollectorError):
    """0 карточек при валидной разметке → алерт «пустой разбор»."""


class SourceUnavailable(CollectorError):
    """Сеть/таймаут/5xx → алерт «источник недоступен»."""


@dataclass(frozen=True)
class Vacancy:
    """Нормализованная вакансия из HTML-карточки источника."""

    title: str
    company: str
    salary: Salary | None
    url: str
    source: str
    published_at: datetime
    description: str = ""


@runtime_checkable
class ResponseLike(Protocol):
    status_code: int
    text: str
    headers: Mapping[str, str]


@runtime_checkable
class HttpClient(Protocol):
    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> Any: ...


@runtime_checkable
class Collector(Protocol):
    name: str

    async def collect(
        self, client: HttpClient, *, now: datetime | None = None
    ) -> list[Vacancy]: ...


def canonicalize_url(raw: str) -> str:
    """Канонический URL: https + нижний регистр хоста, без UTM и хвостового ``/``.

    Безопасность (SEC-02/SEC-12): только http/https-схемы; ``javascript:``/``data:``/
    ``file:`` и иные схемы отбрасываются; в результате нет ``"'<>``, пробелов и
    управляющих символов. Никогда не бросает исключений.
    """
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        text = raw.strip()
        if _HTTP_SCHEME_RE.match(text):
            return _canonical_http(text)
        scheme = _SCHEME_RE.match(text)
        if scheme is not None:
            text = text[scheme.end() :]  # опасная/чужая схема не попадает в результат
        return _quote_safe(text)
    except Exception:  # noqa: BLE001 - канонизация тотальна (P-DED-01)
        return _quote_safe(str(raw))


def normalize_text(raw: str) -> str:
    """Нормализованный текст для дедупа: lower, без пунктуации, одинарные пробелы."""
    if not isinstance(raw, str):
        return ""
    letters = "".join(ch if ch.isalnum() else " " for ch in raw.lower())
    return " ".join(letters.split())


def clamp_text(raw: str, limit: int = FIELD_LIMIT) -> str:
    """Обрезка внешнего поля до ``limit`` code points с «…» (QA §6.10).

    Гарантия «остальные поля короткие»: карточка с гигантским ``company``/
    ``description`` остаётся разрешимо короткой и не даёт ``DigestError``.
    Короткий текст возвращается как есть; исключений не бросает.
    """
    text = raw if isinstance(raw, str) else str(raw)
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "\u2026"


async def fetch_page(
    client: HttpClient,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """GET страницы источника; любая ошибка транспорта → ``SourceUnavailable``."""
    try:
        response = await client.get(url, headers=dict(headers or {}))
    except CollectorError:
        raise
    except Exception as exc:  # noqa: BLE001 - любые ошибки сети/клиента
        raise SourceUnavailable(f"request failed: {exc}") from exc
    status = getattr(response, "status_code", 200)
    body = getattr(response, "text", "") or ""
    if status in (403, 429):
        raise SourceBlocked(f"HTTP {status}")
    if status >= 500 or status < 200:
        raise SourceUnavailable(f"HTTP {status}")
    raise_if_blocked(body)
    return body


# ---------------------------------------------------------------------------
# Детект challenge-страниц (F-22, решение арбитра)
# ---------------------------------------------------------------------------


def raise_if_blocked(body: str) -> None:
    """Классификация challenge-страницы → ``SourceBlocked`` (F-22, решение арбитра).

    (а) тело нормализуется: комментарии снимаются, entity декодируются (в т.ч.
    ``&nbsp;``), пробелы схлопываются, регистр/разделители игнорируются — маркер,
    разорванный комментарием/entity/дефисом (``SmartCaptcha``), всё равно матчится;
    (б) сильные маркеры триггерят блокировку ТОЛЬКО в структурных позициях:
    ``<script>``, ``<link>``, cookie-атрибуты, ``<title>``;
    (в) видимый текст (в т.ч. текст карточек вакансий) не триггерит блокировку
    никогда: вакансия «Qrator» или фраза «just a moment» не должны лишать источник;
    (г) слабые маркеры («captcha»/«access denied») ищутся только в ``<title>``/``<h1>``.
    HTTP 403/429 классифицируется в :func:`fetch_page`.
    """
    if not isinstance(body, str):
        return
    text = _strip_comments(body)
    strong, weak = _marker_zones(text)
    strong_key = _marker_key(strong)
    for marker in _STRONG_MARKERS:
        if _marker_key(marker) in strong_key:
            raise SourceBlocked(f"challenge marker: {marker}")
    weak_key = _marker_key(weak)
    for marker in _WEAK_BLOCK_MARKERS:
        if _marker_key(marker) in weak_key:
            raise SourceBlocked("captcha / access denied")


def _marker_key(text: str) -> str:
    """Ключ сравнения маркера (F-22, (а)): entity декодируются (``&nbsp;``),
    регистр и разделители игнорируются (``SmartCaptcha`` ~ ``smart-captcha``) —
    для тела и маркера ключ считается одинаково, «закрывает обход»."""
    return "".join(ch for ch in html.unescape(text).lower() if ch.isalnum())


def _strip_comments(text: str) -> str:
    """Линейное снятие HTML-комментариев ``<!-- … -->`` (незакрытый — до конца)."""
    out: list[str] = []
    pos = 0
    while True:
        lt = text.find("<!--", pos)
        if lt < 0:
            out.append(text[pos:])
            return "".join(out)
        out.append(text[pos:lt])
        end = text.find("-->", lt + 4)
        if end < 0:
            return "".join(out)  # незакрытый комментарий тянется до конца
        pos = end + 3


def _marker_zones(text: str) -> tuple[str, str]:
    """(сильная, слабая) зоны для маркеров: линейный скан тегов (F-20/F-22).

    Сильная зона: элементы ``<script>`` (включая cookie-строки в JS),
    ``<link>``, cookie-атрибуты любых тегов, содержимое ``<title>``.
    Слабая зона: содержимое ``<title>``/``<h1>``. Видимый текст не входит
    ни в одну зону (в).
    """
    strong_parts: list[str] = []
    weak_parts: list[str] = []
    pos = 0
    while True:
        lt = text.find("<", pos)
        if lt < 0:
            break
        gt = text.find(">", lt + 1)
        if gt < 0:
            break  # '<' без '>' — не тег; видимый текст (в) не проверяется
        tag = text[lt : gt + 1]
        name = _tag_name(tag)
        if name == "script":
            close = _find_close(text, "</script>", gt + 1)
            stop = len(text) if close is None else close + len("</script>")
            strong_parts.append(text[lt:stop])
            pos = stop
        elif name == "link":
            strong_parts.append(tag)
            pos = gt + 1
        elif name in ("title", "h1"):
            close = _find_close(text, f"</{name}>", gt + 1)
            stop = len(text) if close is None else close
            content = text[gt + 1 : stop]
            if name == "title":
                strong_parts.append(content)  # (б): <title> — и для сильных
            weak_parts.append(content)  # (г): слабые — <title>/<h1>
            pos = stop if close is None else close + len(name) + 3
        else:
            if "cookie" in tag.lower():  # дешёвый гейт: cookie-атрибуты редки
                for value in _cookie_attr_values(tag):
                    strong_parts.append(value)  # (б): cookie-атрибуты
            pos = gt + 1
    return " ".join(strong_parts), " ".join(weak_parts)


_COOKIE_ATTR_RE = re.compile(r'([\w-]*cookie[\w-]*)\s*=\s*("[^"]*"|\'[^\']*\')', re.IGNORECASE)
_DOC_COOKIE_RE = re.compile(r"document\s*\.\s*cookie", re.IGNORECASE)


def _cookie_attr_values(tag: str) -> Iterator[str]:
    """Cookie-атрибуты тега: имена с «cookie» в имени и значения с
    ``document.cookie`` (F-22, «cookie-атрибуты» в структурных позициях)."""
    for match in _COOKIE_ATTR_RE.finditer(tag):
        yield match.group(2)
    if _DOC_COOKIE_RE.search(tag):
        yield tag


def _tag_name(tag: str) -> str:
    """Имя тега в нижнем регистре (без ``<``); для ``<!--`` → ``!--``."""
    pos = 1
    end = pos
    while end < len(tag) and (tag[end].isalpha() or tag[end].isdigit()):
        end += 1
    return tag[pos:end].lower()


def _find_close(text: str, close: str, start: int) -> int | None:
    """Индекс закрывающего маркера (без учёта регистра) или ``None``."""
    match = _compile(re.escape(close)).search(text, start)
    return None if match is None else match.start()


@cache
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)


# ---------------------------------------------------------------------------
# Линейный разбор карточек (F-20, CWE-1333): никаких квадратичных regex
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldRule:
    """Правило извлечения поля из блока карточки линейным сканом (F-20).

    ``open_re`` матчится только по тексту одного тега (``<``…``>``), поэтому
    стоимость правила O(размер блока) даже на патологическом входе.

    Захват: ``attr=True`` — группа 1 ``open_re`` (значение атрибута тега);
    ``anchor=True`` — весь элемент от ``<`` открытого тега до ``close_re``
    (включительно); иначе — содержимое после тега (опционального ``inner_re``)
    до ``close_re``; пустой ``close_re`` — до следующего ``<``, который обязателен
    (семантика старых ``([^<]*)<``).
    """

    open_re: str
    close_re: str = ""
    inner_re: str = ""
    anchor: bool = False
    attr: bool = False


@dataclass(frozen=True)
class CardRule:
    """Нахождение начала карточек (F-20): тег по ``tag_re`` либо литерал."""

    tag_re: str = ""
    literal: str = ""


def _iter_tags(text: str, start: int = 0) -> Iterator[tuple[int, int]]:
    """Все теги как пары (начало, конец за ``>``) сканом ``<``…``>``: O(n).

    Незакрытый ``<`` без ``>`` в хвосте даёт последнюю «псевдотег»-область до
    конца текста — регулярка сама решает, подходит ли она (старые regex такие
    хвосты тоже рассматривали).
    """
    pos = start
    while True:
        lt = text.find("<", pos)
        if lt < 0:
            return
        gt = text.find(">", lt + 1)
        if gt < 0:
            yield lt, len(text)
            return
        yield lt, gt + 1
        pos = gt + 1


def _extract_rule(rule: FieldRule, block: str) -> str | None:
    """Первое совпадение правила в блоке; нет закрытия — правила нет (O(n)).

    Если маркер закрытия не найден после первой подходящей позиции, его нет и
    после любой более поздней (поиск только вперёд) — поэтому достаточно одного
    поиска: это точно семантика старых regex, но без квадратичных повторов.
    """
    open_pat = _compile(rule.open_re)
    inner_pat = _compile(rule.inner_re) if rule.inner_re else None
    close_pat = _compile(rule.close_re) if rule.close_re else None
    for start, end in _iter_tags(block):
        match = open_pat.match(block, start, end)
        if match is None:
            continue
        if rule.attr:
            return match.group(1)
        content_start = end
        anchor_start = start
        if inner_pat is not None:
            gap_end = _WS_RE.match(block, end).end()  # type: ignore[union-attr]
            inner = _next_tag(block, gap_end)
            if inner is None or inner[0] != gap_end:
                continue  # старая семантика: между тегами только пробелы
            if inner_pat.match(block, inner[0], inner[1]) is None:
                continue
            content_start = inner[1]
            anchor_start = inner[0] if rule.anchor else start
        if close_pat is None:
            lt = block.find("<", content_start)
            if lt < 0:
                return None
            return block[content_start:lt]
        close = close_pat.search(block, content_start)
        if close is None:
            return None
        if rule.anchor:
            return block[anchor_start : close.end()]
        return block[content_start : close.start()]
    return None


def _next_tag(text: str, start: int) -> tuple[int, int] | None:
    for span in _iter_tags(text, start):
        return span
    return None


def _strip_tags(fragment: str) -> str:
    """Теги → пробел линейным сканом (аналог ``<[^>]*>``, без квадратичности)."""
    out: list[str] = []
    pos = 0
    while True:
        lt = fragment.find("<", pos)
        if lt < 0:
            out.append(fragment[pos:])
            return "".join(out)
        out.append(fragment[pos:lt])
        gt = fragment.find(">", lt + 1)
        if gt < 0:
            out.append(fragment[lt:])  # '<' без '>' — не тег, остаётся текстом
            return "".join(out)
        out.append(" ")
        pos = gt + 1


def _extract_href(attrs: str) -> str:
    """Линейный аналог ``_HREF_RE``: первое ``href="…"``/``href='…'`` в атрибутах."""
    lower = attrs.lower()
    exhausted: dict[str, bool] = {'"': False, "'": False}
    pos = 0
    while True:
        i = lower.find("href", pos)
        if i < 0:
            return ""
        j = _WS_RE.match(attrs, i + 4).end()  # type: ignore[union-attr]
        if j < len(attrs) and attrs[j] == "=":
            j = _WS_RE.match(attrs, j + 1).end()  # type: ignore[union-attr]
            if j < len(attrs) and attrs[j] in "\"'":
                quote = attrs[j]
                if not exhausted[quote]:
                    end = attrs.find(quote, j + 1)
                    if end < 0:
                        exhausted[quote] = True
                    else:
                        return attrs[j + 1 : end]
        pos = i + 4


# ---------------------------------------------------------------------------
# Схемы разбора
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardLayout:
    """Правила разбора списка карточек источника (api.md §6).

    Каждое поле — fallback-цепочка правил :class:`FieldRule`: принимаются И новые
    маркеры живой разметки (28.10.2026), И старые синтетические (регрессия,
    решения §9). ``card_rules`` — как находить начала карточек (F-20).
    ``allowed_hosts`` (F-25): хосты URL карточек (запись матчит хост и его
    поддомены); пустой кортеж — без ограничений (legacy-схема).
    """

    container_markers: tuple[str, ...]
    card_rules: tuple[CardRule, ...]
    title_rules: tuple[FieldRule, ...]
    company_rules: tuple[FieldRule, ...]
    salary_text_rules: tuple[FieldRule, ...]
    salary_data_pattern: bool = False  # зарплата из `<data value="...">` (hh.ru)
    description_rules: tuple[FieldRule, ...] = ()
    date_rule: FieldRule = field(default_factory=lambda: FieldRule(open_re=_DATETIME_RE, attr=True))
    href_fragment: str | None = None  # promo-фильтр (D6): путь href обязан вести на фрагмент
    allowed_hosts: tuple[str, ...] = ()  # F-25: allowlist хостов URL вакансии


LEGACY_TITLE_RULE = FieldRule(
    open_re=r'<a\b[^>]*data-qa="vacancy-title"[^>]*>',
    close_re=r"</a>",
    anchor=True,
)
LEGACY_COMPANY_RULE = FieldRule(
    open_re=r'<[^>]*data-qa="vacancy-company"[^>]*>',
    close_re="",  # ([^<]*)< — до следующего '<'
)
LEGACY_SALARY_RULE = FieldRule(
    open_re=r'<[^>]*data-qa="vacancy-salary"[^>]*>',
    close_re="",
)
LEGACY_DESCRIPTION_RULE = FieldRule(
    open_re=r'<[^>]*data-qa="vacancy-description"[^>]*>',
    close_re=r"</[a-zA-Z]",
)


def legacy_layout(container_marker: str, card_marker: str) -> CardLayout:
    """Схема старых синтетических маркеров (регрессионные фикстуры ``tests/data``)."""
    return CardLayout(
        container_markers=(container_marker,),
        card_rules=(CardRule(literal=card_marker),),
        title_rules=(LEGACY_TITLE_RULE,),
        company_rules=(LEGACY_COMPANY_RULE,),
        salary_text_rules=(LEGACY_SALARY_RULE,),
        description_rules=(LEGACY_DESCRIPTION_RULE,),
    )


async def parse_listing(
    html_text: str,
    *,
    source: str,
    base_url: str,
    layout: CardLayout,
    now: datetime | None = None,
) -> list[Vacancy]:
    """Разбор списка карточек по схеме ``layout`` (§9.5): скелет есть, карточки
    присутствуют, но ни одна не разобрана → ``ParseError``; карточек нет →
    ``EmptyResult``; пустой список никогда не возвращается молча."""
    if not any(marker in html_text for marker in layout.container_markers):
        raise ParseError(f"{source}: page skeleton not found")
    positions = _card_positions(layout, html_text)
    if not positions:
        raise EmptyResult(f"{source}: no vacancy cards")
    moment = now if now is not None else datetime.now(UTC)
    vacancies: list[Vacancy] = []
    for index, start in enumerate(positions):
        end = positions[index + 1] if index + 1 < len(positions) else len(html_text)
        vacancy = parse_card(
            html_text[start:end], source=source, base_url=base_url, layout=layout, now=moment
        )
        if vacancy is not None:
            vacancies.append(vacancy)
        if index % 25 == 24:
            await asyncio.sleep(0)  # не блокируем event loop (R35, S17)
    if not vacancies:
        raise ParseError(f"{source}: cards present but none parseable")
    return vacancies


def _card_positions(layout: CardLayout, html_text: str) -> list[int]:
    """Начала карточек: первое правило цепочки с совпадениями (как раньше)."""
    for rule in layout.card_rules:
        if rule.literal:
            positions: list[int] = []
            pos = 0
            while True:
                found = html_text.find(rule.literal, pos)
                if found < 0:
                    break
                positions.append(found)
                pos = found + len(rule.literal)
        else:
            pattern = _compile(rule.tag_re)
            positions = [
                start
                for start, end in _iter_tags(html_text)
                if pattern.match(html_text, start, end)
            ]
        if positions:
            return positions
    return []


async def parse_cards(
    html_text: str,
    *,
    source: str,
    base_url: str,
    container_marker: str,
    card_marker: str,
    now: datetime | None = None,
) -> list[Vacancy]:
    """Разбор списка карточек по старым маркерам; валидная страница без карточек →
    ``EmptyResult`` (контракт сохранён для U-COL-07/U-DED-01/E2E-PERF-02)."""
    return await parse_listing(
        html_text,
        source=source,
        base_url=base_url,
        layout=legacy_layout(container_marker, card_marker),
        now=now,
    )


def parse_card(
    block: str, *, source: str, base_url: str, layout: CardLayout, now: datetime
) -> Vacancy | None:
    """Одна карточка; неполная разметка → ``None`` (карточка пропускается молча).

    Промо-карточка (D6): href заголовка не ведёт на ``layout.href_fragment``
    (например ``/vacancy/`` у hh.ru) → пропуск без алерта; чужой хост (F-25) —
    так же молча, как промо; ``published_at`` без даты в источника = момент сбора
    (D5); дата из далёкого будущего (F-23) — тоже момент сбора.
    """
    anchor = _first_extract(layout.title_rules, block)
    if anchor is None:
        return None
    href_raw, inner = _split_anchor(anchor)
    title = _text(inner)
    href = html.unescape(href_raw).strip()
    if not title or not href:
        return None
    if href.startswith("/"):
        href = base_url.rstrip("/") + href
    url = canonicalize_url(href)
    if not url:
        return None
    if layout.href_fragment is not None and layout.href_fragment not in urlsplit(url).path:
        return None  # промо-карточка: мимо кэша и дедупликации, без алерта (D6)
    if not _host_allowed(urlsplit(url).hostname or "", layout.allowed_hosts):
        return None  # чужой хост (фишинг): как промо, мимо кэша (F-25)
    company = _first_text(layout.company_rules, block)
    if not company:
        return None
    return Vacancy(
        title=title,
        company=clamp_text(company),
        salary=_salary(block, layout),
        url=url,
        source=source,
        published_at=_date(block, layout, now) or now,
        description=clamp_text(_first_text(layout.description_rules, block)),
    )


def _host_allowed(host: str, allowed_hosts: Sequence[str]) -> bool:
    """Allowlist хостов (F-25): хост или его поддомен; пустой список — без
    ограничений (legacy-схема ``parse_cards``)."""
    if not allowed_hosts:
        return True
    lowered = host.lower()
    return any(lowered == entry or lowered.endswith("." + entry) for entry in allowed_hosts)


def _first_extract(rules: Sequence[FieldRule], block: str) -> str | None:
    for rule in rules:
        fragment = _extract_rule(rule, block)
        if fragment is not None:
            return fragment
    return None


def _first_text(rules: Sequence[FieldRule], block: str) -> str:
    fragment = _first_extract(rules, block)
    return _text(fragment) if fragment is not None else ""


def _split_anchor(anchor: str) -> tuple[str, str]:
    """Элемент ссылки ``<a ...>текст</a>`` → (значение href, внутренний HTML)."""
    open_end = anchor.find(">")
    attrs = anchor if open_end < 0 else anchor[:open_end]
    inner = "" if open_end < 0 else anchor[open_end + 1 : -4]  # хвост "</a>"
    return _extract_href(attrs), inner


def _salary(block: str, layout: CardLayout) -> Salary | None:
    from app.domain.currency import parse_salary

    if layout.salary_data_pattern:
        synthetic = _salary_from_data_values(block)
        if synthetic is not None:
            salary = parse_salary(synthetic)
            if salary is not None:
                return salary
    for rule in layout.salary_text_rules:
        fragment = _extract_rule(rule, block)
        if fragment is not None:
            salary = parse_salary(_text(fragment))
            if salary is not None:
                return salary
    return None


_DATA_VALUE_OPEN = '<data value="'


def _data_value_pairs(block: str) -> list[tuple[str, str, int]]:
    """Пары (value, текст, позиция) элементов ``<data value="…">…</data>`` (F-20:
    линейный скан; семантика прежнего ``<data value="([^"]*)">([^<]*)</data>``)."""
    pairs: list[tuple[str, str, int]] = []
    pos = 0
    while True:
        start = block.find(_DATA_VALUE_OPEN, pos)
        if start < 0:
            return pairs
        value_start = start + len(_DATA_VALUE_OPEN)
        quote = block.find('"', value_start)
        gt = block.find(">", quote + 1) if quote >= 0 else -1
        ok = (
            quote >= 0
            and gt == quote + 1
            and block.startswith("</data>", gt + 1 + _plain_len(block, gt + 1))
        )
        if ok:
            text_end = gt + 1 + _plain_len(block, gt + 1)
            pairs.append((block[value_start:quote], block[gt + 1 : text_end], start))
        pos = start + 1  # как findall: следующая попытка — со следующей позиции


def _plain_len(block: str, start: int) -> int:
    """Длина фрагмента ``[^<]*`` с позиции ``start``."""
    end = block.find("<", start)
    return (len(block) if end < 0 else end) - start


def _safe_int(value: str) -> int | None:
    """Безопасный разбор целого из value (F-21): ``isdigit()`` истинно и для
    не-десятичных цифр (²), а ``int()`` падает на гигантских числах (>4300
    цифр) — оба краша вне контракта api.md §6. Лимит длины — ширина int64
    (19 цифр); подход как в ``app/domain/currency.py:_extract_amounts``."""
    if not value or not value.isascii() or not value.isdecimal() or len(value) > 19:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _salary_from_data_values(block: str) -> str | None:
    """Зарплата живой разметки hh.ru из ``<data value="...">`` → текст для parse_salary.

    Суммы и валюта берутся из value-атрибутов (без разбиения разрядов), «от»/«до»
    и диапазон — из текста вокруг значений; чипы опыта/оплаты (``value="3-6"``,
    ``value="1-3"`` с ``data-qa``) не считаются зарплатой. Мусорные значения
    (не-десятичные цифры, гигантские числа) пропускаются без исключений (F-21).
    """
    pairs = _data_value_pairs(block)
    amounts = [(start, parsed) for value, _, start in pairs if (parsed := _safe_int(value))]
    if not amounts:
        return None
    currency = next((value for value, _, _ in pairs if _CURRENCY_CODE_RE.fullmatch(value)), None)
    if currency is None:
        currency = next(
            (_CURRENCY_SIGNS[ch] for _, text, _ in pairs for ch in text if ch in _CURRENCY_SIGNS),
            None,
        )
    if currency is None:
        return None
    values = [parsed for _, parsed in amounts]
    first_start = amounts[0][0]
    prefix = block[block.rfind(">", 0, first_start) + 1 : first_start]
    if len(values) > 1:
        return f"{values[0]} \u2013 {values[1]} {currency}"
    if _KEYWORD_TO_RE.search(prefix) and not _KEYWORD_FROM_RE.search(prefix):
        return f"\u0434\u043e {values[0]} {currency}"
    return f"{values[0]} {currency}"


def _date(block: str, layout: CardLayout, now: datetime) -> datetime | None:
    """Дата из атрибута; мусор и далёкое будущее (F-23: > now + сутки, обход
    retention) → ``None`` — карточка получает момент сбора (D5)."""
    raw = _extract_rule(layout.date_rule, block)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if parsed > now + timedelta(days=1):
        return None
    return parsed


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_strip_tags(fragment)).split())


def _canonical_http(text: str) -> str:
    parts = urlsplit(text)
    if not parts.netloc:
        return _quote_safe(_SCHEME_RE.sub("", text))
    path = parts.path.rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    query = urlencode(sorted(query_pairs))
    return _quote_safe(urlunsplit(("https", parts.netloc.lower(), path, query, "")))


def _quote_safe(text: str) -> str:
    return quote(text, safe=":/?#[]@!$&()*+,;=%~-._")
