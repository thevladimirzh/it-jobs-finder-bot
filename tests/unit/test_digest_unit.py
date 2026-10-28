"""Юнит-тесты дайджеста и возраста (U-DIG-03/05/06, U-AGE-01).

Владелец: software-engineer. Рендер по шаблонам brief §6.1 (R4, R11, R23, R24).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.currency import Salary
from app.services.digest import (
    DigestError,
    format_age,
    render_card,
    render_digest,
    render_empty,
    truncate_title,
)

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
ON_DATE = date(2026, 3, 14)


class _Vacancy:
    def __init__(self, **values: object) -> None:
        self.title = "Python Developer"
        self.company = "Ромашка"
        self.salary: Salary | None = Salary(150000, None, "RUB")
        self.url = "https://hh.ru/vacancy/1"
        self.source = "hh.ru"
        self.published_at = NOW
        self.description = ""
        self.__dict__.update(values)


class _Item:
    def __init__(self, n: int, vacancy: _Vacancy) -> None:
        self.n = n
        self.vacancy = vacancy


# --- U-DIG-05 (R24): обрезка {title} безопасна --------------------------------


def test_u_dig05_truncate_title_keeps_entities_and_marker() -> None:
    escaped = "A&amp;B" * 100  # 700 символов
    cut = truncate_title(escaped, 200)
    assert len(cut) <= 200
    assert cut.endswith("\u2026")
    assert "&amp;" in cut
    assert cut.count("&") == cut.count("amp;")
    short = "короткий &amp; заголовок"
    assert truncate_title(short, 200) == short


# --- U-DIG-03 (R4): разбивка ≤4096 по границам карточек -----------------------


def test_u_dig03_parts_bounded_and_split_on_card_boundaries() -> None:
    items = [
        _Item(n, _Vacancy(title=f"Vacancy {n}", company="C" * 900, salary=None))
        for n in range(1, 6)
    ]
    parts = render_digest(items, lang="ru", now=NOW, on_date=ON_DATE)
    assert len(parts) >= 2
    assert all(len(part) <= 4096 for part in parts)
    joined = "\n\n".join(part.strip("\n") for part in parts)
    assert joined.startswith("\U0001f525 Подборка вакансий \u2014 14.03.2026 (5)")
    for n in range(1, 6):
        assert f"{n}. <b>Vacancy {n}</b>" in joined
    with pytest.raises(DigestError):
        render_digest([_Item(1, _Vacancy(company="C" * 4200))], lang="ru", now=NOW, on_date=ON_DATE)


# --- U-DIG-06 (R11): пустой дайджест ------------------------------------------


def test_u_dig06_empty_digest_message() -> None:
    assert render_empty("ru") == "\U0001f525 Новых вакансий нет"
    assert render_empty("en") == "\U0001f525 No new vacancies"
    with pytest.raises(ValueError):
        render_digest([], lang="ru", now=NOW, on_date=ON_DATE)


# --- U-AGE-01 (R23): границы возраста 0/1/2+ ---------------------------------


def test_u_age01_age_boundaries_and_future() -> None:
    assert format_age(NOW, NOW, "ru") == "сегодня"
    assert format_age(NOW - timedelta(hours=3), NOW, "ru") == "сегодня"
    assert format_age(NOW - timedelta(days=1), NOW, "ru") == "вчера"
    assert format_age(NOW - timedelta(days=2), NOW, "ru") == "2 дн."
    assert format_age(NOW + timedelta(days=1), NOW, "ru") == "сегодня"  # будущее → 0
    assert format_age(NOW - timedelta(days=1), NOW, "en") == "yesterday"
    assert format_age(NOW - timedelta(days=5), NOW, "en") == "5 days"
    assert format_age(NOW + timedelta(days=9), NOW, "en") == "today"
    assert "\u2013" not in render_card(1, _Vacancy(), "ru", NOW)  # «-N дн.» невозможно
