"""Зарплаты: разбор строк источников, форматирование, сравнение (api.md §4).

Семантика — brief §6.1/§7.3 и decisions §5.8–§5.10: приблизительные курсы
(только сравнение/сортировка), gross/net не разделяются, ``min > max`` → обмен,
суммы ≤ 0, переполнение int64 и мусор → ``None`` («Зарплата не указана»).
Функции тотальны и не бросают исключений (R8, R22, P-SAL-01/02).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.i18n import Lang, t

_INT64_MAX = 2**63 - 1

# Приблизительные курсы к рублю (brief §7.3: точность не требуется).
RATES: dict[str, Decimal] = {
    "RUB": Decimal("1"),
    "USD": Decimal("100"),
    "EUR": Decimal("105"),
    "GBP": Decimal("120"),
    "CNY": Decimal("13"),
    "KZT": Decimal("0.2"),
    "UAH": Decimal("2.3"),
    "BYN": Decimal("30"),
    "AMD": Decimal("0.25"),
    "GEL": Decimal("37"),
    "TRY": Decimal("2.5"),
    "AZN": Decimal("58"),
}

CURRENCY_SIGNS: dict[str, str] = {"RUB": "\u20bd", "USD": "$", "EUR": "\u20ac"}

_CURRENCY_SYMBOLS = {"\u20bd": "RUB", "\u2044": "", "$": "USD", "\u20ac": "EUR"}
_CURRENCY_WORDS = {"руб": "RUB", "rub": "RUB", "рублей": "RUB", "р": "RUB"}
_ISO_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]{3}(?![A-Za-z])")
_MINUS_RE = re.compile(r"[-\u2212]\s*\d")
_KEYWORD_FROM_RE = re.compile(r"(?<![а-яa-zё])от(?![а-яa-zё])", re.IGNORECASE)
_KEYWORD_TO_RE = re.compile(r"(?<![а-яa-zё])до(?![а-яa-zё])", re.IGNORECASE)
_DASH_RE = re.compile(r"[\u2013\u2014-]")
_GROUP_SEP_RE = re.compile(r"(?<=\d)[. \u00a0\u202f](?=\d{3}(?!\d))")
_AMOUNT_RE = re.compile(
    r"\d+(?:[.,]\d{1,2})?\s*(?:\u0442\u044b\u0441\u043e?\.?|\u043c\u043b\u043d\u043e?\.?)?",
    re.IGNORECASE,
)
_MULT_RE = re.compile(r"(\u0442\u044b\u0441|\u043c\u043b\u043d)", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\d+(?:[.,]\d{1,2})?")


@dataclass(frozen=True)
class Salary:
    """Нормализованная зарплата: ``currency`` — ISO 4217 верхним регистром."""

    min: int | None
    max: int | None
    currency: str


def parse_salary(raw: str | None) -> Salary | None:
    """Разбирает «сырую» строку источника; мусор → ``None`` (никогда не падает)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    if _MINUS_RE.search(raw):
        return None  # отрицательные суммы → None целиком (S16, P-SAL-02)
    currency = _extract_currency(raw)
    if not currency:
        return None
    amounts = _extract_amounts(raw)
    if not amounts:
        return None
    has_from = _KEYWORD_FROM_RE.search(raw) is not None
    has_to = _KEYWORD_TO_RE.search(raw) is not None
    dashed = len(amounts) >= 2 and _dash_between(raw, amounts)
    if has_from and has_to and len(amounts) >= 2 or dashed:
        minimum, maximum = amounts[0], amounts[1]
    elif has_from:
        minimum, maximum = amounts[0], None
    elif has_to:
        minimum, maximum = None, amounts[0]
    else:
        minimum, maximum = amounts[0], None
    if minimum is not None and maximum is not None and minimum > maximum:
        minimum, maximum = maximum, minimum
    for value in (minimum, maximum):
        if value is not None and not 0 < value <= _INT64_MAX:
            return None
    if minimum is None and maximum is None:
        return None
    return Salary(min=minimum, max=maximum, currency=currency)


def format_salary(salary: Salary | None, lang: Lang) -> str:
    """Точная строка зарплаты brief §6.1 (разряды — U+0020, диапазон — U+2013)."""
    if salary is None or (salary.min is None and salary.max is None):
        return t("salary.none", lang)
    sign = CURRENCY_SIGNS.get(salary.currency, salary.currency)
    if salary.min is not None and salary.max is not None:
        return t(
            "salary.range",
            lang,
            minimum=_grouped(salary.min),
            maximum=_grouped(salary.max),
            currency=sign,
        )
    if salary.min is not None:
        return t("salary.from", lang, amount=_grouped(salary.min), currency=sign)
    return t("salary.to", lang, amount=_grouped(salary.max), currency=sign)


def estimate(salary: Salary) -> int | None:
    """Оценка для сравнения: ``min`` если есть, иначе ``max`` (decisions §5.10)."""
    if salary.min is not None:
        return salary.min
    return salary.max


def to_rubles(salary: Salary) -> int | None:
    """Приблизительная сумма в рублях; неизвестная валюта → ``None``."""
    value = estimate(salary)
    if value is None:
        return None
    rate = RATES.get(salary.currency)
    if rate is None:
        return None
    rubles = Decimal(value) * rate
    if rubles > Decimal(_INT64_MAX):
        return None
    return int(rubles.to_integral_value(rounding="ROUND_HALF_UP"))


def meets_minimum(salary: Salary | None, minimum_rub: int | None) -> bool:
    """``salary is None`` → ``True`` (lenient, decisions §5.9)."""
    if salary is None or minimum_rub is None:
        return True
    rubles = to_rubles(salary)
    if rubles is None:
        return True
    return rubles >= minimum_rub


def _grouped(amount: int) -> str:
    """Целое число с разрядами через U+0020 (decisions §3.4)."""
    sign = "-" if amount < 0 else ""
    digits = str(abs(amount))
    chunks: list[str] = []
    while digits:
        chunks.append(digits[-3:])
        digits = digits[:-3]
    return sign + " ".join(reversed(chunks))


def _extract_currency(raw: str) -> str | None:
    for symbol, iso in _CURRENCY_SYMBOLS.items():
        if symbol and symbol in raw:
            return iso
    lowered = raw.lower()
    for word, iso in _CURRENCY_WORDS.items():
        if re.search(rf"(?<![а-яa-z]){word}(?![а-яa-z])", lowered):
            return iso
    match = _ISO_RE.search(raw)
    if match:
        return match.group(0).upper()
    return None


def _extract_amounts(raw: str) -> list[int]:
    cleaned = _GROUP_SEP_RE.sub("", raw)
    values: list[int] = []
    for token in _AMOUNT_RE.findall(cleaned):
        digits = _DIGITS_RE.search(token)
        if not digits:
            continue
        try:
            value = Decimal(digits.group(0).replace(",", "."))
        except InvalidOperation:
            continue
        if _MULT_RE.search(token):
            multiplier = Decimal(1000) if "тыс" in token.lower() else Decimal(1_000_000)
            value *= multiplier
        try:
            as_int = int(value.to_integral_value(rounding="ROUND_HALF_UP"))
        except (InvalidOperation, ValueError, OverflowError):
            continue
        values.append(as_int)
    return values


def _dash_between(raw: str, amounts: list[int]) -> bool:
    """Между двумя суммами стоит тире («100 000 – 200 000 ₽»)."""
    first = str(amounts[0])
    second = str(amounts[1])
    pos_first = raw.find(first)
    pos_second = raw.find(second, pos_first + len(first))
    if pos_first < 0 or pos_second < 0:
        return _DASH_RE.search(raw) is not None
    return _DASH_RE.search(raw[pos_first:pos_second]) is not None
