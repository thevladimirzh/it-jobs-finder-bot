"""Property-тесты кнопочного диалога I-2 (hypothesis, фиксированный seed).

Владелец: qa-engineer. Свойства запланированы реестром рисков
(docs/risk-register.md, R55..R59, R63..R69): P-DLG-01 (round-trip format/parse
callback_data, ≤ 64 байт, белый список шагов/грамматики) и P-DLG-02 (любой
мусорный callback → вежливый отказ, ровно один answer, без исключений).

Конвенции: ``derandomize=True`` (фиксированный seed), ``deadline=None``;
hypothesis не даёт async-тестов — корутины гоняются через ``fakes.run``.

Контракт production API (docs/qa/acceptance-map.md §6.2, реализует
software-engineer): модуль ``app.bot.dialog`` с ``encode_callback(step, value)``
и ``parse_callback(data)``; пока их нет — внятный красный ``NotImplementedYet``.
Семантическая валидация значений (size ∈ {5,10,20,50}, известные коды пресетов)
— работа обработчика callback и покрывается S88/P-DLG-02, здесь проверяются
форма, лимиты и тотальность парсера.
"""

from __future__ import annotations

import re

from dialog import (
    CITY_SLUGS,
    OUTDATED,
    answer_of,
    answers_in,
    events,
    press,
    user_state,
)
from fakes import open_bot, run, send_text
from hypothesis import given, settings
from hypothesis import strategies as st
from support import load_attr

CALLBACK_RE = re.compile(r"^dlg:(lang|preset|format|tz|size):[a-z0-9-]{1,32}$")

# Белый список фиксированных значений (brief §6.1): (step, value).
PRESET_SLUGS = (
    "python-backend",
    "frontend",
    "devops-sre",
    "data-ml",
    "qa",
    "mobile",
    "backend-other",
)
STEP_VALUES = {
    "lang": ("ru", "en"),
    "preset": PRESET_SLUGS + ("done",),
    "format": ("remote", "hybrid", "office", "any"),
    "tz": CITY_SLUGS + ("manual", "page-1", "page-2", "page-3"),
    "size": ("5", "10", "20", "50"),
}
PAIRS = [(step, value) for step, values in STEP_VALUES.items() for value in values]
PAIR_STRATEGY = st.sampled_from(PAIRS)

# Заведомо мусорные callback_data (дополнительно к случайному тексту):
# битые страницы пагинации (R66), переполнение, спецсимволы.
FIXED_GARBAGE = (
    "dlg:tz:page-999",
    "dlg:tz:page-0",
    "dlg:tz:page-1x",
    "dlg:tz:page--1",
    "dlg:size:0",
    "dlg:size:51",
    "dlg:preset:",
    "dlg::x",
    "dlg:<script>alert(1)</script>",
    "not-a-callback",
    "",
    "\x00",
    "\u202eevil",
    "dlg:" + "a" * 200,
    "x" * 300,
)

# Допустимые callback текущего шага (после lang → шаг preset) — «не мусор».
VALID_AT_PRESET_STEP = {f"dlg:preset:{value}" for value in STEP_VALUES["preset"]}


# --- P-DLG-01 (R58/R59/R66): round-trip, лимит 64 байт, белый список --------


@settings(derandomize=True, max_examples=200, deadline=None)
@given(pair=PAIR_STRATEGY)
def test_P_DLG_01_callback_data_round_trip_within_64_bytes(pair: tuple[str, str]) -> None:
    """P-DLG-01: parse(encode(step, value)) == (step, value); ASCII,
    грамматика ``dlg:<step>:<value>``, ≤ 64 байт для всех значений словарей."""
    encode = load_attr("app.bot.dialog", "encode_callback")
    parse = load_attr("app.bot.dialog", "parse_callback")
    step, value = pair
    data = encode(step, value)
    assert data.isascii(), f"P-DLG-01: {pair!r} -> не ASCII: {data!r}"
    assert CALLBACK_RE.match(data), f"P-DLG-01: {pair!r} -> не по грамматике: {data!r}"
    assert len(data.encode("ascii")) <= 64, f"P-DLG-01: {pair!r} -> длиннее 64 байт: {data!r}"
    assert parse(data) == (step, value), f"P-DLG-01: round-trip {pair!r} -> {data!r}"


@settings(derandomize=True, max_examples=200, deadline=None)
@given(raw=st.text(max_size=150))
def test_P_DLG_01_parse_is_total_and_whitelisted(raw: str) -> None:
    """P-DLG-01: parse тотален (не бросает) и возвращает только белый список:
    None либо (известный шаг, значение по грамматике ``[a-z0-9-]{1,32}``)."""
    parse = load_attr("app.bot.dialog", "parse_callback")
    result = parse(raw)
    assert result is None or (
        result[0] in STEP_VALUES and re.fullmatch(r"[a-z0-9-]{1,32}", result[1])
    ), f"P-DLG-01: parse({raw!r}) -> {result!r} вне белого списка"


@settings(derandomize=True, max_examples=150, deadline=None)
@given(step=st.text(max_size=40), value=st.text(max_size=40))
def test_P_DLG_01_encode_either_conforms_or_rejects(step: str, value: str) -> None:
    """P-DLG-01: encode либо возвращает конформную строку (round-trip c parse),
    либо бросает ValueError — ничего «среднего»."""
    encode = load_attr("app.bot.dialog", "encode_callback")
    parse = load_attr("app.bot.dialog", "parse_callback")
    try:
        data = encode(step, value)
    except ValueError:
        return
    assert CALLBACK_RE.match(data), f"P-DLG-01: encode({step!r}, {value!r}) -> {data!r}"
    assert len(data.encode("ascii")) <= 64, f"P-DLG-01: encode({step!r}, {value!r}) -> {data!r}"
    assert parse(data) == (step, value), f"P-DLG-01: round-trip {step!r}, {value!r} -> {data!r}"


# --- P-DLG-02 (R56/R57/R63/R65/R66/R67): мусорный callback → вежливый отказ --


@settings(derandomize=True, max_examples=25, deadline=None)
@given(raw=st.one_of(st.text(max_size=150), st.sampled_from(FIXED_GARBAGE)))
def test_P_DLG_02_garbage_callback_polite_refusal_never_crashes(raw: str) -> None:
    """P-DLG-02: любой мусорный callback_data → вежливый отказ (ровно один
    немедленный answer, toast), сообщения не отправляются, состояние диалога
    и настройки не меняются, исключений нет."""

    async def go() -> tuple[list[str], list, object, object]:
        async with open_bot() as h:
            uid = 1501
            await send_text(h, uid, "/start")
            await press(h, "dlg:lang:ru", user_id=uid)  # диалог на шаге preset
            before = await user_state(h, uid)
            mark = len(events(h))
            replies = await press(h, raw, user_id=uid)
            trail = events(h)[mark:]
            after = await user_state(h, uid)
            return replies, trail, before, after

    replies, trail, before, after = run(go())
    answers = answers_in(trail)
    assert len(answers) == 1 and trail[0][0] == "answer", (
        f"P-DLG-02: для {raw!r} нет ровно одного немедленного подтверждения: {trail!r}"
    )
    text, show_alert = answer_of(answers[0][1])
    if raw in VALID_AT_PRESET_STEP:
        assert text == "", f"P-DLG-02: валидный {raw!r} отвергнут: {text!r}"
        return
    assert text == OUTDATED["ru"], f"P-DLG-02: для {raw!r} ожидаем отказ, получено {text!r}"
    assert show_alert is False, f"P-DLG-02: для {raw!r} отказ не toast: {trail!r}"
    assert replies == [], f"P-DLG-02: для {raw!r} изменены сообщения: {replies!r}"
    assert after == before, f"P-DLG-02: для {raw!r} изменилось состояние: {before!r} -> {after!r}"
