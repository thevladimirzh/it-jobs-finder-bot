"""Юнит-тесты антиспама, команд обратной связи и i18n.

U-AS-01/02/03 (лимиты, мьют, злоупотребления), U-BTN-01/02 (валидация n,
upsert feedback), U-I18N-01 (паритет ключей RU/EN).
"""

from __future__ import annotations

import time

from app.bot.antispam import Antispam
from app.bot.core import BotCore
from app.i18n import keys, t
from app.services.last_digest import record as record_last_digest

FEEDBACK_ERROR = (
    "Не понял номер. Отправьте номер карточки из последнего дайджеста (например: /like 3)."
)


class _Item:
    def __init__(self, n: int, vacancy_id: int) -> None:
        self.n = n

        class _V:
            id = vacancy_id

        self.vacancy = _V()


class _Preset:
    def __init__(self, slug: str, name_ru: str) -> None:
        self.slug = slug
        self.name_ru = name_ru
        self.filter_json: dict = {}


class _Repo:
    """Минимальный репозиторий для BotCore (api.md §9)."""

    def __init__(self) -> None:
        self.users: dict[int, object] = {}
        self.feedback: dict[tuple[int, int], str] = {}
        self.presets: list[_Preset] = []

    async def get_user(self, user_id):
        return self.users.get(user_id)

    async def upsert_user(self, user_id, *, lang, profile):
        self.users[user_id] = _StoredUser(user_id, lang, profile)
        return self.users[user_id]

    async def set_profile(self, user_id, profile):
        return None

    async def upsert_feedback(self, *, user_id, vacancy_id, action):
        self.feedback[(user_id, vacancy_id)] = action

    async def list_presets(self):
        return list(self.presets)

    async def upsert_preset(self, slug, *, name, filter_json):
        self.presets = [p for p in self.presets if p.slug != slug]
        preset = _Preset(slug, name)
        preset.filter_json = filter_json
        self.presets.append(preset)

    async def admin_stats(self):
        class _S:
            users = 0
            like = 0
            dislike = 0
            bookmark = 0

        return _S()


class _StoredUser:
    def __init__(self, user_id, lang, profile) -> None:
        self.id = user_id
        self.lang = lang
        self.profile = profile


def _core() -> tuple[BotCore, _Repo]:
    repo = _Repo()
    return BotCore(repo=repo), repo


def _stored(repo: _Repo, user_id: int, key: str) -> object:
    """Поле профиля из хранилища: до первого сохранения — Profile, после — dict."""
    profile = repo.users[user_id].profile
    return profile[key] if isinstance(profile, dict) else getattr(profile, key)


# --- U-AS-01 (R14): лимит 30/мин, мьют 10 мин --------------------------------


def test_u_as01_limit_mute_and_expiry(monkeypatch) -> None:
    base = time.monotonic()
    offset = {"seconds": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: base + offset["seconds"])
    antispam = Antispam()
    assert all(antispam.allow(1) for _ in range(30))
    assert antispam.allow(1) is False  # 31-е действие → тихий мьют
    assert antispam.allow(1) is False
    offset["seconds"] = 600.0  # мьют истёк
    assert antispam.allow(1) is True


# --- U-AS-02 (R33): in-memory счётчики сбрасываются новым процессом ----------


def test_u_as02_counters_live_in_process_memory() -> None:
    first = Antispam()
    assert all(first.allow(2) for _ in range(30))
    assert first.allow(2) is False
    assert Antispam().allow(2) is True  # «рестарт»: состояние потеряно (R33)


# --- U-AS-03 (R17): злоупотребление не деградирует на других пользователей ---


def test_u_as03_abuse_does_not_affect_other_users() -> None:
    antispam = Antispam()
    for _ in range(35):
        antispam.allow(100)
    assert antispam.allow(100) is False
    assert antispam.allow(200) is True


# --- U-SEC-05 (F-16, CWE-770): крыша памяти Antispam -------------------------


def test_u_sec05_antispam_memory_is_bounded(monkeypatch) -> None:
    """_stamps/_muted_until не растут бесконечно: лимит + вытеснение (F-16)."""
    base = time.monotonic()
    offset = {"seconds": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: base + offset["seconds"])
    antispam = Antispam(limit=1, max_users=3)
    for user_id in range(1, 21):
        assert antispam.allow(user_id) is True, f"U-SEC-05: свежий пользователь {user_id} отклонён"
        assert antispam.allow(user_id) is False, f"U-SEC-05: флуд {user_id} не замьючен"
        assert len(antispam._stamps) <= 3, f"U-SEC-05: _stamps вырос до {len(antispam._stamps)}"
        assert len(antispam._muted_until) <= 3, (
            f"U-SEC-05: _muted_until вырос до {len(antispam._muted_until)}"
        )
    # мьют внутри крыши работает как раньше
    assert antispam.allow(1000) is True
    assert antispam.allow(1000) is False
    assert antispam.allow(1001) is True, "U-SEC-05: мьют одного пользователя задел другого"


def test_u_sec05_antispam_prunes_expired_entries(monkeypatch) -> None:
    """Просроченные метки/мьюты удаляются под давлением лимита (F-16)."""
    base = time.monotonic()
    offset = {"seconds": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: base + offset["seconds"])
    antispam = Antispam(limit=1, window_seconds=60.0, mute_seconds=600.0, max_users=3)
    antispam.allow(1)
    antispam.allow(1)  # мьют пользователя 1
    assert antispam.allow(1) is False
    offset["seconds"] = 700.0  # окно и мьют истекли
    for user_id in range(2, 6):
        antispam.allow(user_id)  # давление лимита запускает чистку
    assert 1 not in antispam._stamps, f"U-SEC-05: метки не вычищены: {list(antispam._stamps)!r}"
    assert 1 not in antispam._muted_until, (
        f"U-SEC-05: истёкший мьют не вычищен: {antispam._muted_until!r}"
    )
    assert antispam.allow(1) is True, "U-SEC-05: вычищенный мьют продолжает блокировать"


# --- U-BTN-01/02 (R5, R26): валидация n и upsert feedback -------------------


def test_u_btn01_feedback_number_validation_and_upsert() -> None:
    import asyncio

    core, repo = _core()
    record_last_digest(501, [_Item(1, 11), _Item(2, 12), _Item(3, 13)])

    async def go() -> None:
        ok = await core.handle("/like 2", 501)
        assert ok == ["\U0001f44d Учтено"]
        again = await core.handle("/dislike 2", 501)  # upsert: последнее действие побеждает
        assert again == ["\U0001f44e Учтено"]
        for bad in ("/like", "/like abc", "/like 0", "/like 4", "/like 01", "/like ٣", "/bookmark"):
            assert await core.handle(bad, 501) == [FEEDBACK_ERROR], bad
        assert await core.handle("/like 2 extra args", 501) == ["\U0001f44d Учтено"]

    asyncio.run(go())
    # одна запись на пару (user, vacancy): последнее действие перезаписало прежние
    assert repo.feedback == {(501, 12): "like"}


def test_u_btn02_feedback_records_vacancy_from_latest_digest() -> None:
    import asyncio

    core, repo = _core()
    record_last_digest(502, [_Item(1, 21)])
    asyncio.run(core.handle("/bookmark 1", 502))
    assert repo.feedback == {(502, 21): "bookmark"}


# --- U-ESC-01/02 (AC-12, F-09): render-пути экранируют чужой текст ------------


def test_u_esc01_display_escapes_profile_strings() -> None:
    import asyncio

    from app.textutil import esc

    core, repo = _core()
    payload = '</b><a href="http://evil.example/">CLICK ME'

    async def go() -> tuple[str, str]:
        await core.handle("/start", 503)
        await core.handle("/settings stop", 503)
        await core.handle(payload, 503)
        from_dialog = "\n".join(await core.handle("/settings", 503))
        # поля из JSONB (presets/work_format) тоже чужой текст
        stored = repo.users[503].profile
        stored["presets"] = [payload]
        stored["work_format"] = payload
        from_jsonb = "\n".join(await core.handle("/settings", 503))
        return from_dialog, from_jsonb

    from_dialog, from_jsonb = asyncio.run(go())
    for label, joined in (("диалог", from_dialog), ("jsonb", from_jsonb)):
        assert esc(payload) in joined, (
            f"U-ESC-01[{label}]: текст не в экранированном виде: {joined!r}"
        )
        assert payload not in joined, f"U-ESC-01[{label}]: сырой текст в /settings: {joined!r}"
        assert "<a href" not in joined, f"U-ESC-01[{label}]: чужая разметка в ответе: {joined!r}"


def test_u_esc02_admin_preset_list_escapes_name_ru() -> None:
    import asyncio

    from app.config import settings
    from app.textutil import esc

    core, _repo = _core()
    name_payload = '<a href="http://evil.example/">X'

    async def go() -> list[str]:
        await core.handle(f"/admin_preset_add evil {name_payload} {{}}", user_id=settings.admin_id)
        return await core.handle("/admin_preset_list", user_id=settings.admin_id)

    replies = asyncio.run(go())
    assert replies, "U-ESC-02: /admin_preset_list не ответил"
    joined = "\n".join(replies)
    assert name_payload not in joined, f"U-ESC-02: сырой name_ru в выводе: {joined!r}"
    assert esc(name_payload) in joined, f"U-ESC-02: name_ru не экранирован: {joined!r}"
    assert "<a href" not in joined, f"U-ESC-02: чужая разметка в ответе: {joined!r}"


# --- U-LIM-01/02 (F-10, SEC-09/SEC-10): лимиты списковых вводов диалога -------


def test_u_lim01_stop_words_bounded_in_count_and_length() -> None:
    import asyncio

    from app.i18n import t as translate

    repo = _Repo()
    core = BotCore(repo=repo, antispam=Antispam(limit=10**6))

    async def go() -> None:
        await core.handle("/start", 504)
        # (а) слово длиннее 100 символов — вежливый отказ, профиль не меняется
        await core.handle("/settings stop", 504)
        replies = await core.handle("w" * 101, 504)
        assert replies == [translate("prompt.stop", "ru")], (
            f"U-LIM-01: отказ не в стиле ответов: {replies!r}"
        )
        assert _stored(repo, 504, "stop_words") == [], "U-LIM-01: длинное слово попало в профиль"
        # (б) флуд: 80 коротких слов подряд → в профиле ≤50
        for index in range(80):
            await core.handle("/settings stop", 504)
            await core.handle(f"word{index}", 504)
        words = _stored(repo, 504, "stop_words")
        assert len(words) <= 50, f"U-LIM-01: {len(words)} стоп-слов (лимит 50)"
        assert all(len(word) <= 100 for word in words), "U-LIM-01: слово длиннее 100 в профиле"
        # (в) после отказа профиль не растёт
        await core.handle("/settings stop", 504)
        replies = await core.handle("word80", 504)
        assert replies == [translate("prompt.stop", "ru")], (
            f"U-LIM-01: нет отказа на лимите: {replies!r}"
        )
        assert len(_stored(repo, 504, "stop_words")) <= 50, "U-LIM-01: профиль вырос за лимит"

    asyncio.run(go())


def test_u_lim02_preset_subscriptions_bounded() -> None:
    import asyncio

    from app.bot.dialog import preset_code
    from app.i18n import t as translate

    repo = _Repo()
    repo.presets = [_Preset(f"slug{index}", f"P{index}") for index in range(51)]
    core = BotCore(repo=repo, antispam=Antispam(limit=10**6))

    async def tap(slug: str) -> list:
        answers: list = []

        async def answer(text: str, show_alert: bool) -> None:
            answers.append((text, show_alert))

        await core.handle_callback(f"dlg:preset:{preset_code(slug)}", 505, answer=answer)
        return answers

    async def go() -> None:
        await core.handle("/start", 505)
        await core.handle("/settings preset", 505)  # I-2: шаг пресетов — мультивыбор кнопками
        for index in range(50):
            answers = await tap(f"slug{index}")
            assert answers == [("", False)], f"U-LIM-02: тап slug{index}: {answers!r}"
        # 51-й пресет — отказ «в стиле подсказки шага» (лимит подписок F-10)
        answers = await tap("slug50")
        assert answers == [(translate("prompt.preset", "ru"), False)], (
            f"U-LIM-02: нет отказа: {answers!r}"
        )
        await core.handle_callback("dlg:preset:done", 505, answer=_silent)
        assert len(_stored(repo, 505, "presets")) == 50
        assert "slug50" not in _stored(repo, 505, "presets"), "U-LIM-02: подписка 51-я добавлена"

    asyncio.run(go())


async def _silent(text: str, show_alert: bool) -> None:
    """Слив подтверждения callback для тестовых нажатий без проверки тоста."""
    return None


# --- U-JSON-01 (F-11, SEC-13): глубоко вложенный JSON пресета — отказ ---------


def test_u_json01_deeply_nested_preset_json_is_contained() -> None:
    import asyncio

    from app.bot.core import _parse_preset_command
    from app.config import settings

    payload = "/admin_preset_add slug name " + '{"a": ' + "[" * 4000
    try:
        result = _parse_preset_command(payload, with_name=True)
    except ValueError:  # контракт §5.3 допускает ValueError
        result = (None, "", None)
    assert result == (None, "", None), f"U-JSON-01: вложенный JSON дал {result!r}"
    # обработчик отвечает «Формат: …», а не падает
    core, _repo = _core()
    replies = asyncio.run(core.handle(payload, settings.admin_id))
    assert replies == ["Формат: /admin_preset_add <slug> <name> <json>"], (
        f"U-JSON-01: обработчик ответил {replies!r}"
    )


# --- U-BOT-02 (F-10 сопутствующий): слот профиля хранит JSONB ----------------


def test_u_bot02_ensure_user_stores_profile_as_jsonb() -> None:
    """Профиль в хранилище — JSONB (users.profile): dict, а не объект Profile."""
    import asyncio
    from collections.abc import Mapping

    from app.domain.profile import REQUIRED_KEYS

    core, repo = _core()
    asyncio.run(core.handle("/start", 506))
    stored = repo.users[506].profile
    assert isinstance(stored, Mapping), (
        f"U-BOT-02: профиль хранится как {type(stored).__name__}, не JSONB"
    )
    assert set(stored) >= set(REQUIRED_KEYS), f"U-BOT-02: неполный JSONB: {sorted(stored)}"


# --- U-SEC-04 (F-14, models.PresetRow): имя ≤128, slug ≤255 — вежливый отказ ---

NAME_REFUSAL = "Имя пресета слишком длинное (максимум 128 символов)"
SLUG_REFUSAL = "Slug слишком длинный (максимум 255 символов)"


def test_u_sec04_preset_name_length_gives_polite_refusal() -> None:
    """Имя пресета (name_ru VARCHAR(128)) не роняет БД DataError (F-14)."""
    import asyncio

    from app.config import settings

    core, repo = _core()

    async def go() -> None:
        # (а) имя 129 символов — вежливый отказ, запись не создаётся
        replies = await core.handle(f"/admin_preset_add p {'А' * 129} {{}}", settings.admin_id)
        assert replies == [NAME_REFUSAL], f"U-SEC-04: отказ не вежливый: {replies!r}"
        assert repo.presets == [], "U-SEC-04: пресет с длинным именем записан"
        # (б) граница: ровно 128 символов — принимается
        replies = await core.handle(f"/admin_preset_add p {'А' * 128} {{}}", settings.admin_id)
        assert replies == ["\u2705 Пресет p добавлен"], f"U-SEC-04: имя 128 отклонено: {replies!r}"
        assert [preset.name_ru for preset in repo.presets] == ["А" * 128], (
            f"U-SEC-04: имя 128 не сохранено: {repo.presets!r}"
        )

    asyncio.run(go())


def test_u_sec04_preset_slug_length_gives_polite_refusal() -> None:
    """Slug (VARCHAR(255)) и имя-fallback = slug тоже ограничены (F-14)."""
    import asyncio

    from app.config import settings

    core, repo = _core()

    async def go() -> None:
        # (а) без имени имя-fallback = slug (200 > 128) — вежливый отказ
        slug200 = "s" + "a" * 199
        replies = await core.handle(f"/admin_preset_add {slug200} {{}}", settings.admin_id)
        assert replies == [NAME_REFUSAL], f"U-SEC-04: fallback-имя не отклонено: {replies!r}"
        assert repo.presets == [], "U-SEC-04: пресет записан после отказа"
        # (б) /admin_preset_edit с неизвестным slug 200 — тот же путь fallback-имени
        replies = await core.handle(f"/admin_preset_edit {slug200} {{}}", settings.admin_id)
        assert replies == [NAME_REFUSAL], f"U-SEC-04: edit не отклонён: {replies!r}"
        assert repo.presets == [], "U-SEC-04: edit записал пресет после отказа"
        # (в) slug 256 символов за грамматикой/колонкой — вежливый отказ, не краш
        replies = await core.handle(f"/admin_preset_add {'s' * 256} n {{}}", settings.admin_id)
        assert replies and "Формат:" in replies[0], f"U-SEC-04: slug 256: {replies!r}"
        # (г) граница: slug 255 с коротким именем — принимается
        slug255 = "s" * 255
        replies = await core.handle(f"/admin_preset_add {slug255} n {{}}", settings.admin_id)
        expected = "\u2705 Пресет " + slug255 + " добавлен"
        assert replies == [expected], f"U-SEC-04: slug 255: {replies!r}"
        # (д) прямая проверка лимита slug (defensive: models.slug VARCHAR(255))
        from app.bot.core import _preset_size_problem

        assert _preset_size_problem("s" * 256, "n") == SLUG_REFUSAL, (
            f"U-SEC-04: лимит slug не проверяется: {_preset_size_problem('s' * 256, 'n')!r}"
        )
        assert _preset_size_problem("s" * 255, "n") is None, "U-SEC-04: slug 255 отклонён"

    asyncio.run(go())


# --- U-I18N-01 (R39): паритет словарей ---------------------------------------


def test_u_i18n01_key_parity_and_totality() -> None:
    assert keys("ru") == keys("en")
    for key in sorted(keys("ru")):
        assert t(key, "ru").strip()
        assert t(key, "en").strip()
    try:
        t("нет такого ключа", "ru")
    except KeyError:
        pass
    else:  # pragma: no cover - контракт api.md §3
        raise AssertionError("t() вернул строку для неизвестного ключа")
