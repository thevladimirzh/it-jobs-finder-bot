"""Acceptance-тесты сценариев S56–S60 — алерты админу, деградация, рассылка.

Чёрный ящик: ``app.services.collect`` (api.md §10) и ``app.services.dispatch``
(api.md §13) с двойниками границы; точный шаблон алерта — brief §6.1
(fakes.alert_line), алерты всегда RU (brief §7.10), не чаще одного в час на
источник (R16, decisions §5.14). S59/S60: FloodWaitError моделирует 429 с
retry_after (duck-typing aiogram TelegramRetryAfter).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import time as dt_time

import pytest
from fakes import (
    BROKEN_MARKUP_HTML,
    CAPTCHA_HTML,
    SOURCE_HABR,
    SOURCE_HH,
    FakeAlertSink,
    FakeClient,
    FakeResponse,
    FakeSender,
    FakeThrottle,
    FloodWaitError,
    InMemoryRepo,
    alert_line,
    habr_empty_page,
    habr_list_page,
    hh_empty_page,
    hh_list_page,
    make_profile,
    make_schedule,
    make_vacancy,
    model_profile_of,
)
from support import load_attr

ALERT_CASES = [
    ("hh.ru", "SourceBlocked", "блокировка/капча"),
    ("hh.ru", "ParseError", "ошибка разбора разметки"),
    ("hh.ru", "EmptyResult", "пустой разбор"),
    ("hh.ru", "SourceUnavailable", "источник недоступен"),
    ("Habr Career", "SourceBlocked", "блокировка/капча"),
    ("Habr Career", "ParseError", "ошибка разбора разметки"),
    ("Habr Career", "EmptyResult", "пустой разбор"),
    ("Habr Career", "SourceUnavailable", "источник недоступен"),
]

STATUS_BY_FAILURE = {
    "SourceBlocked": "blocked",
    "ParseError": "parse_error",
    "EmptyResult": "empty",
    "SourceUnavailable": "unavailable",
}


def _failure_payload(source: str, failure: str):
    """Ответ/ошибка FakeClient для нужного вида сбоя источника."""
    empty_page = hh_empty_page() if source == SOURCE_HH else habr_empty_page()
    return {
        "SourceBlocked": FakeResponse(text=CAPTCHA_HTML, status_code=403),
        "ParseError": FakeResponse(text=BROKEN_MARKUP_HTML),
        "EmptyResult": FakeResponse(text=empty_page),
        "SourceUnavailable": TimeoutError("connection timed out"),
    }[failure]


def _client_with_failure(source: str, failure: str) -> FakeClient:
    failing = _failure_payload(source, failure)
    ok_page = (
        FakeResponse(text=hh_list_page())
        if source == SOURCE_HABR
        else FakeResponse(text=habr_list_page())
    )
    if source == SOURCE_HH:
        return FakeClient.for_sources(hh=failing, habr=ok_page)
    return FakeClient.for_sources(hh=ok_page, habr=failing)


async def _run_collect(client: FakeClient, repo, alerts, now: datetime):
    run_collect = load_attr("app.services.collect", "run_collect")
    return await run_collect(client=client, repo=repo, alerts=alerts, now=now)


# --- S56 (@R1 @R2 @R40): алерт по точному шаблону §6.1 -----------------------


@pytest.mark.parametrize(("source", "failure", "reason"), ALERT_CASES)
async def test_s56_alert_template_verbatim(source: str, failure: str, reason: str) -> None:
    """@S56: ровно одно сообщение «⚠️ Сбор {source}: {reason}» на каждый сбой."""
    repo, alerts = InMemoryRepo(), FakeAlertSink()
    reports = await _run_collect(_client_with_failure(source, failure), repo, alerts, _NOON)
    by_source = {report.source: report for report in reports}
    assert by_source[source].status == STATUS_BY_FAILURE[failure], (
        f"@S56: статус {source}/{failure}: {by_source[source].status!r}"
    )
    assert alerts.texts == [alert_line(source, reason)], (
        f"@S56: алерты {alerts.texts!r} != [{alert_line(source, reason)!r}]"
    )


_NOON = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


# --- S57 (@R16): алерты не чаще одного в час на источник ---------------------


async def test_s57_alerts_aggregated_within_hour_window() -> None:
    """@S57: ≤1 алерта/час; подавленные считаются; после часа следующий сбой алертит."""
    repo, alerts = InMemoryRepo(), FakeAlertSink()
    client = _client_with_failure(SOURCE_HH, "ParseError")
    base = datetime.now(UTC)

    for i in range(6):  # 6 сбоев подряд в течение часа
        await _run_collect(client, repo, alerts, base + timedelta(minutes=5 * i))

    sent_for_hh = [text for text in alerts.texts if SOURCE_HH in text]
    assert len(sent_for_hh) <= 1, f"@S57: алерт-шторм: {alerts.texts!r}"
    assert repo.suppressed.get(SOURCE_HH) == 5, (
        f"@S57: подавленные события не учтены счётчиком: {repo.suppressed!r}"
    )

    await _run_collect(client, repo, alerts, base + timedelta(minutes=65))
    sent_for_hh = [text for text in alerts.texts if SOURCE_HH in text]
    assert len(sent_for_hh) == 2, f"@S57: после часа сбой не отправил новый алерт: {alerts.texts!r}"


# --- S58 (@R1 @R11): graceful degradation -----------------------------------


async def test_s58_degraded_source_still_delivers_digest() -> None:
    """@S58: Habr Career недоступен → дайджест из hh.ru + алерт; без ошибок пользователю."""
    check_schedules = load_attr("app.services.scheduler", "check_schedules")
    repo, alerts = InMemoryRepo(), FakeAlertSink()
    profile = make_profile(schedule=make_schedule(dt_time(9, 30), "Europe/Moscow"))
    await repo.upsert_user(831, lang="ru", profile=model_profile_of(profile))
    await repo.add_vacancies(
        [
            make_vacancy(
                title="Python Developer",
                company="Romashka",
                url="https://hh.ru/vacancy/581",
                source=SOURCE_HH,
                published_at=datetime(2026, 3, 13, 9, 0, tzinfo=UTC),
            )
        ]
    )

    client = FakeClient.for_sources(
        hh=FakeResponse(text=hh_list_page()),
        habr=TimeoutError("connection timed out"),
    )
    await _run_collect(client, repo, alerts, datetime(2026, 3, 14, 6, 0, tzinfo=UTC))
    assert alerts.texts == [alert_line(SOURCE_HABR, "источник недоступен")], (
        f"@S58: алерты: {alerts.texts!r}"
    )

    sender, throttle = FakeSender(), FakeThrottle()
    await check_schedules(
        repo=repo,
        sender=sender,
        throttle=throttle,
        now=datetime(2026, 3, 14, 6, 30, tzinfo=UTC),
    )
    texts = sender.texts_for(831)
    assert texts, "@S58: дайджест из оставшегося источника не доставлен"
    assert all("⚠️" not in text and "Сбор" not in text for text in texts), (
        f"@S58: пользователю ушли ошибки парсинга: {texts!r}"
    )


# --- S59 (@R9): троттлинг и ретраи при FloodWait -----------------------------


async def test_s59_dispatch_throttled_with_flood_retries() -> None:
    """@S59: очередь со паузами (throttle); 429 повторяются после retry_after; все получают."""
    dispatch = load_attr("app.services.dispatch", "dispatch")
    message_cls = load_attr("app.services.dispatch", "OutgoingMessage")
    flood_chats = {2000 + i for i in range(10)}
    failures = {chat: [FloodWaitError(0.01)] for chat in flood_chats}
    sender, throttle = FakeSender(failures), FakeThrottle()
    messages = [message_cls(chat_id=2000 + i, text=f"digest {i}") for i in range(100)]

    report = await dispatch(messages, sender=sender, throttle=throttle, now=_NOON)

    assert report.sent == 100, f"@S59: отправлено {report.sent} из 100: {report.failed!r}"
    assert report.failed == (), f"@S59: неудачные отправки в отчёте: {report.failed!r}"
    assert len(sender.sent) == 100, f"@S59: доставлено {len(sender.sent)} сообщений"
    assert len({chat for chat, _text in sender.sent}) == 100, (
        f"@S59: есть повторные отправки: {sender.sent!r}"
    )
    assert throttle.waits > 0, "@S59: рассылка без троттлинга (пауз под лимиты Telegram)"


# --- S60 (@R42): ошибка одного получателя не рвёт очередь --------------------


async def test_s60_dispatch_failure_does_not_break_queue() -> None:
    """@S60: chat not found у пользователя 2 → остальные доставлены ровно по разу."""
    dispatch = load_attr("app.services.dispatch", "dispatch")
    message_cls = load_attr("app.services.dispatch", "OutgoingMessage")
    sender = FakeSender(failures={2: [RuntimeError("chat not found")]})
    throttle = FakeThrottle()
    messages = [message_cls(chat_id=chat, text=f"digest {chat}") for chat in (1, 2, 3)]

    report = await dispatch(messages, sender=sender, throttle=throttle, now=_NOON)

    assert report.sent == 2, f"@S60: отправлено {report.sent}: {report.failed!r}"
    failed_chats = [chat for chat, _reason in report.failed]
    assert failed_chats == [2], f"@S60: в отчёте не тот получатель: {report.failed!r}"
    assert [chat for chat, _text in sender.sent] == [1, 3], (
        f"@S60: очередь прервана или продублирована: {sender.sent!r}"
    )
