"""Корневая обвязка тестов: тестовая БД до импорта ``app`` и guard R29 (S72).

Обязательства (AGENTS.md, docs/qa/acceptance-map.md §6.11):
- ``TEST_DATABASE_URL`` выставляется до любого импорта ``app``;
- имя тестовой БД обязано оканчиваться на ``_test`` — иначе прогон падает
  ДО выполнения любых тестов (защита рабочей БД, R29);
- e2e-тесты пропускаются, если PostgreSQL недоступен (AC-1).
"""

from __future__ import annotations

import os

_DEFAULT_TEST_DB = "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs_test"

os.environ.setdefault("TEST_DATABASE_URL", _DEFAULT_TEST_DB)
os.environ.setdefault("BOT_TOKEN", "1000000000:" + "T" * 35)
os.environ.setdefault("ADMIN_ID", "1000")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs")

# Guard R29: импорт app.config выполняется здесь же — до импорта app в тестах.
from app.config import validate_test_database_url  # noqa: E402

validate_test_database_url(os.environ["TEST_DATABASE_URL"])
