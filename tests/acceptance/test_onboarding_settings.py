"""Acceptance-тесты сценариев S1–S7 — onboarding и настройки пользователя.

Чёрный ящик: BotHarness (api.md §15) — команды ``/start``, ``/settings <шаг>``
и callback-нажатия ``dlg:<step>:<value>`` (api.md §15.1); точные строки ответов
— brief §6.1 (дословно, из fakes/dialog) и decisions.md §4.
Теги рисков сценариев — tests/features/onboarding_settings.feature.

ИТЕРАЦИЯ I-2 (решение владельца 27.10, decisions §8): диалог на инлайн-кнопках.
Кнопками: язык, пресеты (мультивыбор ✅ + «Готово»), формат работы, таймзона
(города/ручной offset), размер дайджеста (5/10/20/50); текстом остаются время
HH:MM, мин. зарплата, стоп-слова, ручной UTC-offset (AC-21..AC-24). Прежний
текстовый ввод «lang:ru», slug-пресета и размера текстом упразднён — тесты
S1/S4/S5/S7 обновлены под кнопочный диалог (ожидаемая переделка, не регрессия).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from dialog import (
    DONE_ONBOARDING,
    FORMAT_HEADER,
    FORMAT_SAVED,
    LANG_SAVED,
    PRESET_HEADER,
    PRESET_SAVED,
    PROMPT_SALARY_RU,
    PROMPT_STOP_RU,
    SIZE_BUTTONS,
    SIZE_HEADER,
    SIZE_SAVED,
    TIME_HEADER_RU,
    TIME_SAVED,
    TZ_HEADER,
    TZ_SAVED,
    keyboard,
    onboard,
    open_step,
    press,
    user_state,
)
from fakes import (
    BAD_SALARY_RU,
    BAD_SIZE_RU,
    BAD_TIME_RU,
    BAD_TZ_RU,
    FEEDBACK_ERROR_EN,
    REMINDER_RU,
    FakeSender,
    FakeThrottle,
    InMemoryRepo,
    make_profile,
    open_bot,
    send_text,
    talk,
)
from support import load_attr

USER_ONBOARDING = 101
USER_SCHEDULE = 102
USER_SETTINGS = 103


# --- S1 (@R18): полная настройка нового пользователя кнопками ---------------


async def test_s01_new_user_full_onboarding_saves_schedule() -> None:
    """@S1: /start → кнопки (язык, пресеты, формат, город, время текстом,
    размер); расписание сохранено, дайджест не сразу (brief §7.8)."""
    async with open_bot() as h:
        uid = USER_ONBOARDING
        replies = await send_text(h, uid, "/start")
        replies += await press(h, "dlg:lang:ru", user_id=uid)
        replies += await press(h, "dlg:preset:python-backend", user_id=uid)
        replies += await press(h, "dlg:preset:done", user_id=uid)
        replies += await press(h, "dlg:format:any", user_id=uid)  # «Не важно»
        replies += await press(h, "dlg:tz:msk", user_id=uid)  # «Москва»
        replies += await send_text(h, uid, "09:30")
        replies += await press(h, "dlg:size:10", user_id=uid)
        onboarding_text = "\n".join(replies)
        assert "🔥" not in onboarding_text, (
            f"@S1: дайджест отправлен сразу после /start (первый выпуск — в ближайшее "
            f"выбранное время, brief §7.8): {onboarding_text!r}"
        )
        for confirmation in (
            LANG_SAVED["ru"],
            PRESET_SAVED["ru"],
            FORMAT_SAVED["ru"],
            TZ_SAVED["ru"],
            TIME_SAVED["ru"],
            SIZE_SAVED["ru"],
            DONE_ONBOARDING["ru"],
        ):
            assert confirmation in onboarding_text, (
                f"@S1: нет подтверждения {confirmation!r}: {onboarding_text!r}"
            )
        for step_prompt in (
            PRESET_HEADER["ru"],
            FORMAT_HEADER["ru"],
            TZ_HEADER["ru"],
            TIME_HEADER_RU,
            SIZE_HEADER["ru"],
        ):
            assert step_prompt in onboarding_text, (
                f"@S1: нет подсказки шага {step_prompt!r}: {onboarding_text!r}"
            )

        display = "\n".join(await send_text(h, uid, "/settings"))
        assert "09:30" in display, f"@S1: время дайджеста не сохранено: {display!r}"
        assert "Europe/Moscow" in display, f"@S1: таймзона не сохранена: {display!r}"
        assert "python-backend" in display, f"@S1: пресет не сохранён: {display!r}"
        assert "Формат работы: —" in display, (
            f"@S1: формат «Не важно» не выведен как «—» в сводке (brief §6.1): {display!r}"
        )

        state = await user_state(h, uid)
        assert state.profile["schedule"] == {"local_time": "09:30", "tz": "Europe/Moscow"}, (
            f"@S1: расписание не сохранено: {state.profile!r}"
        )
        assert state.profile["presets"] == ["python-backend"], (
            f"@S1: подписка не сохранена: {state.profile!r}"
        )
        assert state.profile["digest_size"] == 10, f"@S1: размер не сохранён: {state.profile!r}"


# --- S2 (@R18): без расписания — ни дайджеста, одно напоминание ---------------


async def test_s02_no_schedule_no_digest_single_reminder() -> None:
    """@S2: без расписания дайджест не отправляется; напоминание — ровно один раз."""
    check_schedules = load_attr("app.services.scheduler", "check_schedules")
    repo = InMemoryRepo()
    profile = make_profile(schedule=None)
    await repo.upsert_user(USER_SCHEDULE, lang="ru", profile=profile)
    sender, throttle = FakeSender(), FakeThrottle()

    await check_schedules(repo=repo, sender=sender, throttle=throttle, now=_utc_noon(1))
    await check_schedules(repo=repo, sender=sender, throttle=throttle, now=_utc_noon(2))

    digests = [text for _chat, text in sender.sent if text.startswith("🔥")]
    assert digests == [], f"@S2: без расписания отправлен дайджест: {digests!r}"
    reminders = [text for _chat, text in sender.sent if text == REMINDER_RU]
    assert len(reminders) == 1, (
        f"@S2: напоминание «{REMINDER_RU}» отправлено {len(reminders)} раз "
        f"(ожидалось ровно 1, decisions §5.20): {sender.sent!r}"
    )


# --- S3 (@R15): невалидное время ---------------------------------------------


@pytest.mark.parametrize("bad", ["25:00", "9-30", "09", "abc", ""])
async def test_s03_invalid_digest_time_rejected(bad: str) -> None:
    """@S3: мусорное время → точная ошибка, расписание не меняется; 09:30 принимается."""
    replies = await talk(
        USER_SETTINGS, "/settings", "/settings time", bad, "/settings", "09:30", "/settings"
    )
    assert replies[2] == [BAD_TIME_RU], f"@S3: ожидаем {BAD_TIME_RU!r}, получено {replies[2]!r}"
    assert TIME_HEADER_RU in "\n".join(replies[1]), (
        f"@S3: шаг времени открыт не по шаблону brief §6.1 {TIME_HEADER_RU!r}: {replies[1]!r}"
    )
    assert replies[3] == replies[0], (
        f"@S3: расписание изменилось после невалидного времени {bad!r}: "
        f"было {replies[0]!r} стало {replies[3]!r}"
    )
    assert "09:30" in "\n".join(replies[5]), (
        f"@S3: валидное время 09:30 не применилось: {replies[5]!r}"
    )


# --- S4 (@R15): невалидный ручной UTC-offset ---------------------------------


# I-2: шаг таймзоны кнопочный; текстовым остаётся только ручной UTC-offset
# (кнопка «Указать UTC offset вручную»). Смысл сценария сохранён: невалидный
# текстовый ввод отклоняется, настройка восстанавливается.
@pytest.mark.parametrize("bad", ["Mars/Olymp", "UTC+99", "UTC-х", "25:00", ""])
async def test_s04_invalid_timezone_rejected(bad: str) -> None:
    """@S4: мусорный ручной offset → точная ошибка, tz не меняется; город
    кнопкой «Москва» сохраняет Europe/Moscow."""
    async with open_bot() as h:
        uid = USER_SETTINGS + 1
        await onboard(h, uid)
        await open_step(h, uid, "tz")
        replies = await press(h, "dlg:tz:manual", user_id=uid)  # «Указать UTC offset вручную»
        assert replies, "@S4: шаг ручного offset не открылся"
        before = await user_state(h, uid)

        replies = await send_text(h, uid, bad)
        assert replies == [BAD_TZ_RU], f"@S4: ожидаем {BAD_TZ_RU!r}, получено {replies!r}"
        assert await user_state(h, uid) == before, (
            f"@S4: таймзона изменилась после невалидного ввода {bad!r}"
        )

        replies = await press(h, "dlg:tz:msk", user_id=uid)  # кнопка города «Москва»
        assert TZ_SAVED["ru"] in "\n".join(replies), f"@S4: таймзона не сохранена: {replies!r}"
        state = await user_state(h, uid)
        assert state.profile["schedule"]["tz"] == "Europe/Moscow", (
            f"@S4: валидная таймзона не применилась: {state.profile!r}"
        )


# --- S5 (@R27): размер дайджеста кнопками 5/10/20/50 -------------------------


# СУТЬ ИЗМЕНИЛАСЬ (I-2, decisions §8.4): размер выбирается кнопками из набора
# 5/10/20/50; текстового ввода в UI нет. Домен 1..50 остаётся контрактом
# валидации (Profile.digest_size); значения вне набора достижимы только
# подделанным callback — см. S88. Строка error.bad_size удаляется из словаря.
@pytest.mark.parametrize("value", ["5", "10", "20", "50"])
async def test_s05_digest_size_chosen_by_button(value: str) -> None:
    """@S5: кнопка размера сохраняет значение из набора 5/10/20/50."""
    async with open_bot() as h:
        uid = USER_SETTINGS + 2
        await onboard(h, uid)
        await open_step(h, uid, "size")
        assert dict(keyboard(h)) == SIZE_BUTTONS, (
            f"@S5: клавиатура размера — не кнопки 5/10/20/50 (brief §6.1): {keyboard(h)!r}"
        )
        replies = await press(h, f"dlg:size:{value}", user_id=uid)
        text = "\n".join(replies)
        assert SIZE_SAVED["ru"] in text, f"@S5: ожидаем {SIZE_SAVED['ru']!r}, получено {text!r}"
        assert BAD_SIZE_RU not in text, f"@S5: валидный размер {value} отклонён: {text!r}"
        state = await user_state(h, uid)
        assert state.profile["digest_size"] == int(value), (
            f"@S5: размер {value} не сохранён: {state.profile!r}"
        )


# --- S6 (@R15, @R22): невалидная мин. зарплата --------------------------------


@pytest.mark.parametrize("bad", ["-100", "сто тысяч", "12.5", ""])
async def test_s06_invalid_min_salary_rejected(bad: str) -> None:
    """@S6: мусорная мин. зарплата → точная ошибка; 150000 принимается."""
    replies = await talk(
        USER_SETTINGS + 3,
        "/settings",
        "/settings salary",
        bad,
        "/settings",
        "150000",
        "/settings",
    )
    assert replies[2] == [BAD_SALARY_RU], f"@S6: ожидаем {BAD_SALARY_RU!r}, получено {replies[2]!r}"
    assert PROMPT_SALARY_RU in "\n".join(replies[1]), (
        f"@S6: шаг зарплаты открыт не по шаблону brief §6.1 {PROMPT_SALARY_RU!r}: {replies[1]!r}"
    )
    assert replies[3] == replies[0], (
        f"@S6: мин. зарплата изменилась после невалидного ввода {bad!r}"
    )
    assert "150000" in "\n".join(replies[5]), (
        f"@S6: валидная зарплата 150000 не применилась: {replies[5]!r}"
    )


# --- S7 (@R20, @R15): смена настроек через /settings --------------------------


# I-2: пресеты — мультивыбором (✅ + «Готово»), формат/размер/язык — кнопками;
# стоп-слова и время — текстом. Смысл сценария сохранён: смена всех настроек.
async def test_s07_settings_change_presets_stops_and_language() -> None:
    """@S7: смена пресетов/стоп-слова/формата/размера/времени/языка через /settings."""
    async with open_bot() as h:
        uid = USER_SETTINGS + 4
        await onboard(h, uid)  # RU, python-backend, 09:30, Europe/Moscow

        await open_step(h, uid, "preset")
        await press(h, "dlg:preset:devops-sre", user_id=uid)
        await press(h, "dlg:preset:done", user_id=uid)
        stop_prompt = await open_step(h, uid, "stop")
        assert PROMPT_STOP_RU in "\n".join(stop_prompt), (
            f"@S7: шаг стоп-слов открыт не по шаблону brief §6.1 "
            f"{PROMPT_STOP_RU!r}: {stop_prompt!r}"
        )
        await send_text(h, uid, "junior")
        await open_step(h, uid, "format")
        await press(h, "dlg:format:remote", user_id=uid)  # «Удалёнка»
        await open_step(h, uid, "size")
        await press(h, "dlg:size:20", user_id=uid)
        await open_step(h, uid, "time")
        await send_text(h, uid, "10:15")
        await open_step(h, uid, "lang")
        await press(h, "dlg:lang:en", user_id=uid)  # «English»

        state = await user_state(h, uid)
        assert set(state.profile["presets"]) == {"python-backend", "devops-sre"}, (
            f"@S7: подписка не включает оба пресета: {state.profile!r}"
        )
        assert "junior" in state.profile["stop_words"], (
            f"@S7: стоп-слово не сохранено: {state.profile!r}"
        )
        assert state.profile["work_format"] == "remote", (
            f"@S7: формат работы не сохранён: {state.profile!r}"
        )
        assert state.profile["digest_size"] == 20, f"@S7: размер не сохранён: {state.profile!r}"
        assert state.profile["schedule"] == {"local_time": "10:15", "tz": "Europe/Moscow"}, (
            f"@S7: расписание не обновлено на 10:15: {state.profile!r}"
        )

        display = "\n".join(await send_text(h, uid, "/settings"))
        assert "Удалёнка" in display, (
            f"@S7: формат работы не выводится меткой «Удалёнка» в /settings: {display!r}"
        )
        reply = await send_text(h, uid, "/like 1")
        assert reply == [FEEDBACK_ERROR_EN], (
            f"@S7: переключение на EN не применилось к ответам бота: {reply!r}"
        )


def _utc_noon(day: int) -> datetime:
    """Удобное «сейчас» для check_schedules (дата не попадает в слот 09:30)."""
    return datetime(2026, 3, day, 12, 0, tzinfo=UTC)
