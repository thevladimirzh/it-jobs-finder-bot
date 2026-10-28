"""Ядро бота (api.md §15): протокол диалога, команды обратной связи, админ-контур.

Точные строки ответов — ``app/i18n.py`` (brief §6.1 + decisions §4/§8); весь
внешний/пользовательский текст проходит ``esc``; админ-команды — только для
``settings.admin_id`` (строгое int-сравнение, SEC-07), не-админу молчаливый
игнор. Антиспам: 30 действий/мин → тихий мьют 10 мин (AC-16); callback-действия
кнопочного диалога считаются так же (SEC-15).

Диалог на инлайн-кнопках (I-2, api.md §15.1): ``handle_callback`` отвечает на
каждый callback_query немедленно (``answer`` вызывается первым действием — до
обращений к БД), валидация — белым списком (``app.bot.dialog``), состояние
диалога in-memory per-user (decisions §8.6), устаревший/чужой/битый callback —
единый вежливый отказ без изменения состояния. Кнопочный выбор открывает
следующий шаг сразу (lang → preset → format → tz → time → size → «Готово!»);
текстом остаются время HH:MM, мин. зарплата, стоп-слова и ручной UTC-offset.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import UTC, datetime
from datetime import time as dt_time
from typing import Any

from app.bot import dialog as dlg
from app.bot.antispam import Antispam
from app.bot.dialog import DialogState, DialogStore, Reply
from app.collectors.base import Vacancy
from app.config import settings as app_settings
from app.domain.profile import Profile, Schedule, parse_hhmm, parse_tz, profile_to_jsonb
from app.i18n import Lang, t
from app.services.collect import REASONS, run_collect
from app.services.last_digest import lookup as lookup_card
from app.services.last_digest import record as record_last_digest
from app.services.select import profile_of, select_digest
from app.textutil import esc

STEPS = dlg.ALL_STEPS
_FEEDBACK_RE = re.compile(r"^/(like|dislike|bookmark)(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_NUMBER_RE = re.compile(r"[1-9][0-9]*")
_SALARY_RE = re.compile(r"[0-9]{1,18}")
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,254}")

# Лимиты списковых вводов диалога (F-10, SEC-09/SEC-10): рост JSONB профиля ограничен.
_STOP_WORDS_LIMIT = 50
_STOP_WORD_LIMIT = 100
_PRESETS_LIMIT = 50

# Лимиты колонок БД (F-14, models.PresetRow): вежливый отказ вместо DataError.
_PRESET_NAME_LIMIT = 128  # name_ru/name_en VARCHAR(128)
_PRESET_SLUG_LIMIT = 255  # slug VARCHAR(255)


class BotCore:
    """Обработчик сообщений и callback: одна точка для сценариев S1–S89."""

    def __init__(
        self,
        *,
        repo: Any,
        client: Any = None,
        alerts: Any = None,
        antispam: Antispam | None = None,
    ) -> None:
        self._repo = repo
        self._client = client
        self._alerts = alerts
        self._antispam = antispam or Antispam()
        self._dialogs = DialogStore()

    # -- публичное API ---------------------------------------------------------

    def set_client(self, client: Any) -> None:
        """Подмена HTTP-клиента (S54; тесты — только FakeClient, R41)."""
        self._client = client

    async def handle(self, text: str, user_id: Any) -> list[str]:
        """Одно входящее сообщение → тексты ответов (готовый Telegram HTML)."""
        if not self._antispam.allow(user_id):
            return []
        raw = text if isinstance(text, str) else str(text)
        stripped = raw.strip()
        if stripped.startswith("/"):
            return await self._command(stripped, raw, user_id)
        return await self._value(raw, user_id)

    async def handle_callback(self, data: str, user_id: Any, *, answer: Any) -> list[str]:
        """Callback_query кнопочного диалога (api.md §15.1).

        ``answer(text, show_alert)`` вызывается ПЕРВЫМ действием — до обращений
        к БД (AC-22), включая устаревший/чужой/битый callback и флуд (SEC-15:
        каждый callback подтверждается ровно один раз). Любой callback —
        пользовательское действие для антиспама.
        """
        raw = data if isinstance(data, str) else str(data)
        parsed = dlg.parse_callback(raw)
        state = self._dialogs.get(user_id)
        lang = self._dialogs.lang_of(user_id)
        toast = ""
        if parsed is None or state is None or not self._callback_allowed(state, *parsed):
            toast = t("dialog.outdated", lang)  # устаревший/чужой/битый — общий отказ
        elif parsed == ("preset", dlg.PRESET_DONE) and not state.selected:
            toast = t("dialog.preset_empty", lang)  # «Готово» без выбора (S83)
        elif (
            parsed[0] == "preset"
            and parsed[1] != dlg.PRESET_DONE
            and state.codes.get(parsed[1]) not in state.selected
            and len(state.selected) >= _PRESETS_LIMIT
        ):
            toast = t("prompt.preset", lang)  # лимит подписок (F-10) — отказ подсказкой
        await _emit_answer(answer, toast, False)
        if not self._antispam.allow(user_id):
            return []
        if toast or parsed is None or state is None:
            return []
        return await self._apply_callback(state, user_id, *parsed)

    async def deliver_digest(self, user_id: Any) -> list[str]:
        """Доставить очередной дайджест сейчас (служебный триггер слота)."""
        user = await self._repo.get_user(user_id)
        if user is None:
            return []
        selection = await select_digest(repo=self._repo, user=user, now=datetime.now(UTC))
        if selection is None:
            return []
        profile = self._profile_of(user)
        record_last_digest(user_id, selection.items)
        from app.services.digest import render_digest

        return render_digest(
            selection.items,
            lang=profile.lang,
            now=datetime.now(UTC),
            on_date=datetime.now(UTC).date(),
        )

    async def seed_vacancies(self, vacancies: list[Vacancy]) -> int:
        """Положить вакансии в кэш бота (расширение BotHarness, §6.1 acceptance-map)."""
        return await self._repo.add_vacancies(vacancies)

    # -- команды ----------------------------------------------------------------

    async def _command(self, stripped: str, raw: str, user_id: Any) -> list[str]:
        head = stripped.split()[0]
        base = head.split("@", 1)[0].lower()
        if base == "/start":
            return await self._start(user_id)
        if base == "/settings":
            parts = stripped.split(None, 1)
            step = parts[1].split()[0].lower() if len(parts) > 1 and parts[1].split() else ""
            if step in STEPS:
                return await self._open_step(user_id, step)
            return await self._display(user_id)
        feedback = _FEEDBACK_RE.match(stripped)
        if feedback is not None:
            return await self._feedback(user_id, feedback.group(1).lower(), feedback.group(2) or "")
        if base.startswith("/admin"):
            return await self._admin(base, stripped, user_id)
        return []

    async def _start(self, user_id: Any) -> list[str]:
        await self._ensure_user(user_id)
        lang = await self._lang(user_id)
        self._dialogs.open(user_id, "lang", mode="onboarding", lang=lang)
        return [Reply(t("start.welcome", lang), keyboard=dlg.lang_keyboard())]

    async def _feedback(self, user_id: Any, action: str, arg: str) -> list[str]:
        lang = await self._lang(user_id)
        tokens = arg.split()
        token = tokens[0] if tokens else ""
        if len(token) <= 18 and _NUMBER_RE.fullmatch(token):
            vacancy_id = lookup_card(user_id, int(token))
            if vacancy_id is not None:
                await self._ensure_user(user_id)
                await self._repo.upsert_feedback(
                    user_id=user_id,
                    vacancy_id=vacancy_id,
                    action=action,  # type: ignore[arg-type]
                )
                return [Reply(t(f"feedback.ok.{action}", lang))]
        return [Reply(t("feedback.error", lang))]

    # -- админ-контур ---------------------------------------------------------------

    async def _admin(self, base: str, text: str, user_id: Any) -> list[str]:
        if not _is_admin(user_id):
            return []
        if base == "/admin":
            return await self._admin_summary()
        if base == "/admin_preset_list":
            return await self._admin_preset_list()
        if base == "/admin_preset_add":
            return await self._admin_preset_add(text)
        if base == "/admin_preset_edit":
            return await self._admin_preset_edit(text)
        if base == "/admin_preset_del":
            return await self._admin_preset_del(text)
        if base == "/admin_stats":
            return await self._admin_stats()
        if base == "/admin_collect":
            return await self._admin_collect()
        if base == "/admin_health":
            return await self._admin_health()
        return []

    async def _admin_summary(self) -> list[str]:
        stats = await self._repo.admin_stats()
        presets = await self._repo.list_presets()
        return [
            f"Сводка: пользователей {stats.users}, пресетов {len(presets)} "
            f"(лайки {stats.like}, дизлайки {stats.dislike}, закладки {stats.bookmark})"
        ]

    async def _admin_preset_list(self) -> list[str]:
        presets = await self._repo.list_presets()
        return [f"{esc(preset.slug)} \u2014 {esc(preset.name_ru)}" for preset in presets] or [
            "пресетов нет"
        ]

    async def _admin_preset_add(self, text: str) -> list[str]:
        slug, name, payload = _parse_preset_command(text, with_name=True)
        if slug is None or payload is None:
            return ["Формат: /admin_preset_add <slug> <name> <json>"]
        name = name or slug
        problem = _preset_size_problem(slug, name)
        if problem is not None:
            return [problem]
        await self._repo.upsert_preset(slug, name=name, filter_json=payload)
        return [f"\u2705 Пресет {slug} добавлен"]

    async def _admin_preset_edit(self, text: str) -> list[str]:
        slug, _name, payload = _parse_preset_command(text, with_name=False)
        if slug is None or payload is None:
            return ["Формат: /admin_preset_edit <slug> <json>"]
        existing = {preset.slug: preset for preset in await self._repo.list_presets()}
        name = existing[slug].name_ru if slug in existing else slug
        problem = _preset_size_problem(slug, name)
        if problem is not None:
            return [problem]
        await self._repo.upsert_preset(slug, name=name, filter_json=payload)
        return [f"\u2705 Пресет {slug} обновлён"]

    async def _admin_preset_del(self, text: str) -> list[str]:
        parts = text.split()
        if len(parts) < 2 or not _SLUG_RE.fullmatch(parts[1]):
            return ["Формат: /admin_preset_del <slug>"]
        await self._repo.delete_preset(parts[1])
        return [f"\u2705 Пресет {parts[1]} удалён"]

    async def _admin_stats(self) -> list[str]:
        stats = await self._repo.admin_stats()
        return [
            "Статистика:",
            f"Всего пользователей: {stats.users}",
            f"like: {stats.like}",
            f"dislike: {stats.dislike}",
            f"bookmark: {stats.bookmark}",
        ]

    async def _admin_collect(self) -> list[str]:
        reports = await run_collect(
            client=self._client,
            repo=self._repo,
            alerts=self._alerts,
            now=datetime.now(UTC),
        )
        lines = ["Сбор завершён:"]
        lines.extend(f"{report.source}: добавлено {report.added}" for report in reports)
        return lines

    async def _admin_health(self) -> list[str]:
        runs = await self._repo.recent_parse_runs(limit=50)
        latest: dict[str, Any] = {}
        for run in runs:
            latest.setdefault(run.source, run)
        lines = ["Здоровье парсеров:"]
        for name in ("hh.ru", "Habr Career"):
            run = latest.get(name)
            if run is None:
                lines.append(f"{name}: ещё не запускался")
                continue
            reason = REASONS.get(run.status, "ok")
            stamp = run.finished_at.astimezone(UTC).strftime("%d.%m.%Y %H:%M")
            lines.append(
                f"{name}: {reason} \u2014 {stamp} UTC (подавлено: {run.suppressed_alerts})"
            )
        return lines

    # -- диалог: шаги и сообщения ----------------------------------------------------

    async def _open_step(self, user_id: Any, step: str) -> list[str]:
        """``/settings <шаг>``: открыть один шаг кнопочного диалога (S3–S7)."""
        profile = await self._profile(user_id)
        selected = set(profile.presets) if step == "preset" else set()
        state = self._dialogs.open(
            user_id, step, mode="single", lang=profile.lang, selected=selected
        )
        return await self._render_step(state, profile)

    async def _render_step(self, state: DialogState, profile: Profile) -> list[str]:
        """Подсказка текущего шага с клавиатурой (AC-24: текст не применяется)."""
        return [await self._step_reply(state, profile)]

    async def _step_reply(
        self, state: DialogState, profile: Profile, *, header: str | None = None
    ) -> Reply:
        lang = state.lang
        step = state.step
        if step == "lang":
            return Reply(t("prompt.lang", lang), keyboard=dlg.lang_keyboard())
        if step == "preset":
            return await self._preset_reply(state, profile, header=header)
        if step == "format":
            return Reply(t("prompt.format", lang), keyboard=dlg.format_keyboard(lang))
        if step == "tz":
            return Reply(t("prompt.tz", lang), keyboard=dlg.tz_keyboard(lang, state.page))
        if step == "size":
            return Reply(t("prompt.size", lang), keyboard=dlg.size_keyboard())
        return Reply(header or t(f"prompt.{step}", lang))

    async def _preset_reply(
        self,
        state: DialogState,
        profile: Profile,
        *,
        header: str | None = None,
        summary: bool = False,
        edit: bool = False,
    ) -> Reply:
        """Шаг пресетов: заголовок + экранированные имена + клавиатура мультивыбора.

        Имена пресетов — недоверенный текст админа, в HTML-тексте только через
        ``esc`` (S85); метки кнопок — plain text (brief §6.1).
        """
        lang = state.lang
        presets = await self._repo.list_presets()
        pairs = [(preset.slug, dlg.preset_label(preset, lang)) for preset in presets]
        try:
            codes = dlg.preset_codes(slug for slug, _name in pairs)
        except ValueError:
            # F-17: неразрешимая коллизия кодов — fail-closed, без перезаписи
            codes = {}
        state.codes = {code: slug for slug, code in codes.items()}
        lines = [
            f"{dlg.SELECTED_PREFIX}{esc(name)}" if slug in state.selected else esc(name)
            for slug, name in pairs
        ]
        head = header or t("saved.preset" if summary else "prompt.preset", lang)
        text = "\n\n".join([head, *lines]) if lines else head
        if summary:
            return Reply(text, keyboard=(), edit=True)
        return Reply(
            text, keyboard=dlg.preset_keyboard(pairs, state.selected, lang, codes=codes), edit=edit
        )

    async def _finish_step(self, state: DialogState, user_id: Any, saved_key: str) -> list[str]:
        """Шаг сохранён: подтверждение + следующий шаг (onboarding) или закрытие."""
        profile = await self._profile(user_id)
        replies = [Reply(t(saved_key, state.lang))]
        if state.mode != "onboarding":
            self._dialogs.close(user_id)
            return replies
        nxt = _next_in_chain(state.step)
        if nxt is None:
            self._dialogs.close(user_id)
            replies.append(Reply(t("start.done", state.lang)))
            return replies
        state.step = nxt
        state.page = 1
        replies.append(await self._step_reply(state, profile))
        return replies

    # -- callback-нажатия ------------------------------------------------------------

    def _callback_allowed(self, state: DialogState, step: str, value: str) -> bool:
        """Белый список значений текущего шага (без БД; S88/P-DLG-02)."""
        if state.step != step:
            return False
        if step == "lang":
            return value in dlg.LANG_VALUES
        if step == "preset":
            return value == dlg.PRESET_DONE or value in state.codes
        if step == "format":
            return value in dlg.FORMAT_VALUES
        if step == "size":
            return value in dlg.SIZE_VALUES
        if step == "tz":
            if value == dlg.TZ_MANUAL:
                return True
            if value.startswith("page-"):
                page = value.removeprefix("page-")
                return page.isdecimal() and 1 <= int(page) <= dlg.tz_page_count()
            return dlg.city_zone(value) is not None
        return False

    async def _apply_callback(
        self, state: DialogState, user_id: Any, step: str, value: str
    ) -> list[str]:
        if step == "lang":
            return await self._apply_lang(state, user_id, value)
        if step == "preset":
            return await self._apply_preset(state, user_id, value)
        if step == "format":
            return await self._apply_format(state, user_id, value)
        if step == "tz":
            return await self._apply_tz(state, user_id, value)
        return await self._apply_size(state, user_id, value)

    async def _apply_lang(self, state: DialogState, user_id: Any, code: str) -> list[str]:
        profile = await self._profile(user_id)
        updated = _replace(profile, lang=code)
        await self._save(user_id, updated)
        state.lang = code
        self._dialogs.note_lang(user_id, code)
        replies = [Reply(t("saved.lang", code))]
        if state.mode != "onboarding":
            self._dialogs.close(user_id)
            return replies
        state.step = "preset"
        state.selected = set(updated.presets)
        replies.append(await self._preset_reply(state, updated))
        return replies

    async def _apply_preset(self, state: DialogState, user_id: Any, value: str) -> list[str]:
        profile = await self._profile(user_id)
        if value != dlg.PRESET_DONE:
            slug = state.codes[value]
            if slug in state.selected:
                state.selected.discard(slug)
            else:
                state.selected.add(slug)
            return [await self._preset_reply(state, profile, edit=True)]
        presets = await self._repo.list_presets()
        order = [preset.slug for preset in presets]
        chosen = [slug for slug in order if slug in state.selected]
        updated = _replace(profile, presets=chosen)
        await self._save(user_id, updated)
        replies = [await self._preset_reply(state, updated, summary=True)]
        if state.mode != "onboarding":
            self._dialogs.close(user_id)
            return replies
        state.step = "format"
        state.page = 1
        replies.append(await self._step_reply(state, updated))
        return replies

    async def _apply_format(self, state: DialogState, user_id: Any, value: str) -> list[str]:
        profile = await self._profile(user_id)
        updated = _replace(profile, work_format=None if value == "any" else value)
        await self._save(user_id, updated)
        return await self._finish_step(state, user_id, "saved.format")

    async def _apply_tz(self, state: DialogState, user_id: Any, value: str) -> list[str]:
        if value == dlg.TZ_MANUAL:
            return [
                Reply(
                    t("prompt.tz_manual", state.lang),
                    keyboard=dlg.tz_keyboard(state.lang, state.page),
                )
            ]
        if value.startswith("page-"):
            state.page = int(value.removeprefix("page-"))
            return [
                Reply(
                    t("prompt.tz", state.lang),
                    keyboard=dlg.tz_keyboard(state.lang, state.page),
                    edit=True,
                )
            ]
        zone = dlg.city_zone(value)
        profile = await self._profile(user_id)
        schedule = profile.schedule or Schedule(local_time=dt_time(9, 0), tz="UTC")
        updated = _replace(profile, schedule=Schedule(schedule.local_time, zone))
        await self._save(user_id, updated)
        return await self._finish_step(state, user_id, "saved.tz")

    async def _apply_size(self, state: DialogState, user_id: Any, value: str) -> list[str]:
        profile = await self._profile(user_id)
        updated = _replace(profile, digest_size=int(value))
        await self._save(user_id, updated)
        return await self._finish_step(state, user_id, "saved.size")

    # -- текстовые шаги (время, зарплата, стоп-слова, ручной offset) --------------------

    async def _value(self, raw: str, user_id: Any) -> list[str]:
        state = self._dialogs.get(user_id)
        if state is None:
            return []
        value = raw.strip()
        if state.step == "time":
            return await self._apply_time(state, user_id, value)
        if state.step == "tz":
            return await self._apply_tz_text(state, user_id, value)
        if state.step == "salary":
            return await self._apply_salary(state, user_id, value)
        if state.step == "stop":
            return await self._apply_stop(state, user_id, value)
        # кнопочный шаг: текст не применяется — переотправка подсказки (AC-24)
        return await self._render_step(state, await self._profile(user_id))

    async def _apply_time(self, state: DialogState, user_id: Any, value: str) -> list[str]:
        try:
            local_time = parse_hhmm(value)
        except ValueError:
            return [Reply(t("error.bad_time", state.lang))]
        profile = await self._profile(user_id)
        schedule = profile.schedule or Schedule(local_time=dt_time(9, 0), tz="UTC")
        updated = _replace(profile, schedule=Schedule(local_time, schedule.tz))
        await self._save(user_id, updated)
        return await self._finish_step(state, user_id, "saved.time")

    async def _apply_tz_text(self, state: DialogState, user_id: Any, value: str) -> list[str]:
        """Текст на шаге tz — ручной UTC-offset (AC-24, S89)."""
        try:
            parse_tz(value)
        except ValueError:
            return [Reply(t("error.bad_tz", state.lang))]
        profile = await self._profile(user_id)
        schedule = profile.schedule or Schedule(local_time=dt_time(9, 0), tz="UTC")
        updated = _replace(profile, schedule=Schedule(schedule.local_time, value))
        await self._save(user_id, updated)
        return await self._finish_step(state, user_id, "saved.tz")

    async def _apply_salary(self, state: DialogState, user_id: Any, value: str) -> list[str]:
        if not _SALARY_RE.fullmatch(value):
            return [Reply(t("error.bad_salary", state.lang))]
        salary = int(value)
        if salary <= 0:
            return [Reply(t("error.bad_salary", state.lang))]
        profile = await self._profile(user_id)
        await self._save(user_id, _replace(profile, min_salary_rub=salary))
        return await self._finish_step(state, user_id, "saved.salary")

    async def _apply_stop(self, state: DialogState, user_id: Any, value: str) -> list[str]:
        if not value:
            return [Reply(t("prompt.stop", state.lang))]
        requested = [part.strip() for part in value.split(",") if part.strip()]
        # Лимиты F-10: слово ≤100 символов, всего ≤50; превышение — вежливый отказ.
        if any(len(word) > _STOP_WORD_LIMIT for word in requested):
            return [Reply(t("prompt.stop", state.lang))]
        profile = await self._profile(user_id)
        words = list(profile.stop_words)
        for word in requested:
            if word in words:
                continue
            if len(words) >= _STOP_WORDS_LIMIT:
                return [Reply(t("prompt.stop", state.lang))]
            words.append(word)
        await self._save(user_id, _replace(profile, stop_words=words))
        return await self._finish_step(state, user_id, "saved.stop")

    # -- профиль -----------------------------------------------------------------

    async def _ensure_user(self, user_id: Any) -> None:
        existing = await self._repo.get_user(user_id)
        if existing is None:
            # слот профиля хранит JSONB (users.profile), как и _save (F-10, SEC-09)
            await self._repo.upsert_user(
                user_id, lang="ru", profile=profile_to_jsonb(_default_profile())
            )

    async def _profile(self, user_id: Any) -> Profile:
        user = await self._repo.get_user(user_id)
        if user is None:
            await self._ensure_user(user_id)
            user = await self._repo.get_user(user_id)
        if user is None:
            return _default_profile()
        return self._profile_of(user)

    def _profile_of(self, user: Any) -> Profile:
        try:
            return profile_of(user)
        except ValueError:
            return _default_profile()

    async def _lang(self, user_id: Any) -> Lang:
        lang = (await self._profile(user_id)).lang
        self._dialogs.note_lang(user_id, lang)
        return lang

    async def _save(self, user_id: Any, profile: Profile) -> None:
        await self._repo.upsert_user(user_id, lang=profile.lang, profile=profile_to_jsonb(profile))

    async def _display(self, user_id: Any) -> list[str]:
        profile = await self._profile(user_id)
        lang = profile.lang
        schedule = profile.schedule
        return [
            Reply(t("settings.title", lang)),
            Reply(f"{t('settings.lang', lang)}: {esc(profile.lang)}"),
            Reply(
                f"{t('settings.presets', lang)}: "
                f"{', '.join(esc(preset) for preset in profile.presets) or '\u2014'}"
            ),
            Reply(f"{t('settings.min_salary', lang)}: {profile.min_salary_rub or '\u2014'}"),
            Reply(f"{t('settings.work_format', lang)}: {_format_label(profile.work_format, lang)}"),
            Reply(
                f"{t('settings.stop_words', lang)}: "
                f"{', '.join(esc(word) for word in profile.stop_words) or '\u2014'}"
            ),
            Reply(f"{t('settings.size', lang)}: {profile.digest_size}"),
            Reply(
                f"{t('settings.time', lang)}: "
                f"{schedule.local_time.strftime('%H:%M') if schedule else '\u2014'}"
            ),
            Reply(f"{t('settings.tz', lang)}: {esc(schedule.tz) if schedule else '\u2014'}"),
        ]


async def _emit_answer(answer: Any, text: str, show_alert: bool) -> None:
    """Немедленное подтверждение callback (AC-22): синхронный/асинхронный sink."""
    result = answer(text, show_alert)
    if inspect.isawaitable(result):
        await result


def _next_in_chain(step: str) -> str | None:
    """Следующий шаг онбординга (decisions §8.6): lang→preset→format→tz→time→size."""
    try:
        index = dlg.CHAIN.index(step)
    except ValueError:
        return None
    return dlg.CHAIN[index + 1] if index + 1 < len(dlg.CHAIN) else None


def _format_label(value: Any, lang: Lang) -> str:
    """Метка формата работы в сводке /settings (brief §6.1): метка на языке
    пользователя + каноническое имя значения; «Не важно» → «—»; чужой текст — esc."""
    if not value or value == "any":
        return "\u2014"
    key = f"format.{value}"
    try:
        ru, shown = t(key, "ru"), t(key, lang)
    except KeyError:
        return esc(str(value))
    if shown == ru:
        return esc(shown)
    return f"{esc(shown)} ({esc(ru)})"


def _is_admin(user_id: Any) -> bool:
    """Строгий int-сравнение (SEC-07): str/подстроки/соседи id не проходят."""
    return (
        isinstance(user_id, int)
        and not isinstance(user_id, bool)
        and user_id == app_settings.admin_id
    )


def _default_profile() -> Profile:
    return Profile(
        lang="ru",
        presets=[],
        min_salary_rub=None,
        work_format=None,
        stop_words=[],
        digest_size=app_settings.digest_size_default,
        schedule=None,
    )


def _replace(profile: Profile, **changes: Any) -> Profile:
    values = {
        "lang": profile.lang,
        "presets": list(profile.presets),
        "min_salary_rub": profile.min_salary_rub,
        "work_format": profile.work_format,
        "stop_words": list(profile.stop_words),
        "digest_size": profile.digest_size,
        "schedule": profile.schedule,
    }
    values.update(changes)
    return Profile(**values)


def _preset_size_problem(slug: str, name: str) -> str | None:
    """Лимиты колонок БД (F-14): вежливый отказ админу вместо ``DataError``.

    Имя пресета ограничено 128 символами (``name_ru/name_en VARCHAR(128)``),
    slug — 255 (``slug VARCHAR(255)``); выход за лимит — текст отказа, БД
    не вызывается.
    """
    if len(slug) > _PRESET_SLUG_LIMIT:
        return f"Slug слишком длинный (максимум {_PRESET_SLUG_LIMIT} символов)"
    if len(name) > _PRESET_NAME_LIMIT:
        return f"Имя пресета слишком длинное (максимум {_PRESET_NAME_LIMIT} символов)"
    return None


def _parse_preset_command(text: str, *, with_name: bool) -> tuple[str | None, str, dict | None]:
    brace = text.find("{")
    if brace < 0:
        return None, "", None
    try:
        payload = json.loads(text[brace:])
    except (ValueError, RecursionError):
        # битый/глубоко вложенный JSON (F-11) — отказ валидации, не краш
        return None, "", None
    if not isinstance(payload, dict):
        return None, "", None
    head = text[:brace].split()
    if len(head) < 2:
        return None, "", None
    slug = head[1]
    if not _SLUG_RE.fullmatch(slug):
        return None, "", None
    name = " ".join(head[2:]) if with_name else ""
    return slug, name, payload
