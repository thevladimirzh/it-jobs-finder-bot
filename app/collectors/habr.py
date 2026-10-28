"""Коллектор Habr Career (api.md §6): HTML-разбор списка вакансий.

URL — константа (SSRF: ссылки из вакансий не скачиваются, SEC-12);
ссылки карточек относительные — разрешаются относительно ``BASE_URL``.
Маркеры живой разметки 28.10.2026 (``data-vacancy-list`` / ``div.vacancy-card`` /
``a.vacancy-card__title-link`` / ``div.vacancy-card__company a`` /
``div.vacancy-card__salary .basic-salary`` / ``time.basic-date[datetime]``) —
впереди старых синтетических как fallback-цепочка (решения §9).
"""

from __future__ import annotations

from datetime import datetime

from app.collectors.base import (
    LEGACY_COMPANY_RULE,
    LEGACY_DESCRIPTION_RULE,
    LEGACY_SALARY_RULE,
    LEGACY_TITLE_RULE,
    CardLayout,
    CardRule,
    FieldRule,
    HttpClient,
    Vacancy,
    fetch_page,
    parse_listing,
)

SOURCE = "Habr Career"
SEARCH_URL = "https://career.habr.com/vacancies"
BASE_URL = "https://career.habr.com"
CONTAINER_MARKER = 'class="vacancies-list"'
CARD_MARKER = 'class="vacancy-card"'

LAYOUT = CardLayout(
    container_markers=("data-vacancy-list", CONTAINER_MARKER),
    card_rules=(
        CardRule(tag_re=r'<div class="vacancy-card[ "]'),
        CardRule(literal=CARD_MARKER),
    ),
    title_rules=(
        FieldRule(
            open_re=r'<a\b[^>]*class="[^"]*vacancy-card__title-link[^"]*"[^>]*>',
            close_re=r"</a>",
            anchor=True,
        ),
        LEGACY_TITLE_RULE,
    ),
    company_rules=(
        FieldRule(
            open_re=r'<div[^>]*class="[^"]*vacancy-card__company(?:[ "])[^>]*>',
            inner_re=r"<a\b[^>]*>",
            close_re=r"</a>",
        ),
        LEGACY_COMPANY_RULE,
    ),
    salary_text_rules=(
        FieldRule(
            open_re=r'<div[^>]*class="[^"]*basic-salary[^"]*"[^>]*>',
            close_re=r"</div>",
        ),
        LEGACY_SALARY_RULE,
    ),
    description_rules=(LEGACY_DESCRIPTION_RULE,),
    href_fragment="/vacancies/",  # ссылки карточек ведут в раздел вакансий
    allowed_hosts=("career.habr.com", "habr.com"),  # F-25
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


class HabrCareerCollector:
    """Сбор вакансий с Habr Career (одна выдача вакансий)."""

    name = SOURCE

    async def collect(self, client: HttpClient, *, now: datetime | None = None) -> list[Vacancy]:
        body = await fetch_page(client, SEARCH_URL, headers=_HEADERS)
        return await parse_listing(
            body,
            source=SOURCE,
            base_url=BASE_URL,
            layout=LAYOUT,
            now=now,
        )
