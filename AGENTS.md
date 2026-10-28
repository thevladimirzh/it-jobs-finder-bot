# it-jobs-finder-bot — project profile (read by every agent in the dev-cycles loop)

## Стек

Python 3.12, aiogram 3 (>=3.29.1), SQLAlchemy 2 (async) + asyncpg, Alembic,
APScheduler >=3.11.3,<4 (`AsyncIOScheduler`/`CronTrigger`), aiohttp >=3.14.1,
pydantic-settings, httpx + beautifulsoup4,
PostgreSQL (local: 14, Docker: `postgres:16-alpine`), Docker Compose.
Тесты: pytest + pytest-asyncio (`asyncio_mode="auto"`) + hypothesis (PBT).

## Команды (запускать из корня репозитория)

| Действие | Команда |
|---|---|
| Тесты (clean test command) | `.venv/bin/python -m pytest` |
| Линтинг | `ruff check . && ruff format --check .` |
| Миграции (Docker) | выполняются при старте контейнера `bot` (`alembic upgrade head`) |
| Миграции (локально) | `.venv/bin/alembic upgrade head` (нужен `.env` с `BOT_TOKEN`, `ADMIN_ID`) |
| Запуск (Docker) | `docker compose up -d --build` |
| Запуск (локально) | `.venv/bin/python -m app.main` (после `alembic upgrade head`) |
| Окружение | `python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt` |

Важно:
- `.venv/bin/pytest` напрямую НЕ использовать — падает `ModuleNotFoundError: app`
  (нужен `python -m pytest`, он кладёт корень в `sys.path`).
- Пакет не устанавливается: `pip install -e .` не работает, запуск только из корня.
- Линтер — глобальный `/opt/homebrew/bin/ruff` (ruff намеренно не входит в requirements-dev).
  Из-за локального каталога `alembic/` ruff считает `import alembic` first-party и ставит его
  отдельным блоком после сторонних импортов — доверять `ruff check --fix`.
- Docker-демон на машине разработки нестабилен: Docker-файлы проверяются статически,
  `docker build`/`docker compose` в цикле не запускать.

## Настройки и конфигурация

- Все настройки — `app/config.py` (pydantic-settings, читает `.env`); объект `settings`
  с полями: `bot_token`, `admin_id`, `database_url`, `test_database_url`,
  `collect_interval_minutes`, `digest_size_default`, `digest_catchup_minutes`,
  `retention_days`, `cleanup_time`, `http_timeout_seconds`.
- Новая переменная окружения → дублировать в `.env.example` (со всеми уже перечисленными).
- `DATABASE_URL` по умолчанию указывает на хост `db` (Docker); тестовая БД обязана
  оканчиваться на `_test`. Списки в env — через запятую/точку с запятой или JSON-массив
  (парсинг в `app/config.py`).
- Время в БД — UTC; расписание пользователя — в его таймзоне (`zoneinfo`, честный DST).
- Курсы валют — `app/domain/currency.py`, приблизительные (только сравнение/сортировка).

## Контракты между агентами

- `app/config.py`: экспортирует `settings` (см. выше) — на него опирается `alembic/env.py`.
- `app/storage/models.py`: экспортирует `Base` (declarative base) — `alembic/env.py`
  берёт `target_metadata = Base.metadata`. Изменение моделей требует новой миграции
  в `alembic/versions/` в том же цикле.
- `app/textutil.py`: `esc`, `esc_attr` — экранирование внешнего/пользовательского текста.
- Парсеры бросают `ParseError` (битая разметка) и `SourceBlocked` (блокировка/капча);
  пустой сбор не возвращается молча — это алерт админу.

## Тесты

- Раскладка: `tests/unit` — чистая логика (без БД); `tests/acceptance` — чёрный ящик по
  сценариям; `tests/security` — security; `tests/e2e` — БД/хендлеры; `tests/features` —
  Gherkin-файлы; `tests/data` — HTML-фикстуры источников.
- `tests/conftest.py` задаёт `TEST_DATABASE_URL` до импорта `app` (по умолчанию
  `postgresql+asyncpg://jobs:jobs@localhost:5432/jobs_test`), делает
  `drop_all`/`create_all` на каждый тест и падает, если имя БД не оканчивается на `_test`.
- Схема БД в тестах — из моделей, не из миграций; e2e не трогает рабочие БД.
  `tests/e2e` пропускаются, если PostgreSQL недоступен.
- `asyncio_mode="auto"` — маркер `@pytest.mark.asyncio` не нужен.
- Тесты не ходят в сеть: коллекторы — через `FakeClient` и фикстуры `tests/data/`;
  e2e — через `tests/e2e/fixtures.py` и `BotHarness` из `tests/e2e/helpers.py`.

## TDD обязателен

Цикл: red → green → refactor → полный прогон (`.venv/bin/python -m pytest`).
Тесты никогда не правятся, чтобы «посадить» их в зелёный: чинится код; спорный тест —
обсуждается явно. PBT (hypothesis) чередуется с TDD для чистых функций и инвариантов.

## Telegram-текст

Весь текст для Telegram — HTML (`parse_mode="HTML"`); внешний и пользовательский текст
экранируется через `app.textutil.esc`/`esc_attr`; допустимые теги проверяет
`tests/html_check.py`.

## Целевая структура `app/` (production-код пишет software-engineer)

- `app/main.py` — бот и планировщик в одном процессе.
- `app/config.py` — настройки (см. выше).
- `app/collectors/__init__.py` — реестр источников (`build_collectors()`).
- `app/services/` — сбор в кэш, подбор, рассылка, планировщик: сбор каждые N минут,
  проверка расписания раз в минуту с догоняющим окном (`DIGEST_CATCHUP_MINUTES`, 3 ч),
  очистка в `CLEANUP_TIME` (04:15) вакансий старше `RETENTION_DAYS` (30).
  Планировщик использует только `MemoryJobStore` — persistent job stores запрещены
  (требование безопасности F-01: pickle-десериализация job_state = RCE).
- `app/i18n.py` — словари RU/EN (`t`, `keys`, `Lang`; контракт `docs/spec/api.md` §3).
- `app/filters/rules.py` — правила и скоринг.
- `app/domain/profile.py` — профиль/расписание (JSONB); `app/domain/currency.py` — курсы.
- `app/storage/models.py`, `app/storage/repo.py` — репозиторий коммитит сам, короткие
  сессии, без удержания сессии при HTTP-вызовах.

## Роли (dev-cycles)

Права на файлы — по skill `dev-cycles` (Roles): тесты `unit/` пишет software-engineer,
`acceptance/` и `docs/qa/` — qa-engineer, `security/` и `docs/security/` — security-engineer,
`*.feature` и `docs/spec/` — business-analyst, `docs/risk-register.md` — product-manager
и qa-engineer, `docs/plan.md` — project-manager, сборка/CI/этот файл — devops-sre.
