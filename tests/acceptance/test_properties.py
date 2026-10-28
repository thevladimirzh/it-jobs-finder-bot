"""Property-тесты acceptance-уровня (hypothesis, фиксированный seed).

Свойства запланированы реестром рисков (docs/risk-register.md): P-COL-01/02,
P-SAL-01/02, P-AGE-01, P-DIG-01/03/04, P-TEX-01, P-UX-01/02, P-SES-01,
P-SEL-01/02, P-SEND-01, P-BTN-01, P-DED-01, P-SCH-01, P-AS-01, P-I18N-01.
Security-свойства P-SEC-* пишет security-engineer (tests/security) — здесь их нет.

Конвенции: ``derandomize=True`` (фиксированный seed), ``deadline=None``;
hypothesis не даёт async-тестов — корутины гоняются через ``fakes.run``.
P-BTN-01 переписан под актуальный контракт (решение Q1): кнопок нет, обратная
связь — командами ``/like|/dislike|/bookmark <n>``. P-SEL-01/02 идут на
InMemoryRepo (модель документированной семантики Repo): под тестом — логика
``select_digest``/``check_schedules``; гарантии хранилища — U-SEL-*/E2E-*.
"""

from __future__ import annotations

import html
import re
import string
from datetime import UTC, date, datetime, timedelta

from dialog import onboard
from fakes import (
    AGE_EN,
    AGE_RU,
    EMPTY_DIGEST_EN,
    EMPTY_DIGEST_RU,
    FEEDBACK_ERROR_RU,
    FEEDBACK_OK,
    PERMISSIVE_FILTER,
    PRESET_NAMES_RU,
    FakeAlertSink,
    FakeClient,
    FakeResponse,
    FakeSender,
    FakeThrottle,
    FloodWaitError,
    InMemoryRepo,
    ProbeSessionFactory,
    expected_card,
    expected_header,
    expected_salary_line,
    make_digest_item,
    make_profile,
    make_salary,
    make_schedule,
    make_vacancy,
    model_profile_of,
    run,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from support import assert_no_raw_markup, load_attr

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
ON_DATE = date(2026, 3, 14)

AMOUNT = r"\d(?:[\d ]*\d)?"
CUR = r"(?:₽|\$|€|[A-Z]{3})"
RU_SALARY_RE = re.compile(
    rf"^(?:от {AMOUNT} {CUR}|до {AMOUNT} {CUR}|{AMOUNT} \u2013 {AMOUNT} {CUR}|Зарплата не указана)$"
)
EN_SALARY_RE = re.compile(
    rf"^(?:from {AMOUNT} {CUR}|up to {AMOUNT} {CUR}|{AMOUNT} \u2013 {AMOUNT} {CUR}"
    rf"|Salary not specified)$"
)
BROKEN_ENTITY_RE = re.compile(r"&(?!#?\w+;)")

TZ_NAMES = (
    "Europe/Moscow",
    "Europe/Berlin",
    "America/New_York",
    "Asia/Tokyo",
    "UTC",
    "UTC+3",
    "UTC-5",
)


# --- P-COL-01 (R1/R2/R40): collect либо ≥1 вакансия, либо ошибка источника ----


@settings(derandomize=True, max_examples=120, deadline=None)
@given(page=st.text(max_size=400))
def test_P_COL_01_collect_never_empty_never_unexpected_error(page: str) -> None:
    """P-COL-01: collect() никогда не возвращает [] и не падает иным исключением."""
    collectors = load_attr("app.collectors", "build_collectors")
    catalog = tuple(
        load_attr("app.collectors", name)
        for name in ("ParseError", "SourceBlocked", "EmptyResult", "SourceUnavailable")
    )
    collector = next(c for c in collectors() if c.name == "hh.ru")
    client = FakeClient(fallback=FakeResponse(text=page))
    try:
        vacancies = run(collector.collect(client))
    except catalog:
        return
    assert vacancies, f"P-COL-01: collect вернул пустой список для {page!r}"


# --- P-COL-02 (R28): артефакты фикстур не роняют парсер ----------------------


@settings(derandomize=True, max_examples=120, deadline=None)
@given(
    artifact=st.one_of(
        st.text(max_size=120),
        st.binary(max_size=200).map(lambda raw: raw.decode("latin-1")),
        st.just(""),
        st.just("\ufeff"),
        st.just(" \n\t "),
    )
)
def test_P_COL_02_fixture_artifacts_never_crash(artifact: str) -> None:
    """P-COL-02: пустой/BOM/mojibake/мусор — ошибка источника, не падение парсера."""
    collectors = load_attr("app.collectors", "build_collectors")
    catalog = tuple(
        load_attr("app.collectors", name)
        for name in ("ParseError", "SourceBlocked", "EmptyResult", "SourceUnavailable")
    )
    collector = next(c for c in collectors() if c.name == "hh.ru")
    client = FakeClient(fallback=FakeResponse(text=artifact))
    try:
        vacancies = run(collector.collect(client))
    except catalog:
        return
    assert vacancies, f"P-COL-02: пустой возврат молча для артефакта {artifact!r}"


# --- P-SAL-01 (R8): parse_salary/format_salary — тотальны и форматно строги ---


@settings(derandomize=True, max_examples=200, deadline=None)
@given(raw=st.text(max_size=120))
def test_P_SAL_01_parse_and_format_salary_are_total(raw: str) -> None:
    """P-SAL-01: ни одно исключение; вывод format_salary — строго по шаблонам §6.1."""
    parse_salary = load_attr("app.domain.currency", "parse_salary")
    format_salary = load_attr("app.domain.currency", "format_salary")
    salary = parse_salary(raw)
    if salary is not None:
        assert salary.currency, f"P-SAL-01: пустая валюта для {raw!r}"
        for value in (salary.min, salary.max):
            assert value is None or (isinstance(value, int) and value > 0), (
                f"P-SAL-01: ненормализованная сумма {value!r} для {raw!r}"
            )
    ru_line = format_salary(salary, "ru")
    en_line = format_salary(salary, "en")
    assert RU_SALARY_RE.match(ru_line), f"P-SAL-01: RU-строка вне шаблона: {ru_line!r}"
    assert EN_SALARY_RE.match(en_line), f"P-SAL-01: EN-строка вне шаблона: {en_line!r}"
    assert "\u00a0" not in ru_line + en_line, f"P-SAL-01: NBSP в разрядах: {ru_line!r}"


# --- P-SAL-02 (R22): граничные значения зарплаты нормализуются безопасно ------


@settings(derandomize=True, max_examples=150, deadline=None)
@given(
    left=st.one_of(st.integers(-(10**9), 10**9), st.integers(10**18, 10**25)),
    right=st.one_of(st.integers(-(10**9), 10**9), st.integers(10**18, 10**25)),
)
def test_P_SAL_02_boundary_amounts_normalize_safely(left: int, right: int) -> None:
    """P-SAL-02: min>max обмениваются; ≤0 и переполнение → None; без исключений."""
    parse_salary = load_attr("app.domain.currency", "parse_salary")
    result = parse_salary(f"от {left} до {right} ₽")
    if result is None:
        return
    assert result.min is not None and result.max is not None, (
        f"P-SAL-02: диапазон разобран не полностью: от {left} до {right} -> {result}"
    )
    assert 0 < result.min <= result.max <= 2**63 - 1, (
        f"P-SAL-02: не нормализован диапазон от {left} до {right}: {result}"
    )


# --- P-AGE-01 (R23): формы возраста инвариантны ------------------------------


@settings(derandomize=True, max_examples=200, deadline=None)
@given(days=st.integers(-400, 400), lang=st.sampled_from(("ru", "en")))
def test_P_AGE_01_age_forms_are_invariant(days: int, lang: str) -> None:
    """P-AGE-01: без «-1 дн.»/«1 days»; границы 0/1/2+ дают формы brief §6.1."""
    format_age = load_attr("app.services.digest", "format_age")
    age = format_age(NOW - timedelta(days=days), NOW, lang)
    if days <= 0:
        expected = AGE_RU[0] if lang == "ru" else AGE_EN[0]
    elif days == 1:
        expected = AGE_RU[1] if lang == "ru" else AGE_EN[1]
    else:
        expected = f"{days} дн." if lang == "ru" else f"{days} days"
    assert age == expected, f"P-AGE-01: days={days} lang={lang}: {age!r} != {expected!r}"


# --- P-DIG-01 (R4): части ≤4096, разбивка только по границам карточек --------


@settings(derandomize=True, max_examples=60, deadline=None)
@given(
    specs=st.lists(
        st.tuples(st.integers(1, 500), st.integers(0, 900), st.booleans()),
        min_size=1,
        max_size=12,
    )
)
def test_P_DIG_01_digest_parts_bounded_and_split_on_card_boundaries(specs) -> None:
    """P-DIG-01: каждая часть ≤4096; части складываются в единый список без разрывов."""
    esc = load_attr("app.textutil", "esc")
    render_digest = load_attr("app.services.digest", "render_digest")
    items, cards = [], []
    for n, (title_len, company_len, with_salary) in enumerate(specs, start=1):
        vacancy = make_vacancy(
            title="T" * title_len,
            company="C" * company_len,
            salary=make_salary_rub(150000) if with_salary else None,
            url=f"https://hh.ru/vacancy/{n}",
            published_at=NOW,
        )
        items.append(make_digest_item(n, vacancy))
        cards.append(
            expected_card(
                n,
                title=esc(vacancy.title),
                company=esc(vacancy.company),
                source="hh.ru",
                age="сегодня",
                salary=expected_salary_line(
                    lang="ru",
                    minimum=150000 if with_salary else None,
                    maximum=None,
                    currency="RUB",
                ),
                url=vacancy.url,
            )
        )
    parts = render_digest(items, lang="ru", now=NOW, on_date=ON_DATE)
    for part in parts:
        assert len(part) <= 4096, f"P-DIG-01: часть {len(part)} > 4096"
    joined = "\n\n".join(part.strip("\n") for part in parts)
    expected = (
        expected_header(lang="ru", on_date=ON_DATE, count=len(items)) + "\n\n" + "\n\n".join(cards)
    )
    assert joined == expected, f"P-DIG-01: части не складываются в шаблон §6.1: {joined[:300]!r}"
    assert sum(part.startswith("🔥") for part in parts) == 1, (
        f"P-DIG-01: заголовок не только в первой части: {[p[:20] for p in parts]}"
    )


def make_salary_rub(amount: int):
    salary_cls = load_attr("app.domain.currency", "Salary")
    return salary_cls(min=amount, max=None, currency="RUB")


def _ordered_salary(minimum: int, maximum: int | None, currency: str):
    """Salary с min <= max (формат строки для min>max контракт не фиксирует)."""
    if maximum is not None and minimum > maximum:
        minimum, maximum = maximum, minimum
    return make_salary(minimum, maximum, currency)


# --- P-DIG-03 (R24): обрезка {title} безопасна для HTML -----------------------


@settings(derandomize=True, max_examples=150, deadline=None)
@given(text=st.text(max_size=600))
def test_P_DIG_03_truncate_title_never_breaks_html(text: str) -> None:
    """P-DIG-03: ≤200 code points с «…», сущности целы, HTML валиден."""
    esc = load_attr("app.textutil", "esc")
    truncate_title = load_attr("app.services.digest", "truncate_title")
    escaped = esc(text)
    result = truncate_title(escaped, 200)
    assert len(result) <= 200, f"P-DIG-03: результат {len(result)} > 200: {result!r}"
    if len(escaped) <= 200:
        assert result == escaped, f"P-DIG-03: короткий заголовок изменён: {escaped!r} -> {result!r}"
    else:
        assert result.endswith("\u2026"), f"P-DIG-03: обрезка без «…»: {result!r}"
    assert BROKEN_ENTITY_RE.search(result) is None, (
        f"P-DIG-03: сущность разорвана обрезкой: {result!r}"
    )
    assert_no_raw_markup(f"<b>{result}</b>", "P-DIG-03")


# --- P-DIG-04 (R10/R36): шаблоны вывода байт-в-байт --------------------------


@settings(derandomize=True, max_examples=150, deadline=None)
@given(
    title=st.text(max_size=120),
    company=st.text(max_size=120),
    salary_spec=st.one_of(
        st.none(),
        st.tuples(st.integers(1, 10**9), st.none(), st.just("RUB")),
        st.tuples(
            st.integers(1, 10**6), st.integers(1, 10**6), st.sampled_from(("USD", "EUR", "GBP"))
        ),
    ),
    days=st.integers(0, 40),
)
def test_P_DIG_04_output_templates_byte_exact(title, company, salary_spec, days) -> None:
    """P-DIG-04: карточка/заголовок/пустой дайджест — строго шаблоны brief §6.1."""
    esc = load_attr("app.textutil", "esc")
    render_card = load_attr("app.services.digest", "render_card")
    render_empty = load_attr("app.services.digest", "render_empty")
    render_header = load_attr("app.services.digest", "render_header")
    salary = None if salary_spec is None else _ordered_salary(*salary_spec)
    vacancy = make_vacancy(
        title=title,
        company=company,
        salary=salary,
        url="https://hh.ru/vacancy/1",
        published_at=NOW - timedelta(days=days),
    )
    card = render_card(1, vacancy, "ru", NOW)
    age = AGE_RU.get(days, f"{days} дн.")
    salary_line = expected_salary_line(
        lang="ru",
        minimum=None if salary is None else salary.min,
        maximum=None if salary is None else salary.max,
        currency="RUB" if salary is None else salary.currency,
    )
    assert card == expected_card(
        1,
        title=esc(title),
        company=esc(company),
        source="hh.ru",
        age=age,
        salary=salary_line,
        url=vacancy.url,
    ), f"P-DIG-04: карточка вне шаблона: {card!r}"
    assert render_empty("ru") == EMPTY_DIGEST_RU
    assert render_empty("en") == EMPTY_DIGEST_EN
    header = render_header(3, ON_DATE, "ru")
    assert header == expected_header(lang="ru", on_date=ON_DATE, count=3), (
        f"P-DIG-04: заголовок вне шаблона: {header!r}"
    )


# --- P-TEX-01 (R7/R25): esc тотален и обратим -------------------------------


@settings(derandomize=True, max_examples=200, deadline=None)
@given(text=st.text(max_size=500))
def test_P_TEX_01_esc_never_crashes_never_adds_markup(text: str) -> None:
    """P-TEX-01: esc не падает, не добавляет разметки, обратим (html.unescape)."""
    esc = load_attr("app.textutil", "esc")
    esc_attr = load_attr("app.textutil", "esc_attr")
    nasty = "\x00\u202e\udc00<script>&" * 100  # NUL, RTL-override, суррогаты
    for value in (text, nasty + text):
        out = esc(value)
        assert "<" not in out and ">" not in out, f"P-TEX-01: сырые скобки в esc({value!r})"
        assert html.unescape(out) == value, f"P-TEX-01: esc потерял данные {value!r}"
        out_attr = esc_attr(value)
        for bad in ('"', "<", ">"):
            assert bad not in out_attr, f"P-TEX-01: esc_attr не экранирует {bad!r}"


# --- P-UX-01 (R15): парсеры ввода дают значение или ValueError ---------------


@settings(derandomize=True, max_examples=200, deadline=None)
@given(raw=st.text(max_size=80))
def test_P_UX_01_input_parsers_give_value_or_valueerror(raw: str) -> None:
    """P-UX-01: parse_hhmm/parse_tz — только time/tz либо ValueError, без крашей."""
    from datetime import time as dt_time

    parse_hhmm = load_attr("app.domain.profile", "parse_hhmm")
    parse_tz = load_attr("app.domain.profile", "parse_tz")
    try:
        parsed_time = parse_hhmm(raw)
    except ValueError:
        pass
    else:
        assert isinstance(parsed_time, dt_time), f"P-UX-01: parse_hhmm вернул {parsed_time!r}"
        assert 0 <= parsed_time.hour <= 23 and 0 <= parsed_time.minute <= 59
    try:
        parsed_tz = parse_tz(raw)
    except ValueError:
        pass
    else:
        assert parsed_tz is not None, f"P-UX-01: parse_tz вернул None для {raw!r}"


# --- P-UX-02 (R27): границы digest_size 1..50 --------------------------------


@settings(derandomize=True, max_examples=100, deadline=None)
@given(size=st.integers(1, 50))
def test_P_UX_02_digest_size_bounds(size: int) -> None:
    """P-UX-02: 1..50 переживают JSONB-раунд-трип; вне диапазона — ValueError."""
    profile_to_jsonb = load_attr("app.domain.profile", "profile_to_jsonb")
    profile_from_jsonb = load_attr("app.domain.profile", "profile_from_jsonb")
    select_digest = load_attr("app.services.select", "select_digest")
    profile = make_profile(digest_size=size)
    restored = profile_from_jsonb(dict(profile_to_jsonb(profile)))
    assert restored.digest_size == size, f"P-UX-02: digest_size {size} потерян при сериализации"
    repo = InMemoryRepo()
    user = model_user()
    for bad_limit in (0, 51, -1, 10**6):
        try:
            run(select_digest(repo=repo, user=user, now=NOW, limit=bad_limit))
        except ValueError:
            continue
        raise AssertionError(f"P-UX-02: limit={bad_limit} вне 1..50 принят")


def model_user():
    from fakes import ModelUser

    return ModelUser(id=1, lang="ru", profile=model_profile_of(make_profile()))


# --- P-SES-01 (R31): HTTP никогда не при открытой сессии БД ------------------


@settings(derandomize=True, max_examples=40, deadline=None)
@given(page=st.text(max_size=200))
def test_P_SES_01_no_http_while_db_session_open(page: str) -> None:
    """P-SES-01: во время HTTP-вызовов сбора ни одна сессия БД не удерживается."""
    run_collect = load_attr("app.services.collect", "run_collect")
    repo_cls = load_attr("app.storage.repo", "Repo")
    probe = ProbeSessionFactory()
    repo = repo_cls(probe)
    client = FakeClient(
        fallback=FakeResponse(text=page),
        on_request=lambda url: probe.assert_none_open(f"HTTP {url[:30]!r}"),
    )
    run(run_collect(client=client, repo=repo, alerts=FakeAlertSink(), now=NOW))
    probe.assert_none_open("после run_collect")


# --- P-SEL-01 (R3): (user, vacancy) доставляется не более одного раза --------


@settings(derandomize=True, max_examples=40, deadline=None)
@given(count=st.integers(1, 8), limit=st.integers(1, 3))
def test_P_SEL_01_delivery_at_most_once_per_user(count: int, limit: int) -> None:
    """P-SEL-01: повторные выпуски не содержат уже доставленных вакансий."""
    select_digest = load_attr("app.services.select", "select_digest")
    repo = InMemoryRepo()
    # Подписанный permissive-пресет обязателен: select_candidates отбирает только
    # по фильтру хотя бы одного подписанного пресета (api.md §9); подписка
    # пользователя — model_user() → make_profile() (presets=["python-backend"]).
    run(
        repo.upsert_preset(
            "python-backend", name=PRESET_NAMES_RU["python-backend"], filter_json=PERMISSIVE_FILTER
        )
    )
    user = model_user()
    for n in range(1, count + 1):
        run(
            repo.add_vacancies(
                [
                    make_vacancy(
                        title=f"Vacancy {n}",
                        url=f"https://hh.ru/vacancy/{7000 + n}",
                        published_at=NOW - timedelta(days=n),
                    )
                ]
            )
        )
    delivered: list[str] = []
    for day in range(1, 10):
        selection = run(
            select_digest(
                repo=repo,
                user=user,
                now=NOW + timedelta(days=day),
                limit=limit,
            )
        )
        titles = [item.vacancy.title for item in (selection.items if selection else [])]
        overlap = set(titles) & set(delivered)
        assert not overlap, f"P-SEL-01: вакансии доставлены повторно: {overlap}"
        delivered.extend(titles)
        if not titles:
            break
    assert len(delivered) == count, f"P-SEL-01: доставки потеряны: {delivered}"


# --- P-SEL-02 (R32): слот отрабатывает не более одного раза -------------------


@settings(derandomize=True, max_examples=40, deadline=None)
@given(user_ids=st.lists(st.integers(1, 50), min_size=1, max_size=6, unique=True))
def test_P_SEL_02_slot_processed_at_most_once(user_ids) -> None:
    """P-SEL-02: повторные проверки того же слота не дают второй доставки."""
    check_schedules = load_attr("app.services.scheduler", "check_schedules")
    repo = InMemoryRepo()
    # Подписанный permissive-пресет — иначе посаженная вакансия недостижима
    # (api.md §9: фильтр хотя бы одного подписанного пресета); подписка —
    # make_profile() (presets=["python-backend"]).
    run(
        repo.upsert_preset(
            "python-backend", name=PRESET_NAMES_RU["python-backend"], filter_json=PERMISSIVE_FILTER
        )
    )
    profile = model_profile_of(make_profile(schedule=make_schedule(_time(9, 30), "Europe/Moscow")))
    for user_id in user_ids:
        run(repo.upsert_user(user_id, lang="ru", profile=profile))
    run(repo.add_vacancies([make_vacancy(title="Vacancy", url="https://hh.ru/vacancy/8001")]))
    sender, throttle = FakeSender(), FakeThrottle()
    at_slot = datetime(2026, 3, 14, 6, 30, tzinfo=UTC)
    for _ in range(3):
        run(check_schedules(repo=repo, sender=sender, throttle=throttle, now=at_slot))
    for user_id in user_ids:
        assert len(sender.texts_for(user_id)) == 1, (
            f"P-SEL-02: слот пользователя {user_id} отработан {len(sender.texts_for(user_id))} раз"
        )


def _time(hour: int, minute: int):
    from datetime import time as dt_time

    return dt_time(hour, minute)


# --- P-SEND-01 (R9/R42): рассылка не теряет и не дублирует сообщения ---------


@settings(derandomize=True, max_examples=60, deadline=None)
@given(plan=st.lists(st.sampled_from(("ok", "flood", "dead")), min_size=1, max_size=25))
def test_P_SEND_01_dispatch_accounting_invariants(plan) -> None:
    """P-SEND-01: каждое сообщение учтено ровно один раз; исключения не утекают."""
    dispatch = load_attr("app.services.dispatch", "dispatch")
    message_cls = load_attr("app.services.dispatch", "OutgoingMessage")
    failures: dict[int, list] = {}
    messages = []
    expected_failed = []
    for index, kind in enumerate(plan):
        chat_id = 1000 + index
        messages.append(message_cls(chat_id=chat_id, text=f"digest {index}"))
        if kind == "flood":
            failures[chat_id] = [FloodWaitError(0.0)]
        elif kind == "dead":
            failures[chat_id] = [RuntimeError("chat not found")]
            expected_failed.append(chat_id)
    sender, throttle = FakeSender(failures), FakeThrottle()
    report = run(dispatch(messages, sender=sender, throttle=throttle, now=NOW))
    assert report.sent + len(report.failed) == len(messages), (
        f"P-SEND-01: отчёт неполон: sent={report.sent}, failed={report.failed!r}"
    )
    failed_chats = sorted(chat for chat, _reason in report.failed)
    assert failed_chats == sorted(expected_failed), (
        f"P-SEND-01: неверный список неудач: {report.failed!r}"
    )
    sent_chats = [chat for chat, _text in sender.sent]
    assert len(sent_chats) == len(set(sent_chats)), f"P-SEND-01: дубли отправок: {sent_chats}"
    assert set(sent_chats) == {1000 + i for i in range(len(plan))} - set(expected_failed)


# --- P-BTN-01 (R5/R26): команды обратной связи тотальны (без кнопок) --------


@settings(derandomize=True, max_examples=15, deadline=None)
@given(
    arg=st.text(max_size=30),
    action=st.sampled_from(("like", "dislike", "bookmark")),
)
def test_P_BTN_01_feedback_commands_total(arg: str, action: str) -> None:
    """P-BTN-01: любая аргументация — точный ответ или точная ошибка, без крашей.

    Контракт: решения Q1/§5.3–§5.4 — n = первый токен, целое 1..3 последнего
    дайджеста (карточек 3); успех только для него, иначе точная ошибка.
    """
    from fakes import open_bot, send_text

    async def go() -> list[str]:
        async with open_bot() as h:
            # I-2 (decisions §8): онбординг кнопками (текстовый ввод «lang:ru»
            # и slug-пресета упразднён) — замена текстового setup I-1.
            await onboard(h, 1501)
            await h.seed_vacancies(
                [
                    make_vacancy(
                        title=f"Python Developer {n}",
                        salary=None,
                        url=f"https://hh.ru/vacancy/{9100 + n}",
                    )
                    for n in (1, 2, 3)
                ]
            )
            from fakes import deliver_texts

            await deliver_texts(h, 1501)
            return await send_text(h, 1501, f"/{action} {arg}")

    replies = run(go())
    ok_line = FEEDBACK_OK[action][0]
    assert replies in ([ok_line], [FEEDBACK_ERROR_RU]), (
        f"P-BTN-01: /{action} {arg!r} -> {replies!r}"
    )
    if replies == [ok_line]:
        first_token = arg.split()[0] if arg.split() else ""
        assert first_token in {"1", "2", "3"}, f"P-BTN-01: неверный номер {arg!r} прошёл как успех"


# --- P-DED-01 (R12): канонический URL и нормализация текста инвариантны -----


@settings(derandomize=True, max_examples=200, deadline=None)
@given(raw=st.text(max_size=120))
def test_P_DED_01_canonical_url_and_normalize_text_invariants(raw: str) -> None:
    """P-DED-01: канонизация/нормализация идемпотентны и не создают мусора."""
    canonicalize_url = load_attr("app.collectors", "canonicalize_url")
    normalize_text = load_attr("app.collectors", "normalize_text")
    canonical = canonicalize_url(raw)
    assert canonicalize_url(canonical) == canonical, (
        f"P-DED-01: канонизация неидемпотентна: {raw!r} -> {canonical!r}"
    )
    assert not any(ch.isspace() for ch in canonical), f"P-DED-01: пробел в URL {canonical!r}"
    normalized = normalize_text(raw)
    assert normalize_text(normalized) == normalized, (
        f"P-DED-01: нормализация неидемпотентна: {raw!r} -> {normalized!r}"
    )
    assert normalized == normalized.lower(), f"P-DED-01: не lowercase: {normalized!r}"
    assert "  " not in normalized and normalized == normalized.strip(), (
        f"P-DED-01: лишние пробелы: {normalized!r}"
    )
    assert not set(normalized) & set(string.punctuation), (
        f"P-DED-01: пунктуация в нормализованном тексте: {normalized!r}"
    )
    # фиксированные кейсы дедупликации (S13/S14)
    assert canonicalize_url("https://hh.ru/vacancy/1?utm_source=x") == canonicalize_url(
        "https://hh.ru/vacancy/1/"
    )
    assert normalize_text("  python   developer ") == normalize_text("Python Developer")


# --- P-SCH-01 (R6): слоты расписания инвариантны -----------------------------


@settings(derandomize=True, max_examples=100, deadline=None)
@given(
    tz_name=st.sampled_from(TZ_NAMES),
    hour=st.integers(0, 23),
    minute=st.integers(0, 59),
    day_offset=st.integers(-400, 400),
)
def test_P_SCH_01_local_slot_and_key_invariants(tz_name, hour, minute, day_offset) -> None:
    """P-SCH-01: слот существует, ключ детерминирован и уникален по суткам."""
    local_slot = load_attr("app.services.scheduler", "local_slot")
    slot_key = load_attr("app.services.scheduler", "slot_key")
    schedule = make_schedule(_time(hour, minute), tz_name)
    day = ON_DATE + timedelta(days=day_offset)
    slot = local_slot(schedule, day)
    assert isinstance(slot, datetime) and slot.tzinfo is not None, (
        f"P-SCH-01: слот без tz: {slot!r}"
    )
    key = slot_key(1, schedule, day)
    assert key == slot_key(1, schedule, day), f"P-SCH-01: ключ недетерминирован: {key!r}"
    assert key != slot_key(1, schedule, day + timedelta(days=1)), (
        f"P-SCH-01: один ключ на разные сутки: {key!r}"
    )
    assert key != slot_key(2, schedule, day), f"P-SCH-01: ключ не различает пользователей: {key!r}"
    assert slot.utcoffset() is not None, f"P-SCH-01: слот без смещения: {slot!r}"


# --- P-AS-01 (R14): антиспам не мьютит до лимита -----------------------------


@settings(derandomize=True, max_examples=8, deadline=None)
@given(actions=st.integers(1, 29))
def test_P_AS_01_antispam_never_mutes_below_limit(actions: int) -> None:
    """P-AS-01: любые ≤30 действий/мин обрабатываются полностью и без «мьюта»."""
    from fakes import open_bot, send_text

    def scenario() -> list[list[str]]:
        async def go() -> list[list[str]]:
            async with open_bot() as h:
                return [await send_text(h, 1601, "/settings") for _ in range(actions)]

        return run(go())

    replies = scenario()
    assert all(reply for reply in replies), (
        f"P-AS-01: действие в пределах лимита не обработано (замьючено): {replies!r}"
    )


# --- P-I18N-01 (R39): словари паритетны, t() тотальна ------------------------


@settings(derandomize=True, max_examples=150, deadline=None)
@given(key=st.text(max_size=40))
def test_P_I18N_01_lang_dicts_parity_and_totality(key: str) -> None:
    """P-I18N-01: ключи RU/EN совпадают; t() даёт непустую строку либо KeyError."""
    keys = load_attr("app.i18n", "keys")
    t = load_attr("app.i18n", "t")
    ru_keys, en_keys = keys("ru"), keys("en")
    assert ru_keys == en_keys, f"P-I18N-01: паритет ключей нарушен: {ru_keys ^ en_keys}"
    for lang in ("ru", "en"):
        try:
            value = t(key, lang)
        except KeyError:
            continue
        assert isinstance(value, str) and value.strip(), (
            f"P-I18N-01: пустая строка {key!r} ({lang})"
        )
        assert key in ru_keys, f"P-I18N-01: t() вернула строку для неизвестного ключа {key!r}"
