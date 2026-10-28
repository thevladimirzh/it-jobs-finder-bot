"""Юнит-тесты сервисов без БД: слоты, выборка, рассылка, алерты, retention.

U-SCH-01 (слоты/DST), U-SEL-02/03/04 (at-most-once, claim_slot, выборка),
U-SEND-01/02 (троттлинг/ретраи, изоляция ошибок), U-ALERT-01 (агрегация),
U-RET-01 (граница retention), U-SES-01 (короткие сессии Repo), U-UX-02/03.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from zoneinfo import ZoneInfo

import pytest

from app.domain.currency import Salary
from app.domain.profile import Profile, Schedule, profile_to_jsonb
from app.services.collect import run_collect
from app.services.dispatch import OutgoingMessage, dispatch
from app.services.scheduler import local_slot, run_cleanup, slot_key
from app.services.select import select_digest

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


class _Vacancy:
    _next = 0

    def __init__(self, title: str = "Python Developer", **values: object) -> None:
        _Vacancy._next += 1
        self.id = _Vacancy._next
        self.title = title
        self.company = "Ромашка"
        self.salary: Salary | None = None
        self.url = f"https://hh.ru/vacancy/{self.id}"
        self.source = "hh.ru"
        self.published_at = NOW
        self.description = ""
        self.__dict__.update(values)


class _User:
    def __init__(self, user_id: int = 1, *, with_schedule: bool = True) -> None:
        schedule = Schedule(dt_time(9, 30), "Europe/Moscow") if with_schedule else None
        profile = Profile(
            lang="ru",
            presets=["python-backend"],
            stop_words=[],
            digest_size=10,
            schedule=schedule,
        )
        self.id = user_id
        self.lang = "ru"
        self.profile = profile_to_jsonb(profile)


class _Repo:
    """Минимальная модель семантики Repo (api.md §9) для юнит-тестов."""

    def __init__(self, vacancies: list[_Vacancy] | None = None) -> None:
        self.vacancies = vacancies or []
        self.deliveries: set[tuple[int, int]] = set()
        self.slots: set[tuple[int, str]] = set()
        self.reminders: set[int] = set()
        self.users: dict[int, _User] = {}

    async def select_candidates(self, *, user_id, preset_slugs, tweaks, limit):
        return [v for v in self.vacancies if (user_id, v.id) not in self.deliveries][:limit]

    async def claim_slot(self, *, user_id, slot_key):
        key = (user_id, slot_key)
        if key in self.slots:
            return False
        self.slots.add(key)
        return True

    async def mark_delivered(self, *, user_id, vacancy_ids, slot_key):
        for vacancy_id in vacancy_ids:
            self.deliveries.add((user_id, vacancy_id))
        self.slots.add((user_id, slot_key))

    async def list_users(self):
        return list(self.users.values())

    async def purge_old(self, *, cutoff_utc):
        keep = [v for v in self.vacancies if v.published_at >= cutoff_utc]
        removed = len(self.vacancies) - len(keep)
        self.vacancies = keep
        return removed


class _Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_html(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


class _Throttle:
    def __init__(self) -> None:
        self.waits = 0

    async def wait(self) -> None:
        self.waits += 1


class _Flood(Exception):
    def __init__(self, retry_after: float) -> None:
        super().__init__("flood")
        self.retry_after = retry_after


# --- U-SCH-01 (R6): слоты и DST ----------------------------------------------


def test_u_sch01_local_slot_dst_gap_overlap_and_keys() -> None:
    schedule = Schedule(dt_time(2, 30), "Europe/Berlin")
    gap = local_slot(schedule, date(2026, 3, 29))  # перевод вперёд: 02:30 не существует
    assert (gap.astimezone(ZoneInfo("Europe/Berlin")).hour, gap.minute) >= (3, 0)
    overlap = local_slot(schedule, date(2026, 10, 25))  # перевод назад: 02:30 дважды
    assert overlap == datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    assert slot_key(1, schedule, date(2026, 3, 29)) != slot_key(1, schedule, date(2026, 3, 30))
    assert slot_key(1, schedule, date(2026, 3, 29)) != slot_key(2, schedule, date(2026, 3, 29))


# --- U-SEL-02/03 (R3, R32): at-most-once доставка и слот ---------------------


def test_u_sel02_delivery_at_most_once_per_user() -> None:
    repo = _Repo([_Vacancy(f"Vacancy {n}") for n in range(3)])
    user = _User()

    async def go() -> None:
        first = await select_digest(repo=repo, user=user, now=NOW, limit=2)
        assert first is not None and len(first.items) == 2
        second = await select_digest(repo=repo, user=user, now=NOW + timedelta(days=1), limit=2)
        assert second is not None and len(second.items) == 1

    import asyncio

    asyncio.run(go())
    assert len(repo.deliveries) == 3


def test_u_sel03_claim_slot_processes_slot_only_once() -> None:
    repo = _Repo([_Vacancy()])
    user = _User()

    async def go() -> None:
        first = await select_digest(repo=repo, user=user, now=NOW)
        assert first is not None
        again = await select_digest(repo=repo, user=user, now=NOW)
        assert again is None  # слот отработан (claim_slot)

    import asyncio

    asyncio.run(go())


def test_u_sel04_selection_is_bounded_and_fast() -> None:
    """U-SEL-04 (R34): выборка ограничена лимитом и не разрастается."""
    import asyncio
    import time

    repo = _Repo([_Vacancy(f"Vacancy {n}") for n in range(5000)])
    user = _User()

    async def go() -> int:
        started = time.perf_counter()
        selection = await select_digest(repo=repo, user=user, now=NOW, limit=10)
        assert time.perf_counter() - started < 2
        assert selection is not None and len(selection.items) == 10
        return len(selection.items)

    assert asyncio.run(go()) == 10


# --- U-UX-02 (R27): границы digest_size --------------------------------------


def test_u_ux02_digest_limit_bounds() -> None:
    import asyncio

    repo = _Repo([_Vacancy()])
    user = _User()
    for bad in (0, 51, -1, 10**6):
        with pytest.raises(ValueError):
            asyncio.run(select_digest(repo=repo, user=user, now=NOW, limit=bad))


# --- U-UX-03 (R18): незавершённый /start → одно напоминание ------------------


def test_u_ux03_no_schedule_sends_single_reminder() -> None:
    import asyncio

    from app.services.scheduler import check_schedules

    repo = _Repo()
    repo.users[7] = _User(7, with_schedule=False)
    sender, throttle = _Sender(), _Throttle()

    async def go() -> None:
        for day in (1, 2):
            await check_schedules(
                repo=repo,
                sender=sender,
                throttle=throttle,
                now=datetime(2026, 3, day, 12, 0, tzinfo=UTC),
            )

    asyncio.run(go())
    assert len(sender.sent) == 1


# --- U-SEND-01/02 (R9, R42): ретраи FloodWait и изоляция ошибок -------------


class _PlanSender(_Sender):
    def __init__(self, plan: dict[int, list[Exception]]) -> None:
        super().__init__()
        self.plan = {chat: list(excs) for chat, excs in plan.items()}

    async def send_html(self, chat_id: int, text: str) -> None:
        plan = self.plan.get(chat_id)
        if plan:
            raise plan.pop(0)
        await super().send_html(chat_id, text)


def test_u_send01_flood_wait_retried_with_throttle() -> None:
    import asyncio

    sender = _PlanSender({2: [_Flood(0.0)]})
    throttle = _Throttle()
    messages = [OutgoingMessage(1, "a"), OutgoingMessage(2, "b"), OutgoingMessage(3, "c")]
    report = asyncio.run(dispatch(messages, sender=sender, throttle=throttle, now=NOW))
    assert report.sent == 3
    assert report.failed == ()
    assert throttle.waits >= 3


def test_u_send02_one_recipient_failure_does_not_break_queue() -> None:
    import asyncio

    sender = _PlanSender({2: [RuntimeError("chat not found")]})
    messages = [OutgoingMessage(chat, "digest") for chat in (1, 2, 3)]
    report = asyncio.run(dispatch(messages, sender=sender, throttle=_Throttle(), now=NOW))
    assert report.sent == 2
    assert [chat for chat, _reason in report.failed] == [2]
    assert [chat for chat, _text in sender.sent] == [1, 3]


# --- U-ALERT-01 (R16): агрегация алертов 1/час -------------------------------


class _Alerts:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def send_admin(self, text: str) -> None:
        self.texts.append(text)


class _BrokenRepo(_Repo):
    """Репозиторий с журналом сборов для проверки окна алертов."""

    def __init__(self) -> None:
        super().__init__()
        self.runs: list[tuple[str, bool, datetime]] = []
        self.suppressed: dict[str, int] = {}

    async def record_parse_run(self, *, source, status, added, alert_sent):
        self.runs.append((source, alert_sent, datetime.now(UTC)))
        return len(self.runs)

    async def alert_window_count(self, *, source, since):
        return sum(1 for name, sent, at in self.runs if name == source and sent and at >= since)

    async def bump_suppressed_alerts(self, source):
        self.suppressed[source] = self.suppressed.get(source, 0) + 1

    async def add_vacancies(self, vacancies):
        raise AssertionError("не должен вызываться на пустом разборе")


class _Client:
    async def get(self, url, *, headers=None):  # noqa: ANN001, ANN202

        class _Resp:
            text = "<html><p>не та вёрстка</p></html>"
            status_code = 200
            headers: dict[str, str] = {}

        return _Resp()


def test_u_alert01_alerts_deduplicated_within_hour_window() -> None:
    import asyncio

    base = datetime.now(UTC)  # журнал сборов пишет «серверное» время (§6.5)
    repo, alerts = _BrokenRepo(), _Alerts()

    async def go() -> None:
        for minutes in range(6):
            await run_collect(
                client=_Client(),
                repo=repo,
                alerts=alerts,
                now=base + timedelta(minutes=5 * minutes),
            )
        await run_collect(
            client=_Client(), repo=repo, alerts=alerts, now=base + timedelta(minutes=65)
        )

    asyncio.run(go())
    assert len(alerts.texts) == 4  # по одному алерту на источник в час (2 источника × 2 окна)
    assert repo.suppressed.get("hh.ru") == 5


# --- U-RET-01 (R19): retention строго старше 30 дней -------------------------


def test_u_ret01_cleanup_boundary_strictly_older() -> None:
    import asyncio

    repo = _Repo(
        [
            _Vacancy("старая", published_at=NOW - timedelta(days=31)),
            _Vacancy("граница", published_at=NOW - timedelta(days=30)),
            _Vacancy("свежая", published_at=NOW - timedelta(days=5)),
        ]
    )
    removed = asyncio.run(run_cleanup(repo=repo, now=NOW))
    assert removed == 1
    assert {v.title for v in repo.vacancies} == {"граница", "свежая"}


# --- U-SES-01 (R31): Repo не удерживает сессии --------------------------------


def test_u_ses01_repo_closes_sessions_after_each_call() -> None:
    import asyncio

    from app.storage.repo import Repo

    class _Result:
        rowcount = 0

        def __await__(self):
            async def _done():
                return self

            return _done().__await__()

        def scalars(self):
            return self

        def all(self):
            return []

        def first(self):
            return None

    class _Session(_Result):
        def __init__(self) -> None:
            self.closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            self.closed = True
            return False

        async def close(self):
            self.closed = True

        async def commit(self):
            return None

        def add(self, obj):
            return None

        def __getattr__(self, name):
            def _recorded(*args, **kwargs):
                return _Result()

            return _recorded

    class _Factory:
        def __init__(self) -> None:
            self.sessions: list[_Session] = []

        def __call__(self, *args, **kwargs):
            session = _Session()
            self.sessions.append(session)
            return session

    factory = _Factory()
    repo = Repo(factory)

    async def go() -> None:
        await repo.get_user(1)
        await repo.list_presets()
        await repo.admin_stats()
        await repo.purge_old(cutoff_utc=NOW)

    asyncio.run(go())
    assert factory.sessions, "Repo не открывал сессии — проверка R31 вакуумна"
    assert all(session.closed for session in factory.sessions)
