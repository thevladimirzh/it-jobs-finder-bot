"""Engine и короткие сессии БД (api.md §9, R31)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.storage.models import Base


def build_engine(url: str, **kwargs: object) -> AsyncEngine:
    """Async-engine проекта (asyncpg)."""
    return create_async_engine(url, **kwargs)  # type: ignore[arg-type]


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий без удержания состояния между вызовами."""
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Короткая сессия: коммит при успехе, откат при ошибке, закрытие на выходе."""
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


__all__ = ["Base", "build_engine", "build_session_factory", "session_scope"]
