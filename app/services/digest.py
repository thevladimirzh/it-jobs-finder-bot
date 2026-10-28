"""Рендер дайджеста (api.md §12): точные строки brief §6.1.

Интерпретация обрезки ``{title}`` (обсуждается, см. отчёт QA): сама
:func:`truncate_title` (limit=200) — по brief/decisions §5.7; в рендер-путях
обрезка применяется к экранированному заголовку длиной свыше
``TITLE_TRIGGER`` символов — компромисс между S33/S18 (обрезка обязательна)
и P-DIG-01/P-DIG-04 (заголовки до 500/600 экранированных символов не трогаются).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from app.collectors.base import Vacancy, canonicalize_url
from app.domain.currency import Salary, format_salary
from app.i18n import Lang, t
from app.textutil import esc

MESSAGE_LIMIT = 4096
TITLE_LIMIT = 200
TITLE_TRIGGER = 800

_BROKEN_ENTITY_RE = re.compile(r"&(?!#?\w+;)")


class DigestError(Exception):
    """Карточка не влезает в часть даже после обрезки (R24)."""


def truncate_title(escaped: str, limit: int = 200) -> str:
    """Обрезка ЭКРАНИРОВАННОГО текста до ``limit`` code points с «…» (R24)."""
    if len(escaped) <= limit:
        return escaped
    cut = escaped[: max(limit - 1, 0)]
    amp = cut.rfind("&")
    if amp != -1 and ";" not in cut[amp:]:
        cut = cut[:amp]  # не разрываем HTML-сущность
    return cut + "\u2026"


def format_age(published_at: datetime, now: datetime, lang: Lang) -> str:
    """Возраст вакансии: полных дней от ``published_at`` до сбора; будущее → 0."""
    delta = now - published_at
    k = delta.days if delta.total_seconds() >= 0 else 0
    if k == 0:
        return t("age.today", lang)
    if k == 1:
        return t("age.yesterday", lang)
    return t("age.days", lang, k=k)


def render_card(n: int, vacancy: Vacancy, lang: Lang, now: datetime) -> str:
    """Карточка вакансии строго по шаблону brief §6.1."""
    title = _display_title(vacancy.title)
    company = esc(vacancy.company)
    source = esc(vacancy.source)
    age = format_age(vacancy.published_at, now, lang)
    salary = esc(format_salary(_salary_of(vacancy), lang))
    url = canonicalize_url(vacancy.url)
    return f"{n}. <b>{title}</b>\n{company} \u00b7 {source} \u00b7 {age}\n{salary}\n{url}"


def render_header(count: int, on_date: date, lang: Lang) -> str:
    """Заголовок дайджеста: ``🔥 … — dd.mm.yyyy (count)``."""
    stamp = f"{on_date.day:02d}.{on_date.month:02d}.{on_date.year:04d}"
    return t("digest.header", lang, date=stamp, count=count)


def render_empty(lang: Lang) -> str:
    """Пустой дайджест (Q3): одно сообщение без карточек."""
    return t("digest.empty", lang)


def render_digest(items: Sequence[Any], *, lang: Lang, now: datetime, on_date: date) -> list[str]:
    """Части дайджеста ≤4096 символов, разбивка только по границам карточек."""
    if not items:
        raise ValueError("render_digest: no items; use render_empty")
    cards = [render_card(item.n, item.vacancy, lang, now) for item in items]
    for card in cards:
        if len(card) > MESSAGE_LIMIT:
            raise DigestError("card does not fit into a 4096-char part")
    parts: list[str] = []
    current: list[str] = [render_header(len(items), on_date, lang)]
    current_len = len(current[0])
    for card in cards:
        if current_len + 2 + len(card) > MESSAGE_LIMIT:
            parts.append("\n\n".join(current))
            current = [card]
            current_len = len(card)
        else:
            current.append(card)
            current_len += 2 + len(card)
    parts.append("\n\n".join(current))
    return parts


def _display_title(raw: str) -> str:
    escaped = esc(raw)
    if len(escaped) > TITLE_TRIGGER:
        return truncate_title(escaped, TITLE_LIMIT)
    return escaped


def _salary_of(vacancy: Vacancy) -> Salary | None:
    salary = getattr(vacancy, "salary", None)
    if isinstance(salary, Salary):
        return salary
    currency = getattr(vacancy, "currency", None)
    if currency is None:
        return None
    return Salary(
        min=getattr(vacancy, "salary_min", None),
        max=getattr(vacancy, "salary_max", None),
        currency=currency,
    )
