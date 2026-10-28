"""Крыши памяти in-memory структур (F-16): флуд поддельными user_id.

Угроза F-16 (docs/security/report.md §8.3, CWE-770): in-memory словари
``DialogStore._langs`` и ``Antispam._stamps``/``_muted_until`` росли по числу
``user_id`` без вытеснения. Митигация (software-engineer, I-2-fix): крыши
``DialogStore.MAX_LANGS``/``Antispam.MAX_USERS`` с вытеснением самого старого,
``Antispam._prune`` чистит просроченное при давлении; «залипшие» состояния
диалога заменяются при повторном ``open`` и убираются при ``close``.

Угол security-тестов — атакующий вход (косвенно, через публичный вход ядра
``BotCore.handle``/``handle_callback``, а не прямые вызовы структур как в
U-SEC-05/U-SEC-06 tests/unit): массовый флуд поддельными/чужими ``user_id``
(5200 пользователей — больше дефолтной крыши 4096), флуд мьютами от многих
пользователей, «залипание» состояния диалога. Каждый callback во время флуда
подтверждается ровно один раз («часиков» нет, SEC-15).
"""

from __future__ import annotations

from typing import Any

from support import load_attr, memory_bot


async def _flood(core: Any, first_uid: int, users: int, actions: int) -> list[int]:
    """Флуд ``actions`` сообщениями от каждого из ``users`` поддельных user_id.

    Возвращает числа answer_callback_query на каждый callback (инвариант: 1).
    """
    answered: list[int] = []

    async def answer(text: str | None, show_alert: bool) -> None:
        answered.append(1)

    for index in range(users):
        user_id = first_uid + index
        for _ in range(actions):
            await core.handle("/start", user_id)
            await core.handle_callback("dlg:lang:ru", user_id, answer=answer)
    return answered


async def test_F16_spoofed_user_flood_keeps_memory_structures_bounded() -> None:
    """F-16: флуд 5200 поддельными user_id (больше крыши 4096) через публичный
    вход не раздувает ``_langs``/``_stamps``/``_muted_until`` сверх крыш;
    каждый callback подтверждён ровно один раз; после флуда реальный
    пользователь обслуживается (бот жив)."""
    dialog_store_cls = load_attr("app.bot.dialog", "DialogStore")
    max_users = load_attr("app.bot.antispam", "MAX_USERS")
    core = memory_bot()
    users = 5200  # > MAX_USERS == MAX_LANGS == 4096

    answered = await _flood(core, first_uid=760_000, users=users, actions=1)
    assert len(answered) == users, (
        f"F-16: подтверждены не все callback'и флуда: {len(answered)} из {users}"
    )

    assert len(core._dialogs._langs) <= dialog_store_cls.MAX_LANGS, (
        f"F-16: _langs вырос до {len(core._dialogs._langs)} (крыша {dialog_store_cls.MAX_LANGS})"
    )
    assert len(core._antispam._stamps) <= max_users, (
        f"F-16: _stamps вырос до {len(core._antispam._stamps)} (крыша {max_users})"
    )
    assert len(core._antispam._muted_until) <= max_users, (
        f"F-16: _muted_until вырос до {len(core._antispam._muted_until)} (крыша {max_users})"
    )
    # структуры реально упёрлись в крышу (иначе тест ничего не проверяет)
    assert len(core._dialogs._langs) == dialog_store_cls.MAX_LANGS, (
        f"F-16: флуд не достиг крыши _langs ({len(core._dialogs._langs)}) — детектор вакуумен"
    )

    replies = await core.handle("/start", 769_999)
    assert replies, "F-16: после флуда бот не обслуживает обычного пользователя"


async def test_F16_mute_map_roof_holds_under_multi_user_flood() -> None:
    """F-16: флуд мьютами от многих пользователей (каждый ломает лимит
    антиспама) не раздувает ``_muted_until``/``_stamps`` сверх крыши; посторонний
    пользователь не задет."""
    antispam_cls = load_attr("app.bot.antispam", "Antispam")
    flood_antispam = antispam_cls(limit=5, window_seconds=60.0, mute_seconds=600.0, max_users=16)
    core = memory_bot(antispam=flood_antispam)
    users, actions = 40, 8  # каждый пользователь упирается в лимит 5 → мьют

    await _flood(core, first_uid=770_000, users=users, actions=actions)

    assert len(core._antispam._muted_until) <= 16, (
        f"F-16: _muted_until вырос до {len(core._antispam._muted_until)} (крыша 16)"
    )
    assert len(core._antispam._stamps) <= 16, (
        f"F-16: _stamps вырос до {len(core._antispam._stamps)} (крыша 16)"
    )
    assert core._antispam._muted_until, (
        "F-16: флуд не создал ни одного мьюта — тест ничего не проверяет"
    )

    assert core._antispam.allow(779_999) is True, (
        "F-16: мьют флудящих задел постороннего пользователя"
    )


async def test_F16_dialog_state_is_replaced_on_reopen_and_removed_on_close() -> None:
    """F-16: состояние диалога не «залипает»: повторный /start одного
    пользователя заменяет состояние (нет накопления), завершённый шаг
    закрывает диалог (нет заброшенного состояния), диалог снова открывается."""
    core = memory_bot()
    uid = 780_000

    for _ in range(5):
        await core.handle("/start", uid)
    assert len(core._dialogs._states) == 1, (
        f"F-16: повторный /start накопил состояния: {list(core._dialogs._states)!r}"
    )

    await core.handle("/settings size", uid)
    assert core._dialogs.get(uid) is not None, "F-16: шаг size не открыл состояние"

    async def answer(text: str | None, show_alert: bool) -> None:
        return None

    await core.handle_callback("dlg:size:10", uid, answer=answer)
    assert core._dialogs.get(uid) is None, "F-16: завершённый шаг оставил «залипшее» состояние"

    replies = await core.handle("/settings", uid)
    assert replies, "F-16: диалог не открывается после закрытия состояния"
    assert core._dialogs.get(uid) is None, "F-16: /settings без шага открыл состояние заново"
