"""Acceptance-тесты сценариев S79–S89 — механика callback кнопочного диалога (I-2).

Чёрный ящик: BotHarness (api.md §15.1) через обвязку ``dialog.py``; точные
строки — brief §6.1 «Диалог на инлайн-кнопках (I-2)» (дословно); контракт
callback_data ``dlg:<step>:<value>`` ≤ 64 байт — api.md §15.1, decisions §8.
Теги рисков — tests/features/dialog_callbacks.feature (провизорные R55..R62,
перепривязка — business-analyst; строки реестра: R55..R59 — product-manager,
R60..R62 — security-engineer, R63..R69 — технические, qa-engineer;
docs/risk-register.md).

Краснота до реализации I-2 идёт через ``NotImplementedYet`` (BotHarness.press/
keyboard/events ещё не реализованы) — не ошибками импорта.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from dialog import (
    CITY_LABELS_RU,
    FORMAT_BUTTONS_RU,
    FORMAT_HEADER,
    GREETING,
    LANG_BUTTONS,
    LANG_SAVED,
    OUTDATED,
    PRESET_BUTTONS_RU,
    PRESET_EMPTY,
    PRESET_HEADER,
    PRESET_SAVED,
    SIZE_BUTTONS,
    TZ_MANUAL_LABEL,
    TZ_MANUAL_PROMPT,
    TZ_SAVED,
    answer_of,
    answers_in,
    events,
    keyboard,
    onboard,
    open_step,
    press,
    selected,
    user_state,
)
from fakes import (
    FEEDBACK_OK,
    FakeSender,
    FakeThrottle,
    deliver_texts,
    make_vacancy,
    open_bot,
    send_text,
)
from support import app_settings, assert_no_raw_markup, load_attr, tag_violations

# callback_data каждой кнопки диалога (brief §6.1): step из белого списка,
# value — канонический ASCII-код [a-z0-9-]{1,32}, полная длина ≤ 64 байт.
CALLBACK_RE = re.compile(r"^dlg:(lang|preset|format|tz|size):[a-z0-9-]{1,32}$")

USER = 3001


# --- S79 (@R55): немедленное подтверждение каждого callback ------------------


async def test_s79_every_callback_answered_immediately() -> None:
    """@S79: ровно один answer_callback_query на каждый callback, первым действием.

    Валидный callback подтверждается пустым текстом (show_alert=false) до
    завершения обработки шага — «часики» Telegram не появляются (api.md §15.1).
    """
    async with open_bot() as h:
        uid = USER
        await send_text(h, uid, "/start")
        await press(h, "dlg:lang:ru", user_id=uid)
        for _ in range(2):  # «пользователь нажимает любую кнопку диалога»
            mark = len(events(h))
            await press(h, "dlg:preset:qa", user_id=uid)
            trail = events(h)[mark:]
            answers = answers_in(trail)
            assert len(answers) == 1, (
                f"@S79: {len(answers)} подтверждений callback (ожидалось ровно 1): {trail!r}"
            )
            assert trail[0][0] == "answer", (
                f"@S79: подтверждение не первое действие обработчика: {trail!r}"
            )
            text, show_alert = answer_of(answers[0][1])
            assert text == "", f"@S79: валидный callback подтверждён не пустым текстом: {text!r}"
            assert show_alert is False, (
                f"@S79: подтверждение валидного callback не toast (show_alert=true): {trail!r}"
            )


# --- S80 (@R56 @R26): устаревший callback -----------------------------------


async def test_s80_stale_callback_polite_refusal() -> None:
    """@S80: кнопка старого шага → вежливый отказ; настройки и шаг не меняются."""
    async with open_bot() as h:
        uid = USER + 1
        await send_text(h, uid, "/start")
        stale = dict(keyboard(h))["English"]  # кнопка шага lang
        await press(h, "dlg:lang:ru", user_id=uid)  # диалог перешёл к шагу preset
        before = await user_state(h, uid)

        mark = len(events(h))
        replies = await press(h, stale, user_id=uid)
        trail = events(h)[mark:]
        assert replies == [], f"@S80: устаревший callback изменил сообщения: {replies!r}"
        answers = answers_in(trail)
        assert len(answers) == 1 and trail[0][0] == "answer", (
            f"@S80: нет ровно одного немедленного подтверждения: {trail!r}"
        )
        text, show_alert = answer_of(answers[0][1])
        assert text == OUTDATED["ru"], f"@S80: ожидаем {OUTDATED['ru']!r}, получено {text!r}"
        assert show_alert is False, f"@S80: вежливый отказ не toast: {trail!r}"
        assert await user_state(h, uid) == before, "@S80: настройки пользователя изменились"

        # текущий шаг диалога не изменился: кнопка шага preset работает
        replies = await press(h, "dlg:preset:qa", user_id=uid)
        assert replies, "@S80: текущий шаг диалога изменился (кнопка preset не работает)"


# --- S81 (@R56 @R26): чужой callback ----------------------------------------


async def test_s81_foreign_callback_polite_refusal() -> None:
    """@S81: кнопка чужого диалога → вежливый отказ; чужие настройки целы."""
    async with open_bot() as h:
        user_a, user_b = USER + 2, USER + 3
        await send_text(h, user_a, "/start")
        await press(h, "dlg:lang:ru", user_id=user_a)  # у A открыт диалог с кнопками
        foreign = dict(keyboard(h))["QA"]  # кнопка из диалога пользователя A
        state_a = await user_state(h, user_a)
        state_b = await user_state(h, user_b)

        mark = len(events(h))
        replies = await press(h, foreign, user_id=user_b)
        trail = events(h)[mark:]
        assert replies == [], f"@S81: чужой callback изменил сообщения: {replies!r}"
        answers = answers_in(trail)
        assert len(answers) == 1 and trail[0][0] == "answer", (
            f"@S81: нет ровно одного немедленного подтверждения: {trail!r}"
        )
        text, show_alert = answer_of(answers[0][1])
        assert text == OUTDATED["ru"], (
            f"@S81: пользователю B ожидаем {OUTDATED['ru']!r}, получено {text!r}"
        )
        assert show_alert is False, f"@S81: вежливый отказ не toast: {trail!r}"
        assert await user_state(h, user_a) == state_a, "@S81: диалог/настройки A изменились"
        assert await user_state(h, user_b) == state_b, "@S81: настройки B изменились"


# --- S82 (@R57): мультивыбор пресетов ----------------------------------------


async def test_s82_preset_multiselect_toggles_and_saves_on_done() -> None:
    """@S82: ✅ переключается, подписка сохраняется только по «Готово»."""
    async with open_bot() as h:
        uid = USER + 4
        await send_text(h, uid, "/start")
        await press(h, "dlg:lang:ru", user_id=uid)
        buttons = keyboard(h)
        for label, data in PRESET_BUTTONS_RU.items():
            assert (label, data) in buttons, f"@S82: нет кнопки {label!r}: {buttons!r}"
        state0 = await user_state(h, uid)

        await press(h, "dlg:preset:python-backend", user_id=uid)
        buttons = keyboard(h)
        assert (selected("Python Backend"), "dlg:preset:python-backend") in buttons, (
            f"@S82: пресет не отмечен ✅: {buttons!r}"
        )
        assert await user_state(h, uid) == state0, (
            "@S82: подписка изменилась до «Готово» (после python-backend)"
        )

        await press(h, "dlg:preset:devops-sre", user_id=uid)
        buttons = keyboard(h)
        assert (selected("DevOps/SRE"), "dlg:preset:devops-sre") in buttons, (
            f"@S82: пресет не отмечен ✅: {buttons!r}"
        )
        assert await user_state(h, uid) == state0, (
            "@S82: подписка изменилась до «Готово» (после devops-sre)"
        )

        await press(h, "dlg:preset:python-backend", user_id=uid)  # повторно — снимает ✅
        buttons = keyboard(h)
        assert ("Python Backend", "dlg:preset:python-backend") in buttons, (
            f"@S82: повторное нажатие не сняло отметку: {buttons!r}"
        )
        assert await user_state(h, uid) == state0, (
            "@S82: подписка изменилась до «Готово» (после снятия python-backend)"
        )

        replies = await press(h, "dlg:preset:done", user_id=uid)
        assert PRESET_SAVED["ru"] in "\n".join(replies), (
            f"@S82: нет подтверждения {PRESET_SAVED['ru']!r}: {replies!r}"
        )
        state = await user_state(h, uid)
        assert state.profile["presets"] == ["devops-sre"], (
            f"@S82: подписка сохранена не как devops-sre: {state.profile!r}"
        )


# --- S83 (@R57): «Готово» без выбора ----------------------------------------


async def test_s83_done_without_selection_refuses() -> None:
    """@S83: «Готово» при 0 выбранных → toast «Выберите хотя бы один пресет.»."""
    async with open_bot() as h:
        uid = USER + 5
        await send_text(h, uid, "/start")
        await press(h, "dlg:lang:ru", user_id=uid)
        state0 = await user_state(h, uid)
        buttons0 = keyboard(h)

        mark = len(events(h))
        replies = await press(h, "dlg:preset:done", user_id=uid)
        trail = events(h)[mark:]
        assert replies == [], f"@S83: сообщение изменилось: {replies!r}"
        assert [kind for kind, _ in trail] == ["answer"], f"@S83: лишние события: {trail!r}"
        text, show_alert = answer_of(trail[0][1])
        assert text == PRESET_EMPTY["ru"], (
            f"@S83: ожидаем {PRESET_EMPTY['ru']!r}, получено {text!r}"
        )
        assert show_alert is False, f"@S83: отказ не toast: {trail!r}"
        assert await user_state(h, uid) == state0, "@S83: подписка изменилась"

        # шаг выбора пресетов остаётся открытым
        assert keyboard(h) == buttons0, f"@S83: клавиатура шага изменилась: {keyboard(h)!r}"
        replies = await press(h, "dlg:preset:qa", user_id=uid)
        assert replies, "@S83: шаг выбора пресетов закрылся после отказа"


# --- S84 (@R58): callback_data ≤ 64 байт на каждом шаге ----------------------


async def test_s84_callback_data_within_64_bytes_everywhere() -> None:
    """@S84: все кнопки всех шагов — «dlg:<step>:<value>», ASCII, ≤ 64 байт.

    Пресет со slug длиной 100 символов кодируется коротким кодом (decisions
    §8.2) и остаётся выбираемым: его можно отметить и сохранить.
    """
    async with open_bot() as h:
        uid = USER + 6
        admin = app_settings().admin_id
        slug100 = "s" + "a" * 99
        assert len(slug100) == 100
        added = await send_text(h, admin, f"/admin_preset_add {slug100} Long Slug {{}}")
        assert added, "@S84: админ не смог добавить пресет со slug 100 символов"

        seen: list[tuple[str, str]] = []
        await send_text(h, uid, "/start")
        seen += keyboard(h)  # шаг lang
        await press(h, "dlg:lang:ru", user_id=uid)
        seen += keyboard(h)  # шаг preset (включая пресет со slug 100 символов)
        long_buttons = [data for label, data in keyboard(h) if label == "Long Slug"]
        assert long_buttons, f"@S84: пресет со slug 100 символов не показан: {keyboard(h)!r}"
        await press(h, long_buttons[0], user_id=uid)
        seen += keyboard(h)
        await press(h, "dlg:preset:done", user_id=uid)
        seen += keyboard(h)  # шаг format
        await press(h, "dlg:format:any", user_id=uid)

        pages = 0
        while True:  # шаг tz: все страницы городов
            buttons = keyboard(h)
            seen += buttons
            pages += 1
            assert pages <= 10, f"@S84: пагинация городов не завершается: {buttons!r}"
            next_page = [data for label, data in buttons if label == "➡️"]
            if not next_page:
                break
            await press(h, next_page[0], user_id=uid)
        await press(h, "dlg:tz:msk", user_id=uid)
        await send_text(h, uid, "09:30")  # шаг time — текстовый, без клавиатуры
        seen += keyboard(h)  # шаг size

        assert seen, "@S84: ни одной кнопки не наблюдалось"
        for expected in (LANG_BUTTONS, PRESET_BUTTONS_RU, FORMAT_BUTTONS_RU, SIZE_BUTTONS):
            missing = set(expected.items()) - set(seen)
            assert not missing, f"@S84: кнопки brief §6.1 не показаны: {missing!r}"
        for label, data in seen:
            assert CALLBACK_RE.match(data), (
                f"@S84: callback_data кнопки {label!r} не по грамматике: {data!r}"
            )
            assert data.isascii(), f"@S84: callback_data кнопки {label!r} не ASCII: {data!r}"
            assert len(data.encode("ascii")) <= 64, (
                f"@S84: callback_data кнопки {label!r} длиннее 64 байт: {data!r}"
            )

        state = await user_state(h, uid)
        assert slug100 in state.profile["presets"], (
            f"@S84: пресет со slug 100 символов не выбран/не сохранён: {state.profile!r}"
        )


# --- S85 (@R59 @R7): экранирование имени пресета ----------------------------


async def test_s85_hostile_preset_name_is_escaped() -> None:
    """@S85: вредоносное имя пресета экранировано — HTML-инъекция невозможна."""
    hostile = '<script>alert(1)</script> <a href="evil">X</a> & "quotes"'
    async with open_bot() as h:
        admin = app_settings().admin_id
        added = await send_text(h, admin, f"/admin_preset_add evil-1 {hostile} {{}}")
        assert added, "@S85: админ не смог добавить пресет с вредоносным именем"

        uid = USER + 7
        await send_text(h, uid, "/start")
        replies = await press(h, "dlg:lang:ru", user_id=uid)  # шаг preset
        text = "\n".join(replies)
        assert "<script>" not in text and "<a href" not in text, (
            f"@S85: имя пресета не экранировано в тексте сообщения: {text!r}"
        )
        assert "&lt;script&gt;" in text, f"@S85: имя пресета не показано экранированным: {text!r}"
        assert not tag_violations(text), f"@S85: сообщение не валидный HTML: {text!r}"
        assert_no_raw_markup(text, "@S85: текст сообщения над кнопками")

        buttons = keyboard(h)  # текст кнопки Telegram — plain text (brief §6.1)
        evil_buttons = [data for label, data in buttons if label == hostile]
        assert evil_buttons, f"@S85: кнопка пресета с вредоносным именем не показана: {buttons!r}"

        await press(h, evil_buttons[0], user_id=uid)
        replies = await press(h, "dlg:preset:done", user_id=uid)  # + подтверждение сохранения
        text = "\n".join(replies)
        assert "<script>" not in text and "<a href" not in text, (
            f"@S85: имя пресета не экранировано в подтверждении сохранения: {text!r}"
        )
        assert "&lt;script&gt;" in text, (
            f"@S85: имя пресета не показано экранированным в подтверждении: {text!r}"
        )
        assert_no_raw_markup(text, "@S85: подтверждение сохранения")

        display = "\n".join(await send_text(h, uid, "/settings"))  # сводка /settings
        assert_no_raw_markup(display, "@S85: сводка /settings")
        assert not tag_violations(display), f"@S85: сводка не валидный HTML: {display!r}"


# --- S86 (@R60 @R20): язык кнопкой сохраняется и действует ------------------


async def test_s86_language_button_saves_and_applies() -> None:
    """@S86: «English» пишет lang=en в профиль; все ответы — EN; повторный
    /start без кнопки язык не меняет."""
    async with open_bot() as h:
        uid = USER + 8
        replies = await send_text(h, uid, "/start")
        assert GREETING in "\n".join(replies), f"@S86: нет приветствия /start: {replies!r}"

        replies = await press(h, "dlg:lang:en", user_id=uid)
        state = await user_state(h, uid)
        assert state.lang == "en", f"@S86: язык не сохранён как en: {state!r}"
        assert LANG_SAVED["en"] in "\n".join(replies), (
            f"@S86: нет подтверждения {LANG_SAVED['en']!r}: {replies!r}"
        )
        assert PRESET_HEADER["en"] in "\n".join(replies), (
            f"@S86: следующий шаг не на английском: {replies!r}"
        )

        # вежливый отказ EN-пользователю приходит на EN (brief §6.1)
        mark = len(events(h))
        replies = await press(h, "dlg:size:51", user_id=uid)
        trail = events(h)[mark:]
        assert replies == [], f"@S86: подделанный callback изменил сообщения: {replies!r}"
        answers = answers_in(trail)
        assert len(answers) == 1 and trail[0][0] == "answer", (
            f"@S86: нет ровно одного немедленного подтверждения: {trail!r}"
        )
        text, show_alert = answer_of(answers[0][1])
        assert text == OUTDATED["en"], f"@S86: ожидаем {OUTDATED['en']!r}, получено {text!r}"
        assert show_alert is False, f"@S86: вежливый отказ не toast: {trail!r}"

        # завершение настройки (S1-цепочка кнопками)
        await press(h, "dlg:preset:python-backend", user_id=uid)
        await press(h, "dlg:preset:done", user_id=uid)
        await press(h, "dlg:format:any", user_id=uid)
        await press(h, "dlg:tz:msk", user_id=uid)
        await send_text(h, uid, "09:30")
        replies = await press(h, "dlg:size:10", user_id=uid)
        assert "\n".join(replies), "@S86: завершение онбординга не подтверждено"

        await h.seed_vacancies(
            [make_vacancy(title="Python Developer", salary=None, url="https://hh.ru/vacancy/861")]
        )
        digest = await deliver_texts(h, uid)
        assert digest and "🔥 Job digest" in "\n".join(digest), (
            f"@S86: дайджест не на английском: {digest!r}"
        )
        reply = await send_text(h, uid, "/like 1")
        assert reply == [FEEDBACK_OK["like"][1]], f"@S86: ответ /like не EN: {reply!r}"

        await send_text(h, uid, "/start")  # без нажатия кнопки выбора языка
        state = await user_state(h, uid)
        assert state.lang == "en", f"@S86: повторный /start изменил язык: {state!r}"


# --- S87 (@R61 @R18): переходы и прерывание диалога -------------------------


async def test_s87_step_transitions_and_interruption_keep_saved_settings() -> None:
    """@S87: выбор открывает следующий шаг; прерывание не теряет сохранённое;
    завершение через /settings восстанавливает настройку."""
    async with open_bot() as h:
        uid = USER + 9
        await send_text(h, uid, "/start")
        replies = await press(h, "dlg:lang:ru", user_id=uid)
        assert PRESET_HEADER["ru"] in "\n".join(replies), (
            f"@S87: после языка не открылся выбор пресетов: {replies!r}"
        )
        await press(h, "dlg:preset:python-backend", user_id=uid)
        replies = await press(h, "dlg:preset:done", user_id=uid)
        assert FORMAT_HEADER["ru"] in "\n".join(replies), (
            f"@S87: после «Готово» не открылся формат работы: {replies!r}"
        )

        # прерывание: оставшиеся шаги (tz, time, size) не пройдены
        state = await user_state(h, uid)
        assert state.lang == "ru", f"@S87: язык не сохранён: {state!r}"
        assert state.profile["presets"] == ["python-backend"], (
            f"@S87: пресеты не сохранены: {state.profile!r}"
        )
        assert not state.profile.get("schedule"), (
            f"@S87: расписание заполнено без прохождения шагов: {state.profile!r}"
        )
        check_schedules = load_attr("app.services.scheduler", "check_schedules")
        sender, throttle = FakeSender(), FakeThrottle()
        await check_schedules(
            repo=h.repo,
            sender=sender,
            throttle=throttle,
            now=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        )
        digests = [text for _chat, text in sender.sent if text.startswith("🔥")]
        assert digests == [], f"@S87: без расписания отправлен дайджест: {digests!r}"

        # /settings — завершение оставшихся шагов
        await open_step(h, uid, "format")
        await press(h, "dlg:format:any", user_id=uid)
        await open_step(h, uid, "tz")
        await press(h, "dlg:tz:msk", user_id=uid)
        await open_step(h, uid, "time")
        await send_text(h, uid, "09:30")
        await open_step(h, uid, "size")
        replies = await press(h, "dlg:size:10", user_id=uid)
        assert "\n".join(replies), "@S87: завершение настройки не подтверждено"

        state = await user_state(h, uid)
        assert state.profile["schedule"] == {"local_time": "09:30", "tz": "Europe/Moscow"}, (
            f"@S87: расписание не сохранено: {state.profile!r}"
        )
        await h.seed_vacancies(
            [make_vacancy(title="Python Developer", salary=None, url="https://hh.ru/vacancy/871")]
        )
        assert await deliver_texts(h, uid), "@S87: дайджест по расписанию не формируется"


# --- S88 (@R26 @R62): подделанный callback_data ------------------------------


@pytest.mark.parametrize(
    "forged",
    [
        "dlg:unknown:x",
        "dlg:size:51",
        "dlg:size:-5",
        "dlg:lang:de",
        "dlg:preset:nonexistent",
        "dlg:tz:UTC+99",
        "dlg:<script>alert(1)</script>",
        "not-a-callback",
        "",
    ],
)
async def test_s88_forged_callback_polite_refusal(forged: str) -> None:
    """@S88: подделанный/невалидный callback_data → вежливый отказ, состояние
    не меняется, бот не падает (Examples dialog_callbacks.feature)."""
    async with open_bot() as h:
        uid = USER + 10
        await send_text(h, uid, "/start")
        await press(h, "dlg:lang:ru", user_id=uid)
        before = await user_state(h, uid)

        mark = len(events(h))
        replies = await press(h, forged, user_id=uid)
        trail = events(h)[mark:]
        assert replies == [], f"@S88: callback {forged!r} изменил сообщения: {replies!r}"
        answers = answers_in(trail)
        assert len(answers) == 1 and trail[0][0] == "answer", (
            f"@S88: нет ровно одного немедленного подтверждения для {forged!r}: {trail!r}"
        )
        text, show_alert = answer_of(answers[0][1])
        assert text == OUTDATED["ru"], (
            f"@S88: для {forged!r} ожидаем {OUTDATED['ru']!r}, получено {text!r}"
        )
        assert show_alert is False, f"@S88: вежливый отказ не toast для {forged!r}: {trail!r}"
        assert await user_state(h, uid) == before, (
            f"@S88: состояние изменилось после callback {forged!r}"
        )
        assert await send_text(h, uid, "/settings"), (
            f"@S88: бот перестал отвечать после callback {forged!r}"
        )


# --- S89 (@R61 @R15): пагинация городов + ручной UTC-offset -----------------


async def test_s89_city_pagination_and_manual_offset() -> None:
    """@S89: города постранично (≤10 на странице), все достижимы; ручной
    offset текстом сохраняется как «UTC+3»."""
    async with open_bot() as h:
        uid = USER + 11
        await onboard(h, uid)
        await open_step(h, uid, "tz")

        pages: list[list[str]] = []
        while True:
            buttons = keyboard(h)
            city_labels = [
                label
                for label, data in buttons
                if data.startswith("dlg:tz:")
                and data != "dlg:tz:manual"
                and not data.startswith("dlg:tz:page-")
            ]
            assert 1 <= len(city_labels) <= 10, (
                f"@S89: на странице {len(city_labels)} городов (нужно 1..10): {buttons!r}"
            )
            pages.append(city_labels)
            if len(pages) == 1:
                assert (TZ_MANUAL_LABEL["ru"], "dlg:tz:manual") in buttons, (
                    f"@S89: нет кнопки {TZ_MANUAL_LABEL['ru']!r}: {buttons!r}"
                )
            assert len(pages) <= 10, f"@S89: пагинация не завершается: {buttons!r}"
            next_page = [data for label, data in buttons if label == "➡️"]
            if not next_page:
                break
            replies = await press(h, next_page[0], user_id=uid)
            assert replies, "@S89: следующая страница городов не показана"

        flat = [label for page in pages for label in page]
        assert len(flat) == len(set(flat)), f"@S89: города дублируются между страницами: {pages!r}"
        assert set(flat) == set(CITY_LABELS_RU), (
            f"@S89: не все города списка достижимы: "
            f"нет {set(CITY_LABELS_RU) - set(flat)!r}, лишние {set(flat) - set(CITY_LABELS_RU)!r}"
        )

        replies = await press(h, "dlg:tz:manual", user_id=uid)
        assert TZ_MANUAL_PROMPT["ru"] in "\n".join(replies), (
            f"@S89: нет промпта {TZ_MANUAL_PROMPT['ru']!r}: {replies!r}"
        )
        replies = await send_text(h, uid, "UTC+3")
        assert TZ_SAVED["ru"] in "\n".join(replies), (
            f"@S89: нет подтверждения {TZ_SAVED['ru']!r}: {replies!r}"
        )
        state = await user_state(h, uid)
        assert state.profile["schedule"]["tz"] == "UTC+3", (
            f"@S89: таймзона не сохранена как UTC+3: {state.profile!r}"
        )
