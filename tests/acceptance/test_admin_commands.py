"""Acceptance-тесты сценариев S51–S55 — админ-контур.

Чёрный ящик: бот через BotHarness (api.md §15); имена команд — decisions §5.19,
доступ — только ADMIN_ID (S55: не-админу молчаливый игнор, decisions §5.19).

Договорённости (docs/qa/acceptance-map.md):
- BotHarness не ходит в сеть: его HTTP-клиент — тестовый (фикстуры tests/data);
  подмена ответов — методом ``set_client(client)`` (нужен S54);
- формат ответов админ-команд, кроме строк brief §6.1, — структурный (по составу
  полей); команды парсятся так: ``/admin_preset_add <slug> <name...> <json>``,
  имя может содержать пробелы, JSON — последний аргумент (строка feature S52).
"""

from __future__ import annotations

import re

import pytest
from dialog import keyboard, onboard, open_step, press
from fakes import (
    BROKEN_MARKUP_HTML,
    FakeClient,
    FakeResponse,
    deliver_texts,
    habr_list_page,
    make_vacancy,
    open_bot,
    send_text,
)
from support import app_settings

NON_ADMIN = 2000

ADMIN_COMMANDS = (
    "/admin",
    "/admin_preset_list",
    "/admin_preset_add probe Probe {}",
    "/admin_preset_edit probe {}",
    "/admin_preset_del probe",
    "/admin_stats",
    "/admin_collect",
    "/admin_health",
)


def _admin_id() -> int:
    """Доступ — только ADMIN_ID (api.md §15); значение из настроек (env)."""
    return app_settings().admin_id


def _line_with(text: str, *words: str) -> str:
    for line in text.splitlines():
        lowered = line.lower()
        if all(word.lower() in lowered for word in words):
            return line
    raise AssertionError(f"в ответе нет строки со словами {words}: {text!r}")


def _numbers(line: str) -> list[int]:
    return [int(token) for token in re.findall(r"\d+", line)]


# --- S51 (@R1 @R40): ручной сбор обновляет кэш и отчитывается ---------------


async def test_s51_admin_collect_runs_and_reports_counts() -> None:
    """@S51: /admin_collect — немедленный сбор, ответ с числом добавленных по источникам."""
    async with open_bot() as h:
        reply = await send_text(h, _admin_id(), "/admin_collect")
        text = "\n".join(reply)
        assert reply, "@S51: /admin_collect не вернул ответа"
        for source in ("hh.ru", "Habr Career"):
            line = _line_with(text, source)
            assert _numbers(line), f"@S51: нет числа добавленных для {source}: {line!r}"


# --- S52 (@R21 @R27): CRUD пресетов -----------------------------------------


async def test_s52_admin_preset_crud() -> None:
    """@S52: add → list, edit → фильтр обновлён, del → исчез; подписки не ломают дайджест."""
    async with open_bot() as h:
        admin = _admin_id()
        await onboard(h, admin)  # I-2: онбординг кнопками (text «lang:ru» упразднён)

        added = await send_text(
            h, admin, '/admin_preset_add rust-backend Rust Backend {"must": ["rust"]}'
        )
        assert added, "@S52: /admin_preset_add не ответил"
        listing = "\n".join(await send_text(h, admin, "/admin_preset_list"))
        assert "rust-backend" in listing, f"@S52: пресет не появился в списке: {listing!r}"
        assert "Rust Backend" in listing, f"@S52: имя пресета не показано: {listing!r}"

        edited = await send_text(
            h, admin, '/admin_preset_edit rust-backend {"must": ["rust", "axum"]}'
        )
        assert edited, "@S52: /admin_preset_edit не ответил"
        assert "rust-backend" in "\n".join(await send_text(h, admin, "/admin_preset_list")), (
            "@S52: пресет пропал после редактирования"
        )

        # пользователь подписан на редактируемый пресет (S7-протокол настроек,
        # I-2: пресеты — мультивыбором кнопками, подписка сохраняется по «Готово»)
        await onboard(h, NON_ADMIN)
        await open_step(h, NON_ADMIN, "preset")
        rust_buttons = [data for label, data in keyboard(h) if label == "Rust Backend"]
        assert rust_buttons, f"@S52: кнопка пресета rust-backend не показана: {keyboard(h)!r}"
        await press(h, rust_buttons[0], user_id=NON_ADMIN)
        await press(h, "dlg:preset:done", user_id=NON_ADMIN)

        deleted = await send_text(h, admin, "/admin_preset_del rust-backend")
        assert deleted, "@S52: /admin_preset_del не ответил"
        listing = "\n".join(await send_text(h, admin, "/admin_preset_list"))
        assert "rust-backend" not in listing, (
            f"@S52: удалённый пресет остался в списке: {listing!r}"
        )

        # подписка на удалённый пресет не ломает формирование дайджеста
        digest = await deliver_texts(h, NON_ADMIN)
        assert isinstance(digest, list), f"@S52: дайджест после удаления пресета сломан: {digest!r}"


# --- S53 (@R5 @R17): статистика — пользователи и клики ----------------------


async def test_s53_admin_stats_users_and_feedback_counters() -> None:
    """@S53: /admin_stats содержит число пользователей и счётчики like/dislike/bookmark."""
    async with open_bot() as h:
        actions = [("like", 201), ("dislike", 202), ("bookmark", 203)]
        await h.seed_vacancies(
            [
                make_vacancy(
                    title=f"Python Developer {n}",
                    salary=None,
                    url=f"https://hh.ru/vacancy/{600 + n}",
                )
                for n in range(1, 4)
            ]
        )
        for action, uid in actions:
            await onboard(h, uid)  # I-2: онбординг кнопками
            delivered = await deliver_texts(h, uid)
            assert delivered is not None, f"@S53: дайджест пользователю {uid} не доставлен"
            await send_text(h, uid, f"/{action} 1")

        stats = "\n".join(await send_text(h, _admin_id(), "/admin_stats"))
        if "пользовател" in stats:
            users_line = _line_with(stats, "пользовател")
        else:
            users_line = _line_with(stats, "user")
        assert _numbers(users_line), f"@S53: нет числа пользователей: {users_line!r}"
        for action, _uid in actions:
            line = _line_with(stats, action)
            assert _numbers(line), f"@S53: нет счётчика {action}: {line!r}"


# --- S54 (@R1 @R2): здоровье парсеров ---------------------------------------


async def test_s54_admin_health_shows_source_statuses() -> None:
    """@S54: /admin_health — статус последнего сбора по источникам и время (UTC)."""
    async with open_bot() as h:
        admin = _admin_id()
        h.set_client(
            FakeClient.for_sources(
                hh=FakeResponse(text=BROKEN_MARKUP_HTML),
                habr=FakeResponse(text=habr_list_page()),
            )
        )
        await send_text(h, admin, "/admin_collect")
        text = "\n".join(await send_text(h, admin, "/admin_health"))
        hh_line = _line_with(text, "hh.ru")
        assert "ошибка разбора разметки" in hh_line, f"@S54: статус hh.ru: {hh_line!r}"
        habr_line = _line_with(text, "Habr Career")
        assert "ошибка разбора разметки" not in habr_line, (
            f"@S54: статус Habr Career: {habr_line!r}"
        )
        assert "UTC" in text, f"@S54: время последнего сбора не в UTC: {text!r}"


# --- S55 (@R17): админ-команды недоступны не-администраторам -----------------


@pytest.mark.parametrize("command", ADMIN_COMMANDS)
async def test_s55_admin_commands_silent_for_non_admin(command: str) -> None:
    """@S55: не-админ получает молчаливый игнор; данные статистики/пресетов не меняются."""
    async with open_bot() as h:
        admin = _admin_id()
        before = "\n".join(await send_text(h, admin, "/admin_stats"))
        replies = await send_text(h, NON_ADMIN + 1, command)
        assert replies == [], (
            f"@S55: не-админ получил ответ на {command!r}: {replies!r} — "
            "раскрыто существование админ-команд"
        )
        after = "\n".join(await send_text(h, admin, "/admin_stats"))
        assert after == before, f"@S55: {command!r} изменила данные: {before!r} → {after!r}"
