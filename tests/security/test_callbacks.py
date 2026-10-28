"""Callback-канал инлайн-диалога (I-2) — подделка, инъекция, флуд (SEC-15).

Угроза SEC-15 (threat-model §3, граница TB-8): ``callback_data`` инлайн-кнопок
диалога — НЕДОВЕРЕННЫЙ ввод (недоверенный клиент может прислать что угодно,
кнопку из чужого/старого диалога может нажать кто угодно). Митигация:
грамматика ``dlg:<step>:<value>`` ≤64 байт + белые списки step/value
(brief §6.1), владелец действия — только ``callback_query.from``, состояние
диалога per-user, ровно один немедленный ``answer_callback_query`` на каждый
callback (включая путь отказа и флуд), значения в HTML — только через ``esc``.

Контракт: docs/spec/api.md §15.1, docs/product/brief.md §6.1
(«Диалог на инлайн-кнопках»), сценарии S79..S88
tests/features/dialog_callbacks.feature. Тестовый вход — ``BotHarness.tap`` /
``BotHarness.answers()`` (threat-model §5.8, support.BotSession.tap); тесты
красные, пока callback-обработчик и API харнеса не реализованы
(:class:`support.NotImplementedYet`). Риски: R60..R62 (пересечения R26/R48/R57/R59).
"""

from __future__ import annotations

import itertools
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from support import (
    CALLBACK_PAYLOADS,
    CallbackFuzzer,
    app_settings,
    assert_no_raw_markup,
    bot_session,
    load_attr,
)

#: Строки тостов (brief §6.1): единый вежливый отказ и отказ мультивыбора.
RU_REFUSAL = "Эта кнопка устарела. Откройте настройки заново (/settings)."
EN_REFUSAL = "This button is outdated. Open settings again (/settings)."
RU_PICK = "Выберите хотя бы один пресет."
EN_PICK = "Pick at least one preset."
KNOWN_TOASTS = frozenset({"", RU_REFUSAL, EN_REFUSAL, RU_PICK, EN_PICK})

# --- независимый oracle белого списка (brief §6.1), без ссылок на app/ --------

PRESET_SLUGS = frozenset(
    {
        "python-backend",
        "frontend",
        "devops-sre",
        "data-ml",
        "qa",
        "mobile",
        "backend-other",
    }
)
TZ_CITY_SLUGS = frozenset(
    {
        "msk",
        "spb",
        "ekb",
        "nsk",
        "kzn",
        "nnv",
        "chel",
        "sam",
        "omsk",
        "rnd",
        "ufa",
        "krs",
        "vrn",
        "perm",
        "volg",
        "krd",
        "sar",
        "tum",
        "tol",
        "izh",
        "bar",
        "uln",
        "irk",
        "khb",
        "vvo",
        "yar",
        "tom",
        "mns",
        "ala",
        "tas",
    }
)
VALUE_BY_STEP = {
    "lang": frozenset({"ru", "en"}),
    "preset": PRESET_SLUGS | {"done"},
    "format": frozenset({"remote", "hybrid", "office", "any"}),
    "size": frozenset({"5", "10", "20", "50"}),
}
CALLBACK_GRAMMAR = re.compile(r"^dlg:(lang|preset|format|tz|size):([a-z0-9-]{1,32})$")
TZ_PAGE = re.compile(r"page-[1-9][0-9]*")


def whitelisted(data: str) -> bool:
    """callback_data — известный step + значение из белого списка (brief §6.1)."""
    match = CALLBACK_GRAMMAR.fullmatch(data)
    if match is None:
        return False
    step, value = match.groups()
    if step == "tz":
        return value in TZ_CITY_SLUGS | {"manual"} or TZ_PAGE.fullmatch(value) is not None
    return value in VALUE_BY_STEP[step]


def _assert_generic_refusal(outcome: object, where: str) -> None:
    """Любой невалидный callback — ровно один тост общего отказа, без крашей."""
    answers = outcome.answers  # type: ignore[attr-defined]
    assert answers in ([RU_REFUSAL], [EN_REFUSAL]), (
        f"{where}: ожидался единый вежливый отказ (toast), получено {answers!r}"
    )


async def _settings(session: object, user_id: int) -> list[str]:
    replies = await session.send("/settings", user_id=user_id)  # type: ignore[attr-defined]
    assert isinstance(replies, list), f"SEC-15: /settings упал для user_id={user_id}"
    return replies


# --- SEC-15: подделка callback (чужое/устаревшее состояние диалога) -----------


async def test_SEC_15_stale_callback_refused_and_state_unchanged() -> None:
    """SEC-15: кнопка «чужого» шага (не текущего) — отказ, состояние не меняется.

    Позитивный контроль: кнопка ТЕКУЩЕГО шага применяется (иначе тест вакуумен).
    """
    async with bot_session() as session:
        uid = 710_001
        await session.send("/start", user_id=uid)
        before = await _settings(session, uid)

        stale = await session.tap("dlg:size:5", user_id=uid)  # шаг lang, кнопка шага size
        _assert_generic_refusal(stale, "устаревший callback (не тот шаг)")
        assert await _settings(session, uid) == before, (
            "SEC-15: устаревший callback изменил настройки/состояние диалога"
        )

        ok = await session.tap("dlg:lang:ru", user_id=uid)  # кнопка текущего шага
        assert ok.answers == [""], (
            f"SEC-15: валидный callback текущего шага должен подтверждаться пустым "
            f"текстом, получено {ok.answers!r}"
        )
        for reply in ok.replies:
            assert_no_raw_markup(reply, "SEC-15 валидный tap")


async def test_SEC_15_foreign_user_cannot_tap_into_another_dialog() -> None:
    """SEC-15: tap кнопкой чужого диалога/чужим пользователем — отказ, чужие
    настройки и чужое состояние не меняются (CWE-639)."""
    async with bot_session() as session:
        victim, attacker, stranger = 710_002, 710_003, 710_004
        # жертва ведёт диалог: шаг пресетов, частично отмеченный мультивыбор
        await session.send("/start", user_id=victim)
        await session.tap("dlg:lang:ru", user_id=victim)
        await session.tap("dlg:preset:python-backend", user_id=victim)
        # у атакующего свой диалог на шаге lang, у постороннего диалога нет
        await session.send("/start", user_id=attacker)

        before_victim = await _settings(session, victim)
        before_attacker = await _settings(session, attacker)
        before_stranger = await _settings(session, stranger)

        # кнопка из диалога жертвы, нажатая чужим пользователем
        forged = await session.tap("dlg:preset:python-backend", user_id=attacker)
        _assert_generic_refusal(forged, "чужой callback (не тот шаг атакующего)")
        # callback от пользователя без открытого диалога вовсе
        outside = await session.tap("dlg:lang:ru", user_id=stranger)
        _assert_generic_refusal(outside, "callback без открытого диалога")

        assert await _settings(session, victim) == before_victim, (
            "SEC-15: чужой callback изменил состояние/настройки жертвы"
        )
        assert await _settings(session, attacker) == before_attacker, (
            "SEC-15: tap кнопкой чужого шага изменил состояние атакующего"
        )
        assert await _settings(session, stranger) == before_stranger, (
            "SEC-15: callback постороннего изменил его настройки"
        )


# --- SEC-15: мусор/инъекция/oversized в callback_data -------------------------


@pytest.mark.parametrize("payload", CALLBACK_PAYLOADS)
async def test_SEC_15_garbage_and_injection_callback_get_generic_refusal(payload: str) -> None:
    """SEC-15: мусорный/инъекционный/oversized callback_data — общий отказ без крашей.

    Payload включает ≥64 байт (лимит Telegram), HTML/SQL-инъекции в value,
    NUL/RTL/полноширинные символы и значения вне белого списка.
    """
    async with bot_session() as session:
        uid = 710_100
        await session.send("/start", user_id=uid)
        before = await _settings(session, uid)

        outcome = await session.tap(payload, user_id=uid)
        _assert_generic_refusal(outcome, f"мусорный callback {payload!r}")
        for reply in outcome.replies:
            assert_no_raw_markup(reply, f"SEC-15 ответ на {payload!r}")
            if payload:
                assert payload not in reply, (
                    f"SEC-15: недоверенный callback_data отражён в ответе: {reply!r}"
                )
        assert await _settings(session, uid) == before, (
            f"SEC-15: мусорный callback {payload!r} изменил состояние/настройки"
        )
        # бот жив после любого payload
        assert isinstance(await session.send("/start", user_id=uid), list), (
            f"SEC-15: бот не ожил после callback {payload!r}"
        )


# --- SEC-15: ровно один answer_callback_query на каждый callback --------------


async def test_SEC_15_every_callback_gets_exactly_one_answer() -> None:
    """SEC-15/S79: каждый callback (валидный, устаревший, мусорный) подтверждён
    ровно один раз — «часиков» нет ни на одном пути, включая отказ."""
    async with bot_session() as session:
        uid = 710_200
        await session.send("/start", user_id=uid)
        payloads = (
            "dlg:lang:ru",  # валидный, текущий шаг
            "dlg:size:5",  # устаревший
            "not-a-callback",  # мусор
            "dlg:preset:" + "a" * 80,  # oversized
            "",  # пустой
        )
        for payload in payloads:
            outcome = await session.tap(payload, user_id=uid)
            assert len(outcome.answers) == 1, (
                f"SEC-15: callback {payload!r} дал {len(outcome.answers)} "
                f"answer_callback_query (ожидался ровно 1, «часики»/двойной ответ): "
                f"{outcome.answers!r}"
            )


# --- SEC-15: флуд callback'ами не обходит антиспам ---------------------------


async def test_SEC_15_callback_flood_does_not_bypass_antispam() -> None:
    """SEC-15: callback-действия учитываются антиспамом (30 действий/мин → тихий
    мьют, AC-16); флуд кнопками не раздувает нагрузку и не мьютит посторонних.
    Каждый tap флуда всё равно подтверждается ровно один раз (S79)."""
    async with bot_session() as session:
        flooder, control = 710_300, 710_301
        await session.send("/start", user_id=flooder)
        await session.send("/start", user_id=control)

        for _ in range(40):
            outcome = await session.tap("dlg:size:5", user_id=flooder)
            assert len(outcome.answers) == 1, (
                "SEC-15: во время флуда callback без answer_callback_query («часики»)"
            )
        for _ in range(2):
            await session.tap("dlg:size:5", user_id=control)

        probe_flood = await session.send("/like 1", user_id=flooder)
        probe_control = await session.send("/like 1", user_id=control)
        assert probe_flood == [], (
            f"SEC-15: флуд 40 callback'ами не учтён антиспамом (AC-16): "
            f"ответ после флуда {probe_flood!r}"
        )
        assert probe_control, (
            "SEC-15: контрольный пользователь без флуда заглушен — антиспам ловит всех"
        )


# --- SEC-15: вредоносное имя пресета (админ-ввод) экранировано ---------------


async def test_SEC_15_malicious_preset_name_is_escaped_in_dialog() -> None:
    """SEC-15/SEC-05: имя пресета из админского ввода не даёт HTML-инъекцию в
    диалоге (S85): метки кнопок — plain text, но весь HTML-текст шагов/ответов
    экранируется (app.textutil.esc)."""
    admin_id = app_settings().admin_id
    name_payload = '<script>alert(1)</script> <a href="evil">X</a> & "quotes"'
    esc = load_attr("app.textutil", "esc")
    async with bot_session() as session:
        uid = 710_400
        await session.send(f"/admin_preset_add evilx {name_payload} {{}}", user_id=admin_id)
        await session.send("/start", user_id=uid)

        replies: list[str] = []
        for payload in ("dlg:lang:ru", "dlg:preset:evilx", "dlg:preset:done"):
            outcome = await session.tap(payload, user_id=uid)
            assert len(outcome.answers) == 1, f"SEC-15: callback {payload!r} не подтверждён"
            replies.extend(outcome.replies)
        replies.extend(await _settings(session, uid))

        joined = "\n".join(replies)
        for reply in replies:
            assert_no_raw_markup(reply, "SEC-15 имя пресета в диалоге")
            assert name_payload not in reply, (
                f"SEC-15: сырое имя пресета (админ-ввод) в HTML-ответе: {reply!r}"
            )
        assert esc(name_payload) in joined or name_payload not in joined, (
            f"SEC-15: имя пресета выводится в HTML без esc(): {joined!r}"
        )


# --- P-SEC-06 (hypothesis, фиксированный seed) -------------------------------


_FUZZER = CallbackFuzzer()
_FUZZ_IDS = itertools.count(720_000)


@pytest.fixture(scope="module")
def fuzzer() -> CallbackFuzzer:
    """Один BotHarness/схема на весь прогон P-SEC-06 (не функциональная область —
    hypothesis требует, чтобы фикстура не «сбрасывалась» между примерами)."""
    yield _FUZZER
    _FUZZER.close()


@settings(derandomize=True, max_examples=200, deadline=None)
@given(
    st.text(max_size=120) | st.binary(max_size=120).map(lambda raw: raw.decode("utf-8", "replace"))
)
def test_P_SEC_06_callback_data_is_whitelisted_or_refused_never_crashes(
    fuzzer: CallbackFuzzer, data: str
) -> None:
    """P-SEC-06: произвольный callback_data → либо валидный шаг с белым списком,
    либо общий отказ; никогда — исключение/краш/инъекция (SEC-15).

    Свойства на каждом примере: ровно один answer_callback_query; если callback_data
    не проходит грамматику/белый список (независимый oracle brief §6.1) — строго
    тост общего отказа; любой текст ответа — без сырой разметки.
    """
    outcome = _FUZZER.tap(data, user_id=next(_FUZZ_IDS))
    assert len(outcome.answers) == 1, (
        f"P-SEC-06: callback {data!r} дал {len(outcome.answers)} answer_callback_query"
    )
    answer = outcome.answers[0]
    if whitelisted(data):
        assert answer in KNOWN_TOASTS, (
            f"P-SEC-06: неизвестный тост {answer!r} для белосписочного {data!r}"
        )
    else:
        assert answer in (RU_REFUSAL, EN_REFUSAL), (
            f"P-SEC-06: callback_data {data!r} вне белого списка не дал общий отказ: {answer!r}"
        )
    for reply in outcome.replies:
        assert_no_raw_markup(reply, f"P-SEC-06 callback {data!r}")
