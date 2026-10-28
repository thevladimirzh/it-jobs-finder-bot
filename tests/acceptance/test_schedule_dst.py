"""Acceptance-тесты сценариев S38–S44 — расписание, DST и догоняющее окно.

Чёрный ящик: ``app.services.scheduler`` (api.md §14) с инжекцией репозитория и
отправителя (api.md §0); время передаётся явно через ``now`` — часы не тикают.
S38–S42: InMemoryRepo (семантика слотов — предмет теста); S43–S44: реальный
``Repo`` + тестовая БД (персистентность отметок при рестарте, гонки).

DST-даты Europe/Berlin: 29.03.2026 — перевод вперёд («дыра» 02:00–03:00),
25.10.2026 — перевод назад (двойное локальное время 02:00–03:00). Сценарии
требуют ровно один выпуск за локальные сутки (decisions §5.15).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from fakes import (
    PERMISSIVE_FILTER,
    PRESET_NAMES_RU,
    SOURCE_HH,
    FakeClient,
    FakeResponse,
    FakeSender,
    FakeThrottle,
    InMemoryRepo,
    ProbeSessionFactory,
    hh_list_page,
    make_profile,
    make_schedule,
    make_vacancy,
    model_profile_of,
    real_repo,
)
from support import load_attr

UID = 801
BERLIN = ZoneInfo("Europe/Berlin")
_URL_SEQ = iter(range(1000, 10000))


def _schedule(hour: int, minute: int = 30) -> object:
    return make_schedule(dt_time(hour, minute), "Europe/Berlin")


def _profile(hour: int, minute: int = 30) -> object:
    return model_profile_of(make_profile(schedule=_schedule(hour, minute)))


async def _seed_vacancy(repo, title: str = "Python Developer") -> None:
    """Кэш вакансий + подписанный permissive-пресет.

    Пресет обязателен: ``select_candidates`` отбирает только по фильтру хотя бы
    одного подписанного пресета (api.md §9) — без него кандидатов нет и уходит
    пустой дайджест (Q3), а не «🔥 Подборка вакансий». Подписка пользователя —
    ``make_profile()`` (presets=["python-backend"]), как в S35/S43/S44.
    """
    await repo.upsert_preset(
        "python-backend", name=PRESET_NAMES_RU["python-backend"], filter_json=PERMISSIVE_FILTER
    )
    await repo.add_vacancies(
        [
            make_vacancy(
                title=title,
                company="Romashka",
                url=f"https://hh.ru/vacancy/{next(_URL_SEQ)}",
                source=SOURCE_HH,
                published_at=datetime(2026, 6, 14, 9, 0, tzinfo=UTC),
            )
        ]
    )


async def _sweep(repo, sender, throttle, start: datetime, end: datetime, step_min: int) -> None:
    """Ежеминутная проверка расписания, смоделированная с шагом step_min."""
    check_schedules = load_attr("app.services.scheduler", "check_schedules")
    now = start
    while now <= end:
        await check_schedules(repo=repo, sender=sender, throttle=throttle, now=now)
        now += timedelta(minutes=step_min)


# --- S38 (@R6): дайджест в выбранное время, один раз за слот -----------------


async def test_s38_digest_at_selected_local_time_once_per_slot() -> None:
    """@S38: в 09:30 Europe/Berlin дайджест уходит; повторно в тот же слот — нет."""
    repo = InMemoryRepo()
    await repo.upsert_user(UID, lang="ru", profile=_profile(9))
    await _seed_vacancy(repo)
    sender, throttle = FakeSender(), FakeThrottle()

    before = datetime(2026, 6, 15, 7, 29, tzinfo=UTC)  # 09:29 Berlin
    at_slot = datetime(2026, 6, 15, 7, 30, tzinfo=UTC)  # 09:30 Berlin
    after = datetime(2026, 6, 15, 7, 31, tzinfo=UTC)  # 09:31 Berlin

    await _sweep(repo, sender, throttle, before, before, 1)
    assert sender.texts_for(UID) == [], f"@S38: дайджест пришёл раньше слота: {sender.sent!r}"
    await _sweep(repo, sender, throttle, at_slot, after, 1)
    texts = sender.texts_for(UID)
    assert len(texts) == 1, f"@S38: за слот отправлено сообщений: {len(texts)} ({sender.sent!r})"
    assert texts[0].startswith("🔥 Подборка вакансий"), f"@S38: это не дайджест: {texts[0]!r}"


# --- S39 (@R6): перевод часов вперёд — без пропуска выпуска -----------------


async def test_s39_spring_forward_gap_sends_exactly_one_digest() -> None:
    """@S39: «дыра» 02:30 → выпуск в первый существующий момент после дыры, один."""
    local_slot = load_attr("app.services.scheduler", "local_slot")
    repo = InMemoryRepo()
    await repo.upsert_user(UID, lang="ru", profile=_profile(2))
    await _seed_vacancy(repo)
    sender, throttle = FakeSender(), FakeThrottle()

    slot = local_slot(_schedule(2), date(2026, 3, 29))
    local = slot.astimezone(BERLIN)
    assert (local.hour, local.minute) >= (3, 0), (
        f"@S39: слот {local.isoformat()} попал в «дыру» или раньше её "
        "(первый существующий момент после дыры — не раньше 03:00)"
    )

    await _sweep(
        repo,
        sender,
        throttle,
        datetime(2026, 3, 28, 22, 0, tzinfo=UTC),
        datetime(2026, 3, 29, 5, 0, tzinfo=UTC),
        15,
    )
    texts = sender.texts_for(UID)
    assert len(texts) == 1, f"@S39: за локальные сутки выпусков: {len(texts)} ({sender.sent!r})"


# --- S40 (@R6): перевод часов назад — без дубля выпуска ----------------------


async def test_s40_fall_back_overlap_sends_exactly_one_digest() -> None:
    """@S40: двойное локальное время 02:30 → ровно один выпуск за сутки."""
    repo = InMemoryRepo()
    await repo.upsert_user(UID, lang="ru", profile=_profile(2))
    await _seed_vacancy(repo)
    sender, throttle = FakeSender(), FakeThrottle()

    await _sweep(
        repo,
        sender,
        throttle,
        datetime(2026, 10, 24, 22, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 6, 0, tzinfo=UTC),
        15,
    )
    texts = sender.texts_for(UID)
    assert len(texts) == 1, f"@S40: за локальные сутки выпусков: {len(texts)} ({sender.sent!r})"


# --- S41 (@R6 @R11): простой ≤3 ч — слот догоняется -------------------------


async def test_s41_catchup_within_three_hours() -> None:
    """@S41: восстановление через 2 ч 59 мин → догон сразу; слот повторно не живёт."""
    repo = InMemoryRepo()
    await repo.upsert_user(UID, lang="ru", profile=_profile(9))
    await _seed_vacancy(repo)
    sender, throttle = FakeSender(), FakeThrottle()

    recovered = datetime(2026, 6, 15, 10, 29, tzinfo=UTC)  # слот 07:30 UTC + 2:59
    later = datetime(2026, 6, 15, 11, 0, tzinfo=UTC)
    await _sweep(repo, sender, throttle, recovered, recovered, 1)
    assert len(sender.texts_for(UID)) == 1, f"@S41: слот не догнан: {sender.sent!r}"
    await _sweep(repo, sender, throttle, later, later, 1)
    assert len(sender.texts_for(UID)) == 1, f"@S41: слот отработан повторно: {sender.sent!r}"


# --- S42 (@R6): простой >3 ч — слот не догоняется ---------------------------


async def test_s42_no_catchup_after_three_hours() -> None:
    """@S42: восстановление через 3 ч 1 мин → пропуск; следующий выпуск — в свой слот."""
    repo = InMemoryRepo()
    await repo.upsert_user(UID, lang="ru", profile=_profile(9))
    await _seed_vacancy(repo)
    sender, throttle = FakeSender(), FakeThrottle()

    recovered = datetime(2026, 6, 15, 10, 31, tzinfo=UTC)  # слот + 3:01
    await _sweep(repo, sender, throttle, recovered, recovered, 1)
    assert sender.texts_for(UID) == [], f"@S42: старый слот догнан за окном: {sender.sent!r}"

    next_slot = datetime(2026, 6, 16, 7, 30, tzinfo=UTC)  # следующий обычный слот
    await _sweep(repo, sender, throttle, next_slot, next_slot, 1)
    assert len(sender.texts_for(UID)) == 1, f"@S42: следующий слот не пришёл: {sender.sent!r}"


# --- S43 (@R32 @R3): рестарт посреди рассылки без повторов -------------------


async def test_s43_restart_mid_dispatch_no_duplicate_delivery() -> None:
    """@S43: после рестарта уже получившие не получают повторно, остальные — в окне."""
    check_schedules = load_attr("app.services.scheduler", "check_schedules")
    select_digest = load_attr("app.services.select", "select_digest")
    async with real_repo() as db:
        repo = db.repo
        profile = make_profile(schedule=_schedule(9))
        user_a = await repo.upsert_user(811, lang="ru", profile=profile)
        await repo.upsert_user(812, lang="ru", profile=profile)
        await repo.upsert_preset(
            "python-backend", name=PRESET_NAMES_RU["python-backend"], filter_json=PERMISSIVE_FILTER
        )
        await repo.add_vacancies(
            [
                make_vacancy(
                    title="Python Developer",
                    company="Romashka",
                    url="https://hh.ru/vacancy/431",
                    source=SOURCE_HH,
                    published_at=datetime(2026, 6, 14, 9, 0, tzinfo=UTC),
                )
            ]
        )

        slot_now = datetime(2026, 6, 15, 7, 30, tzinfo=UTC)
        delivered = await select_digest(repo=repo, user=user_a, now=slot_now)
        assert delivered is not None, "@S43: не удалось выдать дайджест первому получателю"

        # «рестарт»: состояние только в БД; догон в пределах окна (+30 мин)
        sender, throttle = FakeSender(), FakeThrottle()
        await check_schedules(
            repo=repo, sender=sender, throttle=throttle, now=slot_now + timedelta(minutes=30)
        )
        assert sender.texts_for(811) == [], (
            f"@S43: уже получивший дайджест получил его повторно: {sender.sent!r}"
        )
        assert len(sender.texts_for(812)) == 1, f"@S43: оставшийся без дайджеста: {sender.sent!r}"


# --- S44 (@R32 @R31): сбор и рассылка одновременно, без гонок и удержаний ----


async def test_s44_concurrent_collect_and_digest_without_races() -> None:
    """@S44: одновременные сбор и дайджест без двойных доставок; сессии БД не
    удерживаются на время HTTP-вызовов (R31)."""
    check_schedules = load_attr("app.services.scheduler", "check_schedules")
    run_collect = load_attr("app.services.collect", "run_collect")
    select_digest = load_attr("app.services.select", "select_digest")

    # Фаза 1: гонка «сбор + рассылка» — каждая вакансия доставляется не более раза.
    async with real_repo() as db:
        repo = db.repo
        profile = make_profile(schedule=_schedule(9))
        user = await repo.upsert_user(821, lang="ru", profile=profile)
        await repo.upsert_preset(
            "python-backend", name=PRESET_NAMES_RU["python-backend"], filter_json=PERMISSIVE_FILTER
        )
        slot_now = datetime(2026, 6, 15, 7, 30, tzinfo=UTC)
        client = FakeClient.for_sources(
            hh=FakeResponse(text=hh_list_page()),
            habr=FakeResponse(text=hh_list_page()),
        )
        sender, throttle, alerts = FakeSender(), FakeThrottle(), _Sink()
        await asyncio.gather(
            run_collect(client=client, repo=repo, alerts=alerts, now=slot_now),
            check_schedules(repo=repo, sender=sender, throttle=throttle, now=slot_now),
        )
        assert len(sender.texts_for(821)) == 1, f"@S44: дайджест не один: {sender.sent!r}"
        again = await select_digest(repo=repo, user=user, now=slot_now)
        assert again is None or not again.items, f"@S44: слот отработал повторно: {again!r}"

    # Фаза 2 (R31): ни одна сессия БД не удерживается на время HTTP-вызова.
    probe = ProbeSessionFactory()
    repo = load_attr("app.storage.repo", "Repo")(probe)
    slow_client = FakeClient.for_sources(
        hh=FakeResponse(text=hh_list_page()),
        habr=FakeResponse(text=hh_list_page()),
        fallback=FakeResponse(text=hh_list_page()),
    )
    slow_client.delay = 0.02
    slow_client.on_request = lambda url: probe.assert_none_open(f"HTTP-запрос {url[:40]!r}")

    async def db_hammer() -> None:
        for i in range(10):
            await repo.get_user(i)

    await asyncio.gather(
        run_collect(client=slow_client, repo=repo, alerts=_Sink(), now=slot_now),
        db_hammer(),
    )
    probe.assert_none_open("после завершения сбора")
    assert probe.sessions, "@S44: сбор не открывал сессий — проверка R31 вакуумна"


class _Sink:
    """Минимальный AlertSink для фаз, где алерты не проверяются."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def send_admin(self, text: str) -> None:
        self.texts.append(text)
