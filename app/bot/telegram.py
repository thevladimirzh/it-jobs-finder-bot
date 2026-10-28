"""Адаптеры Telegram API (api.md §13): отправитель, троттлинг, алерты админу."""

from __future__ import annotations

import asyncio
from typing import Any


class TelegramSender:
    """``Sender`` поверх aiogram ``Bot``: HTML уже экранирован."""

    def __init__(self, bot: Any) -> None:
        self._bot = bot

    async def send_html(self, chat_id: int, text: str) -> None:
        await self._bot.send_message(chat_id, text, parse_mode="HTML")


class TelegramThrottle:
    """Простая пауза под лимиты Telegram API (≈30 msg/s)."""

    def __init__(self, delay_seconds: float = 0.05) -> None:
        self._delay = delay_seconds

    async def wait(self) -> None:
        await asyncio.sleep(self._delay)


class AdminAlertSink:
    """Алерты админу («⚠️ Сбор {source}: {reason}», всегда RU)."""

    def __init__(self, sender: Any, admin_id: int) -> None:
        self._sender = sender
        self._admin_id = admin_id

    async def send_admin(self, text: str) -> None:
        await self._sender.send_html(self._admin_id, text)
