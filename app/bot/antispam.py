"""Антиспам (AC-16, decisions §5.18): 30 действий/мин → тихий мьют 10 минут.

Счётчики живут в памяти процесса (R33: сброс при рестарте — принятое
ограничение). Время берётся через ``time.monotonic()`` (договорённость
acceptance-map §6.8 — S69 управляет временем подменой).

Память ограничена (F-16, CWE-770): не более ``max_users`` записей в
``_stamps``/``_muted_until`` — при давлении просроченные метки и истёкшие
мьюты удаляются, далее вытесняются самые старые записи (метки — по порядку
обращения, мьюты — ближайшие к истечению).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

LIMIT = 30
WINDOW_SECONDS = 60.0
MUTE_SECONDS = 600.0

#: Крыша числа отслеживаемых пользователей (F-16): ~сотни байт на запись.
MAX_USERS = 4096


class Antispam:
    """Скользящее окно действий на пользователя + тихий мьют."""

    def __init__(
        self,
        limit: int = LIMIT,
        window_seconds: float = WINDOW_SECONDS,
        mute_seconds: float = MUTE_SECONDS,
        max_users: int = MAX_USERS,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._mute = mute_seconds
        self._max_users = max_users
        self._stamps: dict[object, deque[float]] = defaultdict(deque)
        self._muted_until: dict[object, float] = {}

    def allow(self, user_id: object) -> bool:
        """``True`` — действие обрабатывается; ``False`` — тихо игнорируется."""
        now = time.monotonic()
        allowed = self._check(user_id, now)
        self._prune(now)  # крыша памяти (F-16)
        return allowed

    def _check(self, user_id: object, now: float) -> bool:
        muted_until = self._muted_until.get(user_id)
        if muted_until is not None and now < muted_until:
            return False
        stamps = self._stamps[user_id]
        while stamps and stamps[0] <= now - self._window:
            stamps.popleft()
        if len(stamps) >= self._limit:
            self._muted_until[user_id] = now + self._mute
            return False
        stamps.append(now)
        return True

    def _prune(self, now: float) -> None:
        """Крыша памяти (F-16): чистка просроченного + вытеснение при переполнении.

        Вызывается после каждого действия; без переполнения — две проверки
        длины, без обхода словарей.
        """
        if len(self._stamps) <= self._max_users and len(self._muted_until) <= self._max_users:
            return
        for key in list(self._stamps):
            stamps = self._stamps[key]
            while stamps and stamps[0] <= now - self._window:
                stamps.popleft()
            if not stamps and self._muted_until.get(key, now) <= now:
                self._stamps.pop(key, None)
                self._muted_until.pop(key, None)
        while len(self._stamps) > self._max_users:
            self._stamps.pop(next(iter(self._stamps)))
        while len(self._muted_until) > self._max_users:
            doomed = min(self._muted_until, key=self._muted_until.__getitem__)
            self._muted_until.pop(doomed)
