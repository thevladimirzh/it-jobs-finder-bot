"""Юнит-тесты кнопочного диалога I-2: U-DLG-01..U-DLG-06 (TDD, software-engineer).

Модуль ``app/bot/dialog.py`` (контракт docs/qa/acceptance-map.md §6.2 п.15,
api.md §15.1, decisions §8.2): ``encode_callback``/``parse_callback`` (белый
список шагов, грамматика значения ``[a-z0-9-]{1,32}``, лимит 64 байт), короткие
коды пресетов для длинных slug, постраничные города (≤10 на странице), клавиатуры
шагов (callback_data каждой кнопки конформна). ``BotCore.handle_callback`` —
учёт callback-действий антиспамом (SEC-15: флуд кнопками в лимит 30/мин) и
ровно один ``answer_callback_query`` на каждый callback, включая мьют и отказ.
"""

from __future__ import annotations

import copy
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.bot.antispam import Antispam
from app.bot.core import BotCore
from app.bot.dialog import (
    CITIES,
    TZ_PAGE_SIZE,
    DialogStore,
    encode_callback,
    format_keyboard,
    lang_keyboard,
    parse_callback,
    preset_code,
    preset_codes,
    preset_keyboard,
    size_keyboard,
    tz_keyboard,
    tz_page_count,
)

CALLBACK_RE = re.compile(r"^dlg:(lang|preset|format|tz|size):[a-z0-9-]{1,32}$")
REFUSAL = "Эта кнопка устарела. Откройте настройки заново (/settings)."

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
    "tz": tuple(city[0] for city in CITIES) + ("manual", "page-1", "page-2", "page-3"),
    "size": ("5", "10", "20", "50"),
}
GARBAGE = (
    "dlg:unknown:x",
    "dlg:size:51",
    "dlg:size:-5",
    "dlg:size:05",
    "dlg:lang:de",
    "dlg:preset:nonexistent",
    "dlg:tz:UTC+99",
    "dlg:tz:page-0",
    "dlg:tz:page-1x",
    "dlg:tz:../../../etc/passwd",
    "dlg:<script>alert(1)</script>",
    "dlg:",
    "dlg::x",
    "not-a-callback",
    "",
    "\x00",
    "\u202eevil",
    "dlg:" + "a" * 200,
    "x" * 300,
    "dlg:preset:",
    "DLG:size:5",
)


# --- U-DLG-01: round-trip encode/parse, грамматика, лимит 64 байт ------------


def test_u_dlg01_encode_parse_round_trip_within_64_bytes() -> None:
    for step, values in STEP_VALUES.items():
        for value in values:
            data = encode_callback(step, value)
            assert data.isascii(), f"U-DLG-01: {step}:{value} -> не ASCII: {data!r}"
            assert CALLBACK_RE.match(data), f"U-DLG-01: {step}:{value} -> не по грамматике"
            assert len(data.encode("ascii")) <= 64, f"U-DLG-01: {step}:{value} -> >64 байт"
            assert parse_callback(data) == (step, value), f"U-DLG-01: round-trip {step}:{value}"


def test_u_dlg01_long_slug_gets_short_code_within_limit() -> None:
    """Короткий код пресета: slug 100 символов не попадает в callback_data целиком."""
    slug = "s" + "a" * 99
    code = preset_code(slug)
    assert code != slug and len(code) <= 32, f"U-DLG-01: код пресета не короткий: {code!r}"
    assert re.fullmatch(r"[a-z0-9-]{1,32}", code), f"U-DLG-01: код не по грамматике: {code!r}"
    data = encode_callback("preset", code)
    assert len(data.encode("ascii")) <= 64, f"U-DLG-01: callback_data длиннее 64 байт: {data!r}"
    assert parse_callback(data) == ("preset", code)


# --- U-DLG-02: тотальность parse, отказ encode вне формы ----------------------


def test_u_dlg02_parse_is_total_and_whitelisted() -> None:
    for raw in GARBAGE:
        result = parse_callback(raw)
        assert result is None or (
            result[0] in STEP_VALUES and re.fullmatch(r"[a-z0-9-]{1,32}", result[1])
        ), f"U-DLG-02: parse({raw!r}) -> {result!r} вне белого списка"


def test_u_dlg02_parse_rejects_garbage_and_returns_none() -> None:
    for raw in GARBAGE:
        if raw in {
            "dlg:size:51",
            "dlg:size:-5",
            "dlg:size:05",
            "dlg:lang:de",
            "dlg:preset:nonexistent",
            "dlg:tz:UTC+99",
            "dlg:tz:page-0",
            "dlg:tz:page-1x",
        }:
            continue  # форма валидна, семантику отклоняет обработчик (S88)
        assert parse_callback(raw) is None, f"U-DLG-02: мусор {raw!r} прошёл parse"


def test_u_dlg02_encode_rejects_steps_and_values_outside_grammar() -> None:
    for step in ("", "unknown", "LANG", "lang ", "х", "lang:ru"):
        with pytest.raises(ValueError):
            encode_callback(step, "ru")
    for value in ("", "RU", "a" * 33, "a b", "a:b", "\x00", "х", "a/b", "a.b", "a_b"):
        with pytest.raises(ValueError):
            encode_callback("lang", value)


# --- U-DLG-03: короткие коды пресетов детерминированы и различимы -------------


def test_u_dlg03_preset_codes_are_short_stable_and_distinct() -> None:
    long_a, long_b = "s" + "a" * 99, "s" + "b" * 99
    code_a, code_b = preset_code(long_a), preset_code(long_b)
    assert code_a != code_b, "U-DLG-03: разные slug получили один код"
    assert preset_code(long_a) == code_a, "U-DLG-03: код slug не детерминирован"
    for slug in PRESET_SLUGS:
        assert preset_code(slug) == slug, f"U-DLG-03: канонический slug перекодирован: {slug}"
        assert preset_code(slug) != code_a, "U-DLG-03: код длинного slug совпал с каноническим"


# --- U-DLG-04: пагинация городов ---------------------------------------------


def _city_labels(rows) -> list[str]:
    return [
        label
        for row in rows
        for label, data in row
        if data.startswith("dlg:tz:") and "page" not in data and data != "dlg:tz:manual"
    ]


def test_u_dlg04_city_pages_cover_all_cities_without_gaps() -> None:
    assert len(CITIES) == 30, f"U-DLG-04: в таблице {len(CITIES)} городов (нужно 30)"
    assert tz_page_count() == (len(CITIES) + TZ_PAGE_SIZE - 1) // TZ_PAGE_SIZE
    seen: list[str] = []
    for page in range(1, tz_page_count() + 1):
        labels = _city_labels(tz_keyboard("ru", page))
        assert 1 <= len(labels) <= TZ_PAGE_SIZE, f"U-DLG-04: страница {page}: {labels!r}"
        seen += labels
    assert len(seen) == len(set(seen)), f"U-DLG-04: города дублируются между страницами: {seen!r}"
    assert set(seen) == {city[1] for city in CITIES}, "U-DLG-04: не все города списка на страницах"
    first = [button for row in tz_keyboard("ru", 1) for button in row]
    assert ("Указать UTC offset вручную", "dlg:tz:manual") in first, (
        f"U-DLG-04: нет кнопки ручного offset: {first!r}"
    )


def test_u_dlg04_out_of_range_page_is_rejected() -> None:
    for page in (0, -1, tz_page_count() + 1, 999):
        with pytest.raises(ValueError):
            tz_keyboard("ru", page)


# --- U-DLG-05: клавиатуры шагов конформны (грамматика + 64 байта) -------------


def test_u_dlg05_keyboards_conform_to_callback_contract() -> None:
    long_slug = "s" + "a" * 99
    presets = [(slug, f"Name {slug}") for slug in (*PRESET_SLUGS, long_slug)]
    keyboards: dict[str, tuple] = {
        "lang": lang_keyboard(),
        "preset": preset_keyboard(presets, selected=({"qa", long_slug})),
        "format": format_keyboard("ru"),
        "size": size_keyboard(),
    }
    for page in range(1, tz_page_count() + 1):
        keyboards[f"tz:{page}"] = tz_keyboard("ru", page)
    for where, rows in keyboards.items():
        assert rows, f"U-DLG-05[{where}]: пустая клавиатура"
        for row in rows:
            for label, data in row:
                assert CALLBACK_RE.match(data), f"U-DLG-05[{where}]: кнопка {label!r}: {data!r}"
                assert data.isascii(), f"U-DLG-05[{where}]: {data!r} не ASCII"
                assert len(data.encode("ascii")) <= 64, f"U-DLG-05[{where}]: {data!r} > 64 байт"
                assert parse_callback(data) is not None, f"U-DLG-05[{where}]: {data!r} не парсится"


def test_u_dlg05_preset_keyboard_marks_selected_with_check() -> None:
    presets = [("qa", "QA"), ("mobile", "Mobile")]
    rows = preset_keyboard(presets, selected={"qa"})
    labels = {data: label for row in rows for label, data in row}
    assert labels["dlg:preset:qa"] == "✅ QA", f"U-DLG-05: выбран без ✅: {labels!r}"
    assert labels["dlg:preset:mobile"] == "Mobile", f"U-DLG-05: лишний ✅: {labels!r}"
    assert labels["dlg:preset:done"] in ("Готово", "Done"), f"U-DLG-05: нет «Готово»: {labels!r}"


# --- U-DLG-06: callback-действия в антиспаме; ровно один answer ---------------


class _User:
    def __init__(self, user_id: int, lang: str, profile: dict) -> None:
        self.id, self.lang, self.profile = user_id, lang, profile


class _Repo:
    """Минимальный репозиторий для BotCore (api.md §9)."""

    def __init__(self) -> None:
        self.users: dict[int, _User] = {}
        self.calls: list[str] = []

    async def get_user(self, user_id: int) -> _User | None:
        self.calls.append("get_user")
        return self.users.get(user_id)

    async def upsert_user(self, user_id: int, *, lang: str, profile) -> _User:
        self.calls.append("upsert_user")
        self.users[user_id] = _User(user_id, lang, profile)
        return self.users[user_id]

    async def list_presets(self) -> list:
        self.calls.append("list_presets")
        return []


async def _tap(core: BotCore, user_id: int, data: str) -> list:
    recorded: list = []

    async def answer(text: str, show_alert: bool) -> None:
        recorded.append((text, show_alert))

    await core.handle_callback(data, user_id, answer=answer)
    return recorded


async def test_u_dlg06_callback_flood_counted_by_antispam_one_answer_each() -> None:
    core = BotCore(repo=_Repo(), antispam=Antispam())
    for index in range(30):
        answers = await _tap(core, 1, "dlg:size:5")
        assert len(answers) == 1, f"U-DLG-06: tap #{index + 1} дал {len(answers)} answer"
    # 31-е действие — мьют; callback всё равно подтверждается ровно один раз
    for index in range(5):
        answers = await _tap(core, 1, "dlg:size:5")
        assert len(answers) == 1, f"U-DLG-06: замьюченный tap #{index + 1} без answer"
    # мьют действует и на текстовые действия (тихий игнор)
    assert await core.handle("/settings", 1) == [], "U-DLG-06: мьют не коснулся текстовых действий"
    # флуд одного пользователя не мьютит другого
    assert await core.handle("/settings", 2), "U-DLG-06: чужой флуд замьютил другого пользователя"


async def test_u_dlg06_every_callback_gets_exactly_one_toast_answer() -> None:
    core = BotCore(repo=_Repo(), antispam=Antispam(limit=10**6))
    for data in ("dlg:lang:ru", "not-a-callback", ""):
        answers = await _tap(core, 5, data)
        assert len(answers) == 1, f"U-DLG-06: callback {data!r} дал {len(answers)} answer"
        text, show_alert = answers[0]
        assert show_alert is False, f"U-DLG-06: подтверждение {data!r} не toast"
        assert text in ("", REFUSAL), f"U-DLG-06: неожиданный текст подтверждения: {text!r}"


async def test_u_dlg06_stale_and_forged_callbacks_do_not_change_state() -> None:
    core = BotCore(repo=_Repo(), antispam=Antispam(limit=10**6))
    await core.handle("/start", 6)
    before = copy.deepcopy(core._repo.users[6].profile)
    for forged in ("dlg:size:5", "dlg:lang:de", "dlg:preset:nonexistent", "dlg:tz:page-999"):
        answers = await _tap(core, 6, forged)
        assert len(answers) == 1, f"U-DLG-06: {forged!r} без подтверждения"
        assert answers[0][0] == REFUSAL, f"U-DLG-06: {forged!r} не дал общий отказ: {answers!r}"
    assert core._repo.users[6].profile == before, "U-DLG-06: подделанные callback изменили профиль"


# --- U-DLG-07: answer — первое действие, до обращений к БД ---------------------


async def test_u_dlg07_answer_fires_before_db_access_and_replies() -> None:
    """U-DLG-02/threat-model §5.8: подтверждение callback уходит до БД и до
    отправки сообщений (S79: «часиков» нет), на всех путях — и валидном, и отказе."""
    repo = _Repo()
    core = BotCore(repo=repo, antispam=Antispam(limit=10**6))
    await core.handle("/start", 7)  # диалог открыт: шаг lang
    for data in ("dlg:lang:ru", "dlg:size:5"):
        baseline = len(repo.calls)
        at_answer: list[int] = []
        replies: list = []

        async def answer(text: str, show_alert: bool, *, repo=repo, sink=at_answer) -> None:
            sink.append(len(repo.calls))

        replies = await core.handle_callback(data, 7, answer=answer)
        assert at_answer == [baseline], (
            f"U-DLG-07: answer для {data!r} ушёл после обращений к БД: {repo.calls[baseline:]!r}"
        )
        assert isinstance(replies, list), f"U-DLG-07: {data!r} дал неожиданный ответ"


# --- U-SEC-06 (F-16, CWE-770): крыша памяти DialogStore._langs ----------------


def test_u_sec06_dialog_store_lang_memory_is_bounded() -> None:
    """``_langs`` ограничен: вытеснение самых старых записей (F-16)."""
    store = DialogStore(max_langs=2)
    for user_id in range(1, 6):
        store.note_lang(user_id, "en")
        assert len(store._langs) <= 2, f"U-SEC-06: _langs вырос до {len(store._langs)}"
    assert store.lang_of(1) == "ru", "U-SEC-06: вытесненная запись пользователя 1 осталась"
    assert store.lang_of(2) == "ru", "U-SEC-06: вытесненная запись пользователя 2 осталась"
    assert store.lang_of(5) == "en", "U-SEC-06: свежая запись потеряна"
    # обновление существующего ключа не вытесняет другие записи
    store.note_lang(5, "ru")
    assert len(store._langs) == 2, f"U-SEC-06: обновление ключа изменило размер: {store._langs!r}"
    assert store.lang_of(5) == "ru", "U-SEC-06: обновление языка не применилось"
    # open() диалога идёт через note_lang — крыша соблюдается и там
    store = DialogStore(max_langs=2)
    for user_id in range(1, 6):
        store.open(user_id, "lang")
    assert len(store._langs) <= 2, f"U-SEC-06: _langs через open() вырос до {len(store._langs)}"


# --- U-SEC-07 (F-17, CWE-334): коллизии кодов пресетов не перезаписываются ----


class _Preset:
    def __init__(self, slug: str, name_ru: str) -> None:
        self.slug, self.name_ru, self.name_en = slug, name_ru, ""


class _PresetRepo(_Repo):
    """Репозиторий с пресетами для map «код → slug» (F-17)."""

    def __init__(self, presets: tuple[tuple[str, str], ...]) -> None:
        super().__init__()
        self._preset_rows = [_Preset(slug, name) for slug, name in presets]

    async def list_presets(self) -> list:
        self.calls.append("list_presets")
        return list(self._preset_rows)


def test_u_sec07_preset_codes_resolve_collisions_without_overwrite(monkeypatch) -> None:
    """F-17: два slug с одним кодом не перезаписываются — код расширяется."""
    monkeypatch.setattr("app.bot.dialog.preset_code", lambda slug: "same")
    codes = preset_codes(("alpha", "beta", "gamma"))
    assert set(codes) == {"alpha", "beta", "gamma"}, f"U-SEC-07: slug потеряны: {codes!r}"
    assert len(set(codes.values())) == 3, f"U-SEC-07: коды не различимы: {codes!r}"
    for code in codes.values():
        assert re.fullmatch(r"[a-z0-9-]{1,32}", code), f"U-SEC-07: код {code!r} вне грамматики"
        data = encode_callback("preset", code)
        assert len(data.encode("ascii")) <= 64, f"U-SEC-07: {data!r} > 64 байт"
        assert parse_callback(data) == ("preset", code), f"U-SEC-07: {data!r} не парсится"


def test_u_sec07_unresolvable_collision_is_explicit_refusal(monkeypatch) -> None:
    """F-17: неразрешимая коллизия — явный отказ (ValueError), не перезапись."""
    monkeypatch.setattr("app.bot.dialog.preset_code", lambda slug: "same")
    monkeypatch.setattr("app.bot.dialog._extended_preset_code", lambda slug: "same")
    with pytest.raises(ValueError):
        preset_codes(("alpha", "beta"))


async def test_u_sec07_core_state_codes_and_keyboard_stay_bijective(monkeypatch) -> None:
    """F-17: state.codes и клавиатура не перезаписывают коллизию — тап
    переключает «свой» пресет, а не «не тот»."""
    monkeypatch.setattr("app.bot.dialog.preset_code", lambda slug: "same")
    core = BotCore(
        repo=_PresetRepo((("alpha", "Alpha"), ("beta", "Beta"))),
        antispam=Antispam(limit=10**6),
    )
    await core.handle("/start", 8)
    replies = await core.handle("/settings preset", 8)
    state = core._dialogs.get(8)
    assert state is not None, "U-SEC-07: диалог не открыт"
    assert len(state.codes) == 2, f"U-SEC-07: коллизия перезаписана: {state.codes!r}"
    assert set(state.codes.values()) == {"alpha", "beta"}, (
        f"U-SEC-07: slug потеряны: {state.codes!r}"
    )
    preset_datas = [
        data for row in replies[0].keyboard for _label, data in row if data != "dlg:preset:done"
    ]
    assert len(set(preset_datas)) == 2, (
        f"U-SEC-07: кнопки дублируют callback_data: {preset_datas!r}"
    )
    for code, slug in state.codes.items():
        answers = await _tap(core, 8, f"dlg:preset:{code}")
        assert answers == [("", False)], f"U-SEC-07: тап {code!r} не принят: {answers!r}"
        assert slug in core._dialogs.get(8).selected, (
            f"U-SEC-07: код {code!r} переключил не {slug!r}: {core._dialogs.get(8).selected!r}"
        )


@settings(derandomize=True, max_examples=200, deadline=None)
@given(slugs=st.lists(st.text(min_size=0, max_size=40), min_size=0, max_size=12, unique=True))
def test_u_sec07_preset_codes_property_injective_and_conform(slugs: list[str]) -> None:
    """PBT (F-17): для любых slug коды различимы, в грамматике ≤32, round-trip."""
    codes = preset_codes(tuple(slugs))
    assert set(codes) == set(slugs), f"U-SEC-07: slug потеряны/добавлены: {codes!r}"
    values = list(codes.values())
    assert len(set(values)) == len(values), f"U-SEC-07: коллизия кодов: {codes!r}"
    for code in values:
        assert re.fullmatch(r"[a-z0-9-]{1,32}", code), f"U-SEC-07: код вне грамматики: {code!r}"
        data = encode_callback("preset", code)
        assert len(data.encode("ascii")) <= 64, f"U-SEC-07: {data!r} > 64 байт"
        assert parse_callback(data) == ("preset", code), f"U-SEC-07: {data!r} не парсится"
    assert preset_codes(tuple(slugs)) == codes, "U-SEC-07: коды недетерминированы"
