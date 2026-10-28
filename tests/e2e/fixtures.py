"""Фикстуры e2e: доступность PostgreSQL (AC-1: e2e пропускаются без БД)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests.e2e.helpers import BotHarness


def postgres_available() -> bool:
    """Проверка доступности PostgreSQL для e2e (без сети — только localhost БД)."""
    import asyncio

    from sqlalchemy import text

    from app.config import settings as app_settings
    from app.storage.db import build_engine

    async def probe() -> bool:
        engine = build_engine(app_settings.test_database_url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - любая ошибка соединения = БД недоступна
            return False
        finally:
            await engine.dispose()
        return True

    return asyncio.run(probe())


@pytest.fixture
async def harness() -> AsyncIterator[BotHarness]:
    """Один запуск бота на тестовой БД."""
    if not postgres_available():
        pytest.skip("PostgreSQL недоступен — e2e пропущены")
    async with BotHarness() as bot:
        yield bot
