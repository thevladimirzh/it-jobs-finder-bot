"""E2E-обвязка: BotHarness и фикстуры тестовой БД (api.md §15, threat-model §5.8).

BotHarness — минимальный тестовый вход в бота: ``send``/``sent`` (§5.8) +
договорённые расширения ``seed_vacancies``/``deliver_digest``/``set_client``
(acceptance-map §6.1). Только тестовая БД (суффикс ``_test``) и тестовый
HTTP-клиент (фикстуры ``tests/data``, без сети — R41).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from app.bot.core import BotCore
from app.bot.dialog import CallbackAnswer
from app.config import settings as app_settings
from app.config import validate_test_database_url
from app.storage.db import build_engine, build_session_factory
from app.storage.models import Base
from app.storage.repo import Repo

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "tests" / "data"

SEED_PRESETS: tuple[tuple[str, str, str], ...] = (
    ("python-backend", "Python Backend", "Python, Django, FastAPI, backend-сервисы"),
    ("frontend", "Frontend", "JavaScript, TypeScript, React, Vue, вёрстка"),
    ("devops-sre", "DevOps/SRE", "DevOps, SRE, Kubernetes, Docker, инфраструктура"),
    ("data-ml", "Data/ML", "Data Science, ML, аналитика, пайплайны данных"),
    ("qa", "QA", "Тестирование, автотесты, QA-инженер"),
    ("mobile", "Mobile", "Android, iOS, кроссплатформенная разработка"),
    ("backend-other", "Другие backend-языки", "Go, Java, Kotlin, Ruby, PHP, Scala, C++"),
)

PERMISSIVE_FILTER: dict[str, Any] = {
    "role": "",
    "must": [],
    "nice": [],
    "grades": [],
    "min_salary": None,
    "work_format": None,
    "location": None,
    "stop_words": [],
    "employment": None,
}


class FixtureResponse:
    """Ответ тестового HTTP-клиента (api.md §6: status_code, text, headers)."""

    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.headers: Mapping[str, str] = {}


class FixtureClient:
    """HTTP-клиент без сети: отдаёт HTML-фикстуры ``tests/data`` по хостам."""

    def __init__(
        self,
        *,
        hh: str | Exception | None = None,
        habr: str | Exception | None = None,
    ) -> None:
        self._routes: dict[str, Any] = {}
        if hh is not None:
            self._routes["hh.ru"] = hh
        if habr is not None:
            self._routes["habr"] = habr
        self.calls: list[str] = []

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> FixtureResponse:
        self.calls.append(url)
        for host, payload in self._routes.items():
            if host in url:
                if isinstance(payload, Exception):
                    raise payload
                return FixtureResponse(text=payload)
        return FixtureResponse(text=_fixture("hh_list.html"))


class AlertLog:
    """Приёмник алертов админу для BotHarness."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def send_admin(self, text: str) -> None:
        self.texts.append(text)


def _fixture(name: str) -> str:
    return (DATA_DIR / name).read_text(encoding="utf-8")


class BotHarness:
    """Тестовый запуск бота: реальный ``Repo`` на тестовой БД, без сети.

    Контракт I-2 (threat-model §5.8, dialog.py): ``press(callback_data, *,
    user_id)`` — нажатие кнопки (тексты ответов без toast); ``tap(data, user=None)``
    — callback_query от ``user`` (по умолчанию — пользователь последнего
    ``send``/``tap``); ``answers()`` — подтверждения последнего ``tap`` (ровно
    один на callback); ``keyboard()`` — кнопки последнего сообщения;
    ``events()`` — журнал ``("answer", CallbackAnswer)`` / ``("send"|"edit", text)``
    в реальном порядке (answer — первым действием обработчика, S79).
    """

    def __init__(self) -> None:
        self._engine: Any = None
        self.repo: Any = None
        self.bot: Any = None
        self.alerts = AlertLog()
        self.client: Any = None
        self._sent: list[str] = []
        self._answers: list[Any] = []
        self._events: list[tuple[str, Any]] = []
        self._keyboard: list[tuple[str, str]] = []
        self._last_user: Any = None

    async def __aenter__(self) -> BotHarness:
        url = validate_test_database_url(app_settings.test_database_url)
        self._engine = build_engine(url)
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.repo = Repo(build_session_factory(self._engine))
        self.client = FixtureClient(hh=_fixture("hh_list.html"), habr=_fixture("habr_list.html"))
        self.bot = BotCore(repo=self.repo, client=self.client, alerts=self.alerts)
        for slug, name, _description in SEED_PRESETS:
            await self.repo.upsert_preset(slug, name=name, filter_json=dict(PERMISSIVE_FILTER))
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        if self._engine is not None:
            await self._engine.dispose()
        return False

    def _record(self, replies: Sequence[Any]) -> list[str]:
        texts: list[str] = []
        for reply in replies:
            text = reply.text if hasattr(reply, "text") else str(reply)
            kind = "edit" if getattr(reply, "edit", False) else "send"
            self._events.append((kind, text))
            self._keyboard = [button for row in getattr(reply, "keyboard", ()) for button in row]
            texts.append(text)
        return texts

    async def send(self, text: str, *, user_id: Any) -> list[str]:
        """Сообщение боту; ответы доступны через :meth:`sent`."""
        self._last_user = user_id
        self._answers = []
        replies = await self.bot.handle(text, user_id)
        self._sent = self._record(replies)
        return self._sent

    def sent(self) -> list[str]:
        """Ответы на последний ``send``/``tap`` (объекты со ``.text`` либо строки)."""
        return list(self._sent)

    async def tap(self, data: str, user: Any = None) -> list[str]:
        """Callback_query с ``callback_data=data`` от ``user`` (threat-model §5.8)."""
        user_id = self._last_user if user is None else user
        self._last_user = user_id
        self._answers = []

        async def answer(text: str, show_alert: bool) -> None:
            payload = CallbackAnswer(text=text, show_alert=show_alert)
            self._answers.append(payload)
            self._events.append(("answer", payload))

        replies = await self.bot.handle_callback(data, user_id, answer=answer)
        self._sent = self._record(replies)
        return self._sent

    async def press(self, callback_data: str, *, user_id: Any) -> list[str]:
        """Нажатие инлайн-кнопки диалога от ``user_id`` (контракт dialog.py)."""
        return await self.tap(callback_data, user=user_id)

    def answers(self) -> list[Any]:
        """Подтверждения ``answer_callback_query`` последнего ``tap`` (ровно один)."""
        return list(self._answers)

    def keyboard(self) -> list[tuple[str, str]]:
        """Кнопки (метка, callback_data) последнего сообщения (пусто, если нет)."""
        return list(self._keyboard)

    def events(self) -> list[tuple[str, Any]]:
        """Журнал событий сессии: answer / send / edit в реальном порядке."""
        return list(self._events)

    async def seed_vacancies(self, vacancies: list[Any]) -> int:
        """Положить вакансии в кэш бота (договорённость acceptance-map §6.1)."""
        return await self.bot.seed_vacancies(vacancies)

    async def deliver_digest(self, *, user_id: Any) -> list[str]:
        """Доставить очередной дайджест сейчас (служебный триггер слота)."""
        replies = await self.bot.deliver_digest(user_id)
        self._record(replies)
        return replies

    def set_client(self, client: Any) -> None:
        """Подмена HTTP-клиента (S54): только тестовый клиент, без сети."""
        self.client = client
        self.bot.set_client(client)


@asynccontextmanager
async def open_harness() -> AsyncIterator[BotHarness]:
    async with BotHarness() as harness:
        yield harness
