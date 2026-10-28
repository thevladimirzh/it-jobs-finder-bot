"""Коллекторы источников (api.md §6): реестр и публичный контракт модуля."""

from __future__ import annotations

from app.collectors.base import (
    Collector,
    CollectorError,
    EmptyResult,
    HttpClient,
    ParseError,
    ResponseLike,
    SourceBlocked,
    SourceUnavailable,
    Vacancy,
    canonicalize_url,
    normalize_text,
)
from app.collectors.habr import HabrCareerCollector
from app.collectors.hh import HhCollector


def build_collectors() -> list[Collector]:
    """Реестр источников сбора (порядок стабилен)."""
    return [HhCollector(), HabrCareerCollector()]


__all__ = [
    "Collector",
    "CollectorError",
    "EmptyResult",
    "HttpClient",
    "ParseError",
    "ResponseLike",
    "SourceBlocked",
    "SourceUnavailable",
    "Vacancy",
    "build_collectors",
    "canonicalize_url",
    "normalize_text",
]
