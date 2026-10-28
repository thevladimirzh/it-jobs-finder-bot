"""Сбор вакансий (api.md §10): graceful degradation и алерты админу.

Алерт — точный шаблон brief §6.1 «⚠️ Сбор {source}: {reason}» (всегда RU),
не чаще одного на источник в час; подавленные события учитываются счётчиком
(decisions §5.14). Исключения не бросаются: сбой источника — отчёт + алерт.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol, runtime_checkable

from app.collectors import build_collectors
from app.collectors.base import (
    EmptyResult,
    HttpClient,
    ParseError,
    SourceBlocked,
    SourceUnavailable,
)
from app.i18n import t

REASONS: Mapping[str, str] = {
    "blocked": "блокировка/капча",
    "parse_error": "ошибка разбора разметки",
    "empty": "пустой разбор",
    "unavailable": "источник недоступен",
}


@runtime_checkable
class AlertSink(Protocol):
    async def send_admin(self, text: str) -> None: ...


@dataclass(frozen=True)
class CollectReport:
    """Итог сбора одного источника."""

    source: str
    status: Literal["ok", "blocked", "parse_error", "empty", "unavailable"]
    added: int
    alert: str | None


async def run_collect(
    *, client: HttpClient, repo: Any, alerts: AlertSink, now: datetime
) -> list[CollectReport]:
    """Сбор всех источников в кэш с дедупликацией; исключений не бросает."""
    reports: list[CollectReport] = []
    for collector in build_collectors():
        status: Literal["ok", "blocked", "parse_error", "empty", "unavailable"]
        added = 0
        try:
            vacancies = await collector.collect(client, now=now)
            added = await repo.add_vacancies(vacancies)
        except SourceBlocked:
            status = "blocked"
        except ParseError:
            status = "parse_error"
        except EmptyResult:
            status = "empty"
        except SourceUnavailable:
            status = "unavailable"
        except Exception:  # noqa: BLE001 - любая иная ошибка = источник недоступен
            status = "unavailable"
        else:
            reports.append(
                CollectReport(source=collector.name, status="ok", added=added, alert=None)
            )
            await repo.record_parse_run(
                source=collector.name, status="ok", added=added, alert_sent=False
            )
            continue
        alert_text = await _maybe_alert(
            repo=repo,
            alerts=alerts,
            source=collector.name,
            status=status,
            reason=REASONS[status],
            now=now,
        )
        reports.append(
            CollectReport(source=collector.name, status=status, added=0, alert=alert_text)
        )
    return reports


async def _maybe_alert(
    *, repo: Any, alerts: AlertSink, source: str, status: str, reason: str, now: datetime
) -> str | None:
    """Дедуп алертов: не чаще одного в час на источник (R16)."""
    window = await repo.alert_window_count(source=source, since=now - timedelta(hours=1))
    alert_text = t("alert.template", "ru", source=source, reason=reason)
    if window == 0:
        await alerts.send_admin(alert_text)
        await repo.record_parse_run(source=source, status=status, added=0, alert_sent=True)
        return alert_text
    await repo.bump_suppressed_alerts(source)
    await repo.record_parse_run(source=source, status=status, added=0, alert_sent=False)
    return None
