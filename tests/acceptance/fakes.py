"""Двойники, строители и точные строки acceptance-тестов (tests/acceptance/).

Владелец: qa-engineer. Чёрный ящик строго по контракту ``docs/spec/api.md``:
production-код импортируется лениво (``support.load`` / ``support.load_attr``),
сетевых и Telegram-вызовов тесты не делают (R41) — вместо них двойники границы
(FakeClient/FakeSender/FakeThrottle/FakeAlertSink), которые api.md §0 разрешает
передавать извне.

Точные строки вывода копируются дословно из ``docs/product/brief.md`` §6.1 и
``docs/spec/decisions.md`` §4; значимые символы заданы явно:
``\\u00b7`` = «·» (карточка), ``\\u2013`` = «–» (диапазон зарплаты),
``\\u2014`` = «—» (заголовок дайджеста), разряды чисел — U+0020 (decisions §3.4).

Договорённости там, где спека молчит (зафиксированы в docs/qa/acceptance-map.md):
- фикстуры источников лежат в ``tests/data/``: ``hh_list.html``, ``habr_list.html``,
  ``hh_empty.html``, ``habr_empty.html`` (валидный скелет страницы без карточек);
  отсутствие фикстуры — внятный красный ``NotImplementedYet``, не ошибка импорта;
- диалог настроек: ``/settings`` + подкоманды ``time|tz|size|salary|preset|stop|lang``
  открывают шаг, значение приходит следующим сообщением (см. feature-сценарии S3–S7);
- ошибка FloodWait моделируется исключением с атрибутом ``retry_after`` (duck-typing
  под aiogram ``TelegramRetryAfter``).
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any

from support import (
    REPO_ROOT,
    NotImplementedYet,
    RecordingSession,
    RecordingSessionFactory,
    app_settings,
    ensure_test_env,
    load_attr,
)

# ---------------------------------------------------------------------------
# Точные строки вывода (brief §6.1, decisions §4) — дословно
# ---------------------------------------------------------------------------

FEEDBACK_OK = {
    "like": ("\U0001f44d Учтено", "\U0001f44d Noted"),
    "dislike": ("\U0001f44e Учтено", "\U0001f44e Noted"),
    "bookmark": ("\U0001f516 Сохранено", "\U0001f516 Saved"),
}
FEEDBACK_ERROR_RU = (
    "Не понял номер. Отправьте номер карточки из последнего дайджеста (например: /like 3)."
)
FEEDBACK_ERROR_EN = (
    "I didn't get the number. Send the card number from your latest digest (e.g. /like 3)."
)
EMPTY_DIGEST_RU = "\U0001f525 Новых вакансий нет"
EMPTY_DIGEST_EN = "\U0001f525 No new vacancies"
BAD_TIME_RU = "Не понял время. Отправьте в формате ЧЧ:ММ (например: 09:30)."
BAD_TIME_EN = "I didn't get the time. Send it as HH:MM (e.g. 09:30)."
BAD_TZ_RU = (
    "Не понял таймзону. Выберите город из списка или укажите смещение UTC (например: UTC+3)."
)
BAD_TZ_EN = (
    "I didn't get the timezone. Pick a city from the list or send a UTC offset (e.g. UTC+3)."
)
BAD_SIZE_RU = "Размер дайджеста \u2014 число от 1 до 50."
BAD_SIZE_EN = "Digest size must be a number between 1 and 50."
BAD_SALARY_RU = "Не понял зарплату. Отправьте целое число (например: 150000)."
BAD_SALARY_EN = "I didn't get the salary. Send a whole number (e.g. 150000)."
REMINDER_RU = (
    "Чтобы получать подборку, завершите настройку: выберите время дайджеста и таймзону (/settings)."
)
REMINDER_EN = "To get your digest, finish setup: choose digest time and timezone (/settings)."

ALERT_REASONS = (
    "блокировка/капча",
    "ошибка разбора разметки",
    "пустой разбор",
    "источник недоступен",
)
SOURCE_HH = "hh.ru"
SOURCE_HABR = "Habr Career"


def alert_line(source: str, reason: str) -> str:
    """Точный шаблон алерта brief §6.1: «⚠️ Сбор {source}: {reason}» (всегда RU)."""
    return f"\u26a0\ufe0f Сбор {source}: {reason}"


CARD_SEPARATOR = "\u00b7"  # «·» в строке метаданных карточки
SALARY_DASH = "\u2013"  # «–» в диапазоне зарплаты
HEADER_DASH = "\u2014"  # «—» в заголовке дайджеста

AGE_RU = {0: "сегодня", 1: "вчера"}
AGE_EN = {0: "today", 1: "yesterday"}
SALARY_NONE = {"ru": "Зарплата не указана", "en": "Salary not specified"}
CURRENCY_SIGNS = {"RUB": "\u20bd", "USD": "$", "EUR": "\u20ac"}

PRESET_SLUGS = (
    "python-backend",
    "frontend",
    "devops-sre",
    "data-ml",
    "qa",
    "mobile",
    "backend-other",
)

# «Пропускающий всё» JSONB-фильтр пресета (api.md §7): пустые must/stop-слова.
PERMISSIVE_FILTER: dict[str, Any] = {
    "role": "",
    "must": [],
    "nice": [],
    "grades": [],
    "min_salary": None,
    "work_format": None,
    "location": None,
    "stop_words": [],
    "employment": None,
}
PRESET_NAMES_RU = {
    "python-backend": "Python Backend",
    "frontend": "Frontend",
    "devops-sre": "DevOps/SRE",
    "data-ml": "Data/ML",
    "qa": "QA",
    "mobile": "Mobile",
    "backend-other": "Другие backend-языки",
}


def grouped(amount: int) -> str:
    """Целое число с разрядами, разделёнными U+0020 (decisions §3.4)."""
    sign = "-" if amount < 0 else ""
    digits = str(abs(amount))
    chunks: list[str] = []
    while digits:
        chunks.append(digits[-3:])
        digits = digits[:-3]
    return sign + " ".join(reversed(chunks))


def expected_salary_line(
    *, lang: str, minimum: int | None, maximum: int | None, currency: str
) -> str:
    """Независимый oracle строки зарплаты (brief §6.1) для проверки format_salary."""
    sign = CURRENCY_SIGNS.get(currency, currency)
    if minimum is not None and maximum is not None:
        return f"{grouped(minimum)} {SALARY_DASH} {grouped(maximum)} {sign}"
    if minimum is not None:
        prefix = "от" if lang == "ru" else "from"
        return f"{prefix} {grouped(minimum)} {sign}"
    if maximum is not None:
        prefix = "до" if lang == "ru" else "up to"
        return f"{prefix} {grouped(maximum)} {sign}"
    return SALARY_NONE[lang]


def expected_age_line(*, lang: str, full_days: int) -> str:
    """Независимый oracle строки возраста (brief §6.1 + decisions §3.1)."""
    k = max(full_days, 0)  # published_at в будущем → k = 0 (decisions §5.6)
    if lang == "ru":
        return AGE_RU.get(k, f"{k} дн.")
    return AGE_EN.get(k, f"{k} days")


def expected_header(*, lang: str, on_date: date, count: int) -> str:
    """Независимый oracle заголовка дайджеста (brief §6.1)."""
    stamp = f"{on_date.day:02d}.{on_date.month:02d}.{on_date.year:04d}"
    if lang == "ru":
        return f"\U0001f525 Подборка вакансий {HEADER_DASH} {stamp} ({count})"
    return f"\U0001f525 Job digest {HEADER_DASH} {stamp} ({count})"


def expected_card(
    n: int, *, title: str, company: str, source: str, age: str, salary: str, url: str
) -> str:
    """Независимый oracle карточки вакансии (brief §6.1), 4 строки без хвостового \\n."""
    return (
        f"{n}. <b>{title}</b>\n"
        f"{company} {CARD_SEPARATOR} {source} {CARD_SEPARATOR} {age}\n"
        f"{salary}\n"
        f"{url}"
    )


# ---------------------------------------------------------------------------
# Модельные строки (duck-type под production-типы, обе возможные формы)
# ---------------------------------------------------------------------------


# Стабильные id для вакансий-двойников (duck-type под VacancyRow.id из api.md §8).
_VACANCY_IDS = itertools.count(1)


@dataclass(frozen=True)
class ModelVacancy:
    """Вакансия-двойник: совместима и с ``Vacancy`` (api.md §6), и с ``VacancyRow``.

    Схема ``vacancies`` (api.md §8) хранит зарплату как ``salary_min/salary_max/
    currency``, а рендеры берут ``salary: Salary`` — объект несёт обе формы,
    чтобы чёрные тесты не зависели от внутреннего выбора реализации.
    """

    title: str
    company: str
    salary: Any  # Salary | None (production) либо None
    url: str
    source: str
    published_at: datetime
    description: str = ""
    id: int = field(default_factory=lambda: next(_VACANCY_IDS))

    @property
    def canonical_url(self) -> str:
        return self.url

    @property
    def salary_min(self) -> int | None:
        return None if self.salary is None else self.salary.min

    @property
    def salary_max(self) -> int | None:
        return None if self.salary is None else self.salary.max

    @property
    def currency(self) -> str | None:
        return None if self.salary is None else self.salary.currency


@dataclass(frozen=True)
class ModelUser:
    """Пользователь-двойник (duck-type под ``UserRow``, api.md §8/§9)."""

    id: int
    lang: str
    profile: Any  # ModelProfile | Profile | None
    created_at: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=UTC))


class ModelProfile(dict):
    """JSONB-профиль: доступ и по ключу, и по атрибуту (``profile.digest_size``).

    Контракт api.md не фиксирует, отдаёт ли ``UserRow.profile`` dict или
    ``Profile`` — двойник поддерживает оба стиля доступа; вложенные словари
    (например ``schedule``) заворачиваются так же.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            value = self[name]
        except KeyError as exc:  # pragma: no cover - защита от опечаток в тестах
            raise AttributeError(name) from exc
        return value


def model_profile(data: Mapping[str, Any]) -> ModelProfile:
    wrapped = ModelProfile()
    for key, value in data.items():
        wrapped[key] = model_profile(value) if isinstance(value, Mapping) else value
    return wrapped


def model_profile_of(profile: Any) -> ModelProfile:
    """Профиль-двойник: JSONB-словарь ``profile_to_jsonb`` с атрибутным доступом."""
    profile_to_jsonb = load_attr("app.domain.profile", "profile_to_jsonb")
    return model_profile(dict(profile_to_jsonb(profile)))


@dataclass(frozen=True)
class ModelParseRun:
    source: str
    status: str
    added: int
    alert_sent: bool
    suppressed_alerts: int
    started_at: datetime
    finished_at: datetime


class ModelAdminStats:
    """Сводка статистики (api.md §9): пользователи + счётчики обратной связи.

    Имена полей api.md не фиксирует — объект несёт алиасы (``users``/``user_count``,
    ``like``/``likes`` и т.д.).
    """

    def __init__(self, *, users: int, like: int, dislike: int, bookmark: int) -> None:
        self.users = users
        self.like = like
        self.dislike = dislike
        self.bookmark = bookmark

    @property
    def user_count(self) -> int:
        return self.users

    @property
    def likes(self) -> int:
        return self.like

    @property
    def dislikes(self) -> int:
        return self.dislike

    @property
    def bookmarks(self) -> int:
        return self.bookmark


# ---------------------------------------------------------------------------
# Двойники границы I/O
# ---------------------------------------------------------------------------


BROKEN_MARKUP_HTML = (
    "<html><body><p>совсем не та вёрстка</p></body></html>"  # «неожиданная вёрстка»
)
CAPTCHA_HTML = "<html><body>Access denied: please solve the captcha</body></html>"


@dataclass(frozen=True)
class FakeResponse:
    """Ответ HTTP-клиента (api.md §6: status_code, text, headers)."""

    text: str = ""
    status_code: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)


class FakeClient:
    """Двойник ``HttpClient`` (api.md §6): маршруты по подстроке URL, учёт вызовов.

    Никакой сети: ``get`` либо отдаёт заготовленный ответ, либо бросает
    подготовленную ошибку (таймаут/сеть) — ровно то, что описывают сценарии.
    """

    def __init__(
        self,
        routes: Mapping[str, FakeResponse] | None = None,
        *,
        fallback: FakeResponse | None = None,
        error: Exception | None = None,
        delay: float = 0.0,
        on_request: Callable[[str], None] | None = None,
    ) -> None:
        self.routes = dict(routes or {})
        self.fallback = fallback
        self.error = error
        self.delay = delay
        self.on_request = on_request
        self.calls: list[tuple[str, dict[str, str]]] = []

    @classmethod
    def for_sources(
        cls,
        *,
        hh: FakeResponse | Exception | None = None,
        habr: FakeResponse | Exception | None = None,
        fallback: FakeResponse | None = None,
    ) -> FakeClient:
        """Маршруты по хостам источников (URL коллекторов спека не фиксирует)."""
        client = cls(fallback=fallback)
        for host, payload in (("hh.ru", hh), ("habr", habr)):
            if payload is None:
                continue
            if isinstance(payload, Exception):
                client.routes[host] = payload
            else:
                client.routes[host] = payload
        return client

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> FakeResponse:
        self.calls.append((url, dict(headers or {})))
        if self.on_request is not None:
            self.on_request(url)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        payload: Any = self.fallback
        for host, candidate in self.routes.items():
            if host in url:
                payload = candidate
                break
        if isinstance(payload, Exception):
            raise payload
        if payload is None:
            raise AssertionError(f"FakeClient: неожиданный URL запроса {url!r}")
        return payload


class FakeSender:
    """Двойник ``Sender`` (api.md §13): записывает отправки, умеет падать по плану."""

    def __init__(self, failures: Mapping[int, Sequence[Exception]] | None = None) -> None:
        self.sent: list[tuple[int, str]] = []
        self.failures = {chat: deque(plan) for chat, plan in (failures or {}).items()}

    async def send_html(self, chat_id: int, text: str) -> None:
        plan = self.failures.get(chat_id)
        if plan:
            raise plan.popleft()
        self.sent.append((chat_id, text))

    def texts_for(self, chat_id: int) -> list[str]:
        return [text for chat, text in self.sent if chat == chat_id]


class FakeThrottle:
    """Двойник ``Throttle`` (api.md §13): считает паузы под лимиты Telegram."""

    def __init__(self) -> None:
        self.waits = 0

    async def wait(self) -> None:
        self.waits += 1


class FakeAlertSink:
    """Двойник ``AlertSink`` (api.md §10): собирает алерты админу."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def send_admin(self, text: str) -> None:
        self.texts.append(text)


class FloodWaitError(Exception):
    """Ошибка «429 / FloodWait» с атрибутом retry_after (duck-typing aiogram)."""

    def __init__(self, retry_after: float, message: str = "Flood control") -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProbeSession(RecordingSession):
    """Сессия БД с учётом жизненного цикла (закрыта ли) для R31/P-SES-01.

    Наследует общий двойник ``tests/security/support.py`` (не дублирует его):
    цепочки ``scalars()/all()/...`` уже поддерживаются, добавлен только флаг
    закрытия — сессия считается удерживаемой с момента создания до ``close()``
    или выхода из ``async with``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def __aexit__(self, *exc: Any) -> bool:
        self.closed = True
        return False

    async def close(self) -> None:
        self.closed = True


class ProbeSessionFactory(RecordingSessionFactory):
    """Фабрика сессий с подсчётом удерживаемых (незакрытых) сессий."""

    def __call__(self, *args: Any, **kwargs: Any) -> ProbeSession:
        session = ProbeSession()
        self.sessions.append(session)
        return session

    def open_count(self) -> int:
        return sum(1 for session in self.sessions if not session.closed)

    def assert_none_open(self, where: str) -> None:
        assert self.open_count() == 0, (
            f"{where}: сессия БД удерживается открытой во время внешнего I/O "
            f"(открыто {self.open_count()} из {len(self.sessions)}) — R31"
        )


# ---------------------------------------------------------------------------
# InMemoryRepo — модель документированной семантики Repo (api.md §9)
# ---------------------------------------------------------------------------


class InMemoryRepo:
    """Репозиторий-двойник: in-memory реализация семантики api.md §9.

    Используется там, где под тестом логика сервисов (сбор, алерты, дайджест,
    рассылка), а не хранилище; сценарии, проверяющие состояние кэша/доставок,
    идут на реальном ``Repo`` + тестовой БД (``real_repo``). Имена методов —
    строго контракт §9; неизвестные методы записываются и возвращают ``None``
    (расширения реализации не роняют двойник). Все вызовы пишутся в ``calls``.
    """

    def __init__(self, *, presets: Sequence[Any] = ()) -> None:
        self.calls: list[str] = []
        self.users: dict[int, ModelUser] = {}
        self.presets: dict[str, Any] = {preset.slug: preset for preset in presets}
        self.vacancies: list[Any] = []
        self.canonical_urls: set[str] = set()
        self.dedup_keys: set[str] = set()
        self.deliveries: set[tuple[int, Any]] = set()
        self.slots: set[tuple[int, str]] = set()
        self.feedback: dict[tuple[int, Any], str] = {}
        self.parse_runs: list[ModelParseRun] = []
        self.suppressed: dict[str, int] = {}
        self.unknown_calls: list[str] = []

    # -- пользователи -------------------------------------------------------

    async def list_users(self) -> list[ModelUser]:
        """Перечисление пользователей (расширение §9 — api.md не фиксирует метод,
        но check_schedules обязан обходить подписчиков; см. acceptance-map.md)."""
        self.calls.append("list_users")
        return list(self.users.values())

    async def get_user(self, user_id: int) -> ModelUser | None:
        self.calls.append("get_user")
        return self.users.get(user_id)

    async def upsert_user(self, user_id: int, *, lang: str, profile: Any) -> ModelUser:
        self.calls.append("upsert_user")
        user = ModelUser(id=user_id, lang=lang, profile=profile)
        self.users[user_id] = user
        return user

    async def set_profile(self, user_id: int, profile: Any) -> None:
        self.calls.append("set_profile")
        if user_id in self.users:
            old = self.users[user_id]
            self.users[user_id] = ModelUser(id=old.id, lang=old.lang, profile=profile)

    # -- пресеты ------------------------------------------------------------

    async def list_presets(self) -> list[Any]:
        self.calls.append("list_presets")
        return list(self.presets.values())

    async def upsert_preset(self, slug: str, *, name: str, filter_json: Any) -> None:
        self.calls.append("upsert_preset")
        self.presets[slug] = ModelPreset(slug=slug, name=name, filter_json=dict(filter_json))

    async def delete_preset(self, slug: str) -> None:
        self.calls.append("delete_preset")
        self.presets.pop(slug, None)

    # -- кэш вакансий --------------------------------------------------------

    async def add_vacancies(self, vacancies: Sequence[Any]) -> int:
        """Дедупликация по каноническому URL, иначе по нормализованным title+company.

        Семантика — AC-4/§7.1; ключи строятся production-функциями
        ``canonicalize_url``/``normalize_text`` (сами они проверяются P-DED-01).
        """
        self.calls.append("add_vacancies")
        canonicalize_url = load_attr("app.collectors", "canonicalize_url")
        normalize_text = load_attr("app.collectors", "normalize_text")
        added = 0
        for vacancy in vacancies:
            canonical = canonicalize_url(vacancy.url)
            dedup_key = normalize_text(f"{vacancy.title} {vacancy.company}")
            if canonical in self.canonical_urls or dedup_key in self.dedup_keys:
                continue
            self.canonical_urls.add(canonical)
            self.dedup_keys.add(dedup_key)
            self.vacancies.append(vacancy)
            added += 1
        return added

    async def select_candidates(
        self, *, user_id: int, preset_slugs: Sequence[str], tweaks: Any, limit: int
    ) -> list[Any]:
        self.calls.append("select_candidates")
        matches = load_attr("app.filters.rules", "matches")
        score = load_attr("app.filters.rules", "score")
        preset_by_slug = self.presets
        chosen: list[tuple[int, Any]] = []
        for vacancy in self.vacancies:
            if (user_id, id_of(vacancy)) in self.deliveries:
                continue
            for slug in preset_slugs:
                preset = preset_by_slug.get(slug)
                if preset is None:
                    continue
                if matches(vacancy, load_filter_of(preset), tweaks):
                    chosen.append((score(vacancy, load_filter_of(preset), tweaks), vacancy))
                    break
        chosen.sort(key=lambda pair: (pair[0], pair[1].published_at), reverse=True)
        return [vacancy for _score, vacancy in chosen[:limit]]

    async def mark_delivered(
        self, *, user_id: int, vacancy_ids: Sequence[Any], slot_key: str
    ) -> None:
        self.calls.append("mark_delivered")
        for vacancy_id in vacancy_ids:
            self.deliveries.add((user_id, vacancy_id))
        self.slots.add((user_id, slot_key))

    async def claim_slot(self, *, user_id: int, slot_key: str) -> bool:
        self.calls.append("claim_slot")
        key = (user_id, slot_key)
        if key in self.slots:
            return False
        self.slots.add(key)
        return True

    # -- обратная связь -------------------------------------------------------

    async def upsert_feedback(self, *, user_id: int, vacancy_id: Any, action: str) -> None:
        self.calls.append("upsert_feedback")
        self.feedback[(user_id, vacancy_id)] = action

    # -- сборы и алерты -------------------------------------------------------

    async def record_parse_run(
        self, *, source: str, status: str, added: int, alert_sent: bool
    ) -> int:
        self.calls.append("record_parse_run")
        run = ModelParseRun(
            source=source,
            status=status,
            added=added,
            alert_sent=alert_sent,
            suppressed_alerts=self.suppressed.get(source, 0),
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        self.parse_runs.append(run)
        return len(self.parse_runs)

    async def recent_parse_runs(self, limit: int = 10) -> list[ModelParseRun]:
        self.calls.append("recent_parse_runs")
        return self.parse_runs[-limit:]

    async def alert_window_count(self, *, source: str, since: datetime) -> int:
        self.calls.append("alert_window_count")
        return sum(
            1
            for run in self.parse_runs
            if run.source == source and run.alert_sent and run.finished_at >= since
        )

    async def bump_suppressed_alerts(self, source: str) -> None:
        self.calls.append("bump_suppressed_alerts")
        self.suppressed[source] = self.suppressed.get(source, 0) + 1

    # -- retention и статистика ------------------------------------------------

    async def purge_old(self, *, cutoff_utc: datetime) -> int:
        self.calls.append("purge_old")
        keep = [v for v in self.vacancies if v.published_at >= cutoff_utc]
        removed = len(self.vacancies) - len(keep)
        self.vacancies = keep
        return removed

    async def admin_stats(self) -> ModelAdminStats:
        self.calls.append("admin_stats")
        counts = {"like": 0, "dislike": 0, "bookmark": 0}
        for action in self.feedback.values():
            counts[action] = counts.get(action, 0) + 1
        return ModelAdminStats(users=len(self.users), **counts)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)

        async def _unknown(*args: Any, **kwargs: Any) -> None:
            self.unknown_calls.append(name)
            return None

        return _unknown


@dataclass(frozen=True)
class ModelPreset:
    slug: str
    name: str
    filter_json: Mapping[str, Any]


def id_of(vacancy: Any) -> Any:
    """Идентификатор вакансии в кэше (у двойника — сам объект)."""
    return getattr(vacancy, "id", id(vacancy))


def load_filter_of(preset: Any) -> Any:
    """Фильтр пресета через production ``load_filter`` (JSONB → PresetFilter)."""
    load_filter = load_attr("app.filters.rules", "load_filter")
    raw = getattr(preset, "filter_json", None)
    if raw is None:
        raw = getattr(preset, "filter", None)
    return load_filter(dict(raw))


# ---------------------------------------------------------------------------
# Строители production-объектов и фикстур
# ---------------------------------------------------------------------------


def make_salary(minimum: int | None, maximum: int | None, currency: str) -> Any:
    salary_cls = load_attr("app.domain.currency", "Salary")
    return salary_cls(min=minimum, max=maximum, currency=currency)


def make_tweaks(**overrides: Any) -> Any:
    """Правки пользователя (api.md §7) через production ``UserTweaks``."""
    tweaks_cls = load_attr("app.filters.rules", "UserTweaks")
    values: dict[str, Any] = {"min_salary_rub": None, "work_format": None, "stop_words": []}
    values.update(overrides)
    return tweaks_cls(**values)


def make_vacancy(**overrides: Any) -> ModelVacancy:
    """Вакансия-двойник с разумными умолчаниями (для рендеров и моделей)."""
    defaults: dict[str, Any] = {
        "title": "Python Developer",
        "company": "Ромашка",
        "salary": None,
        "url": "https://hh.ru/vacancy/123",
        "source": SOURCE_HH,
        "published_at": datetime(2026, 3, 14, 8, 0, tzinfo=UTC),
        "description": "",
    }
    defaults.update(overrides)
    return ModelVacancy(**defaults)


def make_digest_item(n: int, vacancy: Any) -> Any:
    item_cls = load_attr("app.services.select", "DigestItem")
    return item_cls(n=n, vacancy=vacancy)


def make_profile(**overrides: Any) -> Any:
    """Профиль через production-датаклассы (api.md §5)."""
    profile_cls = load_attr("app.domain.profile", "Profile")
    schedule_cls = load_attr("app.domain.profile", "Schedule")
    values: dict[str, Any] = {
        "lang": "ru",
        "presets": ["python-backend"],
        "min_salary_rub": None,
        "work_format": None,
        "stop_words": [],
        "digest_size": 10,
        "schedule": schedule_cls(local_time=dt_time(9, 30), tz="Europe/Moscow"),
    }
    values.update(overrides)
    return profile_cls(**values)


def make_schedule(local_time: dt_time, tz: str) -> Any:
    schedule_cls = load_attr("app.domain.profile", "Schedule")
    return schedule_cls(local_time=local_time, tz=tz)


def fixture_text(name: str) -> str:
    """HTML-фикстура источника из ``tests/data/`` (отсутствие — внятный красный)."""
    path = REPO_ROOT / "tests" / "data" / name
    if not path.is_file():
        raise NotImplementedYet(
            f"фикстура tests/data/{name} ещё не добавлена (владелец — software-engineer)"
        )
    return path.read_text(encoding="utf-8")


def hh_list_page() -> str:
    return fixture_text("hh_list.html")


def habr_list_page() -> str:
    return fixture_text("habr_list.html")


def hh_empty_page() -> str:
    return fixture_text("hh_empty.html")


def habr_empty_page() -> str:
    return fixture_text("habr_empty.html")


# ---------------------------------------------------------------------------
# Реальный Repo + тестовая БД (сценарии состояния кэша/доставок)
# ---------------------------------------------------------------------------


@dataclass
class DBHandle:
    """Результат :func:`real_repo`: ``repo`` + ``engine``/``factory`` для сидинга."""

    repo: Any
    engine: Any
    factory: Any
    base: Any
    migration: Any = None  # CompletedProcess у migrated_db()


@asynccontextmanager
async def real_repo() -> AsyncIterator[DBHandle]:
    """Черный ящик поверх реального ``Repo`` на тестовой БД (суффикс ``_test``).

    Схема создаётся из моделей ``app.storage.models.Base`` (как в tests/e2e);
    перед любой работой с БД загружаются production-модули — пока их нет,
    тест падает внятным «модуль ... ещё не реализован», а не ошибкой соединения.
    """
    ensure_test_env()
    validate = load_attr("app.config", "validate_test_database_url")
    repo_cls = load_attr("app.storage.repo", "Repo")
    base = load_attr("app.storage.models", "Base")
    url = validate(app_settings().test_database_url)

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(base.metadata.drop_all)
            await conn.run_sync(base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        yield DBHandle(repo=repo_cls(factory), engine=engine, factory=factory, base=base)
    finally:
        await engine.dispose()


def run_alembic(*args: str) -> Any:
    """Публичная команда миграций проекта (AGENTS.md: ``alembic upgrade head``)."""
    import os
    import subprocess
    import sys

    ensure_test_env()
    validate = load_attr("app.config", "validate_test_database_url")
    url = validate(app_settings().test_database_url)
    alembic_bin = Path(sys.executable).parent / "alembic"
    env = {**os.environ, "DATABASE_URL": url}
    return subprocess.run(  # noqa: S603 - фиксированный аргументы, без shell
        [str(alembic_bin), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


@asynccontextmanager
async def migrated_db() -> AsyncIterator[DBHandle]:
    """Чистая тестовая БД + ``alembic upgrade head`` (миграции + сиды пресетов)."""
    import sqlalchemy

    ensure_test_env()
    validate = load_attr("app.config", "validate_test_database_url")
    repo_cls = load_attr("app.storage.repo", "Repo")
    base = load_attr("app.storage.models", "Base")
    url = validate(app_settings().test_database_url)

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(base.metadata.drop_all)
            await conn.execute(sqlalchemy.text("DROP TABLE IF EXISTS alembic_version"))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        migration = run_alembic("upgrade", "head")
        yield DBHandle(
            repo=repo_cls(factory),
            engine=engine,
            factory=factory,
            base=base,
            migration=migration,
        )
    finally:
        await engine.dispose()


def run(coro: Any) -> Any:
    """Запуск корутины из синхронного property-теста (hypothesis не даёт async)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Вход в бота (BotHarness, api.md §15 / threat-model §5.8)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def open_bot() -> AsyncIterator[Any]:
    """Открыть BotHarness; тестовый вход — только через его публичные методы."""
    ensure_test_env()
    harness_cls = load_attr("tests.e2e.helpers", "BotHarness")
    async with harness_cls() as harness:
        yield harness


async def _normalize(messages: Any) -> list[str]:
    if inspect.isawaitable(messages):
        messages = await messages
    return [message.text if hasattr(message, "text") else str(message) for message in messages]


async def sent_texts(harness: Any) -> list[str]:
    """Тексты ответов на последний ``send`` (объекты с ``.text`` либо строки)."""
    return await _normalize(harness.sent())


async def send_text(harness: Any, user_id: int, text: str) -> list[str]:
    """Отправить сообщение боту и вернуть тексты ответов."""
    result = harness.send(text, user_id=user_id)
    if inspect.isawaitable(result):
        await result
    return await sent_texts(harness)


async def deliver_texts(harness: Any, user_id: int) -> list[str]:
    """Доставить текущий дайджест пользователю (служебный триггер слота).

    Расширение минимального API BotHarness (threat-model §5.8 допускает его):
    acceptance-тестам нужен наблюдаемый момент доставки дайджеста; возвращает
    тексты доставленных сообщений (частей дайджеста).
    """
    return await _normalize(harness.deliver_digest(user_id=user_id))


async def talk(user_id: int, *steps: str) -> list[list[str]]:
    """Серия сообщений боту в одном запуске (BotHarness): ответы по каждому шагу.

    Протокол диалога настроек (договорённость — см. докстринг модуля):
    ``/settings`` показывает текущие настройки; ``/settings time|tz|size|salary``
    открывают шаг, значение приходит следующим сообщением; ``/settings preset|
    stop|lang`` — так же. Выбор языка при ``/start`` — ``lang:{code}``
    (api.md §15, текстовая форма для BotHarness).
    """
    replies: list[list[str]] = []
    async with open_bot() as harness:
        for step in steps:
            replies.append(await send_text(harness, user_id, step))
    return replies


async def ask(user_id: int, text: str) -> list[str]:
    """Одно сообщение боту и ответы на него (BotHarness, threat-model §5.8)."""
    async with open_bot() as harness:
        return await send_text(harness, user_id, text)
