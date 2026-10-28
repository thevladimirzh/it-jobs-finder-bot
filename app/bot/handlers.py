"""Хендлеры aiogram 3: мост между Telegram и ``app.bot.core.BotCore``.

Вся логика команд/диалога — в ``BotCore`` (общая с тестовой обвязкой);
хендлер только доставляет текст, клавиатуры и подтверждения callback.
``callback_query`` подтверждается ПЕРВЫМ действием (``answer`` — до обработки
шага, AC-22): «часики» Telegram не появляются. Текст сообщений — готовый
Telegram HTML (уже экранирован), метки кнопок — plain text.

Диалог работает только в личном чате (F-15, SEC review I-2): в группе
команды молча игнорируются, нажатие кнопки молча подтверждается (без
обработки) — настройки пользователя не публикуются в общий чат. Сбои
Telegram API (``TelegramBadRequest``: устаревшее/чужое/пересланное сообщение,
старый callback) не роняют хендлер: правка без возможности править
деградирует в отправку нового сообщения.
"""

from __future__ import annotations

from typing import Any

from aiogram import Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.core import BotCore
from app.bot.dialog import Keyboard, Reply


def _markup(keyboard: Keyboard) -> InlineKeyboardMarkup | None:
    """Инлайн-клавиатура из рядов (метка, callback_data) диалога."""
    if not keyboard:
        return None
    rows = [
        [InlineKeyboardButton(text=label, callback_data=data) for label, data in row]
        for row in keyboard
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _is_private(message: Any) -> bool:
    """Приватный ли чат у сообщения (F-15); ``None``/неизвестный чат — нет.

    Fail-closed: если ``chat.type`` подтвердить нельзя, диалог не работает.
    """
    chat = getattr(message, "chat", None)
    return getattr(chat, "type", None) == "private"


async def _safe_answer(
    callback: CallbackQuery, text: str | None = None, show_alert: bool = False
) -> None:
    """Подтверждение callback: старый/просроченный запрос — молча (F-15)."""
    try:
        await callback.answer(text, show_alert=show_alert)
    except TelegramBadRequest:
        return


async def _safe_send(message: Any, reply: Reply, markup: InlineKeyboardMarkup | None) -> None:
    """Отправка ответа: сбой Telegram API — молча, без краша (F-15)."""
    try:
        await message.answer(reply, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest:
        return


async def _safe_edit(message: Any, reply: Reply, markup: InlineKeyboardMarkup | None) -> None:
    """Правка шага диалога: чужое/пересланное/устаревшее сообщение не роняет
    хендлер (F-15); правка без возможности править — отправкой нового."""
    try:
        await message.edit_text(reply, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest:
        await _safe_send(message, reply, markup)


async def handle_message(message: Message, bot_core: BotCore) -> None:
    """Входящее сообщение: только личный чат (F-15); группы — молча."""
    user = message.from_user
    if user is None or not _is_private(message):
        return
    text = message.text or message.caption or ""
    replies = await bot_core.handle(text, user.id)
    for reply in replies:
        await _safe_send(message, reply, _markup(getattr(reply, "keyboard", ())))


async def handle_callback_query(callback: CallbackQuery, bot_core: BotCore) -> None:
    """Callback кнопочного диалога: только личный чат (F-15).

    В группе (или если чат подтвердить нельзя) нажатие молча подтверждается —
    «часики» снимаются, но действие не обрабатывается и ничего не публикуется.
    """
    user = callback.from_user
    if user is None:
        return
    if not _is_private(callback.message):
        await _safe_answer(callback)
        return

    async def answer(text: str, show_alert: bool) -> None:
        await _safe_answer(callback, text or None, show_alert)

    replies = await bot_core.handle_callback(callback.data or "", user.id, answer=answer)
    for reply in replies:
        markup = _markup(getattr(reply, "keyboard", ()))
        if getattr(reply, "edit", False):
            await _safe_edit(callback.message, reply, markup)
        else:
            await _safe_send(callback.message, reply, markup)


def build_dispatcher(bot_core: BotCore) -> Dispatcher:
    """Dispatcher: сообщения и callback_query кнопочного диалога (api.md §15)."""
    router = Router()

    @router.message()
    async def on_message(message: Message) -> None:
        await handle_message(message, bot_core)

    @router.callback_query()
    async def on_callback(callback: CallbackQuery) -> None:
        await handle_callback_query(callback, bot_core)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_polling(bot: Any, dispatcher: Dispatcher) -> None:
    await dispatcher.start_polling(bot)
