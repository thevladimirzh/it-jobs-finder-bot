"""Acceptance-тесты сценариев S27–S37 — дайджест: карточки, форматы, разбивка.

Чёрный ящик: публичное API ``app.services.digest`` / ``app.services.select``
(api.md §11–§12) и ``Repo`` (api.md §9) на тестовой БД для сценариев состояния
доставок (S35, S37). Точные строки — brief §6.1, копируются дословно; значимые
символы заданы явно (``\\u00b7``, ``\\u2013``, ``\\u2014`` — decisions §3.4).
Независимый oracle строк — ``fakes.expected_card/expected_salary_line/...``.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time

import pytest
from fakes import (
    EMPTY_DIGEST_RU,
    PERMISSIVE_FILTER,
    PRESET_NAMES_RU,
    SOURCE_HH,
    FakeSender,
    FakeThrottle,
    InMemoryRepo,
    expected_card,
    expected_salary_line,
    make_digest_item,
    make_profile,
    make_salary,
    make_schedule,
    make_vacancy,
    model_profile_of,
    real_repo,
)
from support import assert_no_raw_markup, found_tags, load_attr

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
ON_DATE = date(2026, 3, 14)
HEADER_RU = "🔥 Подборка вакансий \u2014 14.03.2026 (3)"

CARD_S27 = (
    "1. <b>Python Developer</b>\n"
    "Ромашка \u00b7 hh.ru \u00b7 сегодня\n"
    "от 150 000 ₽\n"
    "https://hh.ru/vacancy/123"
)
CARD_S28 = (
    "1. <b>Python Developer</b>\n"
    "Romashka \u00b7 Habr Career \u00b7 yesterday\n"
    "Salary not specified\n"
    "https://career.habr.com/vacancies/1000"
)

SALARY_LINE_CASES = [
    ("ru", 150000, None, "RUB", "от 150 000 ₽"),
    ("ru", None, 200000, "RUB", "до 200 000 ₽"),
    ("ru", 100000, 200000, "RUB", "100 000 \u2013 200 000 ₽"),
    ("ru", None, None, None, "Зарплата не указана"),
    ("en", 1500, None, "USD", "from 1 500 $"),
    ("en", None, 2000, "USD", "up to 2 000 $"),
    ("en", 1000, 2000, "EUR", "1 000 \u2013 2 000 €"),
    ("en", None, None, None, "Salary not specified"),
    ("ru", 300000, None, "GBP", "от 300 000 GBP"),
]

AGE_LINE_CASES = [
    # (lang, сдвиг published_at от NOW в часах, ожидаемый {age}).
    # Сдвиг > 0 — в прошлое (примеры @S30: «вчера», «2 полных дня назад»,
    # «5 полных дней назад»), < 0 — в будущем («в будущем (смещение tz)»).
    # Будущее → k = 0 («сегодня»/today) — decisions §5.6, brief §6.1 {age}.
    ("ru", 0, "сегодня"),
    ("ru", 24, "вчера"),
    ("ru", 48, "2 дн."),
    ("ru", 120, "5 дн."),
    ("ru", -3, "сегодня"),  # published_at в будущем (смещение tz) → «сегодня»
    ("en", 0, "today"),
    ("en", 24, "yesterday"),
    ("en", 48, "2 days"),
    ("en", 120, "5 days"),
]


def _card_vacancy(**overrides):
    values = {
        "title": "Python Developer",
        "company": "Ромашка",
        "salary": make_salary(150000, None, "RUB"),
        "url": "https://hh.ru/vacancy/123",
        "source": SOURCE_HH,
        "published_at": NOW,
    }
    values.update(overrides)
    return make_vacancy(**values)


# --- S27 (@R10 @R36): карточка строго по шаблону §6.1 (RU) --------------------


async def test_s27_card_format_ru_verbatim() -> None:
    """@S27: RU-карточка байт-в-байт совпадает с шаблоном brief §6.1."""
    render_card = load_attr("app.services.digest", "render_card")
    card = render_card(1, _card_vacancy(), "ru", NOW)
    assert card == CARD_S27, f"@S27: карточка не совпала с шаблоном:\n{card!r}"
    assert card == expected_card(
        1,
        title="Python Developer",
        company="Ромашка",
        source=SOURCE_HH,
        age="сегодня",
        salary=expected_salary_line(lang="ru", minimum=150000, maximum=None, currency="RUB"),
        url="https://hh.ru/vacancy/123",
    ), f"@S27: oracle-сборка карточки разошлась: {card!r}"


# --- S28 (@R10 @R20): карточка строго по шаблону §6.1 (EN) --------------------


async def test_s28_card_format_en_verbatim() -> None:
    """@S28: EN-карточка байт-в-байт (yesterday, Salary not specified)."""
    render_card = load_attr("app.services.digest", "render_card")
    vacancy = _card_vacancy(
        company="Romashka",
        salary=None,
        url="https://career.habr.com/vacancies/1000",
        source="Habr Career",
        published_at=NOW.replace(day=13),
    )
    card = render_card(1, vacancy, "en", NOW)
    assert card == CARD_S28, f"@S28: карточка не совпала с шаблоном:\n{card!r}"


# --- S29 (@R10): форматы строки зарплаты -------------------------------------


@pytest.mark.parametrize(("lang", "minimum", "maximum", "currency", "line"), SALARY_LINE_CASES)
async def test_s29_salary_line_formats_verbatim(
    lang: str, minimum, maximum, currency, line: str
) -> None:
    """@S29: строки зарплаты RU/EN дословно по brief §6.1 (пробелы U+0020, «–» U+2013)."""
    format_salary = load_attr("app.domain.currency", "format_salary")
    salary = (
        None if minimum is None and maximum is None else make_salary(minimum, maximum, currency)
    )
    assert format_salary(salary, lang) == line, (
        f"@S29: format_salary({minimum}, {maximum}, {currency}, {lang!r}) != {line!r}"
    )


# --- S30 (@R23): возраст вакансии -------------------------------------------


@pytest.mark.parametrize(("lang", "delta_hours", "age"), AGE_LINE_CASES)
async def test_s30_age_line_boundaries(lang: str, delta_hours: int, age: str) -> None:
    """@S30: границы 0/1/2 полных дня и published_at в будущем → «сегодня»/«today»."""
    format_age = load_attr("app.services.digest", "format_age")
    published_at = NOW - timedelta(hours=delta_hours)
    assert format_age(published_at, NOW, lang) == age, (
        f"@S30: format_age({published_at}, {lang!r}) != {age!r}"
    )


# --- S31 (@R10 @R36): заголовок, {count} и сквозная нумерация ----------------


async def test_s31_digest_header_count_and_numbering() -> None:
    """@S31: заголовок с общей численностью; карточки 1,2,3 через пустую строку."""
    render_header = load_attr("app.services.digest", "render_header")
    render_digest = load_attr("app.services.digest", "render_digest")
    assert render_header(3, ON_DATE, "ru") == HEADER_RU, f"@S31: render_header != {HEADER_RU!r}"
    items = [
        make_digest_item(
            n, _card_vacancy(title=f"Python Developer {n}", url=f"https://hh.ru/vacancy/{n}")
        )
        for n in (1, 2, 3)
    ]
    parts = render_digest(items, lang="ru", now=NOW, on_date=ON_DATE)
    cards = [
        expected_card(
            n,
            title=f"Python Developer {n}",
            company="Ромашка",
            source=SOURCE_HH,
            age="сегодня",
            salary=expected_salary_line(lang="ru", minimum=150000, maximum=None, currency="RUB"),
            url=f"https://hh.ru/vacancy/{n}",
        )
        for n in (1, 2, 3)
    ]
    expected = HEADER_RU + "\n\n" + "\n\n".join(cards)
    assert "\n\n".join(part.strip("\n") for part in parts) == expected, (
        f"@S31: дайджест не совпал с шаблоном §6.1: {parts!r}"
    )


# --- S32 (@R4): разбивка по границам карточек, части ≤4096 -------------------


async def test_s32_digest_split_at_card_boundaries() -> None:
    """@S32: части ≤4096, разбивка только по карточкам, заголовок в части 1, count=10."""
    render_digest = load_attr("app.services.digest", "render_digest")
    items, cards = [], []
    for n in range(1, 11):
        company = "C" * 650 + f"{n:02d}"
        vacancy = _card_vacancy(
            title=f"Python Developer {n:02d}",
            company=company,
            salary=None,
            url=f"https://hh.ru/vacancy/{n:02d}",
        )
        items.append(make_digest_item(n, vacancy))
        cards.append(
            expected_card(
                n,
                title=f"Python Developer {n:02d}",
                company=company,
                source=SOURCE_HH,
                age="сегодня",
                salary="Зарплата не указана",
                url=f"https://hh.ru/vacancy/{n:02d}",
            )
        )
    parts = render_digest(items, lang="ru", now=NOW, on_date=ON_DATE)
    assert len(parts) >= 2, f"@S32: дайджест из 10 больших карточек не разбит: {len(parts)}"
    for part in parts:
        assert len(part) <= 4096, f"@S32: часть длиной {len(part)} > 4096 (включая HTML-теги)"
    assert parts[0].startswith("🔥 Подборка вакансий \u2014 14.03.2026 (10)"), (
        f"@S32: заголовок части 1: {parts[0][:60]!r}"
    )
    assert all("🔥" not in part for part in parts[1:]), (
        f"@S32: заголовок повторён в частях 2+: {parts}"
    )
    joined = "\n\n".join(part.strip("\n") for part in parts)
    expected = "🔥 Подборка вакансий \u2014 14.03.2026 (10)" + "\n\n" + "\n\n".join(cards)
    assert joined == expected, (
        f"@S32: разбивка не по границам карточек или нумерация не сквозная: {joined[:400]!r}"
    )


# --- S33 (@R24 @R4): обрезка {title} до 200 символов с «…» --------------------


async def test_s33_long_title_truncated_safely() -> None:
    """@S33: title >200 обрезается по экранированному тексту, «…», HTML цел.

    Строка карточки ищется после заголовка дайджеста (brief §6.1: первая часть
    начинается с «🔥 Подборка вакансий — {date} ({count})», карточка —
    первая строка, начинающаяся с ``{n}. <b>``; см. S31/S32).
    """
    render_digest = load_attr("app.services.digest", "render_digest")
    hostile_title = ("A&B <C> " * 50)[:400]
    vacancy = _card_vacancy(title=hostile_title, salary=None)
    parts = render_digest([make_digest_item(1, vacancy)], lang="ru", now=NOW, on_date=ON_DATE)
    part = parts[0]
    assert len(part) <= 4096, f"@S33: часть с карточкой {len(part)} > 4096"
    lines = part.split("\n")
    assert lines[0] == "🔥 Подборка вакансий \u2014 14.03.2026 (1)", (
        f"@S33: часть не начинается с заголовка дайджеста (brief §6.1): {lines[0]!r}"
    )
    card_line = next((line for line in lines[1:] if re.match(r"\d+\. <b>", line)), "")
    assert card_line.startswith("1. <b>") and card_line.endswith("</b>"), (
        f"@S33: строка заголовка карточки повреждена: {card_line!r}"
    )
    inner = card_line.removeprefix("1. <b>").removesuffix("</b>")
    assert len(inner) <= 200, f"@S33: заголовок не обрезан до 200 code points: {len(inner)}"
    assert inner.endswith("\u2026"), f"@S33: обрезка без «…»: {inner[-15:]!r}"
    assert not _broken_entities(inner), f"@S33: обрезка разорвала HTML-сущность: {inner!r}"
    assert_no_raw_markup(part, "@S33 часть")


# --- S34 (@R7 @R25): экранирование внешнего текста ----------------------------


async def test_s34_external_text_escaped_in_card() -> None:
    """@S34: <script> и & из внешнего текста не попадают в разметку; <b> шаблона жив."""
    render_card = load_attr("app.services.digest", "render_card")
    vacancy = _card_vacancy(
        title="<script>alert(1)</script> Developer",
        company='ООО "Ромашка" & <b>Co</b>',
        salary=None,
    )
    card = render_card(1, vacancy, "ru", NOW)
    assert "<script>" not in card, f"@S34: исполняемый тег из внешнего текста: {card!r}"
    assert "&lt;script&gt;" in card, f"@S34: заголовок не экранирован: {card!r}"
    assert set(found_tags(card)) <= {"b"}, f"@S34: недопустимые теги в карточке: {card!r}"
    assert card.count("<b>") == card.count("</b>") == 1, (
        f"@S34: разбалансированные теги шаблона: {card!r}"
    )
    assert_no_raw_markup(card, "@S34 карточка")


# --- S35 (@R3): доставка per-user не более одного раза -----------------------


async def test_s35_vacancy_delivered_to_user_at_most_once() -> None:
    """@S35 (Q2): доставленная вакансия не возвращается в следующих выпусках."""
    select_digest = load_attr("app.services.select", "select_digest")
    async with real_repo() as db:
        repo = db.repo
        profile = make_profile(
            digest_size=2,
            schedule=make_schedule(dt_time(9, 30), "Europe/Moscow"),
        )
        user = await repo.upsert_user(701, lang="ru", profile=profile)
        await repo.upsert_preset(
            "python-backend", name=PRESET_NAMES_RU["python-backend"], filter_json=PERMISSIVE_FILTER
        )
        await repo.add_vacancies(
            [
                _card_vacancy(title="Python Developer", url="https://hh.ru/vacancy/31"),
                make_vacancy(
                    title="Data Engineer",
                    company="Lavanda",
                    url="https://hh.ru/vacancy/32",
                    source=SOURCE_HH,
                    published_at=NOW.replace(day=13),
                ),
                make_vacancy(
                    title="QA Engineer",
                    company="Kaktus",
                    url="https://hh.ru/vacancy/33",
                    source=SOURCE_HH,
                    published_at=NOW.replace(day=12),
                ),
            ]
        )
        first = await select_digest(
            repo=repo, user=user, now=datetime(2026, 3, 14, 6, 30, tzinfo=UTC)
        )
        assert first is not None and len(first.items) == 2, f"@S35: первый выпуск: {first!r}"
        first_titles = [item.vacancy.title for item in first.items]
        assert "Python Developer" in first_titles, f"@S35: первый выпуск {first_titles}"

        second = await select_digest(
            repo=repo, user=user, now=datetime(2026, 3, 15, 6, 30, tzinfo=UTC)
        )
        second_titles = [item.vacancy.title for item in (second.items if second else [])]
        assert "Python Developer" not in second_titles, (
            f"@S35: доставленная вакансия повторилась: {second_titles}"
        )
        assert second_titles == ["QA Engineer"], (
            f"@S35: в новый выпуск попало не только недоставленное: {second_titles}"
        )


# --- S36 (@R11): пустой дайджест — «🔥 Новых вакансий нет» --------------------


async def test_s36_empty_digest_message_verbatim() -> None:
    """@S36 (Q3): при отсутствии вакансий — ровно одно сообщение по шаблону §6.1."""
    check_schedules = load_attr("app.services.scheduler", "check_schedules")
    repo = InMemoryRepo()
    profile = make_profile(schedule=make_schedule(dt_time(9, 30), "Europe/Moscow"))
    await repo.upsert_user(702, lang="ru", profile=model_profile_of(profile))
    sender, throttle = FakeSender(), FakeThrottle()
    await check_schedules(
        repo=repo,
        sender=sender,
        throttle=throttle,
        now=datetime(2026, 3, 14, 6, 30, tzinfo=UTC),  # 09:30 Europe/Moscow
    )
    assert sender.sent == [(702, EMPTY_DIGEST_RU)], f"@S36: отправлено {sender.sent!r}"


# --- S37 (@R27): размер дайджеста 1..50, «меньше — приходит меньше» -----------


async def test_s37_digest_size_default_and_bounds() -> None:
    """@S37: дефолт 10 из 25; при размере 50 приходят все 25 (меньше вакансий — меньше)."""
    select_digest = load_attr("app.services.select", "select_digest")
    async with real_repo() as db:
        repo = db.repo
        await repo.upsert_preset(
            "python-backend", name=PRESET_NAMES_RU["python-backend"], filter_json=PERMISSIVE_FILTER
        )
        vacancies = [
            _card_vacancy(
                title=f"Python Developer {n:02d}",
                url=f"https://hh.ru/vacancy/{100 + n}",
                published_at=NOW.replace(day=1 + (n % 28)),
            )
            for n in range(25)
        ]
        assert await repo.add_vacancies(vacancies) == 25

        default_user = await repo.upsert_user(
            703,
            lang="ru",
            profile=make_profile(digest_size=10),
        )
        first = await select_digest(
            repo=repo, user=default_user, now=datetime(2026, 3, 14, 6, 30, tzinfo=UTC)
        )
        assert first is not None and len(first.items) == 10, (
            f"@S37: дефолтный размер {len(first.items) if first else 0} != 10"
        )

        big_user = await repo.upsert_user(
            704,
            lang="ru",
            profile=make_profile(digest_size=50),
        )
        second = await select_digest(
            repo=repo, user=big_user, now=datetime(2026, 3, 14, 6, 30, tzinfo=UTC)
        )
        assert second is not None and len(second.items) == 25, (
            f"@S37: при размере 50 из 25 вакансий получено "
            f"{len(second.items) if second else 0} != 25"
        )


def _broken_entities(text: str) -> list[str]:
    """Незакрытые/оборванные HTML-сущности после обрезки (R24)."""
    return re.findall(r"&(?!#?\w+;)", text)
