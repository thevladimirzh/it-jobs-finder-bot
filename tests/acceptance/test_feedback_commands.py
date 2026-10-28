"""Acceptance-тесты сценариев S45–S50 — обратная связь командами.

Чёрный ящик: бот через BotHarness (api.md §15, threat-model §5.8). Решение
владельца Q1 (27.10): inline-кнопок нет, обратная связь — команды
``/like|/dislike|/bookmark <n>`` по номеру карточки последнего дайджеста;
точные строки-ответы — brief §6.1/decisions §1 (fakes.FEEDBACK_*).

Договорённости (docs/qa/acceptance-map.md): BotHarness расширяется методами
``seed_vacancies`` (положить вакансии в кэш бота) и ``deliver_digest``
(доставить очередной дайджест пользователю) — без них сценарии «получил
дайджест» невоспроизводимы минимальным API ``send/sent``.
"""

from __future__ import annotations

import re

import pytest
from dialog import onboard
from fakes import (
    FEEDBACK_ERROR_RU,
    FEEDBACK_OK,
    deliver_texts,
    make_vacancy,
    open_bot,
    send_text,
)
from support import app_settings

USER = 901

BAD_NUMBERS = ["/like", "/like abc", "/like 0", "/like -1", "/like 4", "/like 999", "/bookmark 0"]


def _vacancies(count: int = 3, company_size: int = 40) -> list:
    return [
        make_vacancy(
            title=f"Python Developer {n}",
            company="C" * company_size,
            salary=None,
            url=f"https://hh.ru/vacancy/{500 + n}",
        )
        for n in range(1, count + 1)
    ]


async def _onboard(harness, user_id: int) -> None:
    # I-2 (decisions §8): онбординг кнопками (lang:ru и slug-пресета текстом
    # упразднены) — замена текстового setup I-1, ожидаемая переделка.
    await onboard(harness, user_id)


async def _prepare(harness, user_id: int, count: int = 3, company_size: int = 40) -> list[str]:
    """Настройка пользователя (S1-протокол) + дайджест из count карточек."""
    await _onboard(harness, user_id)
    await harness.seed_vacancies(_vacancies(count, company_size))
    return await deliver_texts(harness, user_id)


def _counter(stats_text: str, action: str) -> int:
    """Счётчик действия из текста /admin_stats (строка с меткой действия)."""
    pattern = re.compile(rf"\b{re.escape(action)}\b.*?(\d+)|(\d+).*?\b{re.escape(action)}\b")
    for line in stats_text.splitlines():
        match = pattern.search(line)
        if match:
            return int(match.group(1) or match.group(2))
    raise AssertionError(f"в /admin_stats нет строки действия {action!r}: {stats_text!r}")


async def _stats(harness) -> str:
    admin_id = app_settings().admin_id  # /admin_stats доступен только ADMIN_ID (api.md §15)
    replies = await send_text(harness, admin_id, "/admin_stats")
    assert replies, "/admin_stats не вернул ответа"
    return "\n".join(replies)


# --- S45 (@R5): /like <n> пишет статистику и отвечает «👍 Учтено» ------------


async def test_s45_like_command_replies_and_records_stat() -> None:
    """@S45: /like 2 → «👍 Учтено»; статистика (пользователь, вакансия 2, like)."""
    async with open_bot() as h:
        delivered = await _prepare(h, USER)
        assert delivered, "@S45: дайджест из 3 карточек не доставлен"
        before = await _stats(h)
        reply = await send_text(h, USER, "/like 2")
        assert reply == [FEEDBACK_OK["like"][0]], f"@S45: ответ {reply!r}"
        after = await _stats(h)
        assert _counter(after, "like") == _counter(before, "like") + 1, (
            f"@S45: статистика like не выросла: {before!r} → {after!r}"
        )


# --- S46 (@R5): /dislike и /bookmark — точные строки и статистика ------------


@pytest.mark.parametrize(
    ("command", "action", "n"),
    [("/dislike 1", "dislike", 1), ("/bookmark 3", "bookmark", 3)],
)
async def test_s46_dislike_and_bookmark_verbatim(command: str, action: str, n: int) -> None:
    """@S46: точные строки-ответы и запись статистики по карточке <n>."""
    async with open_bot() as h:
        delivered = await _prepare(h, USER + 10)
        assert delivered, f"@S46: дайджест не доставлен ({command})"
        before = await _stats(h)
        reply = await send_text(h, USER + 10, command)
        assert reply == [FEEDBACK_OK[action][0]], f"@S46: ответ {command!r}: {reply!r}"
        after = await _stats(h)
        assert _counter(after, action) == _counter(before, action) + 1, (
            f"@S46: статистика {action} не выросла (карточка {n}): {before!r} → {after!r}"
        )


# --- S47 (@R26 @R15): неверный номер — точная ошибка, без статистики --------


@pytest.mark.parametrize("command", BAD_NUMBERS)
async def test_s47_invalid_number_verbatim_error_no_stat(command: str) -> None:
    """@S47: неверный/отсутствующий n → точная ошибка (decisions §1), записей нет."""
    async with open_bot() as h:
        delivered = await _prepare(h, USER + 20)
        assert delivered, f"@S47: дайджест не доставлен ({command})"
        before = await _stats(h)
        reply = await send_text(h, USER + 20, command)
        assert reply == [FEEDBACK_ERROR_RU], f"@S47: ответ {command!r}: {reply!r}"
        after = await _stats(h)
        assert after == before, (
            f"@S47: на {command!r} появилась запись в статистике: {before!r} → {after!r}"
        )


# --- S48 (@R5): статистика не влияет на выдачу ------------------------------


async def test_s48_feedback_does_not_affect_selection() -> None:
    """@S48: like/dislike/bookmark не меняют порядок и состав следующего выпуска."""
    async with open_bot() as h:
        await _onboard(h, USER + 30)
        await _onboard(h, USER + 31)
        await h.seed_vacancies(_vacancies(3))
        assert await deliver_texts(h, USER + 30), "@S48: первый выпуск контрольному не доставлен"
        assert await deliver_texts(h, USER + 31), "@S48: первый выпуск не доставлен"
        await send_text(h, USER + 30, "/like 1")
        await send_text(h, USER + 30, "/dislike 2")
        controlled = await deliver_texts(h, USER + 30)
        control = await deliver_texts(h, USER + 31)
        assert controlled == control, (
            f"@S48: обратная связь изменила выдачу: {controlled!r} != {control!r}"
        )


# --- S49 (@R26 @R5): повтор действия идемпотентен (upsert) ------------------


async def test_s49_repeated_action_overwrites_previous() -> None:
    """@S49: повтор по той же карточке — одна запись, последнее действие побеждает."""
    async with open_bot() as h:
        await _prepare(h, USER + 40)
        await send_text(h, USER + 40, "/like 1")
        reply = await send_text(h, USER + 40, "/dislike 1")
        assert reply == [FEEDBACK_OK["dislike"][0]], f"@S49: ответ {reply!r}"
        stats = await _stats(h)
        assert _counter(stats, "dislike") == 1, f"@S49: dislike != 1: {stats!r}"
        assert _counter(stats, "like") == 0, (
            f"@S49: после перезаписи осталась запись like (должна остаться одна, dislike): "
            f"{stats!r}"
        )


# --- S50 (@R5 @R4): сквозные номера после разбивки на части -----------------


async def test_s50_numbering_works_across_digest_parts() -> None:
    """@S50: /like 7 работает для карточки из второй части (нумерация сквозная)."""
    async with open_bot() as h:
        parts = await _prepare(h, USER + 50, count=8, company_size=650)
        assert len(parts) >= 2, f"@S50: дайджест из 8 больших карточек не разбит: {parts!r}"
        numbers_in_part = [
            {int(match.group(1)) for match in re.finditer(r"(?m)^(\d+)\. ", part)} for part in parts
        ]
        assert 7 in numbers_in_part[-1], (
            f"@S50: карточка 7 не в последней части: номера по частям {numbers_in_part}"
        )
        reply = await send_text(h, USER + 50, "/like 7")
        assert reply == [FEEDBACK_OK["like"][0]], f"@S50: ответ {reply!r}"
        stats = await _stats(h)
        assert _counter(stats, "like") == 1, f"@S50: статистика не по карточке 7: {stats!r}"
