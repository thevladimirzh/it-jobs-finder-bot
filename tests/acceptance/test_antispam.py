"""Acceptance-тесты сценариев S67–S71 — антиспам при открытой регистрации.

Чёрный ящик: бот через BotHarness (api.md §15). AC-16/decisions §5.18: лимит —
30 действий в скользящее окно 60 секунд, превышение → тихий мьют на 10 минут
(игнор без ответа и без сообщения о мьюте); счётчики в памяти процесса (R33).

Договорённость (docs/qa/acceptance-map.md): антиспам берёт время через
``time.monotonic()``/``time.time()``, поэтому S69 управляет временем их подменой.
"""

from __future__ import annotations

import time

from dialog import ONBOARDING_ACTION_COUNT, onboard, open_step, press
from fakes import (
    FEEDBACK_OK,
    deliver_texts,
    make_vacancy,
    open_bot,
    send_text,
)

USER = 1201
SPAM_COMMAND = "/settings"  # нейтральное действие: ответ наблюдаем, эффектов нет


async def _spam(harness, user_id: int, count: int) -> list[list[str]]:
    return [await send_text(harness, user_id, SPAM_COMMAND) for _ in range(count)]


# --- S67 (@R14): превышение лимита → тихий мьют на 10 минут ------------------


async def test_s67_over_limit_actions_muted_silently() -> None:
    """@S67: 30 действий обработаны, 31-е и дальше — без ответа и без упоминания мьюта."""
    async with open_bot() as h:
        first_batch = await _spam(h, USER, 30)
        assert all(replies for replies in first_batch), (
            f"@S67: легитимные действия в пределах лимита не обработаны: {first_batch!r}"
        )
        muted_batch = await _spam(h, USER, 6)
        assert all(replies == [] for replies in muted_batch), (
            f"@S67: после превышения лимита есть ответы (в т.ч. возможный «мьют»): {muted_batch!r}"
        )


# --- S68 (@R14): легитимный сценарий не попадает под мьют --------------------


async def test_s68_legitimate_flow_below_limit() -> None:
    """@S68: онбординг + настройки + 3 команды обратной связи < 30 действий/мин."""
    async with open_bot() as h:
        # I-2 (decisions §8): онбординг и пресеты — кнопками (текстовый ввод
        # «lang:ru»/slug-пресета упразднён); стоп-слова — текстом.
        await onboard(h, USER + 1)
        replies = [
            await open_step(h, USER + 1, "preset"),
            await press(h, "dlg:preset:devops-sre", user_id=USER + 1),
            await press(h, "dlg:preset:done", user_id=USER + 1),
            await open_step(h, USER + 1, "stop"),
            await send_text(h, USER + 1, "junior"),
        ]
        assert all(replies), f"@S68: легитимные действия не обработаны: {replies!r}"
        await h.seed_vacancies(
            [make_vacancy(title="Python Developer", salary=None, url="https://hh.ru/vacancy/681")]
        )
        assert await deliver_texts(h, USER + 1), "@S68: дайджест не доставлен"
        feedback = [
            await send_text(h, USER + 1, "/like 1"),
            await send_text(h, USER + 1, "/dislike 1"),
        ]
        feedback.append(await send_text(h, USER + 1, "/bookmark 1"))

        # 8 действий онбординга + 5 настроек + 1 доставка + 3 обратной связи
        actions = ONBOARDING_ACTION_COUNT + 5 + 1 + 3
        assert actions < 30, f"@S68: легитимный сценарий внезапно ≥ лимита: {actions}"
        assert feedback == [
            [FEEDBACK_OK["like"][0]],
            [FEEDBACK_OK["dislike"][0]],
            [FEEDBACK_OK["bookmark"][0]],
        ], f"@S68: команды обратной связи не обработаны: {feedback!r}"


# --- S69 (@R33 @R14): мьют истекает через 10 минут ---------------------------


async def test_s69_mute_expires_after_ten_minutes(monkeypatch) -> None:
    """@S69: через 10 минут действия снова обрабатываются (ответ «👍 Учтено»)."""
    base = time.monotonic()
    offset = {"seconds": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: base + offset["seconds"])
    monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0 + offset["seconds"])

    async with open_bot() as h:
        await onboard(h, USER + 2)  # I-2: онбординг кнопками
        await h.seed_vacancies(
            [
                make_vacancy(
                    title=f"Python Developer {n}",
                    salary=None,
                    url=f"https://hh.ru/vacancy/{690 + n}",
                )
                for n in (1, 2, 3)
            ]
        )
        assert await deliver_texts(h, USER + 2), "@S69: дайджест не доставлен"
        muted_batch = await _spam(h, USER + 2, 31)
        assert muted_batch[-1] == [], f"@S69: 31-е действие не замьючено: {muted_batch[-1]!r}"

        offset["seconds"] = 600.0  # +10 минут (мьют истёк)
        reply = await send_text(h, USER + 2, "/like 1")
        assert reply == [FEEDBACK_OK["like"][0]], (
            f"@S69: после мьюта действие не обработано: {reply!r}"
        )


# --- S70 (@R17): злоупотребление при открытой регистрации гасится лимитами ----


async def test_s70_mass_abuse_does_not_degrade_legit_users() -> None:
    """@S70: поток действий злоумышленника отбрасывается; легитимный получает дайджест."""
    async with open_bot() as h:
        attacker, legit = 1301, 1302
        await onboard(h, legit)  # I-2: онбординг кнопками
        await h.seed_vacancies(
            [make_vacancy(title="Python Developer", salary=None, url="https://hh.ru/vacancy/701")]
        )
        assert await deliver_texts(h, legit), "@S70: дайджест легитимному не доставлен"

        abuse = await _spam(h, attacker, 40)
        processed = sum(1 for replies in abuse if replies)
        assert processed <= 30, f"@S70: обработано {processed} действий злоумышленника (лимит 30)"
        assert abuse[-1] == [], f"@S70: хвост потока не отброшен: {abuse[-1]!r}"

        reply = await send_text(h, legit, "/like 1")
        assert reply == [FEEDBACK_OK["like"][0]], (
            f"@S70: легитимный пользователь деградировал из-за чужого флуда: {reply!r}"
        )


# --- S71 (@R33): рестарт сбрасывает антиспам-состояние -----------------------


async def test_s71_restart_resets_mute_state() -> None:
    """@S71: после рестарта процесса мьют не сохраняется (ограничение R33 принято)."""
    async with open_bot() as h:
        muted = await _spam(h, USER + 3, 31)
        assert muted[-1] == [], f"@S71: пользователь не замьючен до рестарта: {muted[-1]!r}"

    # «рестарт»: новый процесс бота — состояние в памяти потеряно
    async with open_bot() as h:
        reply = await send_text(h, USER + 3, "/like 1")
        assert reply, f"@S71: мьют пережил рестарт (действие не обработано): {reply!r}"
