"""Очередь рассылки (api.md §13): троттлинг, ретраи FloodWait, изоляция ошибок."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

_RETRY_LIMIT = 3


@runtime_checkable
class Sender(Protocol):
    async def send_html(self, chat_id: int, text: str) -> None: ...


@runtime_checkable
class Throttle(Protocol):
    async def wait(self) -> None: ...


@dataclass(frozen=True)
class OutgoingMessage:
    """Готовое сообщение (HTML уже экранирован)."""

    chat_id: int
    text: str


@dataclass(frozen=True)
class DispatchReport:
    """Итог рассылки: каждое сообщение учтено ровно один раз."""

    sent: int
    failed: tuple[tuple[int, str], ...]


async def dispatch(
    messages: Sequence[OutgoingMessage], *, sender: Sender, throttle: Throttle, now: datetime
) -> DispatchReport:
    """Отправка очереди: ошибка одного получателя не прерывает очередь (R42)."""
    sent = 0
    failed: list[tuple[int, str]] = []
    for message in messages:
        delivered, reason = await _send_one(message, sender=sender, throttle=throttle)
        if delivered:
            sent += 1
        else:
            failed.append((message.chat_id, reason))
    return DispatchReport(sent=sent, failed=tuple(failed))


async def _send_one(
    message: OutgoingMessage, *, sender: Sender, throttle: Throttle
) -> tuple[bool, str]:
    for attempt in range(_RETRY_LIMIT + 1):
        await throttle.wait()
        try:
            await sender.send_html(message.chat_id, message.text)
        except Exception as exc:  # noqa: BLE001 - все ошибки фиксируются в отчёте
            retry_after = getattr(exc, "retry_after", None)
            if retry_after is not None and attempt < _RETRY_LIMIT:
                await asyncio.sleep(float(retry_after) * (attempt + 1))
                continue
            return False, str(exc) or type(exc).__name__
        else:
            return True, ""
    return False, "retries exhausted"
