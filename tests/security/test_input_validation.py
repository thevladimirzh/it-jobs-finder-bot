"""Валидация недоверенного пользовательского ввода и SQL-инъекция.

Угрозы (threat-model §3): SEC-03 (abuse-регистрация), SEC-04 (подделка аргументов
обратной связи), SEC-06 (SQL-инъекция через значения фильтров), SEC-09 (DoS большими
входами), SEC-10 (флуд командами), SEC-12 (SSRF/схемы URL), SEC-13 (небезопасная
десериализация JSONB), SEC-14 (path traversal через parse_tz/файлы).
Свойства P-SEC-02..P-SEC-04 (hypothesis, фиксированный seed).

Контракт: docs/spec/api.md §1, §5, §6, §7, §9, §11; строки ошибок —
docs/spec/decisions.md §4. Тесты красные, пока production-код не реализован.
"""

from __future__ import annotations

import asyncio
import re
from datetime import time as dt_time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from support import (
    REPO_ROOT,
    SQL_PAYLOADS,
    NotImplementedYet,
    bot_session,
    load_attr,
    memory_bot,
    sql_leaks_for,
)

RU_FEEDBACK_ERROR = (
    "Не понял номер. Отправьте номер карточки из последнего дайджеста (например: /like 3)."
)
EN_FEEDBACK_ERROR = (
    "I didn't get the number. Send the card number from your latest digest (e.g. /like 3)."
)

BAD_HHMM = (
    "",
    "9",
    "24:00",
    "23:60",
    "99:99",
    "-1:00",
    "09:30:00",
    "09 30",
    "0930",
    "09:3x",
    "0а:30",  # кириллическая «а»
    "０９:３０",  # полноширинные цифры
    "\x00:30",
    "09:30\n",
    "09:30; DROP TABLE users --",
    "<script>alert(1)</script>",
    "1" * 100_000 + ":00",
    "09:" + "3" * 100,
)

BAD_TZ = (
    "",
    "Not/AZone",
    "UTC+99",
    "UTC+abc",
    "UTC+3<script>",
    "x" * 1_000_000,
    "Europe/Moscow\x00",
    "Europe//Moscow",
    "UTC+3\n",
)

PATH_TRAVERSAL_TZ = (
    "../../../etc/passwd",
    "/etc/passwd",
    "..\\..\\win.ini",
    "././././etc/hosts",
    "zoneinfo/../../../etc/passwd",
)

SQL_SINK_PATTERNS = (
    re.compile(r"(?i)\b(text|execute|executemany|exec_driver_sql)\s*\(\s*f[\"']"),
    re.compile(r"(?i)f[\"'][^\"']*\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)\b"),
    re.compile(r"(?i)\b(text|execute|executemany)\s*\([^)]*\.format\s*\("),
)

UNSAFE_DESERIALIZATION_PATTERNS = (
    re.compile(r"\bpickle\.loads?\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\byaml\.(load|unsafe_load)\s*\("),
    r"\bmarshal\.loads\s*\(",
    r"\bshelve\.open\s*\(",
    r"\bos\.system\s*\(",
    r"shell\s*=\s*True",
)
UNSAFE_RE = tuple(
    re.compile(p) if isinstance(p, str) else p for p in UNSAFE_DESERIALIZATION_PATTERNS
)


def _profile_data() -> dict[str, object]:
    """Валидный профиль в JSONB-формате самого приложения (api.md §5)."""
    profile_cls = load_attr("app.domain.profile", "Profile")
    schedule_cls = load_attr("app.domain.profile", "Schedule")
    profile_to_jsonb = load_attr("app.domain.profile", "profile_to_jsonb")
    profile = profile_cls(
        lang="ru",
        presets=["python-backend"],
        min_salary_rub=None,
        work_format=None,
        stop_words=[],
        digest_size=10,
        schedule=schedule_cls(local_time=dt_time(9, 30), tz="Europe/Moscow"),
    )
    return dict(profile_to_jsonb(profile))


async def _repo_run_one(factory: object, payload: str, index: int) -> None:
    """Серия запросов реального ``Repo`` с недоверенным ``payload`` в значениях."""
    repo_cls = load_attr("app.storage.repo", "Repo")
    tweaks_cls = load_attr("app.filters.rules", "UserTweaks")
    repo = repo_cls(factory)
    tweaks = tweaks_cls(min_salary_rub=None, work_format=payload, stop_words=[payload])
    await repo.upsert_preset(
        f"sec-{index}",
        name=payload,
        filter_json={"role": payload, "stop_words": [payload]},
    )
    await repo.select_candidates(user_id=1, preset_slugs=[f"sec-{index}"], tweaks=tweaks, limit=10)
    await repo.upsert_feedback(user_id=1, vacancy_id=1, action="like")


# --- отрицательный контроль детектора: НАМЕРЕННО уязвимый репозиторий --------


def _vulnerable_run_one(style: str):
    """run_one с интерполяцией payload в SQL-текст (f-string/конкат/.format/kwargs)."""

    async def run_one(factory: object, payload: str, index: int) -> None:
        text = load_attr("sqlalchemy", "text")
        async with factory() as session:  # type: ignore[attr-defined]
            if style == "fstring":
                await session.execute(text(f"SELECT * FROM presets WHERE slug = '{payload}'"))
            elif style == "concat":
                await session.execute(
                    statement=text("SELECT * FROM presets WHERE name = '" + payload + "'")
                )
            elif style == "format":
                template = "SELECT * FROM presets WHERE name LIKE '%{0}%'"
                await session.execute(text(template.format(payload)))
            elif style == "percent":
                template = "SELECT * FROM presets WHERE name LIKE '%%%s%%'"
                await session.execute(text(template % payload))
            else:  # pragma: no cover - защита от опечатки в параметризации
                raise AssertionError(f"неизвестный стиль уязвимости: {style}")

    return run_one


# --- SEC-09: валидация времени/размеров, DoS входами ------------------------


@pytest.mark.parametrize("raw", ["00:00", "09:30", "23:59"])
def test_SEC_09_parse_hhmm_accepts_strict_hhmm(raw: str) -> None:
    parse_hhmm = load_attr("app.domain.profile", "parse_hhmm")
    parsed = parse_hhmm(raw)
    assert isinstance(parsed, dt_time)
    assert parsed == dt_time(*[int(part) for part in raw.split(":")])


@pytest.mark.parametrize("raw", BAD_HHMM)
def test_SEC_09_parse_hhmm_rejects_garbage_and_overflow(raw: str) -> None:
    """SEC-09: мусор/переполнение/unicode во времени — только ValueError, без крашей."""
    parse_hhmm = load_attr("app.domain.profile", "parse_hhmm")
    with pytest.raises(ValueError):
        parse_hhmm(raw)


@pytest.mark.parametrize("raw", BAD_TZ)
def test_SEC_09_parse_tz_rejects_garbage_zones(raw: str) -> None:
    """SEC-09: гигантские/мусорные таймзоны — только ValueError (не KeyError/краш)."""
    parse_tz = load_attr("app.domain.profile", "parse_tz")
    with pytest.raises(ValueError):
        parse_tz(raw)


def test_SEC_09_digest_size_is_bounded_1_to_50() -> None:
    """SEC-09: переполнение digest_size (0/51/-1/10**9) ломает профиль — ValueError."""
    profile_from_jsonb = load_attr("app.domain.profile", "profile_from_jsonb")
    data = _profile_data()
    for bad_size in (0, 51, -1, 10**9, 2**63):
        broken = dict(data)
        broken["digest_size"] = bad_size
        with pytest.raises(ValueError):
            profile_from_jsonb(broken)


async def test_SEC_09_oversized_command_argument_does_not_crash_bot() -> None:
    """SEC-09: аргумент команды на 5000 символов (за лимитом Telegram) не роняет бота."""
    async with bot_session() as session:
        replies = await session.send("/like " + "9" * 5000, user_id=500_001)
        assert isinstance(replies, list), "SEC-09: бот упал на переполненном аргументе"
        for reply in replies:
            assert reply in (RU_FEEDBACK_ERROR, EN_FEEDBACK_ERROR), (
                f"SEC-09: неожиданный ответ на переполненный аргумент: {reply!r}"
            )
        alive = await session.send("/settings", user_id=500_001)
        assert isinstance(alive, list), "SEC-09: бот не ожил после переполненного ввода"


# --- SEC-14: path traversal через таймзоны/файлы -----------------------------


@pytest.mark.parametrize("raw", PATH_TRAVERSAL_TZ)
def test_SEC_14_parse_tz_rejects_path_traversal(raw: str) -> None:
    """SEC-14: ключ таймзоны не может быть путём к файлу (zoneinfo lookup)."""
    parse_tz = load_attr("app.domain.profile", "parse_tz")
    with pytest.raises(ValueError):
        parse_tz(raw)


def test_SEC_14_app_does_not_build_paths_from_untrusted_input() -> None:
    """SEC-14: в app/ нет open()/Path с f-путями из недоверенного ввода."""
    config_py = REPO_ROOT / "app" / "config.py"
    if not config_py.is_file():
        raise NotImplementedYet("app/config.py ещё не реализован")
    path_sink = re.compile(r"(?i)(open|read_text|write_text|read_bytes|Path)\s*\(")
    unsafely_built = re.compile(r"f[\"']|\.format\s*\(|\+\s*(raw|text|value|name)")
    violations: list[str] = []
    for path in sorted((REPO_ROOT / "app").rglob("*.py")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if path_sink.search(line) and unsafely_built.search(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line.strip()[:80]}")
    assert not violations, f"SEC-14: путь строится из недоверенного ввода: {violations}"


# --- SEC-13: десериализация JSONB -------------------------------------------


def test_SEC_13_broken_jsonb_raises_only_value_error() -> None:
    """SEC-13: битый JSONB профиля — ValueError, никаких TypeError/крашей."""
    profile_from_jsonb = load_attr("app.domain.profile", "profile_from_jsonb")
    data = _profile_data()
    broken_variants = (
        {},
        {"lang": "ru"},
        dict(data, lang="klingon"),
        dict(data, schedule="09:30"),
        dict(data, stop_words="не список"),
        dict(data, presets={"a": 1}),
        dict(data, digest_size=None),
    )
    for broken in broken_variants:
        with pytest.raises(ValueError):
            profile_from_jsonb(broken)


def test_SEC_13_no_unsafe_deserialization_or_shell_in_app() -> None:
    """SEC-13: запрещён pickle/eval/exec/yaml.load/marshal и shell=True в app/."""
    config_py = REPO_ROOT / "app" / "config.py"
    if not config_py.is_file():
        raise NotImplementedYet("app/config.py ещё не реализован")
    violations: list[str] = []
    for path in sorted((REPO_ROOT / "app").rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern in UNSAFE_RE:
                if pattern.search(line):
                    violations.append(f"{rel}:{line_no}: {line.strip()[:80]}")
    assert not violations, f"SEC-13: небезопасная десериализация/исполнение: {violations}"


# --- SEC-06: SQL-инъекция ----------------------------------------------------


def test_SEC_06_no_string_interpolation_in_sql_sinks() -> None:
    """SEC-06: запрещён f-string/.format в SQL-запросах (только bind-параметры)."""
    repo_py = REPO_ROOT / "app" / "storage" / "repo.py"
    if not repo_py.is_file():
        raise NotImplementedYet("app/storage/repo.py ещё не реализован")
    violations: list[str] = []
    for path in sorted((REPO_ROOT / "app").rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern in SQL_SINK_PATTERNS:
                if pattern.search(line):
                    violations.append(f"{rel}:{line_no}: {line.strip()[:80]}")
    assert not violations, f"SEC-06: SQL собирается строковой интерполяцией: {violations}"


async def test_SEC_06_filter_values_never_reach_sql_text() -> None:
    """SEC-06: SQL-пейлоады в значениях фильтров живут только в bind-параметрах."""
    leaks = await sql_leaks_for(list(SQL_PAYLOADS), _repo_run_one)
    assert not leaks, f"SEC-06: значения фильтров попали в текст SQL: {leaks}"


@pytest.mark.parametrize("style", ["fstring", "concat", "format", "percent"])
async def test_SEC_06_detector_catches_interpolated_sql(style: str) -> None:
    """SEC-06: отрицательный контроль — интерполяция в SQL обязана фиксироваться.

    Если этот тест падает — детектор ослаблен: настоящие SQL-инъекции
    («'; DROP TABLE ...» и пр. из SQL_PAYLOADS) перестанут ловиться.
    """
    leaks = await sql_leaks_for(list(SQL_PAYLOADS), _vulnerable_run_one(style))
    assert leaks, (
        f"SEC-06: детектор не заметил интерполяцию payload в SQL (стиль {style}) — "
        "покрытие SQL-инъекций потеряно"
    )
    assert any("DROP TABLE" in leak for leak in leaks), (
        f"SEC-06: классический пейлоад «'; DROP TABLE ...» не найден: {leaks}"
    )


SQL_SKELETON_COINCIDENCES: tuple[str, ...] = (
    "O",  # буква из «INSERT INTO» / «FROM»
    "_",  # символ из bind-плейсхолдеров %(user_id)s
    ":",
    "%",
    "S",
    "SELECT",
    "INTO",
    "VALUES",
    "users",
    "presets",
    "action",
    "%(user_id)s",
)


async def test_SEC_06_detector_ignores_sql_skeleton_coincidences() -> None:
    """SEC-06: нормализация детектора — совпадение со «скелетом» SQL не утечка.

    Регресс F-13: односимвольные payload'ы («O», «_») раньше ложно срабатывали
    на подстроке SQL-скелета; теперь сравнивается с baseline-прогоном.
    """
    leaks = await sql_leaks_for(list(SQL_SKELETON_COINCIDENCES), _repo_run_one)
    assert not leaks, f"SEC-06: ложные срабатывания детектора на скелете SQL: {leaks}"


# --- SEC-12: SSRF, схемы URL -------------------------------------------------


def test_SEC_12_canonicalize_url_allows_only_http_schemes() -> None:
    """SEC-12: file:/javascript:/data: не становятся ссылками (SSRF/XSS)."""
    canonicalize_url = load_attr("app.collectors", "canonicalize_url")
    raw_urls = (
        "file:///etc/passwd",
        "FILE:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "ftp://evil.example/x",
        "gopher://evil.example:70/x",
        "dict://evil.example:2628/x",
    )
    for raw in raw_urls:
        canonical = canonicalize_url(raw)
        lowered = canonical.lower().strip()
        for scheme in ("file:", "javascript:", "data:", "vbscript:", "ftp:", "gopher:", "dict:"):
            assert not lowered.startswith(scheme), (
                f"SEC-12: схема {scheme} прошла canonicalize_url({raw!r}) = {canonical!r}"
            )


# --- SEC-04: подделка аргументов обратной связи ------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "/like",
        "/like 0",
        "/like -1",
        "/like 1.5",
        "/like ٣",
        "/like ①",
        "/like 9223372036854775807",
        "/like 99999999999999999999",
        "/like <script>alert(1)</script>",
        "/like 1; DROP TABLE feedback --",
        "/dislike 1' OR '1'='1",
        "/bookmark ../../../3",
    ],
)
async def test_SEC_04_feedback_argument_garbage_gets_fixed_error(command: str) -> None:
    """SEC-04: мусорный n — фиксированная ошибка, без крашей и инъекций в ответ."""
    async with bot_session() as session:
        replies = await session.send(command, user_id=500_002)
    assert replies in ([RU_FEEDBACK_ERROR], [EN_FEEDBACK_ERROR]), (
        f"SEC-04: ответ на {command!r} не по шаблону ошибки: {replies!r}"
    )
    for reply in replies:
        assert "<script" not in reply.lower(), f"SEC-04: инъекция в ответ: {reply!r}"


# --- SEC-03 / SEC-10: abuse и флуд ------------------------------------------


async def test_SEC_03_mass_registration_is_bounded_and_stable() -> None:
    """SEC-03: массовые /start от разных пользователей не роняют бота и ограничены."""
    async with bot_session() as session:
        for index in range(15):
            replies = await session.send("/start", user_id=500_100 + index)
            assert isinstance(replies, list), f"SEC-03: краш на /start пользователя {index}"
            assert len(replies) <= 5, f"SEC-03: раздутый ответ на /start: {replies!r}"
        for _ in range(5):
            replies = await session.send("/start", user_id=500_200)
            assert len(replies) <= 5, f"SEC-03: раздутый ответ на повторный /start: {replies!r}"


async def test_SEC_10_feedback_flood_triggers_silent_mute() -> None:
    """SEC-10: флуд командами упирается в антиспам (30 действий/мин → тихий мьют)."""
    async with bot_session() as session:
        replies = [await session.send("/like 1", user_id=500_300) for _ in range(40)]
    muted = [reply for reply in replies[30:] if reply == []]
    assert muted, (
        f"SEC-10: флуд 40 командами не заглушен антиспамом (AC-16): ответы 31-40 = {replies[30:]!r}"
    )


# --- P-SEC-02..P-SEC-04 (hypothesis, фиксированный seed) ---------------------


JSONISH = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=20),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=15,
)


@settings(derandomize=True, max_examples=150, deadline=None)
@given(JSONISH)
def test_P_SEC_02_profile_from_jsonb_never_raises_anything_but_value_error(data: object) -> None:
    """P-SEC-02: любой JSON-подобный вход → Profile или ValueError, ничего иного."""
    profile_from_jsonb = load_attr("app.domain.profile", "profile_from_jsonb")
    try:
        profile = profile_from_jsonb(data)  # type: ignore[arg-type]
    except ValueError:
        return
    assert profile.lang in ("ru", "en")
    assert 1 <= profile.digest_size <= 50


@settings(derandomize=True, max_examples=150, deadline=None)
@given(st.text(max_size=200))
def test_P_SEC_03_url_and_text_normalization_never_crash(raw: str) -> None:
    """P-SEC-03: canonicalize_url/normalize_text не падают и не дают «ломающего» URL."""
    canonicalize_url = load_attr("app.collectors", "canonicalize_url")
    normalize_text = load_attr("app.collectors", "normalize_text")
    canonical = canonicalize_url(raw)
    assert isinstance(canonical, str), f"P-SEC-03: canonicalize_url вернул {type(canonical)}"
    for bad_char in ('"', "'", "<", ">", "\x00"):
        assert bad_char not in canonical, f"P-SEC-03: {bad_char!r} в URL {canonical!r}"
    assert not any(ch.isspace() or ord(ch) < 0x20 for ch in canonical), (
        f"P-SEC-03: пробел/управляющий символ в URL {canonical!r} (вход {raw!r})"
    )
    normalized = normalize_text(raw)
    assert isinstance(normalized, str), f"P-SEC-03: normalize_text вернул {type(normalized)}"


@settings(derandomize=True, max_examples=100, deadline=None)
@given(st.text(max_size=60).filter(lambda value: value.strip() != ""))
def test_P_SEC_04_arbitrary_filter_value_never_enters_sql_text(payload: str) -> None:
    """P-SEC-04: любое значение фильтра живёт только в bind-параметрах запроса."""
    leaks = asyncio.run(sql_leaks_for([payload], _repo_run_one))
    assert not leaks, f"P-SEC-04: {leaks}"


# --- регрессия контрпримеров ревью (находки закрыты, тесты — постоянные) -----
#
# Бывшие xfail-контрпримеры F-10/F-11: дефекты исправлены (лимиты стоп-слов,
# отказ на глубоко вложенном JSON), тесты переведены в обычные без ослабления
# assert'ов. Находки: docs/security/report.md.


async def test_SEC_09_stop_words_are_bounded_in_count_and_length() -> None:
    """SEC-09/SEC-10: профиль не растёт без ограничений при флуде стоп-словами."""
    antispam_cls = load_attr("app.bot.antispam", "Antispam")
    core = memory_bot(antispam=antispam_cls(limit=10**6))
    uid = 500_400
    await core.handle("/start", uid)
    for index in range(80):
        await core.handle("/settings stop", uid)
        await core.handle(f"word{index}-" + "x" * 300, uid)
    words = core._repo.users[uid].profile["stop_words"]
    assert len(words) <= 50, f"SEC-09: {len(words)} стоп-слов в профиле (лимит 50)"
    oversized = [word for word in words if len(word) > 100]
    assert not oversized, f"SEC-09: стоп-слова без лимита длины: {[len(w) for w in oversized[:5]]}"


def test_SEC_13_deeply_nested_preset_json_is_contained() -> None:
    """SEC-13: глубоко вложенный JSON пресета — отказ, но не RecursionError/краш."""
    parse = load_attr("app.bot.core", "_parse_preset_command")
    payload = "/admin_preset_add slug name " + '{"a": ' + "[" * 4000
    try:
        result = parse(payload, with_name=True)
    except ValueError:
        result = (None, "", None)  # контракт §5.3 допускает ValueError
    assert result == (None, "", None), f"SEC-13: вложенный JSON дал {result!r}"
