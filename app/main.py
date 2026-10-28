"""Точка входа: бот, планировщик и рассылка в одном процессе (api.md §15).

Импорт этого модуля конструирует настройки (``app.config.settings``):
неполная конфигурация env падает явной ``ValidationError`` с именем
переменной (R30, S77) — частичный старт невозможен.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot

from app.bot.core import BotCore
from app.bot.handlers import build_dispatcher, run_polling
from app.bot.telegram import AdminAlertSink, TelegramSender, TelegramThrottle
from app.config import settings
from app.services.http import AiohttpClient
from app.services.scheduler import build_scheduler
from app.storage.db import build_engine, build_session_factory
from app.storage.repo import Repo


async def main() -> None:
    """Сборка bot + dispatcher + scheduler, затем polling (один процесс)."""
    engine = build_engine(settings.database_url)
    repo = Repo(build_session_factory(engine))
    bot = Bot(token=settings.bot_token)
    sender = TelegramSender(bot)
    alerts = AdminAlertSink(sender, settings.admin_id)
    throttle = TelegramThrottle()
    client = AiohttpClient(settings.http_timeout_seconds)
    bot_core = BotCore(repo=repo, client=client, alerts=alerts)
    dispatcher = build_dispatcher(bot_core)
    scheduler = build_scheduler(
        repo=repo,
        sender=sender,
        throttle=throttle,
        settings=settings,
    )
    scheduler.start()
    try:
        await run_polling(bot, dispatcher)
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
