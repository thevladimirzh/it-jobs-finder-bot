"""Соответствие «номер карточки → вакансия» последнего дайджеста (decisions §1).

Хранится в памяти процесса: пустое сообщение не сбрасывает соответствие
(decisions §5.2); при рестарте соответствие теряется — команда отвечает
точной строкой ошибки (brief §6.1).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_LAST: dict[int, dict[int, Any]] = {}


def record(user_id: int, items: Iterable[Any]) -> None:
    """Запомнить соответствие номеров последнего дайджеста с карточками."""
    mapping = {item.n: getattr(item.vacancy, "id", None) for item in items}
    if mapping:
        _LAST[user_id] = mapping


def lookup(user_id: int, n: int) -> Any | None:
    """vacancy_id карточки ``n`` последнего дайджеста (нет → ``None``)."""
    return _LAST.get(user_id, {}).get(n)


def size(user_id: int) -> int:
    """Число карточек в последнем дайджесте пользователя."""
    return len(_LAST.get(user_id, {}))
