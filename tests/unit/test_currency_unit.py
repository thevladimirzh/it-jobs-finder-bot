"""Юнит-тесты зарплат и сравнения (U-SAL-01/02/03).

Владелец: software-engineer. Приблизительные курсы, обмен min/max, границы
int64 (R8, R22).
"""

from __future__ import annotations

from app.domain.currency import (
    Salary,
    estimate,
    format_salary,
    meets_minimum,
    parse_salary,
    to_rubles,
)

INT64_MAX = 2**63 - 1


# --- U-SAL-01 (R8): сравнение зарплат и курсы ---------------------------------


def test_u_sal01_cross_currency_comparison_and_estimate() -> None:
    assert meets_minimum(parse_salary("от 250 000 ₽"), 200000) is True
    assert meets_minimum(parse_salary("от 180 000 ₽"), 200000) is False
    assert meets_minimum(parse_salary("от 2 000 $"), 200000) is True  # USD ≈ 100 ₽
    assert meets_minimum(None, 200000) is True  # lenient (decisions §5.9)
    assert meets_minimum(parse_salary("до 150 000 ₽"), None) is True
    assert estimate(Salary(100, 200, "RUB")) == 100
    assert estimate(Salary(None, 200, "RUB")) == 200
    assert to_rubles(Salary(2, None, "USD")) == 200
    assert to_rubles(Salary(1, None, "GBP")) is not None  # неизвестная валюта → курс есть


# --- U-SAL-02 (R8): «от/до» и формат строки ----------------------------------


def test_u_sal02_from_to_range_formats() -> None:
    assert format_salary(parse_salary("от 150 000 ₽"), "ru") == "от 150 000 \u20bd"
    assert format_salary(parse_salary("до $2000"), "en") == "up to 2 000 $"
    range_line = format_salary(parse_salary("100 000 \u2013 200 000 ₽"), "ru")
    assert range_line == "100 000 \u2013 200 000 \u20bd"
    swapped = parse_salary("от 200 000 до 100 000 ₽")
    assert (swapped.min, swapped.max) == (100000, 200000)
    assert format_salary(None, "ru") == "Зарплата не указана"


# --- U-SAL-03 (R22): граничные значения ---------------------------------------


def test_u_sal03_boundary_amounts_normalized_safely() -> None:
    assert parse_salary("от 0 ₽") is None
    assert parse_salary("от -5 000 ₽") is None
    assert parse_salary("мусор") is None
    assert parse_salary(None) is None
    assert parse_salary(f"от {INT64_MAX + 1} ₽") is None  # переполнение int64
    assert parse_salary("от 1,5 млн ₽") == Salary(1500000, None, "RUB")
    assert parse_salary("от 150\u00a0000 ₽") == Salary(150000, None, "RUB")
    parsed = parse_salary(f"от {INT64_MAX} ₽")
    assert parsed == Salary(INT64_MAX, None, "RUB")
