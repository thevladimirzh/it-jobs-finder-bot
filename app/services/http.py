"""HTTP-клиент сбора (api.md §6): aiohttp с таймаутом настроек (R41).

Лимит тела ответа (F-24, report §10): тело читается ограниченно (``read_limited``)
— гигантский ответ источника не буферизуется целиком (память) и не доходит до
разбора (усилитель F-20 закрыт). Решение: при превышении ``MAX_BODY_BYTES`` —
отказ ``SourceUnavailable``, не обрезка: обрезанный HTML дал бы ложный
``ParseError`` и неверную классификацию алерта.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

import aiohttp

from app.collectors.base import SourceUnavailable

MAX_BODY_BYTES = 5 * 1024 * 1024  # 5 МиБ: больше — отказ (F-24)
_CHUNK_BYTES = 64 * 1024


class _ContentLike(Protocol):
    async def read(self, n: int = -1) -> bytes: ...


async def read_limited(content: _ContentLike, *, limit: int = MAX_BODY_BYTES) -> bytes:
    """Читает тело потоком, не больше ``limit`` байт (F-24).

    Превышение → ``SourceUnavailable`` (отказ, не обрезка); память ограничена
    лимитом даже при гигантском ответе. Исключений транспорта не гасит.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await content.read(_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise SourceUnavailable("response body too large")
        chunks.append(chunk)


@dataclass(frozen=True)
class Response:
    """Ответ источника в форме ResponseLike (api.md §6)."""

    status_code: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)


class AiohttpClient:
    """Тонкий адаптер ``aiohttp`` под протокол ``HttpClient``."""

    def __init__(self, timeout_seconds: float) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> Response:
        async with (
            aiohttp.ClientSession(timeout=self._timeout) as session,
            session.get(url, headers=dict(headers or {})) as response,
        ):
            raw = await read_limited(response.content)
            return Response(
                status_code=response.status,
                text=raw.decode(response.charset or "utf-8", errors="replace"),
                headers=dict(response.headers),
            )


@asynccontextmanager
async def build_client(timeout_seconds: float) -> AsyncIterator[Any]:
    yield AiohttpClient(timeout_seconds)
