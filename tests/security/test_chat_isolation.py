"""Chat-граница хендлеров (F-15): группы, чужие и неподтверждённые чаты.

Угроза F-15 (docs/security/report.md §8.3, CWE-200/CWE-754): ответы диалога
шли в чат нажатого сообщения без проверки ``chat.type == "private"`` — кнопка
в группе (или у пересланного сообщения) публиковала настройки нажавшего
(пресеты/зарплата/стоп-слова) в общий чат. Митигация (software-engineer,
I-2-fix, `app/bot/handlers.py`): диалог работает только в личном чате,
неподтверждённый чат — fail-closed; callback в группе → ровно один молчаливый
``answer`` (снятие «часиков») без обработки и публикаций; ``TelegramBadRequest``
не роняет хендлер.

Угол security-тестов — атакующий вход, НЕ дубль юнит-контрактов U-SEC-01..03
(tests/unit/test_handlers_unit.py, там заглушка ядра):
- реальное ядро (:func:`support.memory_bot`) с настоящими настройками жертвы
  (маркеры в сводке /settings) — «настройки не публикуются» проверяется по
  реальному рендеру, с позитивной контролью (в личке маркер виден);
- вредоносные callback_data/тексты (:data:`support.CALLBACK_PAYLOADS`,
  HTML/SQL-инъекции) из чужого группового чата;
- crafted-объекты update'ов: спуфинг ``chat.type`` (``"Private"``, ``""``,
  числа), отсутствующие атрибуты ``chat``/``from_user``, ``message is None``.

Тестовый вход — threat-model §5.8 (chat-граница): ``app.bot.handlers.handle_message``
/ ``handle_callback_query`` с синтетическими объектами support (``FakeMessage``/
``FakeCallback``) — ``BotHarness`` изолирован от chat-контекста. SEC-15/SEC-05.
"""

from __future__ import annotations

from support import (
    CALLBACK_PAYLOADS,
    HTML_PAYLOADS,
    SQL_PAYLOADS,
    FakeCallback,
    FakeChat,
    FakeMessage,
    load_attr,
    memory_bot,
)

#: Маркеры персональных данных жертвы (стоп-слова в сводке) — не должны утечь.
MARKERS = ("SECRETMARKER777", "SECRETMARKER888")

#: Групповые/публичные типы чатов Telegram (диалог в них запрещён).
GROUP_TYPES = ("group", "supergroup", "channel")

#: Спуфинг/мусор вместо подтверждённого ``chat.type == "private"``.
SPOOFED_CHAT_TYPES = (
    "Private",
    "PRIVATE",
    "private ",
    " private",
    "private_group",
    "personal",
    "",
    "bot",
    "unknown",
    123,
    None,
    True,
)


def _handlers() -> tuple:
    return (
        load_attr("app.bot.handlers", "handle_message"),
        load_attr("app.bot.handlers", "handle_callback_query"),
    )


async def _victim_core(user_id: int) -> tuple:
    """Ядро с реальным профилем жертвы (маркеры в стоп-словах и зарплате)."""
    core = memory_bot()
    profile_cls = load_attr("app.domain.profile", "Profile")
    to_jsonb = load_attr("app.domain.profile", "profile_to_jsonb")
    profile = profile_cls(lang="ru", stop_words=list(MARKERS), min_salary_rub=999_999)
    await core._repo.upsert_user(user_id, lang="ru", profile=to_jsonb(profile))
    return core


def _leaks(texts: list[str]) -> list[str]:
    """Тексты, раскрывающие настройки жертвы (маркеры персональных данных)."""
    return [text for text in texts if any(marker in text for marker in MARKERS)]


# --- F-15: callback в группе → ровно один молчаливый answer, без публикаций ---


async def test_F15_group_callback_answers_silently_once_and_never_publishes_settings() -> None:
    """SEC-15/F-15: нажатие кнопки в группе/канале — ровно один молчаливый
    ``answer_callback_query`` (без текста), настройки нажавшего НЕ публикуются,
    состояние профиля не меняется (CWE-200)."""
    handle_message, handle_callback_query = _handlers()
    uid = 730_001
    core = await _victim_core(uid)

    # позитивная контроль: в личном чате те же настройки показываются (детектор жив)
    private = FakeMessage(chat=FakeChat("private"), text="/settings", user_id=uid)
    await handle_message(private, core)
    assert _leaks(private.published()), (
        f"F-15: контроль в личке не видит маркеры настроек — тест вакуумен: {private.published()!r}"
    )
    before = dict(core._repo.users[uid].profile)

    payloads = ("dlg:lang:ru", "dlg:preset:done", "dlg:size:10") + CALLBACK_PAYLOADS
    for chat_type in GROUP_TYPES:
        for payload in payloads:
            group = FakeMessage(chat=FakeChat(chat_type), user_id=uid)
            callback = FakeCallback(data=payload, message=group, user_id=uid)
            await handle_callback_query(callback, core)
            assert callback.answers == [(None, False)], (
                f"F-15: {chat_type}: callback {payload!r} дал {callback.answers!r}, "
                f"ожидалось ровно одно молчаливое подтверждение (без текста)"
            )
            assert group.published() == [], (
                f"F-15: {chat_type}: настройки опубликованы в общий чат на "
                f"callback {payload!r}: {group.published()!r}"
            )
    assert dict(core._repo.users[uid].profile) == before, (
        "F-15: групповой callback изменил настройки жертвы"
    )


# --- F-15: команда в группе игнорируется, без побочных эффектов -------------


async def test_F15_group_chat_commands_are_ignored_without_side_effects() -> None:
    """SEC-15/F-15: команды и вредоносные тексты из группового чата молча
    игнорируются: ничего не публикуется, ни пользователь, ни пресеты не
    создаются (включая админские команды из группы)."""
    handle_message, _ = _handlers()
    admin_id = load_attr("app.config", "settings").admin_id
    core = memory_bot()

    texts = (
        (
            "/start",
            "/settings",
            "/settings preset",
            "/admin_preset_add evilx <script>alert(1)</script> {}",
            "/admin_preset_list",
            "SECRETMARKER777",
            "A" * 10_000,
        )
        + HTML_PAYLOADS
        + SQL_PAYLOADS
    )
    for chat_type in GROUP_TYPES + SPOOFED_CHAT_TYPES:
        for text in texts:
            for user_id in (730_100, admin_id):  # обычный юзер и админ — один запрет
                message = FakeMessage(chat=FakeChat(chat_type), text=text, user_id=user_id)
                await handle_message(message, core)
                assert message.published() == [], (
                    f"F-15: {chat_type!r}: ответ ушёл в чужой чат на {text!r}: "
                    f"{message.published()!r}"
                )
    assert core._repo.users == {}, "F-15: групповой ввод создал пользователя/состояние в БД"
    assert core._repo.presets == [], "F-15: админская команда из группы записала пресет"


# --- F-15: неподтверждённый/спуфленный чат — fail-closed --------------------


async def test_F15_unconfirmed_or_spoofed_chat_fails_closed() -> None:
    """SEC-15/F-15: если приватность чата подтвердить нельзя (нет ``chat``/
    ``from_user``, неизвестный/спуфленный ``chat.type``) — fail-closed: ничего
    не публикуется и не обрабатывается; callback — не более одного молчаливого
    подтверждения, никогда — исключение (CWE-20)."""
    handle_message, handle_callback_query = _handlers()
    core = memory_bot()

    # --- текстовый канал: отсутствующие/спуфленные атрибуты
    cases: list[FakeMessage] = []
    for chat_type in SPOOFED_CHAT_TYPES:
        cases.append(FakeMessage(chat=FakeChat(chat_type), text="/settings", user_id=730_200))
    cases.append(FakeMessage(chat=None, text="/settings", user_id=730_200))
    cases.append(FakeMessage(chat=object(), text="/settings", user_id=730_200))  # нет .type
    no_chat = FakeMessage(text="/settings", user_id=730_200)
    del no_chat.chat  # атрибута chat нет вовсе
    cases.append(no_chat)
    anonymous = FakeMessage(chat=FakeChat("private"), text="/settings")
    anonymous.from_user = None
    cases.append(anonymous)
    for message in cases:
        await handle_message(message, core)
        assert message.published() == [], (
            f"F-15: fail-closed нарушен (chat={getattr(message, 'chat', '<нет>')!r}): "
            f"{message.published()!r}"
        )

    # --- callback-канал: ровно один молчаливый answer при известном пользователе
    for chat_type in SPOOFED_CHAT_TYPES:
        message = FakeMessage(chat=FakeChat(chat_type), user_id=730_201)
        callback = FakeCallback(data="dlg:lang:ru", message=message, user_id=730_201)
        await handle_callback_query(callback, core)
        assert callback.answers == [(None, False)], (
            f"F-15: {chat_type!r}: callback не дал ровно одно молчаливое "
            f"подтверждение: {callback.answers!r}"
        )
        assert message.published() == [], f"F-15: {chat_type!r}: публикация {message.published()!r}"

    for message in (None, FakeMessage(chat=None), FakeMessage(chat=object())):
        callback = FakeCallback(data="dlg:lang:ru", message=message, user_id=730_202)
        await handle_callback_query(callback, core)
        assert len(callback.answers) <= 1, (
            f"F-15: callback без подтверждённого чата дал {len(callback.answers)} answer"
        )
        published = message.published() if message is not None else []
        assert published == [], f"F-15: публикация без чата: {published!r}"

    # анонимный callback (нет from_user) — исключений нет, ничего не публикуется
    anon_message = FakeMessage(chat=FakeChat("private"))
    anon_callback = FakeCallback(data="dlg:preset:done", message=anon_message)
    anon_callback.from_user = None
    await handle_callback_query(anon_callback, core)
    assert len(anon_callback.answers) <= 1, "F-15: анонимный callback — двойной answer"
    assert anon_callback.message.published() == [], "F-15: анонимный callback что-то опубликовал"

    assert core._repo.users == {}, "F-15: неподтверждённый чат создал пользователя/состояние"


# --- F-15: атака из группы не задевает личный диалог жертвы -----------------


async def test_F15_victim_dialog_survives_group_attack_with_settings_intact() -> None:
    """SEC-15/F-15: бомбардировка кнопками из группы не трогает ни настройки,
    ни открытый диалог жертвы; личный чат продолжает работать (позитивная
    контроль до и после атаки)."""
    handle_message, handle_callback_query = _handlers()
    uid, attacker = 730_300, 730_301
    core = await _victim_core(uid)

    before = FakeMessage(chat=FakeChat("private"), text="/settings", user_id=uid)
    await handle_message(before, core)
    before_text = "\n".join(before.published())
    assert all(marker in before_text for marker in MARKERS), (
        f"F-15: контроль: маркеры настроек не видны в личке: {before_text!r}"
    )

    for payload in ("dlg:lang:en", "dlg:size:50", "dlg:preset:done", "dlg:tz:UTC+99"):
        for chat_type in GROUP_TYPES:
            group = FakeMessage(chat=FakeChat(chat_type), user_id=attacker)
            callback = FakeCallback(data=payload, message=group, user_id=attacker)
            await handle_callback_query(callback, core)
            assert group.published() == [], (
                f"F-15: {chat_type}: атака опубликовала текст: {group.published()!r}"
            )
            assert _leaks(group.published()) == [], "F-15: утечка маркеров в группу"

    after = FakeMessage(chat=FakeChat("private"), text="/settings", user_id=uid)
    await handle_message(after, core)
    after_text = "\n".join(after.published())
    assert after_text == before_text, (
        f"F-15: групповая атака изменила настройки/диалог жертвы:\n"
        f"до: {before_text!r}\nпосле: {after_text!r}"
    )
