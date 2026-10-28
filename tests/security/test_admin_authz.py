"""SEC-07 — обход авторизации админ-команд (в т.ч. id-type-confusion int/str).

Угроза SEC-07 (threat-model §3): каждый админ-вход — `/admin`, CRUD пресетов,
`/admin_stats`, `/admin_collect`, `/admin_health` — отклоняется (молчаливый игнор,
decisions §5.19) для всех, кто не равен ADMIN_ID строго как int. Контракт:
docs/spec/api.md §15, сценарий S55 tests/features/admin_commands.feature.

Тестовый вход — BotHarness (threat-model §5.8); тесты красные, пока app/ и
tests/e2e/helpers.py не реализованы.
"""

from __future__ import annotations

import pytest
from support import app_settings, bot_replies, load

ADMIN_COMMANDS = (
    "/admin",
    "/admin_preset_list",
    "/admin_preset_add test-slug Test {}",
    "/admin_preset_edit test-slug {}",
    "/admin_preset_del test-slug",
    "/admin_stats",
    "/admin_collect",
    "/admin_health",
)

SETTINGS_KWARGS = {
    "_env_file": None,
    "bot_token": "1000000000:" + "T" * 35,
    "database_url": "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs",
}


def _admin_id() -> int:
    admin_id = app_settings().admin_id
    assert isinstance(admin_id, int) and not isinstance(admin_id, bool), (
        f"SEC-07: admin_id должен быть int, получен {type(admin_id).__name__}"
    )
    return admin_id


# --- SEC-07: не-админ не получает доступа ------------------------------------


@pytest.mark.parametrize("command", ADMIN_COMMANDS)
async def test_SEC_07_admin_command_rejected_for_non_admin(command: str) -> None:
    """SEC-07: любая админ-команда от не-админа — молчаливый игнор, без данных."""
    admin_id = _admin_id()
    attacker = admin_id + 1
    replies = await bot_replies(command, user_id=attacker)
    assert replies == [], (
        f"SEC-07: не-админ (chat_id={attacker}) получил ответ на {command!r}: {replies!r} — "
        "возможен обход авторизации админ-контура"
    )


async def test_SEC_07_id_type_confusion_and_substring_ids_rejected() -> None:
    """SEC-07: str-форма ADMIN_ID, подстроки и соседние id не дают админ-доступа."""
    admin_id = _admin_id()
    impostor_ids = (
        str(admin_id),  # id-type-confusion: str вместо int
        f"{admin_id} ",
        f" {admin_id}",
        f"{admin_id}\n",
        f"{admin_id}\x00",
        admin_id * 10,
        admin_id // 10 or 1,  # «100» при ADMIN_ID=1000 — подстрока
        admin_id + 1,
        admin_id - 1,
        -admin_id,
        0,
        1,
    )
    for impostor in impostor_ids:
        replies = await bot_replies("/admin_stats", user_id=impostor)
        assert replies == [], (
            f"SEC-07: id {impostor!r} ({type(impostor).__name__}) получил ответ "
            f"/admin_stats: {replies!r} — id-type-confusion/подстроковое сравнение"
        )


async def test_SEC_07_admin_positive_control_gets_reply() -> None:
    """SEC-07: настоящий ADMIN_ID получает ответ (иначе тесты авторизации вакуумны)."""
    admin_id = _admin_id()
    replies = await bot_replies("/admin_stats", user_id=admin_id)
    assert replies, "SEC-07: админ не получил ответ на /admin_stats — тест авторизации вакумен"


# --- SEC-07: строгий тип ADMIN_ID в конфигурации -----------------------------


def test_SEC_07_settings_admin_id_is_strict_int() -> None:
    """SEC-07: admin_id парсится строго в int; мусор не превращается в «админа»."""
    config = load("app.config")
    with pytest.raises(ValueError):
        config.Settings(admin_id="not-an-int", **SETTINGS_KWARGS)
    with pytest.raises(ValueError):
        config.Settings(admin_id="1000; DROP TABLE users", **SETTINGS_KWARGS)
    settings = config.Settings(admin_id="1000", **SETTINGS_KWARGS)
    assert type(settings.admin_id) is int, (
        f"SEC-07: admin_id должен быть int, получен {type(settings.admin_id).__name__}"
    )
    assert settings.admin_id == 1000
