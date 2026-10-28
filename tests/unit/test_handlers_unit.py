"""Юнит-тесты хендлеров Telegram (F-15, security review I-2): U-SEC-01..U-SEC-03.

Модуль ``app/bot/handlers.py`` — единственная точка публикации текста в чат.
Контракт (решение software-engineer, docs/security/report.md §8 F-15):

- диалоговые действия (текст и callback) работают ТОЛЬКО в личном чате
  (``chat.type == "private"``): в группе команды молча игнорируются, нажатие
  кнопки молча подтверждается (``answer`` — снятие «часиков») и НЕ обрабатывается
  — настройки нажавшего не публикуются в общий чат (CWE-200);
- если приватность чата подтвердить нельзя (``message is None``, неизвестный
  тип чата) — действие тоже игнорируется (fail-closed);
- сбои Telegram API (``TelegramBadRequest``: устаревшее/чужое/пересланное
  сообщение, старый callback) не роняют хендлер: правка без возможности
  править деградирует в отправку нового сообщения.
"""

from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest

from app.bot.dialog import Reply
from app.bot.handlers import handle_callback_query, handle_message

PRIVATE = "private"


def _bad_request(text: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=None, message=text)


class _Chat:
    def __init__(self, type: str) -> None:
        self.type = type


class _User:
    def __init__(self, id: int) -> None:
        self.id = id


class _Message:
    """Утиная заглушка aiogram Message (хендлеру нужны только эти атрибуты)."""

    def __init__(
        self,
        chat_type: str | None = PRIVATE,
        *,
        text: str = "/settings",
        user: _User | None = None,
        fail_answer: bool = False,
        fail_edit: bool = False,
    ) -> None:
        self.chat = _Chat(chat_type) if chat_type is not None else None
        self.from_user = user if user is not None else _User(7)
        self.text = text
        self.caption = None
        self.sent: list[tuple[str, dict]] = []
        self.edited: list[tuple[str, dict]] = []
        self._fail_answer = fail_answer
        self._fail_edit = fail_edit

    async def answer(self, text: str, **kwargs) -> None:
        if self._fail_answer:
            raise _bad_request("Bad Request: chat not found")
        self.sent.append((text, kwargs))

    async def edit_text(self, text: str, **kwargs) -> None:
        if self._fail_edit:
            raise _bad_request("Bad Request: message can't be edited")
        self.edited.append((text, kwargs))


class _Callback:
    """Утиная заглушка aiogram CallbackQuery."""

    def __init__(
        self,
        message: _Message | None,
        *,
        data: str = "dlg:lang:ru",
        user: _User | None = None,
        fail_answer: bool = False,
    ) -> None:
        self.message = message
        self.from_user = user if user is not None else _User(7)
        self.data = data
        self.answers: list[tuple[str | None, bool]] = []
        self._fail_answer = fail_answer

    async def answer(self, text: str | None = None, *, show_alert: bool = False) -> None:
        if self._fail_answer:
            raise _bad_request("Bad Request: query is too old")
        self.answers.append((text, show_alert))


class _Core:
    """Записывающая заглушка BotCore: какие действия вообще дошли до ядра."""

    def __init__(self, replies: tuple = ()) -> None:
        self.calls: list[tuple] = []
        self.replies = tuple(replies)

    async def handle(self, text: str, user_id) -> list:
        self.calls.append(("message", text, user_id))
        return list(self.replies)

    async def handle_callback(self, data: str, user_id, *, answer) -> list:
        self.calls.append(("callback", data, user_id))
        return list(self.replies)


# --- U-SEC-01 (F-15): диалог только в личном чате, группы игнорируются --------


async def test_u_sec01_group_messages_are_ignored() -> None:
    for chat_type in ("group", "supergroup", "channel"):
        message = _Message(chat_type, text="/settings")
        core = _Core(replies=(Reply("настройки"),))
        await handle_message(message, core)
        assert core.calls == [], (
            f"U-SEC-01: {chat_type}: сообщение обработано ядром: {core.calls!r}"
        )
        assert message.sent == [], (
            f"U-SEC-01: {chat_type}: ответ ушёл в общий чат: {message.sent!r}"
        )


async def test_u_sec01_private_messages_are_handled_and_answered() -> None:
    message = _Message(PRIVATE, text="/settings")
    core = _Core(replies=(Reply("ваша сводка"),))
    await handle_message(message, core)
    assert core.calls == [("message", "/settings", 7)], f"U-SEC-01: ядро не вызвано: {core.calls!r}"
    assert len(message.sent) == 1, f"U-SEC-01: ответ не доставлен: {message.sent!r}"
    text, kwargs = message.sent[0]
    assert text == "ваша сводка", f"U-SEC-01: текст ответа изменён: {text!r}"
    assert kwargs.get("parse_mode") == "HTML", f"U-SEC-01: не HTML-отправка: {kwargs!r}"


async def test_u_sec01_anonymous_or_unknown_chat_is_ignored() -> None:
    """Без from_user или без chat.type приватность не подтверждена — игнор (fail-closed)."""
    anonymous = _Message(PRIVATE)
    anonymous.from_user = None
    core = _Core(replies=(Reply("x"),))
    await handle_message(anonymous, core)
    unknown = _Message(None, text="10:00")
    await handle_message(unknown, core)
    assert core.calls == [], f"U-SEC-01: непроверяемые источники обработаны: {core.calls!r}"
    assert anonymous.sent == [] and unknown.sent == [], (
        "U-SEC-01: ответ ушёл без подтверждения чата"
    )


# --- U-SEC-02 (F-15): callback в группе — молчаливый игнор с answer -----------


async def test_u_sec02_group_callback_is_acknowledged_but_not_processed() -> None:
    message = _Message("supergroup")
    callback = _Callback(message, data="dlg:lang:en")
    core = _Core(replies=(Reply("сводка: пресеты X, зарплата Y"),))
    await handle_callback_query(callback, core)
    assert core.calls == [], f"U-SEC-02: нажатие в группе обработано: {core.calls!r}"
    assert message.sent == [] and message.edited == [], (
        f"U-SEC-02: настройки нажавшего опубликованы в группу: {message.sent!r} {message.edited!r}"
    )
    assert callback.answers == [(None, False)], (
        f"U-SEC-02: подтверждение не молчаливое/не одно: {callback.answers!r}"
    )


async def test_u_sec02_unverifiable_callback_is_ignored() -> None:
    callback = _Callback(None, data="dlg:lang:en")  # message is None — чат неизвестен
    core = _Core(replies=(Reply("x"),))
    await handle_callback_query(callback, core)
    assert core.calls == [], f"U-SEC-02: callback без сообщения обработан: {core.calls!r}"
    assert callback.answers == [(None, False)], f"U-SEC-02: нет подтверждения: {callback.answers!r}"


async def test_u_sec02_private_callback_is_processed_and_answered() -> None:
    message = _Message(PRIVATE)
    callback = _Callback(message, data="dlg:lang:en")
    core = _Core(replies=(Reply("Сохранено"),))
    await handle_callback_query(callback, core)
    assert core.calls == [("callback", "dlg:lang:en", 7)], (
        f"U-SEC-02: ядро не вызвано: {core.calls!r}"
    )
    assert len(message.sent) == 1, f"U-SEC-02: ответ не доставлен: {message.sent!r}"

    # reply.edit=True — правка нажатого сообщения (шаг диалога)
    message = _Message(PRIVATE)
    callback = _Callback(message, data="dlg:preset:done")
    core = _Core(replies=(Reply("Итог", edit=True),))
    await handle_callback_query(callback, core)
    assert len(message.edited) == 1 and message.sent == [], (
        f"U-SEC-02: edit-ответ не отредактирован: {message.edited!r} {message.sent!r}"
    )


# --- U-SEC-03 (F-15): TelegramBadRequest — без краша, деградация мягкая ------


async def test_u_sec03_send_failure_does_not_crash_message_handler() -> None:
    message = _Message(PRIVATE, fail_answer=True)
    core = _Core(replies=(Reply("первый"), Reply("второй")))
    await handle_message(message, core)  # не должно бросить
    assert core.calls == [("message", "/settings", 7)], f"U-SEC-03: ядро не вызвано: {core.calls!r}"


async def test_u_sec03_edit_failure_falls_back_to_new_message() -> None:
    """Чужое/пересланное/устаревшее сообщение: правка невозможна → новое сообщение."""
    message = _Message(PRIVATE, fail_edit=True)
    callback = _Callback(message, data="dlg:preset:done")
    core = _Core(replies=(Reply("Итог", edit=True),))
    await handle_callback_query(callback, core)
    assert message.edited == [], f"U-SEC-03: неудачная правка записана: {message.edited!r}"
    assert len(message.sent) == 1 and message.sent[0][0] == "Итог", (
        f"U-SEC-03: ответ потерян после сбоя правки: {message.sent!r}"
    )


async def test_u_sec03_total_send_failure_does_not_crash_callback_handler() -> None:
    message = _Message(PRIVATE, fail_answer=True, fail_edit=True)
    callback = _Callback(message, data="dlg:preset:done")
    core = _Core(replies=(Reply("Итог", edit=True),))
    await handle_callback_query(callback, core)  # не должно бросить
    assert core.calls == [("callback", "dlg:preset:done", 7)], (
        f"U-SEC-03: ядро не вызвано: {core.calls!r}"
    )


async def test_u_sec03_stale_callback_answer_failure_is_contained() -> None:
    """Ответ на старый callback_query тоже падает в Telegram — это не краш хендлера."""
    message = _Message(PRIVATE)
    callback = _Callback(message, data="dlg:lang:en", fail_answer=True)
    core = _Core(replies=(Reply("Сохранено"),))
    await handle_callback_query(callback, core)  # не должно бросить
    assert core.calls == [("callback", "dlg:lang:en", 7)], (
        f"U-SEC-03: ядро не вызвано: {core.calls!r}"
    )
