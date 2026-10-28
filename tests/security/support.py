"""Общие помощники security-тестов (tests/security/).

Владелец: security-engineer. Ключевое правило: production-код импортируется ЛЕНИВО
(см. :func:`load`), поэтому suite собирается до реализации ``app/`` и падает с
понятной причиной «модуль ещё не реализован», а не с ошибкой импорта на сборке.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import sys
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class NotImplementedYet(AssertionError):
    """Production-модуль ещё не реализован — тест обязан быть красным по этой причине."""


def load(module: str) -> Any:
    """Ленивый импорт production-модуля (api.md). Не реализован → красный тест."""
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        raise NotImplementedYet(f"модуль {module} ещё не реализован: {exc}") from exc


def load_attr(module: str, name: str) -> Any:
    """Ленивый импорт атрибута production-модуля по контракту api.md."""
    mod = load(module)
    try:
        return getattr(mod, name)
    except AttributeError as exc:
        raise NotImplementedYet(f"атрибут {module}.{name} ещё не реализован: {exc}") from exc


# ---------------------------------------------------------------------------
# Детерминированное окружение: реальные секреты разработчика в тесты не попадают
# ---------------------------------------------------------------------------

ENV_DEFAULTS: dict[str, str] = {
    "BOT_TOKEN": "1000000000:" + "T" * 35,
    "ADMIN_ID": "1000",
    "DATABASE_URL": "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs",
    "TEST_DATABASE_URL": "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs_test",
}


def ensure_test_env() -> None:
    """Подставляет тестовые значения env, если их нет (не перезаписывает чужие)."""
    for key, value in ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


def app_settings() -> Any:
    """Синглтон настроек (api.md §1) в тестовом окружении."""
    ensure_test_env()
    return load_attr("app.config", "settings")


# ---------------------------------------------------------------------------
# Недоверенные payload'ы (abuse-кейсы)
# ---------------------------------------------------------------------------

HTML_PAYLOADS: tuple[str, ...] = (
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '</b><a href="http://evil.example/">click</a>',
    "<b>bold</b>",
    '" onmouseover="alert(1)',
    "'><svg/onload=alert(1)>",
    "&amp; &lt; &nbsp; &#60;script&#62;",
    '<iframe src="http://evil.example/">',
    "\x00<script>alert(1)</script>",
    "<SCRIPT>Alert(1)</SCRIPT>",
    "‮evil<",
    "\u202e\u202d<javascript:alert(1)>",
    "a" * 100_000 + "<script>",
)

SQL_PAYLOADS: tuple[str, ...] = (
    "'; DROP TABLE vacancies; --",
    '" OR 1=1 --',
    "1; DELETE FROM users WHERE 1=1 --",
    "%(admin)s",
    "${7*7}",
    "' UNION SELECT bot_token FROM settings --",
    "\\'; DROP TABLE feedback; --",
    "admin'--",
    "100; UPDATE presets SET is_active = false --",
)

# ---------------------------------------------------------------------------
# Независимый oracle допустимых тегов Telegram HTML (defense in depth:
# не полагаемся на общий с реализацией tests/html_check.py)
# ---------------------------------------------------------------------------

ALLOWED_TAGS = frozenset(
    {"b", "strong", "i", "em", "u", "s", "code", "pre", "a", "tg-spoiler", "blockquote"}
)
ALLOWED_ATTRS = {"a": frozenset({"href"})}
ALLOWED_HREF_SCHEMES = ("http://", "https://", "mailto:", "tg://")


class _TagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, {k: (v or "") for k, v in attrs}))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def tag_violations(html: str) -> list[str]:
    """Список нарушений allowlist-тегов в готовом Telegram HTML (пустой — всё ок)."""
    parser = _TagCollector()
    parser.feed(html)
    parser.close()
    problems: list[str] = []
    for tag, attrs in parser.tags:
        if tag not in ALLOWED_TAGS:
            problems.append(f"запрещённый тег <{tag}>")
            continue
        allowed_attrs = ALLOWED_ATTRS.get(tag, frozenset())
        for name, value in attrs.items():
            if name not in allowed_attrs:
                problems.append(f"запрещённый атрибут {name} у <{tag}>")
            elif name == "href" and not value.startswith(ALLOWED_HREF_SCHEMES):
                problems.append(f"небезопасная схема href в <{tag}>: {value[:40]!r}")
    return problems


def found_tags(html: str) -> list[str]:
    """Имена всех открывающих тегов (и самозакрывающихся), которые видит парсер."""
    parser = _TagCollector()
    parser.feed(html)
    parser.close()
    return [tag for tag, _ in parser.tags]


def assert_no_raw_markup(html: str, where: str) -> None:
    """В готовом HTML не должно быть сырых `<`/`>` вне разметки допустимых тегов."""
    problems = tag_violations(html)
    assert not problems, f"{where}: нарушения allowlist-тегов: {problems}; html={html!r}"


# ---------------------------------------------------------------------------
# Подмена async_sessionmaker: записывает все SQL-вызовы (SEC-06, P-SEC-04)
# ---------------------------------------------------------------------------


class _FakeResult:
    """Универсальный результат запроса: ничего не падает, всё «пустое»."""

    def __await__(self) -> Any:
        async def _done() -> _FakeResult:
            return self

        return _done().__await__()

    async def __aenter__(self) -> _FakeResult:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return []

    def first(self) -> None:
        return None

    def one(self) -> None:
        return None

    def one_or_none(self) -> None:
        return None

    def scalar(self) -> None:
        return None

    def scalar_one_or_none(self) -> None:
        return None

    def __iter__(self) -> Iterable[Any]:
        return iter(())

    @property
    def rowcount(self) -> int:
        return 0


class RecordingSession(_FakeResult):
    """Сессия-двойник AsyncSession: пишет вызовы, отдаёт пустые результаты."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def __aenter__(self) -> RecordingSession:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def close(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def flush(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        self.calls.append(("add", (obj,), {}))

    def add_all(self, objs: Sequence[Any]) -> None:
        self.calls.append(("add_all", tuple(objs), {}))

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)

        def _recorded(*args: Any, **kwargs: Any) -> _FakeResult:
            self.calls.append((name, args, kwargs))
            return _FakeResult()

        return _recorded


class RecordingSessionFactory:
    """Двойник ``async_sessionmaker[AsyncSession]`` (api.md §9)."""

    def __init__(self) -> None:
        self.sessions: list[RecordingSession] = []

    def __call__(self, *args: Any, **kwargs: Any) -> RecordingSession:
        session = RecordingSession()
        self.sessions.append(session)
        return session

    def statements(self) -> list[str]:
        """Тексты SQL-объектов из args И kwargs (``statement=...`` — не слепая зона).

        История (F-13): Repo передаёт выражения именованным ``statement=``, а
        прежний сканер смотрел только позиционные аргументы — детектор SEC-06
        не видел ни одного запроса. Теперь сканируются оба канала.
        """
        texts: list[str] = []
        for session in self.sessions:
            for name, args, kwargs in session.calls:
                if name in {"add", "add_all", "commit", "close", "rollback", "flush"}:
                    continue
                for value in (*args, *kwargs.values()):
                    if _looks_like_statement(value):
                        texts.append(statement_text(value))
        return texts


def _looks_like_statement(value: Any) -> bool:
    """Строка или SQLAlchemy-выражение — то, что попадает в текст SQL-запроса."""
    if isinstance(value, str):
        return True
    return callable(getattr(value, "compile", None))


def statement_text(obj: Any) -> str:
    """Текст SQL любого объекта SQLAlchemy (или строки) без подстановки значений."""
    try:
        return str(obj)
    except Exception:  # noqa: BLE001 - диагностический помощник, падать не должен
        return repr(obj)


# ---------------------------------------------------------------------------
# Детектор утечки значений в SQL-текст (SEC-06, P-SEC-04): нормализованный
# ---------------------------------------------------------------------------

#: Уникальный маркер baseline-прогона: не может совпасть с «скелетом» SQL.
BASELINE_MARKER = "\u0000BASELINE-sql-value-marker\u0000"

SqlRunOne = Any  # async (factory: RecordingSessionFactory, payload: str, index: int) -> None


async def sql_leaks_for(payloads: Sequence[str], run_one: SqlRunOne) -> list[str]:
    """Утечки недоверенных значений в SQL-текст; пусто — утечек нет.

    Свойство SEC-06: текст запроса НЕ зависит от недоверенных значений —
    значения живут только в bind-параметрах. Поэтому payload-прогон сравнивается
    с baseline-прогоном того же кода (уникальный :data:`BASELINE_MARKER`):
    любой payload, изменивший текст запроса или их число, — утечка.

    Такая нормализация исключает ложные срабатывания на коротких payload'ах,
    совпавших со «скелетом» SQL («O» в ``INSERT INTO``, «_» в ``%(user_id)s``),
    но НЕ ослабляет покрытие: любая интерполяция (f-string, конкатенация,
    ``.format``) меняет текст запроса и фиксируется. Отрицательный контроль —
    ``test_SEC_06_detector_catches_interpolated_sql`` (намеренно уязвимый
    репозиторий обязан дать утечки).
    """
    leaks: list[str] = []
    for index, payload in enumerate(payloads):
        baseline = await _sql_snapshot(run_one, BASELINE_MARKER, index)
        texts = await _sql_snapshot(run_one, payload, index)
        if len(texts) != len(baseline):
            leaks.append(
                f"payload {payload!r}: число SQL-запросов зависит от значения "
                f"({len(baseline)} -> {len(texts)}) — значение управляет SQL"
            )
            continue
        for call_no, (text, base) in enumerate(zip(texts, baseline, strict=True)):
            if text != base:
                leaks.append(
                    f"payload {payload!r} попал в SQL-текст (запрос #{call_no}): "
                    f"{text[:120]!r} != baseline {base[:120]!r}"
                )
    return leaks


async def _sql_snapshot(run_one: SqlRunOne, payload: str, index: int) -> list[str]:
    factory = RecordingSessionFactory()
    await run_one(factory, payload, index)
    return factory.statements()


# ---------------------------------------------------------------------------
# BotCore на in-memory репозитории (без БД/сети): точечные abuse-кейсы рендера
# ---------------------------------------------------------------------------


class MemoryRepo:
    """Минимальный репозиторий-двойник для ``BotCore`` (SEC-05/SEC-09 abuse-кейсы)."""

    def __init__(self) -> None:
        self.users: dict[Any, Any] = {}
        self.presets: list[Any] = []

    async def get_user(self, user_id: Any) -> Any:
        return self.users.get(user_id)

    async def upsert_user(self, user_id: Any, *, lang: str, profile: Any) -> Any:
        row = type("UserRow", (), {})()
        row.id, row.lang, row.profile = user_id, lang, profile
        self.users[user_id] = row
        return row

    async def list_presets(self) -> list[Any]:
        return list(self.presets)

    async def upsert_preset(self, slug: str, *, name: str, filter_json: Any) -> None:
        self.presets = [p for p in self.presets if p.slug != slug] + [
            type("PresetRow", (), {"slug": slug, "name_ru": name, "filter": filter_json})()
        ]

    async def delete_preset(self, slug: str) -> None:
        self.presets = [p for p in self.presets if p.slug != slug]

    async def admin_stats(self) -> Any:
        return type("AdminStats", (), {"users": 0, "like": 0, "dislike": 0, "bookmark": 0})()

    async def upsert_feedback(self, **kwargs: Any) -> None:
        return None

    async def add_vacancies(self, vacancies: Sequence[Any]) -> int:
        return 0

    async def recent_parse_runs(self, limit: int = 10) -> list[Any]:
        return []


def memory_bot(*, antispam: Any = None) -> Any:
    """``BotCore`` на :class:`MemoryRepo`; ``antispam`` — подменяемый (лимиты)."""
    core_cls = load_attr("app.bot.core", "BotCore")
    return core_cls(repo=MemoryRepo(), antispam=antispam)


# ---------------------------------------------------------------------------
# Тестовый вход в бота (SEC-03, SEC-04, SEC-07, SEC-10): BotHarness (api.md §15)
# ---------------------------------------------------------------------------


async def bot_replies(text: str, *, user_id: Any) -> list[str]:
    """Отправить сообщение боту от ``user_id`` и вернуть тексты ответов ему.

    Контракт тестового входа фиксируется security-тестами (threat-model §5.8):
    ``tests.e2e.helpers.BotHarness`` — async context manager с методами
    ``send(text, user_id=...)`` и ``sent()`` — ответы на ПОСЛЕДНИЙ ``send()``
    (объекты с ``.text`` либо строки).
    """
    async with bot_session() as session:
        return await session.send(text, user_id=user_id)


class BotSession:
    """Один запуск бота: серия сообщений без перезапуска харнеса."""

    def __init__(self, harness: Any) -> None:
        self._harness = harness

    async def send(self, text: str, *, user_id: Any) -> list[str]:
        sent = self._harness.send(text, user_id=user_id)
        if inspect.isawaitable(sent):
            await sent
        raw = self._harness.sent()
        if inspect.isawaitable(raw):
            raw = await raw
        return [message.text if hasattr(message, "text") else str(message) for message in raw]

    async def tap(self, data: str, *, user_id: Any = None) -> CallbackOutcome:
        """Нажатие инлайн-кнопки: ``callback_query`` с ``callback_data=data`` (SEC-15).

        Контракт тестового входа фиксируется security-тестами (threat-model §5.8):
        ``BotHarness.tap(data, user=None)`` — симуляция нажатия кнопки от ``user``
        (``None`` — пользователь последнего ``send``/``tap``; для подделанных
        callback тесты передают чужой ``user_id`` явно) и ``BotHarness.answers()`` —
        ``answer_callback_query``'ы последнего ``tap`` (объекты с ``.text`` либо
        строки; пустая строка = подтверждение без текста). Не реализовано → красный
        тест с понятной причиной (:class:`NotImplementedYet`).
        """
        tap_fn = getattr(self._harness, "tap", None)
        answers_fn = getattr(self._harness, "answers", None)
        if not callable(tap_fn) or not callable(answers_fn):
            raise NotImplementedYet(
                "BotHarness.tap(data, user=None)/answers() ещё не реализованы "
                "(threat-model §5.8): callback-канал недоступен"
            )
        result = tap_fn(data, user=user_id)
        if inspect.isawaitable(result):
            result = await result
        raw_replies = self._harness.sent()
        if inspect.isawaitable(raw_replies):
            raw_replies = await raw_replies
        raw_answers = answers_fn()
        if inspect.isawaitable(raw_answers):
            raw_answers = await raw_answers
        replies = [
            message.text if hasattr(message, "text") else str(message) for message in raw_replies
        ]
        answers = [_answer_text(answer) for answer in raw_answers]
        return CallbackOutcome(replies=replies, answers=answers)


@asynccontextmanager
async def bot_session() -> AsyncIterator[BotSession]:
    """Запустить бота (BotHarness) для серии взаимодействий в одном тесте."""
    ensure_test_env()
    harness_cls = load_attr("tests.e2e.helpers", "BotHarness")
    async with harness_cls() as harness:
        yield BotSession(harness)


# ---------------------------------------------------------------------------
# Callback-канал диалога I-2 (SEC-15): tap/answers по threat-model §5.8
# ---------------------------------------------------------------------------


class CallbackOutcome:
    """Результат одного ``tap``: сообщения-ответы и подтверждения callback."""

    def __init__(self, replies: list[str], answers: list[str]) -> None:
        self.replies = replies
        self.answers = answers

    def __repr__(self) -> str:
        return f"CallbackOutcome(replies={self.replies!r}, answers={self.answers!r})"


def _answer_text(answer: Any) -> str:
    """Текст ``answer_callback_query`` (пустая строка = подтверждение без текста)."""
    if answer is None:
        return ""
    if isinstance(answer, str):
        return answer
    if hasattr(answer, "text"):
        text = answer.text
        return text if isinstance(text, str) else ""
    return str(answer)


#: Мусорные/инъекционные/oversized callback_data (abuse-кейсы SEC-15).
#: Лимит Telegram — 64 байта, но тесты сознательно обходят его (недоверенный
#: клиент может прислать что угодно): ≥64 байт обязаны дать общий отказ.
CALLBACK_PAYLOADS: tuple[str, ...] = (
    # не по грамматике dlg:<step>:<value>
    "not-a-callback",
    "",
    "dlg:",
    "dlg:unknown:x",
    "dlg:lang",
    "DROP TABLE users; --",
    # значения вне белого списка (перебор значений)
    "dlg:size:51",
    "dlg:size:-5",
    "dlg:size:05",
    "dlg:lang:de",
    "dlg:preset:nonexistent",
    "dlg:tz:UTC+99",
    "dlg:tz:page-0",
    "dlg:tz:../../../etc/passwd",
    # инъекция в value / step
    "dlg:<script>alert(1)</script>",
    "dlg:lang:<img src=x onerror=alert(1)>",
    'dlg:preset:</b><a href="http://evil.example/">CLICK ME',
    "dlg:size:5; DROP TABLE users --",
    # oversized (лимит Telegram 64 байта)
    "dlg:preset:" + "a" * 100,
    "x" * 1024,
    "dlg:lang:ru" + "\x00" * 60,
    # кодировки/управляющие символы
    "dlg:size:5\x00",
    "dlg:size:\u202e5",
    "\u202e dlg:lang:ru",
    "ＤＬＧ:size:5",
    "dlg:size:5\r\n",
)


class CallbackFuzzer:
    """Один ``BotHarness`` на весь прогон P-SEC-06 (схема не пересоздаётся на пример).

    Свой event loop — hypothesis работает синхронно. Каждый пример получает
    свежего пользователя: антиспам и состояние диалога не влияют на свойство
    «произвольный callback_data → либо белый список, либо общий отказ».
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._session: BotSession | None = None
        self._exit: Any = None

    def tap(self, data: str, *, user_id: Any) -> CallbackOutcome:
        """Один callback_data произвольной формы; исключений быть не должно."""
        if self._loop.is_closed():  # повторное использование после close()
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(self._tap(data, user_id))

    async def _tap(self, data: str, user_id: Any) -> CallbackOutcome:
        if self._session is None:
            manager = bot_session()
            self._session = await manager.__aenter__()
            self._exit = manager.__aexit__
        return await self._session.tap(data, user_id=user_id)

    def close(self) -> None:
        if self._session is not None and self._exit is not None:
            self._loop.run_until_complete(self._exit(None, None, None))
            self._session = None
            self._exit = None
        if not self._loop.is_closed():
            self._loop.close()


# ---------------------------------------------------------------------------
# Chat-граница хендлеров (F-15): синтетические aiogram update-объекты
# ---------------------------------------------------------------------------


_DEFAULT = object()


class FakeChat:
    """Кусок aiogram ``Chat``: хендлеру нужен только ``type`` (F-15)."""

    def __init__(self, chat_type: Any) -> None:
        self.type = chat_type


class FakeUser:
    """Кусок aiogram ``User``: только ``id`` (владелец действия, TB-8)."""

    def __init__(self, user_id: Any) -> None:
        self.id = user_id


class FakeMessage:
    """Синтетический aiogram ``Message`` для chat-границы (F-15, threat-model §5.8).

    Записывает всё, что бот опубликовал в этот чат (``answer``/``edit_text``), —
    атакующий сценарий проверяет, что в чужой/неподтверждённый чат не уходит
    ничего, включая тексты настроек. ``chat`` — объект с ``.type``
    (:class:`FakeChat`) либо crafted-объект (``None``, ``object()``, спуфинг
    ``type``); для fail-closed кейса «атрибута chat нет вовсе» — ``del message.chat``.
    """

    def __init__(
        self,
        *,
        text: str = "",
        chat: Any = None,
        user: Any = _DEFAULT,
        user_id: Any = 1000,
        caption: str | None = None,
    ) -> None:
        self.chat = chat
        self.from_user = FakeUser(user_id) if user is _DEFAULT else user
        self.text = text
        self.caption = caption
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.edited: list[tuple[str, dict[str, Any]]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.sent.append((text, kwargs))

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        self.edited.append((text, kwargs))

    def published(self) -> list[str]:
        """Всё, что бот опубликовал в этот чат (тексты send/edit) — пусто = тишина."""
        return [str(text) for text, _ in self.sent] + [str(text) for text, _ in self.edited]


class FakeCallback:
    """Синтетический aiogram ``CallbackQuery`` (F-15): записывает ``answer``'ы.

    ``answers`` — подтверждения ``answer_callback_query`` в порядке вызова:
    ``(текст, show_alert)``; молчаливое подтверждение = ``(None, False)``.
    """

    def __init__(
        self,
        *,
        data: str,
        message: FakeMessage | None = None,
        user: Any = _DEFAULT,
        user_id: Any = 1000,
    ) -> None:
        self.data = data
        self.message = message
        self.from_user = FakeUser(user_id) if user is _DEFAULT else user
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, *, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))
