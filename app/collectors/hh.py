"""Коллектор hh.ru (api.md §6): HTML-разбор списка вакансий.

URL — константа (SSRF: ссылки из вакансий не скачиваются, SEC-12);
разметка локализуется по ``data-qa``-ключам карточек фикстур ``tests/data/``.
Маркеры живой разметки 28.10.2026 (``vacancy-serp__results`` /
``vacancy-serp__vacancy`` / ``serp-item__title`` / ``vacancy-serp__vacancy-employer-text``,
зарплата из ``<data value="...">``, даты в выдаче нет) — впереди старых
синтетических как fallback-цепочка (решения §9). Промо-карточки пропускаются
(D6); без даты публикации ``published_at`` = момент сбора (D5).
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
from app.domain.currency import Salary  # noqa: F401 (реэкспорт для контракта api.md)

SOURCE = "hh.ru"
SEARCH_URL = "https://hh.ru/search/vacancy?text=python&area=113"
BASE_URL = "https://hh.ru"
CONTAINER_MARKER = 'data-qa="vacancy-serp"'
CARD_MARKER = 'data-qa="vacancy-serp-item"'

LAYOUT = CardLayout(
    container_markers=('data-qa="vacancy-serp__results"', CONTAINER_MARKER),
    card_rules=(
        CardRule(tag_re=r'<article[^>]*data-qa="vacancy-serp__vacancy'),
        CardRule(literal=CARD_MARKER),
    ),
    title_rules=(
        FieldRule(
            open_re=r'<a\b[^>]*data-qa="serp-item__title"[^>]*>',
            close_re=r"</a>",
            anchor=True,
        ),
        LEGACY_TITLE_RULE,
    ),
    company_rules=(
        FieldRule(
            open_re=r'<[^>]*data-qa="vacancy-serp__vacancy-employer-text"[^>]*>',
            close_re=r"</span>",
        ),
        LEGACY_COMPANY_RULE,
    ),
    salary_text_rules=(LEGACY_SALARY_RULE,),
    salary_data_pattern=True,  # <data value="..."> живой разметки hh.ru
    description_rules=(LEGACY_DESCRIPTION_RULE,),
    href_fragment="/vacancy/",  # промо-карточки (adsrv.hh.ru/click) пропускаются (D6)
    allowed_hosts=("hh.ru",),  # F-25: hh.ru и его поддомены
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


class HhCollector:
    """Сбор вакансий с hh.ru (одна поисковая выдача)."""

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
