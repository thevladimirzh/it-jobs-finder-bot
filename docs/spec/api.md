# Контракт публичного API — it-jobs-finder-bot (I-1, уточнения I-2–I-3)

Назначение: acceptance-тесты (qa-engineer) пишут чёрные тесты ровно по этому
контракту; production-код (software-engineer) реализует ровно его. Источники:
`AGENTS.md` (целевая структура `app/`), `docs/spec/decisions.md` (интерпретации,
решения Q1–Q3, §8 — диалог I-2), `docs/product/brief.md` §6.1 (точные строки).

Статус: предложение business-analyst от 27.10.2026; расхождения с кодом фиксируются
в `docs/spec/decisions.md` (R36).

## 0. Общие соглашения

- Python 3.12, все I/O-функции — `async def`; чистая логика — обычные функции.
- Время везде в контракте — `datetime` с tz-aware UTC; хранение в БД — UTC;
  расписание пользователя — в его таймзоне (`zoneinfo`).
- Язык вывода: `Lang = Literal["ru", "en"]`.
- Зависимости для тестов передаются извне (HTTP-клиент, отправитель Telegram,
  репозиторий) — сеть в тестах запрещена (R41).
- Весь текст для Telegram собирается уже экранированным; функции рендера возвращают
  готовый HTML для `sendMessage(parse_mode="HTML")`.
- Исключения перечислены для каждой функции; не перечисленные — не бросаются.

---

## 1. `app/config.py`

```python
class Settings(BaseSettings):
    bot_token: str
    admin_id: int
    database_url: str
    test_database_url: str = "postgresql+asyncpg://jobs:jobs@localhost:5432/jobs_test"
    collect_interval_minutes: int = 60
    digest_size_default: int = 10
    digest_catchup_minutes: int = 180      # догоняющее окно, 3 ч
    retention_days: int = 30
    cleanup_time: str = "04:15"            # HH:MM, UTC
    http_timeout_seconds: float = 15.0

settings: Settings                          # синглтон модуля, читает .env

def validate_test_database_url(url: str) -> str
```

- Вход: env-переменные (pydantic-settings). Выход: `settings`.
- `validate_test_database_url`: возвращает `url`, если имя БД оканчивается на `_test`.
- Исключения: `pydantic.ValidationError` при конструировании `Settings`
  (неполная/кривая конфигурация → падение на старте, R30);
  `ValueError` из `validate_test_database_url` (запрет рабочей БД в тестах, R29).

## 2. `app/textutil.py`

```python
def esc(text: str) -> str        # экранирует & < > для HTML-текста Telegram
def esc_attr(text: str) -> str   # дополнительно экранирует " для атрибутов
```

- Вход: любая строка (внешний/пользовательский текст, включая NUL, суррогаты,
  RTL-override, ~1 МБ). Выход: безопасная строка.
- Исключений не бросают никогда (R25).

## 3. `app/i18n.py` *(добавление к структуре AGENTS.md — см. примечание в конце)*

```python
Lang = Literal["ru", "en"]

def t(key: str, lang: Lang, **params: object) -> str   # строка-шаблон с подстановкой
def keys(lang: Lang) -> frozenset[str]                 # ключи словаря (паритет RU/EN)
```

- Исключения: `KeyError` при отсутствующем ключе (ловится тестами паритета, R39).
- Шаблоны §6.1 brief и строки §4 decisions живут здесь (константы точных строк).

## 4. `app/domain/currency.py`

```python
@dataclass(frozen=True)
class Salary:
    min: int | None
    max: int | None
    currency: str                 # ISO 4217 верхним регистром

def parse_salary(raw: str | None) -> Salary | None
def format_salary(salary: Salary | None, lang: Lang) -> str
def estimate(salary: Salary) -> int | None        # min если есть, иначе max
def to_rubles(salary: Salary) -> int | None       # приблизительные курсы
def meets_minimum(salary: Salary | None, minimum_rub: int | None) -> bool
```

- `parse_salary`: вход — «сырая» строка источника (`от 150 000 ₽`, `до $2000`,
  `100 000 – 200 000 ₽`, U+00A0, `тыс.`, `млн`, ISO-валюты); выход — `Salary` или
  `None` (мусор, min>max без возможности обмена, суммы ≤ 0, переполнение int64).
  Нормализация: `min > max` → обмен; разряды — U+0020 в выводе (decisions §5.8).
- `format_salary`: точные строки brief §6.1 (`от {min} {cur}` | `до {max} {cur}` |
  `{min} – {max} {cur}` | `Зарплата не указана`; EN: `from`/`up to`/range/
  `Salary not specified`); `{cur}` = `₽`|`$`|`€` для RUB/USD/EUR, иначе ISO-код.
- `meets_minimum`: `salary is None` → `True` (lenient, decisions §5.9).
- Исключений не бросают (R8, R22).

## 5. `app/domain/profile.py`

```python
@dataclass(frozen=True)
class Schedule:
    local_time: datetime.time     # локальное время дайджеста
    tz: str                       # IANA ("Europe/Moscow") или "UTC+3"/"UTC-5"

@dataclass(frozen=True)
class Profile:
    lang: Lang
    presets: list[str]            # slug-и подписки
    min_salary_rub: int | None    # правка пользователя
    work_format: str | None       # правка пользователя
    stop_words: list[str]         # правка пользователя
    digest_size: int              # 1..50
    schedule: Schedule | None     # None → дайджест не отправляется (AC-18)

def parse_hhmm(raw: str) -> datetime.time            # "09:30" -> time(9, 30)
def parse_tz(raw: str) -> ZoneInfo | timezone        # "Europe/Moscow", "UTC+3"
def profile_to_jsonb(profile: Profile) -> dict[str, Any]
def profile_from_jsonb(data: Mapping[str, Any]) -> Profile
```

- Исключения: `ValueError` — из `parse_hhmm` (не `HH:MM`, вне 00:00–23:59),
  `parse_tz` (неизвестная зона/offset), `profile_from_jsonb` (битый JSONB).
- Свойство (PBT): `profile_from_jsonb(profile_to_jsonb(p)) == p`.

## 6. `app/collectors/` (`__init__.py`, `hh.py`, `habr.py`)

```python
@dataclass(frozen=True)
class Vacancy:                      # нормализованная вакансия
    title: str
    company: str
    salary: Salary | None
    url: str                        # канонический: схема/хост, без UTM и хвостового "/"
    source: str                     # "hh.ru" | "Habr Career"
    published_at: datetime          # tz-aware; нет даты в источнике → время сбора (decisions §9.1)
    description: str = ""

class HttpClient(Protocol):         # FakeClient в тестах реализует тот же интерфейс
    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> ResponseLike
    # ResponseLike: .status_code: int, .text: str, .headers: Mapping[str, str]

class Collector(Protocol):
    name: str                       # "hh.ru" | "Habr Career"
    async def collect(self, client: HttpClient, *, now: datetime | None = None) -> list[Vacancy]
    # now — момент сбора (tz-aware UTC) для published_at-fallback и дат карточек;
    # None → текущий момент (decisions §9.1/D5, S93)

def build_collectors() -> list[Collector]       # [HhCollector(), HabrCareerCollector()]

class CollectorError(Exception): ...
class ParseError(CollectorError): ...           # битая разметка        → «ошибка разбора разметки»
class SourceBlocked(CollectorError): ...        # 403/429/капча         → «блокировка/капча»
class EmptyResult(CollectorError): ...          # 0 карточек при валидной разметке → «пустой разбор»
class SourceUnavailable(CollectorError): ...    # сеть/таймаут/5xx      → «источник недоступен»

def canonicalize_url(raw: str) -> str           # схема/хост, без UTM, без хвостового "/"
def normalize_text(raw: str) -> str             # lower, без пунктуации/двойных пробелов (для дедупа)
def raise_if_blocked(body: str) -> None         # challenge-страница → SourceBlocked (F-22, решения §9.4 ред. 2)
```

- Вход `collect`: только переданный `client` (сеть наружу не ходит, R41);
  `now: datetime | None = None` — момент сбора (tz-aware UTC) для
  `published_at`-fallback и даты из карточки; `None` → текущий момент.
- Выход: `list[Vacancy]` длиной ≥ 1; **пустой список не возвращается молча** (R40):
  0 карточек → `EmptyResult`.
- `published_at` (уточнение I-3, decisions §9.1): если источник не даёт дату
  публикации (выдача hh.ru) — `published_at` = время сбора, карточка не
  отбрасывается; возраст такой вакансии всегда «сегодня»/`today` (S93).
  Если дата в источнике есть (Habr Career) — берётся она (S91).
- Промо-карточки (уточнение I-3, decisions §9.3): карточка, ссылка заголовка
  которой не ведёт на `/vacancy/` (напр. `https://adsrv.hh.ru/click?...`),
  пропускается при разборе: в выход не попадает, дедупликацию не ломает,
  алерта не вызывает (S92).
- Allowlist хостов URL (уточнение I-3-fix, F-25, decisions §9.7): карточка, чей
  URL после канонизации ведёт не на хост источника или его поддомен
  (hh.ru — `hh.ru` + поддомены; Habr Career — `career.habr.com` и `habr.com` +
  поддомены), пропускается молча — как промо (не в выход, не в дедуп, без
  алерта) (S99); страница, где все карточки пропущены (промо и/или чужие
  хосты) → `ParseError` (S100); поддомены источника разрешены (S101).
  Относительные ссылки карточек разрешаются относительно `base_url` источника
  до канонизации. Правила промо и allowlist независимы (оба применяются).
- Исключения: `ParseError`, `SourceBlocked`, `EmptyResult`, `SourceUnavailable`.
  Классификация (уточнение I-3, decisions §9.4–§9.5; §9.4 — **редакция 2**,
  решение арбитра 28.10, F-22):
  - `raise_if_blocked(body)` вызывается до разбора карточек; тело
    **нормализуется перед матчингом**: снимаются HTML-комментарии,
    декодируются entity (в т.ч. `&nbsp;`), регистр/разделители игнорируются
    (`SmartCaptcha` ~ `smart-captcha`) — маркер, разорванный
    комментарием/entity/дефисом, всё равно матчится (S97);
  - сильные маркеры (`ddos-guard`, `qrator`, `smart-captcha`, «just a moment»)
    → `SourceBlocked` (не `ParseError`) **только в структурных позициях**:
    `<script>`, `<link>`, cookie-атрибуты, `<title>` (S94);
  - видимый текст (включая карточки вакансий: «Qrator», «just a moment» в
    описании) **никогда** не даёт `SourceBlocked` (S96);
  - слабые маркеры (`captcha`, `access denied`) — только в `<title>`/`<h1>`
    (S98);
  - HTTP 403/429 → `SourceBlocked` независимо от тела (S10, S94);
  - скелет страницы есть, карточки присутствуют, но ни одна не разобрана →
    `ParseError` (S95); валидная страница без карточек → `EmptyResult` (S11).
- Фикстуры `tests/data/` коллекторов — только санитизированные живые образцы
  выдачи с шапкой «источник + дата съёмки» (decisions §9.2); селекторы разбора
  сверяются с живой разметкой, синтетика запрещена.
- Свойство (P-BEN-01): для любой HTML-страницы `collect` либо возвращает ≥1
  вакансию, либо бросает одно из четырёх исключений — никогда не падает иным
  способом и никогда не возвращает `[]`.
- Дополнение к AGENTS.md: иерархия `CollectorError`/`EmptyResult`/`SourceUnavailable`
  зафиксирована в decisions.md (маппинг на 4 причины алертов §6.1).

## 7. `app/filters/rules.py`

```python
@dataclass(frozen=True)
class PresetFilter:
    role: str
    must: list[str]
    nice: list[str]
    grades: list[str]
    min_salary: int | None
    work_format: str | None
    location: str | None
    stop_words: list[str]
    employment: str | None

@dataclass(frozen=True)
class UserTweaks:                   # глобальные поверх всех пресетов (brief §7.4)
    min_salary_rub: int | None
    work_format: str | None
    stop_words: list[str]

def load_filter(data: Mapping[str, Any]) -> PresetFilter     # из JSONB пресета
def matches(vacancy: Vacancy, preset: PresetFilter, tweaks: UserTweaks) -> bool
def score(vacancy: Vacancy, preset: PresetFilter, tweaks: UserTweaks) -> int
```

- Семантика (decisions §5.11–5.12): стоп-слова — подстрока без учёта регистра в
  заголовке и компании; все `must` — в нормализованном тексте вакансии;
  `nice` — баллы скоринга; зарплата — `currency.meets_minimum`.
- Исключения: `ValueError` из `load_filter` (битый JSONB пресета).

## 8. `app/storage/models.py`

SQLAlchemy 2 declarative; `Base.metadata` — источник схемы для `alembic/env.py`
и для тестового `drop_all`/`create_all`. Обязательные таблицы и ключевые поля:

| Таблица | Ключи и поля |
|---|---|
| `users` | `id` (telegram chat_id, PK, BigInteger), `lang`, `profile` (JSONB), `created_at` |
| `presets` | `slug` (PK), `name_ru`, `name_en`, `description`, `filter` (JSONB), `is_active` |
| `vacancies` | `id` (PK), `canonical_url` (unique), `dedup_key` (unique, нормализованные title+company), `title`, `company`, `salary_min`, `salary_max`, `currency`, `source`, `published_at` (UTC), `description`, `created_at` |
| `deliveries` | PK (`user_id`, `vacancy_id`), `delivered_at` — учёт Q2 (at-most-once) |
| `feedback` | PK (`user_id`, `vacancy_id`), `action` (`like\|dislike\|bookmark`), `updated_at` — upsert (decisions §5.5) |
| `digest_slots` | PK (`user_id`, `slot_key`) — защита от повторов слота (R32) |
| `parse_runs` | `id`, `source`, `status`, `added`, `alert_sent`, `suppressed_alerts`, `started_at`, `finished_at` |

Изменение моделей обязывает добавить миграцию в `alembic/versions/` в том же цикле.

## 9. `app/storage/repo.py`

```python
class Repo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]): ...

    async def get_user(self, user_id: int) -> UserRow | None
    async def upsert_user(self, user_id: int, *, lang: Lang,
                          profile: Profile | Mapping[str, Any]) -> UserRow
    async def set_profile(self, user_id: int, profile: Profile | Mapping[str, Any]) -> None

    async def list_presets(self) -> list[PresetRow]
    async def upsert_preset(self, slug: str, *, name: str, filter_json: Mapping[str, Any]) -> None
    async def delete_preset(self, slug: str) -> None

    async def add_vacancies(self, vacancies: Sequence[Vacancy]) -> int   # дедуп, вернуло новых
    async def select_candidates(self, *, user_id: int, preset_slugs: Sequence[str],
                                tweaks: UserTweaks, limit: int) -> list[VacancyRow]
    async def mark_delivered(self, *, user_id: int, vacancy_ids: Sequence[int],
                             slot_key: str) -> None
    async def claim_slot(self, *, user_id: int, slot_key: str) -> bool   # False → слот уже отработан

    async def upsert_feedback(self, *, user_id: int, vacancy_id: int,
                              action: Literal["like", "dislike", "bookmark"]) -> None

    async def record_parse_run(self, *, source: str, status: str, added: int,
                               alert_sent: bool) -> int
    async def recent_parse_runs(self, limit: int = 10) -> list[ParseRunRow]
    async def alert_window_count(self, *, source: str, since: datetime) -> int
    async def bump_suppressed_alerts(self, source: str) -> None

    async def purge_old(self, *, cutoff_utc: datetime) -> int   # retention, вернуло удалённых
    async def admin_stats(self) -> AdminStats                   # пользователи + счётчики feedback
```

- Контракт сессий (R31): каждый метод открывает короткую сессию, коммитит сам и
  закрывает её до возврата; ни один метод не выполняет HTTP-вызовов.
- Формы `profile` у `upsert_user`/`set_profile` (решено при реализации,
  decisions §7 «Решено при реализации», п.4): принимается как `Profile`, так и как JSONB-dict
  (`Mapping[str, Any]`). `Profile` сериализуется через `profile_to_jsonb`
  (`app/domain/profile.py`), dict передаётся в БД как есть; хранение в `users.profile` —
  всегда JSONB-dict. Чтение — `profile_of(user)` (`app/services/select.py`):
  `UserRow.profile` допускает оба формата (`Profile` или Mapping →
  `profile_from_jsonb`; битый/отсутствующий профиль → `ValueError`).
- `select_candidates`: только недоставленные (`deliveries`), фильтр хотя бы одного
  подписанного пресета с учётом `tweaks`, сортировка score desc, `published_at` desc.
- Исключения: ошибки SQLAlchemy проходят наверх без изменения.

## 10. `app/services/collect.py`

```python
@dataclass(frozen=True)
class CollectReport:
    source: str
    status: Literal["ok", "blocked", "parse_error", "empty", "unavailable"]
    added: int
    alert: str | None               # «⚠️ Сбор {source}: {reason}» или None

class AlertSink(Protocol):
    async def send_admin(self, text: str) -> None

async def run_collect(*, client: HttpClient, repo: Repo, alerts: AlertSink,
                      now: datetime) -> list[CollectReport]
```

- Вход: HTTP-клиент (в тестах — `FakeClient`), репозиторий, канал алертов, время.
- Выход: отчёт по каждому источнику; кэш пополнен с дедупликацией (AC-4).
- Алерты: точный шаблон brief §6.1 `⚠️ Сбор {source}: {reason}`, `reason` ∈
  {`блокировка/капча`, `ошибка разбора разметки`, `пустой разбор`,
  `источник недоступен`}; не чаще одного на источник в час, подавленные
  учитываются счётчиком (decisions §5.14). Алерты всегда RU.
- Исключений не бросает: любая ошибка источника превращается в `CollectReport`
  и алерт (graceful degradation, R1/R2/R40).

## 11. `app/services/select.py`

```python
@dataclass(frozen=True)
class DigestItem:
    n: int                          # сквозной номер карточки, с 1
    vacancy: VacancyRow

@dataclass(frozen=True)
class Selection:
    items: list[DigestItem]
    slot_key: str

async def select_digest(*, repo: Repo, user: UserRow, now: datetime,
                        limit: int | None = None) -> Selection | None
```

- Выбор: недоставленные вакансии под подписку + правки, сортировка brief §7.5,
  лимит `limit or profile.digest_size` (1..50).
- **Q2 (at-most-once):** при возврате `Selection` выбранные вакансии уже помечены
  доставленными, слот занят через `claim_slot` (decisions §5.1); повторный вызов
  для того же слота вернёт `None`.
- Возвращает `None`, если подходящих вакансий нет (пустой дайджест — см. §12).
- Исключения: `ValueError` при `limit` вне 1..50; ошибки SQLAlchemy.

## 12. `app/services/digest.py`

```python
def truncate_title(escaped: str, limit: int = 200) -> str   # ≤200 code points, «…», без разрыва сущностей
def format_age(published_at: datetime, now: datetime, lang: Lang) -> str
def render_card(n: int, vacancy: Vacancy, lang: Lang, now: datetime) -> str
def render_header(count: int, on_date: datetime.date, lang: Lang) -> str
def render_empty(lang: Lang) -> str
def render_digest(items: Sequence[DigestItem], *, lang: Lang, now: datetime,
                  on_date: datetime.date) -> list[str]
```

- Строки — строго brief §6.1 (карточка, зарплата, возраст, заголовок
  `🔥 Подборка вакансий — {dd}.{mm}.{yyyy} ({count})` / `🔥 Job digest — ...`).
- `render_empty`: RU `🔥 Новых вакансий нет`, EN `🔥 No new vacancies` (Q3).
- `render_digest`: список частей; каждая часть — готовый HTML ≤ 4096 символов
  (включая теги); разбивка только по границам карточек; заголовок только в части 1;
  `count` — общее число карточек; нумерация сквозная (R4, R10).
- Исключения: `ValueError` (пустой `items` — используйте `render_empty`);
  `DigestError` (карточка не влезает в 4096 даже после `truncate_title` — защита
  от регрессии R24).

## 13. `app/services/dispatch.py`

```python
class Sender(Protocol):
    async def send_html(self, chat_id: int, text: str) -> None

class Throttle(Protocol):
    async def wait(self) -> None          # пауза под лимиты Telegram API

@dataclass(frozen=True)
class OutgoingMessage:
    chat_id: int
    text: str                             # готовый HTML (уже через esc)

@dataclass(frozen=True)
class DispatchReport:
    sent: int
    failed: tuple[tuple[int, str], ...]   # (chat_id, причина)

async def dispatch(messages: Sequence[OutgoingMessage], *, sender: Sender,
                   throttle: Throttle, now: datetime) -> DispatchReport
```

- Контракт (R9, R42): очередь с троттлингом; при `FloodWait`/429 — ожидание
  `retry_after` и повтор с бэкоффом; ошибка одного получателя не прерывает
  очередь и не вызывает повторной отправки остальным; исключения не утекают
  наружу — всё фиксируется в `DispatchReport`.

## 14. `app/services/scheduler.py`

```python
def local_slot(schedule: Schedule, day: datetime.date) -> datetime
    # слот в таймзоне пользователя (zoneinfo); «дыра» DST → первый существующий момент
def slot_key(user_id: int, schedule: Schedule, day: datetime.date) -> str
    # ключ слота (для digest_slots): одно наступление в сутки, без дублей при overlap

async def check_schedules(*, repo: Repo, sender: Sender, throttle: Throttle,
                          now: datetime) -> DispatchReport | None
    # вызывается раз в минуту; догоняющее окно digest_catchup_minutes (3 ч)

async def run_cleanup(*, repo: Repo, now: datetime) -> int
    # крон 04:15 UTC: purge_old(cutoff=now − retention_days)

def build_scheduler(*, repo, sender, throttle, settings) -> AsyncIOScheduler
    # job-ы: collect (collect_interval_minutes), check_schedules (каждую минуту),
    # run_cleanup (cron cleanup_time, UTC)
```

- Правила слота (decisions §5.13, §5.15–5.16): один выпуск на локальные сутки;
  при переводе часов — без пропусков и дублей; простой ≤ 3 ч → догон при
  восстановлении, иначе слот пропускается; `claim_slot` исключает повторы при
  рестартах и гонках (R6, R32).
- Исключения: `ValueError` из `local_slot` при невалидной таймзоне (исключено
  валидацией `Profile`).

## 15. `app/main.py` и хендлеры

```python
async def main() -> None    # сборка bot + dispatcher + scheduler, один процесс
```

Публичные точки входа для acceptance-тестов (через `BotHarness`, `tests/e2e/helpers.py`
или его acceptance-адаптацию):

| Вход | Поведение |
|---|---|
| `/start` | кнопочный диалог: выбор языка (`Русский`/`English`), мультивыбор пресетов (✅ + `Готово`), формат работы, таймзона (города/ручной UTC-offset), время `HH:MM` (текст), размер дайджеста (5/10/20/50) (S1, S2, S79–S89) |
| `/settings` | кнопочные шаги: пресеты (мультивыбор ✅ + `Готово`), формат работы, таймзона, размер дайджеста, язык; текстовые шаги: время `HH:MM`, мин. зарплата, стоп-слова, ручной UTC-offset (S3–S7) |
| `callback_query` (инлайн-кнопки диалога) | см. §15.1: `dlg:<step>:<value>` ≤ 64 байт, валидация, немедленный `answer_callback_query`, устаревший/чужой/невалидный → вежливый отказ (S79–S89) |
| `/like <n>`, `/dislike <n>`, `/bookmark <n>` | ответы `👍 Учтено` / `👎 Учтено` / `🔖 Сохранено` (EN `👍 Noted` / `👎 Noted` / `🔖 Saved`); неверный `n` → точная строка ошибки из `docs/spec/decisions.md` §4 / brief §6.1 (S45–S50) |
| `/admin`, `/admin_preset_list|add|edit|del`, `/admin_stats`, `/admin_collect`, `/admin_health` | только `ADMIN_ID`; не-админу — молчаливый игнор (S51–S55) |
| слот расписания | дайджест или `render_empty` (S35–S37, S38–S44) |

Точные строк всех ответов — константы `app/i18n.py`: brief §6.1 +
`docs/spec/decisions.md` §4 и §8 (никаких иных строк, «придуманных» в коде).

### 15.1 Диалог на инлайн-кнопках (I-2): контракт callback_query

Обработчик `callback_query` — в хендлерах `app/main.py` (модуля диалога в
структуре AGENTS.md нет; вынос — правка AGENTS.md, devops-sre). Сценарии
S79..S89 (`tests/features/dialog_callbacks.feature`), решения —
`decisions.md` §8.

| Аспект | Контракт |
|---|---|
| Форма callback_data | `dlg:<step>:<value>` (ASCII), **≤ 64 байт** (лимит Telegram); `step` ∈ белого списка шагов (`lang`, `preset`, `format`, `tz`, `size`, `done`, страницы городов), `value` — короткий код значения (slug/код города/offset/число) |
| Валидация | известный `step` + валидное значение → шаг выполняется; иначе — единый вежливый отказ (ниже), состояние не меняется, исключений нет (S88) |
| Подтверждение | каждый `callback_query` → немедленный `answer_callback_query` (до завершения обработки шага), включая устаревший/чужой/невалидный (S79) |
| Устаревший/чужой callback | кнопка не соответствует текущему шагу диалога пользователя или принадлежит другому пользователю → вежливый отказ, настройки и шаг не меняются (S80, S81) |
| Строка вежливого отказа (BA-предложение, ждёт brief §6.1) | RU `Эта кнопка устарела. Откройте настройки заново (/settings).` / EN `This button is outdated. Open settings again (/settings).` |
| Мультивыбор пресетов | переключение отметки (`✅ ` + имя); подписка сохраняется только по `Готово`; `Готово` без выбора → RU `Выберите хотя бы один пресет.` / EN `Pick at least one preset.` (S82, S83) |
| Состояние диалога | в памяти процесса, per-user (текущий шаг + накопленный мультивыбор); каждый завершённый шаг немедленно пишется в профиль (`users.profile`), пресеты — по `Готово`; рестарт сбрасывает только незавершённый мультивыбор (decisions §8.6) |
| Экранирование | значения (имена пресетов от админа, города, offset) в тексте сообщений — только через `app.textutil.esc`; текст кнопки Telegram — plain text (S85) |

## 16. Каталог исключений

| Исключение | Модуль | Значение |
|---|---|---|
| `CollectorError` | `app/collectors` | базовая ошибка источника |
| `ParseError` | `app/collectors` | битая разметка (в т.ч. карточки есть, но ни одна не разобрана — нет обязательных полей либо все карточки пропущены как промо/чужой хост, S95/S100) → алерт «ошибка разбора разметки» |
| `SourceBlocked` | `app/collectors` | блокировка/капча (403/429; сильные маркеры challenge DDoS-Guard/QRATOR/smart-captcha/«Just a moment» в структурных позициях `<script>`/`<link>`/cookie-атрибуты/`<title>` после нормализации тела, слабые `captcha`/`access denied` в `<title>`/`<h1>`; decisions §9.4 ред. 2, S94/S97/S98) → алерт «блокировка/капча»; видимый текст не триггерит (S96) |
| `EmptyResult` | `app/collectors` | 0 карточек → алерт «пустой разбор» |
| `SourceUnavailable` | `app/collectors` | сеть/таймаут/5xx → алерт «источник недоступен» |
| `DigestError` | `app/services/digest` | карточка не влезает в часть (регрессия R24) |
| `ValueError` | `domain/*`, `services/*` | невалидный пользовательский ввод/JSONB/лимиты |
| `pydantic.ValidationError` | `app/config` | неполная конфигурация env (R30) |
| `KeyError` | `app/i18n` | отсутствующий ключ словаря (R39) |

## 17. Инварианты, проверяемые acceptance/property-тестами

1. Каждая часть дайджеста ≤ 4096 символов готового HTML; карточка не рвётся (R4).
2. Внешний и пользовательский текст всегда проходит `esc`/`esc_attr`; произвольный
   ввод не добавляет HTML-тегов (R7, R38).
3. `(user_id, vacancy_id)` доставляется не более одного раза (Q2, R3).
4. Слот пользователя отрабатывает не более одного раза, включая рестарты и догон (R32).
5. `collect()` никогда не возвращает пустой список и не падает неожиданным
   исключением (R40).
6. Никакой HTTP-вызов не выполняется при открытой сессии БД (R31).
7. Тесты не открывают сеть и не трогают БД без суффикса `_test` (R29, R41).
8. Строки вывода байт-в-байт совпадают с brief §6.1 и решениями Q1–Q3 (R10, R36).
9. Диалог (I-2): каждый `callback_query` подтверждается `answer_callback_query`;
   callback_data каждой кнопки ≤ 64 байт и проходит валидацию (белый список);
   устаревший/чужой/невалидный callback не меняет состояние; **в дайджесте
   inline-кнопок нет** (Q1, решения §8.2–§8.3).
10. Видимый текст страницы источника (в т.ч. карточки вакансий: «Qrator»,
    «just a moment») никогда не приводит к `SourceBlocked`, а разорванный
    комментарием/entity маркер challenge-страницы всё равно детектится
    (F-22, S96/S97). В дайджест не попадает карточка с URL на чужой хост
    (F-25, S99).

## Примечания

1. `app/i18n.py` и иерархия исключений `CollectorError` не перечислены в целевой
   структуре `AGENTS.md` — дополнение согласовано этим контрактом; при включении в
   профиль файл правится его владельцем (devops-sre).
2. Q1 в силе для дайджеста: inline-кнопок 👍/👎/🔖 в дайджесте нет, обратная связь —
   команды; раздел «Кнопки» brief §6.1 устарел. С I-2 callback-формы **есть в
   диалоге настроек**: `dlg:<step>:<value>` (§15.1, решения §8) — только настройки,
   в выдачу кнопки не возвращаются. Свидетельства тестов I-1 вида «в `app/` нет
   `InlineKeyboard`» устаревают для диалога (решения §8.8).
3. Функции `select_digest`/`claim_slot` — место реализации at-most-once (Q2);
   семантика «отметка при формировании дайджеста» зафиксирована в
   `decisions.md` §5.1 и помечена как спорная.
