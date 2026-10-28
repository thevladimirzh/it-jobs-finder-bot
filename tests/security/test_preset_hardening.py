"""Пресеты админа (F-14) и коды пресетов (F-17): злоумышленный ввод.

F-14 (CWE-20/CWE-770, docs/security/report.md §8.3): имя пресета >128 и
slug >255 раньше падали ``asyncpg.DataError`` без ответа админу
(``name_ru VARCHAR(128)``, ``slug VARCHAR(255)``). Митигация (software-engineer,
I-2-fix, ``app/bot/core.py:_preset_size_problem``): вежливый отказ ДО БД.
Security-угол (не дубль U-SEC-04 из tests/unit/test_bot_unit.py — там in-memory
репозиторий и точные строки): БД не вызывается ВООБЩЕ (ноль SQL-запросов —
``RecordingSessionFactory``), отказ не раскрывает внутренности (CWE-209),
вредоносные формы имени/слага (NUL, полноширинные, эмодзи, 10k, мультитокен).

F-17 (CWE-334/CWE-328, там же): ``state.codes = {preset_code(slug): slug}``
молча перезаписывал коллизию двух кодов. Коллизию может сконструировать
атакующий: канонический slug вида ``h<sha256(dругого slug)[:15]>`` совпадает
с хэш-кодом длинного slug (пример воспроизводится программно). Митигация
(``app/bot/dialog.py:preset_codes``): коды биективны (коллизующий slug получает
расширенный код), неразрешимая коллизия — ``ValueError`` (fail-closed).
Риски: R60..R62; PBT — P-SEC-07.
"""

from __future__ import annotations

import hashlib
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from support import (
    RecordingSessionFactory,
    app_settings,
    load,
    load_attr,
    memory_bot,
)

#: Строки, которые отказ админу не должен содержать (CWE-209: утечка внутренностей).
INTERNAL_MARKERS = (
    "traceback",
    "asyncpg",
    "sqlalchemy",
    "varchar",
    "dataerror",
    "dbapierror",
    "exception",
    "psycopg",
    'file "',
    "column",
)

#: Границы колонок БД (F-14): имя ≤128 символов, slug ≤255.
NAME_LIMIT = 128
SLUG_LIMIT = 255

CODE_GRAMMAR = re.compile(r"[a-z0-9-]{1,32}")


def _admin_core() -> tuple:
    """``BotCore`` поверх :class:`RecordingSessionFactory`: каждый SQL-запрос виден."""
    core_cls = load_attr("app.bot.core", "BotCore")
    repo_cls = load_attr("app.storage.repo", "Repo")
    antispam_cls = load_attr("app.bot.antispam", "Antispam")
    factory = RecordingSessionFactory()
    core = core_cls(repo=repo_cls(factory), antispam=antispam_cls(limit=10**6))
    return core, factory


def _assert_polite_refusal(replies: list, where: str) -> None:
    """Отказ — один вежливый текст без внутренностей и без маркера успеха."""
    assert len(replies) == 1, f"{where}: ожидался ровно один ответ, получено {replies!r}"
    text = str(replies[0])
    assert text.strip(), f"{where}: пустой отказ {replies!r}"
    assert "✅" not in text, f"{where}: отказ выглядит как успех: {text!r}"
    lowered = text.lower()
    for marker in INTERNAL_MARKERS:
        assert marker not in lowered, f"{where}: отказ раскрывает внутренности ({marker}): {text!r}"
    assert len(text) <= 500, f"{where}: раздутый отказ ({len(text)} символов): {text[:120]!r}"


# --- F-14: имя пресета за границей 128 — вежливый отказ, БД не вызывается ----


@pytest.mark.parametrize(
    ("name", "case"),
    [
        ("A" * (NAME_LIMIT + 1), "ascii129"),  # классический контрпример F-14
        ("A" * 10_000, "huge10k"),  # огромное имя
        ("Ａ" * (NAME_LIMIT + 1), "fullwidth129"),  # полноширинные: len() == 129
        ("🎉" * (NAME_LIMIT + 1), "emoji129"),  # эмодзи: len() == 129
        ("я" * (NAME_LIMIT + 1), "cyr129"),  # кириллица
        ("A" * (NAME_LIMIT - 1) + "\x00" + "B", "nul129"),  # NUL внутри — > 128
        ("A" * 64 + " " + "B" * 64, "multitoken129"),  # после join — 129
        ("A" * 60 + "\n" + "B" * 68, "newline129"),  # перевод строки между токенами
        ("A" * NAME_LIMIT + "\u202e" + "B", "rtl130"),  # RTL-override
    ],
)
async def test_F14_oversized_preset_name_refused_without_touching_database(
    name: str, case: str
) -> None:
    """F-14: имя >128 символов → вежливый отказ админу, НИ ОДНОГО SQL-запроса
    (БД не вызывается — DataError невозможен в принципе), без краша."""
    core, factory = _admin_core()
    admin_id = app_settings().admin_id
    replies = await core.handle(f"/admin_preset_add evlp {name} {{}}", admin_id)
    _assert_polite_refusal(replies, f"F-14 имя len={len(name)}")
    assert factory.statements() == [], (
        f"F-14: отказ по длине имени всё же дошёл до БД: {factory.statements()!r}"
    )


# --- F-14: slug за границей 255 / вне алфавита — отказ, БД не вызывается -----


@pytest.mark.parametrize(
    ("slug", "case"),
    [
        ("s" * (SLUG_LIMIT + 1), "ascii256"),  # 256 — контрпример F-14
        ("s" * 10_000, "huge10k"),
        ("слаг" * 20, "nonascii"),  # не-ASCII
        ("S" * SLUG_LIMIT, "upper255"),  # верхний регистр вне [a-z0-9_-]
        ("../../etc/passwd", "traversal"),  # path traversal в slug
        ("a\x00b", "nul"),  # NUL в slug
    ],
)
async def test_F14_invalid_preset_slug_refused_without_touching_database(
    slug: str, case: str
) -> None:
    """F-14: slug >255 или вне алфавита → вежливый отказ (формат/лимит), ни
    одного SQL-запроса, без краша."""
    core, factory = _admin_core()
    admin_id = app_settings().admin_id
    replies = await core.handle(f"/admin_preset_add {slug} name {{}}", admin_id)
    _assert_polite_refusal(replies, f"F-14 slug {slug[:20]!r}")
    assert factory.statements() == [], (
        f"F-14: отказ по slug всё же дошёл до БД: {factory.statements()!r}"
    )


# --- F-14: позитивная контроль — границы ровно в лимите принимаются ----------


@pytest.mark.parametrize(
    ("slug", "name", "case"),
    [
        ("evlp", "N" * NAME_LIMIT, "name128"),
        ("s" * SLUG_LIMIT, "n", "slug255"),
        ("evlp2", "N" * (NAME_LIMIT - 1), "name127"),
    ],
)
async def test_F14_boundary_lengths_are_accepted_and_reach_database(
    slug: str, name: str, case: str
) -> None:
    """F-14: позитивная контроль (иначе детектор «БД не вызывается» вакуумен):
    значения в границах лимита сохраняются и SQL-запросы выполняются."""
    core, factory = _admin_core()
    admin_id = app_settings().admin_id
    replies = await core.handle(f"/admin_preset_add {slug} {name} {{}}", admin_id)
    assert any("✅" in str(reply) for reply in replies), (
        f"F-14: имя {len(name)}/slug {len(slug)} в границах отклонены: {replies!r}"
    )
    assert factory.statements(), "F-14: принятый пресет не дошёл до БД (детектор ложно пуст)"


# --- F-14: не-админ — ни ответа, ни БД, даже с вредоносным вводом -----------


async def test_F14_non_admin_oversized_input_gets_no_reply_and_no_database_calls() -> None:
    """SEC-07/F-14: не-админ с вредоносным вводом — молчаливый игнор, БД не
    вызывается (лимиты — не канал обхода админ-контура)."""
    core, factory = _admin_core()
    intruder = app_settings().admin_id + 777_777
    for command in (
        f"/admin_preset_add evilx {'A' * 300} {{}}",
        f"/admin_preset_add {'s' * 300} name {{}}",
        "/admin_preset_list",
    ):
        replies = await core.handle(command, intruder)
        assert replies == [], f"F-14: не-админ получил ответ: {replies!r}"
    assert factory.statements() == [], f"F-14: не-админ дошёл до БД: {factory.statements()!r}"


# --- F-17: коллизию кодов можно сконструировать — и она не перезаписывает ----


def _crafted_collision() -> tuple[str, str]:
    """Реальная коллизия ``preset_code`` без гринда: канонический slug вида
    ``h<sha256(long_slug)[:15]>`` совпадает с хэш-кодом длинного slug."""
    preset_code = load_attr("app.bot.dialog", "preset_code")
    long_slug = "x" * 40  # не в [a-z0-9-]{1,32} → кодируется хэшем
    canonical = "h" + hashlib.sha256(long_slug.encode("utf-8")).hexdigest()[:15]
    assert preset_code(long_slug) == preset_code(canonical), (
        "F-17: контрпример потерял коллизию — пример не воспроизводится"
    )
    return long_slug, canonical


def test_F17_crafted_slug_collision_is_resolved_not_overwritten() -> None:
    """F-17: спроектированная атакующим коллизия кодов не приводит к молчаливой
    перезаписи: карта ``slug → код`` биективна в обоих порядках, детерминирована,
    коды в грамматике и в лимите 64 байт callback_data (CWE-334)."""
    preset_codes = load_attr("app.bot.dialog", "preset_codes")
    encode_callback = load_attr("app.bot.dialog", "encode_callback")
    parse_callback = load_attr("app.bot.dialog", "parse_callback")
    preset_code = load_attr("app.bot.dialog", "preset_code")
    long_slug, canonical = _crafted_collision()

    # негативная контроль: наивная карта молча теряет slug (именно это чинит F-17)
    naive = {preset_code(slug): slug for slug in (long_slug, canonical)}
    assert len(naive) == 1, "F-17: коллизия исчезла — детектор молчаливой перезаписи вакуумен"

    for order in ((long_slug, canonical), (canonical, long_slug)):
        codes = preset_codes(order)
        assert set(codes) == set(order), f"F-17: slug потеряны/добавлены: {codes!r}"
        values = list(codes.values())
        assert len(set(values)) == len(values), f"F-17: коды не различимы (перезапись): {codes!r}"
        assert preset_codes(order) == codes, "F-17: коды недетерминированы"
        for code in values:
            assert CODE_GRAMMAR.fullmatch(code), f"F-17: код {code!r} вне грамматики"
            data = encode_callback("preset", code)
            assert len(data.encode("ascii")) <= 64, f"F-17: callback_data {data!r} > 64 байт"
            assert parse_callback(data) == ("preset", code), f"F-17: {data!r} не парсится"


def test_F17_unresolvable_collision_fails_closed_with_value_error(monkeypatch) -> None:
    """F-17: неразрешимая коллизия (короткий И расширенный код заняты) — явный
    ``ValueError`` (fail-closed), а не молчаливая перезапись чужого slug."""
    dialog = load("app.bot.dialog")
    monkeypatch.setattr(dialog, "preset_code", lambda slug: "dup")
    monkeypatch.setattr(dialog, "_extended_preset_code", lambda slug: "dup")
    with pytest.raises(ValueError, match="collision"):
        dialog.preset_codes(["alpha", "beta"])


async def test_F17_core_fails_closed_on_unresolvable_collision_without_wrong_toggle(
    monkeypatch,
) -> None:
    """F-17: ядро переживает коллизию без краша (fail-closed: кнопки пресетов
    не выдаются), и ни один tap не переключает «не тот» пресет."""
    dialog = load("app.bot.dialog")
    monkeypatch.setattr(dialog, "preset_code", lambda slug: "dup")
    monkeypatch.setattr(dialog, "_extended_preset_code", lambda slug: "dup")
    core = memory_bot()
    admin_id = app_settings().admin_id
    await core.handle("/admin_preset_add alpha A {}", admin_id)
    await core.handle("/admin_preset_add beta B {}", admin_id)
    uid = 750_001

    replies = await core.handle("/settings preset", uid)
    assert replies, "F-17: ядро упало на коллизии кодов"

    answers: list[tuple] = []

    async def answer(text: str, show_alert: bool) -> None:
        answers.append((text, show_alert))

    await core.handle_callback("dlg:preset:dup", uid, answer=answer)
    assert answers and answers[0][0], f"F-17: tap на чужой код не отклонён: {answers!r}"
    profile = core._repo.users[uid].profile
    assert profile.get("presets", []) == [], f"F-17: коллизия переключила пресет: {profile!r}"


# --- F-17: биективность сквозь диалог — коллизирующие пресеты различимы ------


async def test_F17_colliding_presets_toggle_their_own_slug_in_dialog() -> None:
    """F-17: атакующий добавляет пару slug с коллизией кодов (через админ-ввод):
    оба пресета остаются выбираемыми, каждый tap переключает СВОЙ slug."""
    core = memory_bot()
    admin_id = app_settings().admin_id
    long_slug, canonical = _crafted_collision()
    for slug in (long_slug, canonical):
        replies = await core.handle(f"/admin_preset_add {slug} name {{}}", admin_id)
        assert any("✅" in str(reply) for reply in replies), f"F-17: пресет {slug!r} не добавлен"

    uid = 750_100
    replies = await core.handle("/settings preset", uid)
    datas = [
        data for reply in replies for row in getattr(reply, "keyboard", ()) for _label, data in row
    ]
    preset_datas = [
        data for data in datas if data.startswith("dlg:preset:") and not data.endswith("done")
    ]
    assert len(preset_datas) == 2, f"F-17: коллизия спрятала пресет: {datas!r}"
    assert len(set(preset_datas)) == 2, f"F-17: кнопки дублируют callback_data: {preset_datas!r}"

    answers: list[tuple] = []

    async def answer(text: str, show_alert: bool) -> None:
        answers.append((text, show_alert))

    for data in preset_datas:
        answers.clear()
        await core.handle_callback(data, uid, answer=answer)
        assert len(answers) == 1, f"F-17: tap {data!r} не подтверждён: {answers!r}"

    await core.handle_callback("dlg:preset:done", uid, answer=answer)
    chosen = core._repo.users[uid].profile.get("presets", [])
    assert set(chosen) == {long_slug, canonical}, (
        f"F-17: тап по кодам коллизирующих пресетов потерял slug: {chosen!r}"
    )


# --- P-SEC-07 (hypothesis, фиксированный seed): биективность на любом входе --


SLUGS = st.text(max_size=40) | st.from_regex(r"[a-z0-9_-]{1,40}", fullmatch=True)


@settings(derandomize=True, max_examples=150, deadline=None)
@given(st.lists(SLUGS, min_size=1, max_size=8, unique=True))
def test_P_SEC_07_preset_codes_bijective_deterministic_in_grammar(slugs: list[str]) -> None:
    """P-SEC-07/F-17: для любого списка slug коды ``slug → код`` биективны
    (нет молчаливой перезаписи коллизии), детерминированы и в грамматике
    ``[a-z0-9-]{1,32}`` — callback_data не растёт и парсится."""
    preset_codes = load_attr("app.bot.dialog", "preset_codes")
    codes = preset_codes(slugs)
    assert set(codes) == set(slugs), f"P-SEC-07: slug потеряны/добавлены: {codes!r}"
    values = list(codes.values())
    assert len(set(values)) == len(values), f"P-SEC-07: коды не уникальны: {codes!r}"
    assert preset_codes(slugs) == codes, f"P-SEC-07: коды недетерминированы: {codes!r}"
    for code in values:
        assert CODE_GRAMMAR.fullmatch(code), f"P-SEC-07: код {code!r} вне грамматики"
