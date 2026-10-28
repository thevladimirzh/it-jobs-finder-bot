"""Фильтры и скоринг вакансий (api.md §7): пресеты, must/nice, правки пользователя.

Семантика — decisions §5.11–§5.12: стоп-слова — подстрока без учёта регистра в
заголовке и компании; все ``must`` — в нормализованном тексте (заголовок +
описание); ``nice`` — баллы скоринга; зарплата — ``currency.meets_minimum``
(lenient для вакансий без зарплаты). Пустые поля фильтра — «всё проходит».
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.collectors.base import Vacancy, normalize_text
from app.domain.currency import meets_minimum


@dataclass(frozen=True)
class PresetFilter:
    """JSONB-фильтр пресета ролей."""

    role: str = ""
    must: list[str] = field(default_factory=list)
    nice: list[str] = field(default_factory=list)
    grades: list[str] = field(default_factory=list)
    min_salary: int | None = None
    work_format: str | None = None
    location: str | None = None
    stop_words: list[str] = field(default_factory=list)
    employment: str | None = None


@dataclass(frozen=True)
class UserTweaks:
    """Глобальные правки пользователя поверх всех пресетов (brief §7.4)."""

    min_salary_rub: int | None = None
    work_format: str | None = None
    stop_words: list[str] = field(default_factory=list)


def load_filter(data: Mapping[str, Any]) -> PresetFilter:
    """PresetFilter из JSONB; битые данные — только ``ValueError`` (SEC-13)."""
    if not isinstance(data, Mapping):
        raise ValueError("filter must be a mapping")
    try:
        return PresetFilter(
            role=_opt_str(data.get("role"), "role") or "",
            must=_str_list(data.get("must"), "must"),
            nice=_str_list(data.get("nice"), "nice"),
            grades=_str_list(data.get("grades"), "grades"),
            min_salary=_opt_int(data.get("min_salary"), "min_salary"),
            work_format=_opt_str(data.get("work_format"), "work_format"),
            location=_opt_str(data.get("location"), "location"),
            stop_words=_str_list(data.get("stop_words"), "stop_words"),
            employment=_opt_str(data.get("employment"), "employment"),
        )
    except ValueError:
        raise
    except (TypeError, AttributeError, OverflowError) as exc:
        raise ValueError(f"broken filter data: {exc}") from exc


def matches(vacancy: Vacancy, preset: PresetFilter, tweaks: UserTweaks) -> bool:
    """Проходит ли вакансия фильтр пресета с учётом правок пользователя."""
    haystack_title = f"{_title(vacancy)} {_company(vacancy)}".lower()
    for word in (*preset.stop_words, *tweaks.stop_words):
        if word and word.lower() in haystack_title:
            return False
    text = normalize_text(f"{_title(vacancy)} {_description(vacancy)}")
    if any(phrase and normalize_text(phrase) not in text for phrase in preset.must):
        return False
    if preset.grades and not any(normalize_text(grade) in text for grade in preset.grades if grade):
        return False
    if not meets_minimum(_salary(vacancy), preset.min_salary):
        return False
    if not meets_minimum(_salary(vacancy), tweaks.min_salary_rub):
        return False
    wide = normalize_text(f"{_title(vacancy)} {_company(vacancy)} {_description(vacancy)}")
    for value in (preset.work_format, tweaks.work_format, preset.location, preset.employment):
        if value and normalize_text(value) not in wide:
            return False
    return True


def score(vacancy: Vacancy, preset: PresetFilter, tweaks: UserTweaks) -> int:
    """Релевантность: база 5 + 5 баллов за каждую nice-фразу (brief §7.5)."""
    text = normalize_text(f"{_title(vacancy)} {_description(vacancy)}")
    hits = sum(1 for phrase in preset.nice if phrase and normalize_text(phrase) in text)
    return 5 + 5 * hits


def _title(vacancy: Any) -> str:
    return str(getattr(vacancy, "title", "") or "")


def _company(vacancy: Any) -> str:
    return str(getattr(vacancy, "company", "") or "")


def _description(vacancy: Any) -> str:
    return str(getattr(vacancy, "description", "") or "")


def _salary(vacancy: Any):
    salary = getattr(vacancy, "salary", None)
    if salary is not None:
        return salary
    currency = getattr(vacancy, "currency", None)
    if currency is None:
        return None
    from app.domain.currency import Salary

    return Salary(
        min=getattr(vacancy, "salary_min", None),
        max=getattr(vacancy, "salary_max", None),
        currency=currency,
    )


def _str_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"filter.{name} must be a list of strings")
    return list(value)


def _opt_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"filter.{name} must be a string or None")
    return value


def _opt_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"filter.{name} must be an integer or None")
    return value
