"""Acceptance-тесты сценариев S19–S26 — фильтры, пресеты и скоринг.

Чёрный ящик: публичное API ``app.filters.rules`` (api.md §7), ``app.storage.repo``
(api.md §9) и сид-миграция пресетов (``alembic upgrade head`` — AC-5). Теги
рисков — tests/features/filters_presets.feature.

S19/S26 проверяют данные сид-миграции — они создаются только миграциями,
поэтому тест идёт через публичную команду ``alembic upgrade head`` на чистой
тестовой БД (та же механика, что у S76). S20/S25 — отбор через ``select_candidates``
на реальном ``Repo``; S21–S24 — чистые функции фильтров.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fakes import (
    PERMISSIVE_FILTER,
    PRESET_NAMES_RU,
    PRESET_SLUGS,
    make_salary,
    make_tweaks,
    make_vacancy,
    migrated_db,
    real_repo,
)
from support import load_attr

MIN_SALARY_CASES = [
    ("от 250 000 ₽", True),
    ("от 180 000 ₽", False),
    ("от 2 000 $", True),
    ("до 150 000 ₽", False),
]

STOP_WORD_CASES = [
    ("junior", "Junior Python Developer", "Ромашка", False),
    ("junior", "Python Developer", "Junior Labs", False),
    ("junior", "Middle Python Developer", "Ромашка", True),
    ("стажировка", "Python Developer (стажировка)", "Ромашка", False),
    ("senior", "Team Lead Python", "Ромашка", True),
]


def _preset_filter(**overrides):
    """PresetFilter из JSONB-словаря (api.md §7: load_filter — публичный вход)."""
    load_filter = load_attr("app.filters.rules", "load_filter")
    data = dict(PERMISSIVE_FILTER)
    data.update(overrides)
    return load_filter(data)


def _published(day: int, month: int = 3) -> datetime:
    return datetime(2026, month, day, 9, 0, tzinfo=UTC)


# --- S19 (@R21): сид-миграция создаёт ровно 7 пресетов -----------------------


async def test_s19_seed_migration_creates_exactly_seven_presets() -> None:
    """@S19: после сид-миграции — ровно 7 пресетов с slug и именами из AC-5."""
    async with migrated_db() as db:
        assert db.migration.returncode == 0, (
            f"@S19: alembic upgrade head завершился ошибкой: {db.migration.stderr}"
        )
        presets = await db.repo.list_presets()
        by_slug = {preset.slug: preset for preset in presets}
        assert set(by_slug) == set(PRESET_SLUGS), (
            f"@S19: slug-и пресетов {sorted(by_slug)} != {sorted(PRESET_SLUGS)}"
        )
        assert len(presets) == 7, f"@S19: пресетов {len(presets)}, ожидалось ровно 7"
        for slug, name in PRESET_NAMES_RU.items():
            assert by_slug[slug].name_ru == name, (
                f"@S19: имя пресета {slug}: {by_slug[slug].name_ru!r} != {name!r}"
            )


# --- S20 (@R8 @R13): подписки + правки влияют на отбор ------------------------


async def test_s20_subscriptions_and_tweaks_affect_selection() -> None:
    """@S20: OR по подписанным пресетам; стоп-слово и мин. зарплата отсеивают."""
    tweaks = make_tweaks(min_salary_rub=200000, stop_words=["стажировка"])
    async with real_repo() as db:
        await db.repo.upsert_preset(
            "python-backend",
            name=PRESET_NAMES_RU["python-backend"],
            filter_json=dict(PERMISSIVE_FILTER, must=["python"]),
        )
        await db.repo.upsert_preset(
            "devops-sre",
            name=PRESET_NAMES_RU["devops-sre"],
            filter_json=dict(PERMISSIVE_FILTER, must=["devops"]),
        )
        vacancies = [
            make_vacancy(  # проходит оба фильтра — остаётся
                title="Python Developer",
                company="Romashka",
                description="python django",
                salary=make_salary(250000, None, "RUB"),
                url="https://hh.ru/vacancy/1",
            ),
            make_vacancy(  # стоп-слово «стажировка» — отсеивается
                title="Python Developer (стажировка)",
                company="Romashka",
                description="python",
                salary=make_salary(250000, None, "RUB"),
                url="https://hh.ru/vacancy/2",
            ),
            make_vacancy(  # зарплата ниже 200000 ₽ — отсеивается
                title="Python Engineer",
                company="Lavanda",
                description="python postgres",
                salary=make_salary(180000, None, "RUB"),
                url="https://hh.ru/vacancy/3",
            ),
            make_vacancy(  # проходит второй пресет (OR подписок) — остаётся
                title="DevOps Engineer",
                company="Kaktus",
                description="devops kubernetes",
                salary=make_salary(300000, None, "RUB"),
                url="https://hh.ru/vacancy/4",
            ),
            make_vacancy(  # ни один подписанный пресет — отсеивается
                title="Go Developer",
                company="Berezka",
                description="golang",
                salary=make_salary(400000, None, "RUB"),
                url="https://hh.ru/vacancy/5",
            ),
        ]
        assert await db.repo.add_vacancies(vacancies) == 5
        rows = await db.repo.select_candidates(
            user_id=1,
            preset_slugs=["python-backend", "devops-sre"],
            tweaks=tweaks,
            limit=50,
        )
        chosen = {row.title for row in rows}
        assert chosen == {"Python Developer", "DevOps Engineer"}, f"@S20: отбор {chosen}"


# --- S21 (@R8): сравнение мин. зарплаты с другой валютой ----------------------


@pytest.mark.parametrize(("raw", "passes"), MIN_SALARY_CASES)
async def test_s21_min_salary_cross_currency_decision(raw: str, passes: bool) -> None:
    """@S21: приблизительное сравнение по курсам (brief §7.3) даёт решение Examples."""
    parse_salary = load_attr("app.domain.currency", "parse_salary")
    meets_minimum = load_attr("app.domain.currency", "meets_minimum")
    salary = parse_salary(raw)
    assert salary is not None, f"@S21: зарплата {raw!r} не разобрана"
    decision = meets_minimum(salary, 200000)
    assert decision is passes, f"@S21: {raw!r} при мин. 200000: {decision}, ожидалось {passes}"


# --- S22 (@R8): вакансия без зарплаты проходит фильтр -------------------------


async def test_s22_vacancy_without_salary_passes_min_filter() -> None:
    """@S22: lenient-семантика (decisions §5.9): без зарплаты фильтр проходят."""
    meets_minimum = load_attr("app.domain.currency", "meets_minimum")
    assert meets_minimum(None, 200000) is True, (
        "@S22: вакансия без зарплаты должна проходить фильтр мин. зарплаты (decisions §5.9)"
    )


# --- S23 (@R13): стоп-слова по заголовку и компании ---------------------------


@pytest.mark.parametrize(("stop", "title", "company", "passes"), STOP_WORD_CASES)
async def test_s23_stop_words_filter_title_and_company(
    stop: str, title: str, company: str, passes: bool
) -> None:
    """@S23: стоп-слово — подстрока без учёта регистра в заголовке и компании."""
    matches = load_attr("app.filters.rules", "matches")
    preset = _preset_filter()
    tweaks = make_tweaks(stop_words=[stop])
    vacancy = make_vacancy(title=title, company=company)
    decision = matches(vacancy, preset, tweaks)
    assert decision is passes, (
        f"@S23: стоп-слово {stop!r} / {title!r} / {company!r}: {decision}, ожидалось {passes}"
    )


# --- S24 (@R13): must-стек обязателен, nice-стек повышает скоринг -------------


async def test_s24_must_stack_required_nice_stack_boosts_score() -> None:
    """@S24: без must фильтр не проходят; nice даёт баллы скоринга."""
    matches = load_attr("app.filters.rules", "matches")
    score = load_attr("app.filters.rules", "score")
    preset = _preset_filter(must=["python"], nice=["django", "postgres"])
    tweaks = make_tweaks()
    good = make_vacancy(title="Python Developer", description="python django")
    bad = make_vacancy(title="Go Developer", description="go", url="https://hh.ru/vacancy/456")
    assert matches(good, preset, tweaks) is True, "@S24: вакансия с must «python» не прошла"
    assert matches(bad, preset, tweaks) is False, "@S24: вакансия без must «python» прошла"
    assert score(good, preset, tweaks) > score(bad, preset, tweaks), (
        f"@S24: nice-стек не повысил скоринг: {score(good, preset, tweaks)} <= "
        f"{score(bad, preset, tweaks)}"
    )


# --- S25 (@R8): сортировка — скоринг уб., при равенстве свежие первыми --------


async def test_s25_digest_sorted_by_score_then_recency() -> None:
    """@S25: порядок select_candidates — score desc, published_at desc (brief §7.5)."""
    score = load_attr("app.filters.rules", "score")
    preset = _preset_filter(must=["python"], nice=["django"])
    tweaks = make_tweaks()
    fresh = make_vacancy(  # score «10» от 03.03.2026
        title="Python Developer",
        company="Romashka",
        description="python django",
        published_at=_published(3),
        url="https://hh.ru/vacancy/11",
    )
    stale = make_vacancy(  # score «10» от 01.03.2026
        title="Python Analyst",
        company="Lavanda",
        description="python django",
        published_at=_published(1),
        url="https://hh.ru/vacancy/12",
    )
    weak = make_vacancy(  # score «5» от 02.03.2026
        title="Python Junior",
        company="Kaktus",
        description="python",
        published_at=_published(2),
        url="https://hh.ru/vacancy/13",
    )
    assert score(fresh, preset, tweaks) == score(stale, preset, tweaks), (
        "@S25: две верхние вакансии должны иметь равный скоринг"
    )
    assert score(fresh, preset, tweaks) > score(weak, preset, tweaks), (
        "@S25: третья вакансия должна иметь меньший скоринг"
    )
    async with real_repo() as db:
        await db.repo.upsert_preset(
            "python-backend", name="Python Backend", filter_json=preset_json()
        )
        assert await db.repo.add_vacancies([fresh, weak, stale]) == 3
        rows = await db.repo.select_candidates(
            user_id=1, preset_slugs=["python-backend"], tweaks=tweaks, limit=10
        )
        order = [row.title for row in rows]
        assert order == ["Python Developer", "Python Analyst", "Python Junior"], (
            f"@S25: порядок {order} != [скоринг 10 от 03.03, скоринг 10 от 01.03, скоринг 5]"
        )


def preset_json() -> dict:
    return dict(PERMISSIVE_FILTER, must=["python"], nice=["django"])


# --- S26 (@R21): пресет «Другие backend-языки» с описанием --------------------


async def test_s26_backend_other_preset_has_name_and_description() -> None:
    """@S26: backend-other показывается с каноническим RU-именем и описанием фильтра."""
    async with migrated_db() as db:
        assert db.migration.returncode == 0, (
            f"@S26: alembic upgrade head завершился ошибкой: {db.migration.stderr}"
        )
        presets = {preset.slug: preset for preset in await db.repo.list_presets()}
        backend_other = presets.get("backend-other")
        assert backend_other is not None, f"@S26: нет пресета backend-other: {sorted(presets)}"
        assert backend_other.name_ru == "Другие backend-языки", (
            f"@S26: имя {backend_other.name_ru!r} != 'Другие backend-языки'"
        )
        description = (getattr(backend_other, "description", "") or "").strip()
        assert description, f"@S26: у backend-other нет описания состава фильтра: {backend_other!r}"
