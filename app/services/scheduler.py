"""Планировщик и доставка по расписанию (api.md §14).

APScheduler — только ``MemoryJobStore`` (F-01: pickle-десериализация job_state
запрещена). Правила слота: один выпуск на локальные сутки; догоняющее окно
``digest_catchup_minutes`` (3 ч); пустой дайджест — сообщение (Q3).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import settings as app_settings
from app.domain.profile import Schedule
from app.i18n import t
from app.services.digest import render_digest, render_empty
from app.services.dispatch import DispatchReport, OutgoingMessage, dispatch
from app.services.select import profile_of, select_digest
from app.services.slots import local_day, local_slot, make_slot_key, slot_key

__all__ = ["check_schedules", "build_scheduler", "local_slot", "run_cleanup", "slot_key"]


async def check_schedules(
    *, repo: Any, sender: Any, throttle: Any, now: datetime
) -> DispatchReport | None:
    """Проверка расписаний (раз в минуту) с догоняющим окном (R6, R32)."""
    users = await repo.list_users()
    messages: list[OutgoingMessage] = []
    catchup = timedelta(minutes=app_settings.digest_catchup_minutes)
    for user in users:
        try:
            profile = profile_of(user)
        except ValueError:
            continue
        lang = profile.lang
        schedule = profile.schedule
        if schedule is None:
            if await repo.claim_slot(user_id=user.id, slot_key="reminder"):
                messages.append(OutgoingMessage(user.id, t("reminder.finish_setup", lang)))
            continue
        messages.extend(
            await _due_messages(repo=repo, user=user, schedule=schedule, now=now, catchup=catchup)
        )
    if not messages:
        return None
    return await dispatch(messages, sender=sender, throttle=throttle, now=now)


async def _due_messages(
    *, repo: Any, user: Any, schedule: Schedule, now: datetime, catchup: timedelta
) -> list[OutgoingMessage]:
    from app.services.last_digest import record

    out: list[OutgoingMessage] = []
    today = local_day(schedule, now)
    for day in (today, today - timedelta(days=1)):
        slot = local_slot(schedule, day)
        delta = now - slot
        if not timedelta(0) <= delta <= catchup:
            continue
        selection = await select_digest(repo=repo, user=user, now=now, day=day)
        lang = profile_of(user).lang
        if selection is not None:
            record(user.id, selection.items)
            out.extend(
                OutgoingMessage(user.id, part)
                for part in render_digest(
                    selection.items,
                    lang=lang,
                    now=now,
                    on_date=day,
                )
            )
        elif await repo.claim_slot(user_id=user.id, slot_key=make_slot_key(user.id, schedule, day)):
            out.append(OutgoingMessage(user.id, render_empty(lang)))
    return out


async def run_cleanup(*, repo: Any, now: datetime) -> int:
    """Retention: purge старше ``now − retention_days`` (decisions §5.17)."""
    cutoff = now - timedelta(days=app_settings.retention_days)
    return await repo.purge_old(cutoff_utc=cutoff)


def build_scheduler(*, repo: Any, sender: Any, throttle: Any, settings: Any) -> Any:
    """AsyncIOScheduler: сбор, проверка расписаний, очистка (только MemoryJobStore)."""
    from apscheduler.jobstores.memory import MemoryJobStore
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    from app.services.collect import run_collect
    from app.services.http import build_client

    scheduler = AsyncIOScheduler(
        jobstores={"default": MemoryJobStore()},
        timezone="UTC",
    )

    class _Alerts:
        async def send_admin(self, text: str) -> None:
            await sender.send_html(settings.admin_id, text)

    async def job_collect() -> None:
        from app.config import settings as cfg

        async with build_client(cfg.http_timeout_seconds) as client:
            await run_collect(client=client, repo=repo, alerts=_Alerts(), now=datetime.now(UTC))

    async def job_check() -> None:
        await check_schedules(repo=repo, sender=sender, throttle=throttle, now=datetime.now(UTC))

    async def job_cleanup() -> None:
        await run_cleanup(repo=repo, now=datetime.now(UTC))

    hour, minute = (int(part) for part in app_settings.cleanup_time.split(":", 1))
    scheduler.add_job(
        job_collect,
        IntervalTrigger(minutes=settings.collect_interval_minutes),
        id="collect",
        replace_existing=True,
    )
    scheduler.add_job(
        job_check,
        IntervalTrigger(minutes=1),
        id="check_schedules",
        replace_existing=True,
    )
    scheduler.add_job(
        job_cleanup,
        CronTrigger(hour=hour, minute=minute, timezone="UTC"),
        id="cleanup",
        replace_existing=True,
    )
    return scheduler
