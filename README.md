# it-jobs-finder-bot

Telegram-бот регулярной подборки IT-вакансий: парсит hh.ru и Habr Career, копит вакансии
в PostgreSQL и присылает дайджест по расписанию, выбранному пользователем (время + таймзона),
по подписанным ролям-пресетам с личными правками.

## Стек

Python 3.12, aiogram 3, SQLAlchemy 2 (async) + asyncpg, Alembic, APScheduler,
pydantic-settings, httpx + beautifulsoup4, PostgreSQL, Docker Compose.
Тесты: pytest + pytest-asyncio + hypothesis. Линтинг: ruff.

## Быстрый старт

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # заполнить BOT_TOKEN и ADMIN_ID
```

Запуск через Docker Compose (рекомендуется, миграции выполняются при старте контейнера `bot`):

```bash
docker compose up -d --build
```

Или локально (нужен PostgreSQL с БД из `DATABASE_URL`):

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m app.main
```

## Тесты и линтинг

```bash
.venv/bin/python -m pytest            # весь тестовый набор (запуск из корня!)
ruff check . && ruff format --check . # линтинг и проверка формата
```

Важно: тесты запускаются именно как `.venv/bin/python -m pytest` из корня репозитория
(`.venv/bin/pytest` падает с `ModuleNotFoundError: app`; пакет не устанавливается —
`pip install -e .` не поддерживается). `tests/e2e` выполняются против локального
PostgreSQL (`jobs_test`) и пропускаются, если БД недоступна. Тесты не ходят в сеть.

## Структура

- `app/` — код бота (сбор, фильтры/скоринг, дайджест, рассылка, планировщик, хранилище);
- `alembic/` — миграции (`env.py` берёт настройки из `app.config`);
- `tests/` — `unit/`, `acceptance/`, `security/`, `e2e/`, `features/` (Gherkin), `data/`;
- `docs/` — план, реестр рисков, решения, QA-вердикт, security-отчёт;
- `AGENTS.md` — профиль проекта и соглашения для всех агентов.

Детали конфигурации и соглашений — в [AGENTS.md](AGENTS.md).
