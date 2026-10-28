"""Acceptance-тесты сценариев S63–S66 — i18n (RU/EN).

Чёрный ящик: константы ``app/services/digest`` и ``app/domain/currency``
(точные строки brief §6.1), ``app/i18n`` (api.md §3) и бот через BotHarness.
Алерты админу всегда RU (brief §7.10, S66). Точные строки Examples —
tests/features/i18n.feature (копируются дословно).

I-2 (decisions §8): выбор/смена языка — кнопкой «Русский»/«English»
(``dlg:lang:*``); текстовый ввод «lang:ru»/«en» упразднён — setup S63/S64
обновлён под кнопочный диалог (ожидаемая переделка, не регрессия).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from dialog import onboard, open_step, press
from fakes import (
    BROKEN_MARKUP_HTML,
    EMPTY_DIGEST_EN,
    EMPTY_DIGEST_RU,
    FEEDBACK_ERROR_EN,
    FEEDBACK_ERROR_RU,
    SALARY_NONE,
    FakeAlertSink,
    FakeClient,
    FakeResponse,
    InMemoryRepo,
    alert_line,
    deliver_texts,
    habr_list_page,
    make_profile,
    make_vacancy,
    model_profile_of,
    open_bot,
    send_text,
)
from support import load_attr

ON_DATE = date(2026, 3, 14)
NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)

I18N_CASES = [
    ("ru", "🔥 Подборка вакансий \u2014 14.03.2026 (1)", "Зарплата не указана", "👍 Учтено"),
    ("en", "🔥 Job digest \u2014 14.03.2026 (1)", "Salary not specified", "👍 Noted"),
]


# --- S63 (@R20): пользовательские строки на выбранном языке -----------------


@pytest.mark.parametrize(("lang", "header", "salary", "like"), I18N_CASES)
async def test_s63_user_strings_in_selected_language(
    lang: str, header: str, salary: str, like: str
) -> None:
    """@S63: заголовок дайджеста, строка зарплаты и ответ /like — на языке пользователя."""
    render_header = load_attr("app.services.digest", "render_header")
    format_salary = load_attr("app.domain.currency", "format_salary")
    assert render_header(1, ON_DATE, lang) == header, f"@S63: заголовок {lang}: {header!r}"
    assert format_salary(None, lang) == salary, f"@S63: зарплата {lang}: {salary!r}"

    async with open_bot() as h:
        user_id = 1101 if lang == "ru" else 1102
        await onboard(h, user_id, lang=lang)  # I-2: выбор языка кнопкой
        await h.seed_vacancies(
            [make_vacancy(title="Python Developer", salary=None, url="https://hh.ru/vacancy/631")]
        )
        assert await deliver_texts(h, user_id), f"@S63: дайджест не доставлен ({lang})"
        reply = await send_text(h, user_id, "/like 1")
        assert reply == [like], f"@S63: ответ /like на {lang}: {reply!r}"


# --- S64 (@R20): смена языка переключает последующий вывод ------------------


async def test_s64_language_switch_affects_only_new_messages() -> None:
    """@S64: после /settings lang EN ответы на английском; старые сообщения не меняются."""
    async with open_bot() as h:
        user_id = 1103
        await onboard(h, user_id, lang="ru")  # I-2: выбор языка кнопкой
        before = await send_text(h, user_id, "/like 1")
        assert before == [FEEDBACK_ERROR_RU], f"@S64: RU-ответ до смены языка: {before!r}"

        await open_step(h, user_id, "lang")
        await press(h, "dlg:lang:en", user_id=user_id)  # I-2: смена языка кнопкой «English»
        after = await send_text(h, user_id, "/like 1")
        assert after == [FEEDBACK_ERROR_EN], f"@S64: ответ после смены языка: {after!r}"
        assert before == [FEEDBACK_ERROR_RU], f"@S64: старое сообщение изменилось: {before!r}"


# --- S65 (@R39): словари RU/EN паритетны ------------------------------------


async def test_s65_ru_and_en_dictionaries_have_key_parity() -> None:
    """@S65: множества ключей совпадают; строки обоих языков непустые и не смешаны."""
    keys = load_attr("app.i18n", "keys")
    t = load_attr("app.i18n", "t")
    render_empty = load_attr("app.services.digest", "render_empty")
    render_header = load_attr("app.services.digest", "render_header")
    format_salary = load_attr("app.domain.currency", "format_salary")

    assert keys("ru") == keys("en"), (
        f"@S65: ключи RU/EN расходятся: только ru={keys('ru') - keys('en')}, "
        f"только en={keys('en') - keys('ru')}"
    )
    for key in sorted(keys("ru")):
        ru_value, en_value = t(key, "ru"), t(key, "en")
        assert isinstance(ru_value, str) and ru_value.strip(), f"@S65: пустая RU-строка {key!r}"
        assert isinstance(en_value, str) and en_value.strip(), f"@S65: пустая EN-строка {key!r}"

    # наблюдаемые шаблоны не смешивают языки (brief §6.1)
    assert render_empty("ru") == EMPTY_DIGEST_RU, (
        f"@S65: RU-пустой дайджест: {render_empty('ru')!r}"
    )
    assert render_empty("en") == EMPTY_DIGEST_EN, (
        f"@S65: EN-пустой дайджест: {render_empty('en')!r}"
    )
    assert render_header(1, ON_DATE, "ru").startswith("🔥 Подборка вакансий"), (
        f"@S65: RU-заголовок: {render_header(1, ON_DATE, 'ru')!r}"
    )
    assert render_header(1, ON_DATE, "en").startswith("🔥 Job digest"), (
        f"@S65: EN-заголовок: {render_header(1, ON_DATE, 'en')!r}"
    )
    assert format_salary(None, "ru") == SALARY_NONE["ru"]
    assert format_salary(None, "en") == SALARY_NONE["en"]


# --- S66 (@R20 @R38): алерты админу всегда RU --------------------------------


async def test_s66_alerts_are_always_russian() -> None:
    """@S66: алерт о сбое — RU-строка шаблона §6.1 независимо от языка пользователя."""
    run_collect = load_attr("app.services.collect", "run_collect")
    repo, alerts = InMemoryRepo(), FakeAlertSink()
    en_profile = make_profile(lang="en")
    await repo.upsert_user(1104, lang="en", profile=model_profile_of(en_profile))
    client = FakeClient.for_sources(
        hh=FakeResponse(text=BROKEN_MARKUP_HTML),
        habr=FakeResponse(text=habr_list_page()),
    )
    await run_collect(client=client, repo=repo, alerts=alerts, now=NOW)
    assert alerts.texts == [alert_line("hh.ru", "ошибка разбора разметки")], (
        f"@S66: алерт не на русском/не по шаблону: {alerts.texts!r}"
    )
