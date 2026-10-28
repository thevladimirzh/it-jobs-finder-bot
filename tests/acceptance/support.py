"""Общие помощники acceptance-тестов (tests/acceptance/).

Владелец: qa-engineer. Решение об архитектуре обвязки: единый импорт-стаб уже
существует — ``tests/security/support.py`` (владелец: security-engineer) — и этот
модуль НЕ дублирует его, а переиспользует: файл security-поддержки загружается по
пути (как ``_acc_sec_support``, без конфликта имён в ``sys.modules``) и все его
публичные имена ре-экспортируются отсюда.

Зачем мост: acceptance-тесты импортируют помощники как ``from support import ...``
(по соглашению suites), а pytest добавляет ``tests/acceptance`` в ``sys.path``
раньше ``tests/security``. Прозрачный ре-экспорт гарантирует, что оба suites
получают одни и те же имена (``load``, ``load_attr``, ``NotImplementedYet``,
``bot_session``, ...) в любом порядке сбора — имён, которых нет в
``tests/security/support.py``, acceptance-тесты отсюда не берут (свои двойники —
в ``tests/acceptance/fakes.py``).

Краснота: production-модули ``app.*`` импортируются ТОЛЬКО лениво через
:func:`load` / :func:`load_attr` — пока код не реализован, тест падает внятным
``NotImplementedError: «модуль ... ещё не реализован»``, а не ошибкой импорта.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SHARED_SUPPORT = Path(__file__).resolve().parents[1] / "security" / "support.py"
_SHARED_MODULE_NAME = "_acc_sec_support"


def _load_shared_support() -> object:
    """Загружает tests/security/support.py по пути под уникальным именем модуля."""
    existing = sys.modules.get(_SHARED_MODULE_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(_SHARED_MODULE_NAME, _SHARED_SUPPORT)
    if spec is None or spec.loader is None:
        raise ImportError(f"не удалось загрузить общий помощник {_SHARED_SUPPORT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_SHARED_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


# Ре-экспорт всего публичного API tests/security/support.py (прозрачный мост).
_shared = _load_shared_support()
for _name in dir(_shared):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_shared, _name)

__all__ = [name for name in globals() if not name.startswith("_")]
