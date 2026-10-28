# Security-отчёт — it-jobs-finder-bot (I-1, дополнение I-2)

Дата: 27.10.2026 (шаг 2: security review + сканы перед QA gate; обновлено в тот же
день — шаг 3: фиксы F-09..F-12 от software-engineer, перевод контрпримеров в обычные
тесты, риски R53/R54); 27.10.2026 — дополнение I-2 (callback-канал инлайн-диалога,
SEC-15, §7); 28.10.2026 — финальный security review I-2 после реализации
callback-обработчика (§8): SEC-15 covered, находки F-14..F-17; 28.10.2026 —
верификация исправлений F-14..F-17 (§9): fixed, 31 постоянный security-тест,
остаточные наблюдения F-18/F-19 (low); 28.10.2026 — верификация исправлений
F-20..F-25 (§10.9, I-3-fix): fixed (F-20 — замеры до/после в §10.4; F-22 —
решено арбитром, контракт (б)-(е) реализован дословно), тесты SEC-09/SEC-12
обновлены под новый контракт challenge-детекта, 168 passed; 28.10.2026 —
синхронизация документации с decisions §9.4 **редакция 2** и §9.7 D7
(business-analyst): формулировки SEC-17/SEC-19/F-22/F-25 приведены к
действующему контракту (решение арбитра 28.10), история сохранена.
Автор: security-engineer.
Скоуп шага: review production-кода (`app/`, `alembic/versions/0001_initial.py`) по
threat model SEC-01..SEC-14, нормализация SQL-детектора в `tests/security/`,
сканы зависимостей/секретов/запрещённых конструкций.

Модель угроз: `docs/security/threat-model.md` (SEC-01..SEC-14, P-SEC-01..P-SEC-05).
Риски: `docs/risk-register.md` R43..R52 (новые — см. §5, владелец регистра PM/QA),
R53/R54 заведены 27.10 под закрытые находки F-09/F-10.
Шаг 1 (требования + красные тесты + находки F-01..F-08 по зависимостям) — история
этого файла; статусы обновлены ниже.

## 1. Выполненные команды (фактический вывод)

| Команда | Результат |
|---|---|
| `.venv/bin/python -m pytest tests/security -q` | `94 passed in 4.65s` — зелёный, 0 xfail / 0 failed; 4 бывших xfail-контрпримера F-09..F-12 переведены в обычные тесты после фиксов software-engineer (assert'ы не ослаблялись) |
| негативный контроль переведённых тестов (4 прогона `python -c '<мутация> + pytest.main([...])'`; дефект возвращается monkeypatch'ем в памяти, production-код на диске не меняется) | все 4 контрпримера красные на уязвимом поведении: f09 (`esc`→identity) — `1 failed` AssertionError, сырой payload в `/settings`; f10 (лимиты→`10**9`) — `1 failed` AssertionError, 80 стоп-слов и слова >100 символов; f11 (`except ValueError` без `RecursionError`) — `1 failed` RecursionError; f12 (дефолтный pydantic `__repr__`) — `1 failed` AssertionError, пароль DSN в repr |
| `.venv/bin/python -m pytest tests/security -q` (повтор ×4) | стабильно зелёный; в двух прогонах при параллельном прогоне полного suite (qa-engineer, общий `jobs_test`) фиксировалась флуктуация `asyncpg.exceptions.UndefinedTableError: relation "presets" does not exist` в BotHarness-тестах — гонка `drop_all/create_all` с чужим прогоном, не дефект кода (детали §4.1) |
| `ruff check tests/security` | `All checks passed!` (после удаления ставшего ненужным `import pytest` — F401) |
| `ruff format --check tests/security` | `5 files already formatted` |
| `.venv/bin/pip-audit -r requirements.txt` | `No known vulnerabilities found` (exit 0); `pip-audit 2.10.1` (в `requirements-dev.txt`) |
| `pip list \| grep ...` | aiogram 3.29.1, aiohttp 3.14.5, alembic 1.16.5, APScheduler 3.11.3, asyncpg 0.30.0, beautifulsoup4 4.14.3, httpx 0.28.1, pydantic-settings 2.16.1, SQLAlchemy 2.0.46 — пины F-01/F-02 подтверждены |
| grep секретов: `(bot_token\|password\|passwd\|secret\|api_key\|apikey)\s*=\s*['"][^'\"]{8,}` по репозиторию (без `.venv`/`.git`) | 0 совпадений |
| grep секретов: `([0-9]{8,10}:[A-Za-z0-9_-]{30,}\|-----BEGIN [A-Z ]*PRIVATE KEY-----\|AKIA[0-9A-Z]{16}\|ghp_[A-Za-z0-9]{36}\|xox[baprs]-...)` | 0 совпадений |
| grep `BOT_TOKEN\|PASSWORD\|SECRET\|TOKEN\|PRIVATE_KEY` в `.env`/`.env.example` | только плейсхолдеры `BOT_TOKEN=123456789:replace-with-real-token` (маркер `replace-with`) |
| `git ls-files \| grep '^\.env$'` | `.env` не отслеживается git; `.gitignore:153` содержит `.env` |
| grep запрещённого: `pickle.loads?\|eval(\|exec(\|yaml.load\|marshal.loads\|shelve.open\|os.system\|shell=True\|subprocess` по `app/` | 0 совпадений |
| grep SQL-интерполяции: `text(\|execute(` + `f"…SELECT/INSERT/…"\|.format(` по `app/` | 0 реальных совпадений (сработавшие строки — `normalize_text(f"…")` в `app/filters/rules.py:71,80,89`, `app/storage/repo.py:341` — это не SQL; все `session.execute(statement=…)` — ORM с bind-параметрами) |
| grep `parse_mode` по `app/` | 2 места: `app/bot/telegram.py:16`, `app/bot/handlers.py:29` — оба отправляют готовый HTML, экранирование на рендере (см. F-09) |
| grep `JobStore` по `app/` | `app/services/scheduler.py:88,97` — только `MemoryJobStore` (F-01 закрыт архитектурно) |

## 2. Находки

| ID | Severity | CWE | Файл:строка | Описание | Рекомендация | Status |
|---|---|---|---|---|---|---|
| F-01 | high | CWE-502 (CWE-1104) | `requirements.txt` (`apscheduler>=3.11.3,<4`) | APScheduler 3.11.0: pickle-десериализация `job_state` persistent job stores (GHSA-2r6w-vc63-g3hx) + `unmarshal_object` RCE (CVE-2026-31072) | пин ≥3.11.3 + только `MemoryJobStore` | **closed**: devops поднял пин (установлен 3.11.3); `app/services/scheduler.py:97` — `jobstores={"default": MemoryJobStore()}`; pip-audit чист |
| F-02 | medium | CWE-1104 (CWE-400) | транзитивно `aiogram → aiohttp` | CVE-2026-34993 (CookieJar.load RCE), CVE-2026-54273/74/77/78 (DoS), CVE-2026-47265, CVE-2026-69244 в aiohttp 3.13.5 | aiohttp ≥3.14.1 | **closed**: `aiohttp>=3.14.1` в requirements (установлен 3.14.5); pip-audit чист |
| F-03 | medium | CWE-1104 | зависимости (SQLAlchemy 2.0.46 и др.) | зависимостный скан отложен (pip-audit не установлен) | добавить pip-audit и прогнать | **closed**: `pip-audit==2.10.1` в requirements-dev; `.venv/bin/pip-audit -r requirements.txt` → `No known vulnerabilities found` |
| F-04 | medium | CWE-532 (CWE-798) | `app/config.py:49-67` | `repr(Settings)` выводил значения полей → утечка `bot_token` в логи/traceback | маскировать `bot_token` | **closed**: `__repr__`/`__str__` выводят `bot_token='***'`; тесты `test_SEC_08_settings_repr_and_str_hide_bot_token`, `test_SEC_08_config_errors_do_not_leak_bot_token` зелёные |
| F-05 | low | CWE-200 | `docs/spec/api.md` §15 | API `BotHarness`/`tests/html_check.check_html` не зафиксированы контрактом | зафиксировать в api.md | **open → business-analyst** (частично: §15 упоминает `BotHarness`; сигнатуры `send`/`sent` и `check_html -> list[str]` в api.md не прописаны; реализация соответствует threat-model §5.8–5.9, тесты зелёные) |
| F-06 | low | CWE-312 | `.env.example:5-8` | креденшелы `jobs:jobs` в примере | предупреждение о смене пароля при деплое | **closed**: devops добавил SECURITY-комментарий (генерация пароля, env/secret store, ссылка на F-06) |
| F-07 | info | — | `tests/security/probe.md` | случайный файл-заглушка | удалить | fixed |
| F-08 | info | — | репозиторий | grep-сканы секретов чистые; `.env` в `.gitignore` | сторожевые тесты SEC-08 остаются | fixed/pass (повторный скан — чисто) |
| F-09 | medium | CWE-79 (CWE-116) | `app/bot/core.py:382-397` (`_display`), `app/bot/core.py:168-170` (`_admin_preset_list`) | HTML-инъекция в render-путях диалога: `stop_words` (произвольный пользовательский текст), `presets`/`work_format` (строки из JSONB), `name_ru` (ввод админа) выводятся в Telegram HTML **без `esc`** — нарушение threat-model §5.1/SEC-05. Репродукция: `/settings stop` → `</b><a href="http://evil.example/">CLICK ME` → `/settings` отвечает сырой разметкой. Влияние: подмена/порча ответов бота (в т.ч. `<a href>`-фишинг в отражённом тексте), Telegram 400 на мусорной разметке = недоступность ответа; при компрометации JSONB (TB-4) — инъекция в чужие диалоги | экранировать через `esc()` каждое профильное поле в `_display` и `name_ru` в `_admin_preset_list` | **fixed (27.10, software-engineer)**: `esc()` каждого профильного поля в `_display` и `name_ru` в `_admin_preset_list`; подтверждено `test_SEC_05_dialog_render_paths_escape_profile_strings` (переведён из xfail в обычный, зелёный; негативный контроль — красный при снятии экранирования) + `U-ESC-01/02`; риск R53 заведён, covered |
| F-10 | medium | CWE-770 (CWE-400) | `app/bot/core.py:328-337` (`_apply_stop`) | стоп-слова не ограничены ни по числу, ни по длине слова: флуд `/settings stop` + слово (~30 действий/мин после антиспама) растит JSONB профиля без лимита → раздувание БД, рост стоимости `matches()` (стоп-слова × кандидаты) на каждом дайджесте | лимиты: ≤50 стоп-слов, ≤100 символов на слово (отклонять/обрезать); тесты SEC-09/SEC-10 | **fixed (27.10, software-engineer)**: лимиты `_STOP_WORD_LIMIT=100` символов/слово и `_STOP_WORDS_LIMIT=50` в `_apply_stop` (превышение — вежливый отказ); подтверждено `test_SEC_09_stop_words_are_bounded_in_count_and_length` (переведён из xfail в обычный, зелёный; негативный контроль — красный при снятии лимитов) + `U-LIM-01/02`, клампинг company/description в нормализации `U-COL-07/08` (QA §6.10), корневая причина — профиль всегда сохраняется как JSONB (`U-BOT-02`); риск R54 заведён, covered |
| F-11 | low | CWE-502 (CWE-400) | `app/bot/core.py:435-452` (`_parse_preset_command`) | `json.loads` на админском JSON ловит только `ValueError`; глубоко вложенный JSON (`{"a": ` + `[`×4000) даёт `RecursionError`, который проходит мимо обработчиков → краш вызова обработчика (вход только админский, сообщение ≤4096 — влияние ограничено) | ловить `(ValueError, RecursionError)` (или ограничить глубину) и отвечать «Формат: …» | **fixed (27.10, software-engineer)**: `except (ValueError, RecursionError)` в `_parse_preset_command` — глубоко вложенный JSON даёт отказ `(None, "", None)`, не краш; подтверждено `test_SEC_13_deeply_nested_preset_json_is_contained` (переведён из xfail в обычный, зелёный; негативный контроль — красный с RecursionError при `except ValueError`) + `U-JSON-01` |
| F-12 | low | CWE-532 | `app/config.py:49-67` (`__repr__`) | `repr/str(settings)` маскирует `bot_token`, но показывает `database_url`/`test_database_url` целиком — пароль БД из DSN утекает в логи/traceback (SEC-08 называет DSN активом) | маскировать пароль userinfo в DSN (`postgresql+asyncpg://jobs:***@…`) | **fixed (27.10, software-engineer)**: `mask_dsn()` маскирует пароль userinfo в `__repr__`/`__str__` настроек (`postgresql+asyncpg://jobs:***@…`, само значение DSN не меняется); подтверждено `test_SEC_08_settings_repr_hides_database_password` (переведён из xfail в обычный, зелёный; негативный контроль — красный с дефолтным pydantic-repr) + `U-CFG-02` |
| F-13 | medium | CWE-89 (покрытие детектирования) | `tests/security/support.py` (детектор SEC-06/P-SEC-04) | слепая зона детектора SQL-инъекций: сканировались только позиционные аргументы `execute()`, а `Repo` передаёт выражения именованным `statement=` → детектор не видел ни одного запроса (проверка была вакуумной). При включении kwargs возникали ложные срабатывания на односимвольных payload'ах («O» в `INSERT INTO`, «_» в `%(user_id)s`) | нормализованный детектор (см. §4.2) | **fixed (27.10, шаг 2)**: скан args+kwargs, сравнение payload-прогона с baseline-прогном (уникальный маркер), отрицательный контроль на намеренно уязвимом репозитории; регресс-тест на односимвольные payload'ы |

### Открытые находки (итог к QA gate, 27.10)

| ID | Severity | CWE | Файл:строка | Описание | Владелец |
|---|---|---|---|---|---|
| F-05 | low | CWE-200 | `docs/spec/api.md` §15 | сигнатуры `BotHarness.send/sent` и `check_html(text) -> list[str]` не зафиксированы контрактом | business-analyst |

Открытых **high/critical нет**: F-01..F-04, F-06..F-13 — closed/fixed (см. §2),
F-09..F-12 закрыты фиксами software-engineer 27.10 с постоянными тестами-регрессиями
и подтверждённым негативным контролем. Единственная открытая находка F-05 — low,
документационная, QA gate не блокирует (на усмотрение владельца).

## 3. Ручной review production-кода (по чек-листу шага 1)

| # | Проверка | Результат |
|---|---|---|
| 1 | SQL: только ORM/bind-параметры | ✅ `app/storage/repo.py` — все запросы `select/insert/delete` с bind-параметрами, `session.execute(statement=…)`; f-string/%/.format в SQL нет (grep §1) |
| 2 | Весь внешний/пользовательский текст через `esc`/`esc_attr`; URL после `canonicalize_url` | ⚠️ дайджест — ✅ (`app/services/digest.py:57-63`: title/company/source/salary — `esc`, url — `canonicalize_url` без `"`, `'`, `<`, `>`, пробелов/управляющих; алерты — константы); **разрыв — F-09** (`_display`, `_admin_preset_list`) |
| 3 | Админ-хендлеры: строгий `user.id == settings.admin_id` (int) | ✅ `app/bot/core.py:400-406` (`isinstance(user_id, int)`, без `bool`, без `str()`/`in`/`startswith`); молчаливый игнор не-админу (`core.py:140-141`); `admin_id` — строгий int валидатор (`app/config.py:36-42`) |
| 4 | Никаких `pickle`/`eval`/`exec`/`yaml.load`/`shell=True`; JSONB — json-структуры | ✅ grep 0 совпадений; `profile_from_jsonb`/`load_filter` — только `ValueError` (`app/domain/profile.py:110-122`, `app/filters/rules.py:63-83`); **мелкий разрыв — F-11** |
| 5 | Секреты не в `print`/`logging`/`str(exc)`/алерты | ✅ (grep LOG_SINK 0); `repr` маскирует токен (F-04 закрыт); **DSN-пароль в repr — F-12** |
| 6 | Коллекторы: HTTP только к константным URL источников (SSRF) | ✅ `app/collectors/hh.py:17`, `app/collectors/habr.py:15` — константы; ссылки вакансий не скачиваются; `canonicalize_url` отсекает не-http(s) схемы (`app/collectors/base.py:80-98`) |
| 7 | Лимиты: `digest_size` 1..50, обрезка title ≤200, таймауты HTTP, антиспам 30/мин | ✅ частично (`app/bot/core.py:308-316`, `app/services/select.py:45-50`, `app/services/digest.py:33-41`, `app/services/http.py:23`, `app/bot/antispam.py`); **разрыв — F-10** (стоп-слова) |

Дополнительно: `parse_hhmm`/`parse_tz` строгие и отклоняют пути (`app/domain/profile.py:57-88`;
SEC-14 тесты зелёные); feedback-`n` — строго `[1-9][0-9]{0,17}` (`core.py:28-29,121-135`);
slug пресета — `[a-z0-9][a-z0-9_-]{0,62}` (`core.py:32`); `action` feedback — литералы
`like|dislike|bookmark` (regex `core.py:28`); APScheduler — только `MemoryJobStore`;
миграция `0001_initial.py` — схема из моделей + константный сид пресетов, без
интерполяции в SQL. Замечание (не находка): docstring `Repo` открыто фиксирует
`statement=` как «канал, который сканируют security-тесты» — после F-13 детектор
сканирует и kwargs, «обход» больше не работает.

## 4. Тесты (tests/security/)

### 4.1 Состав (94 теста — все passed)

| Файл | Угрозы / свойства |
|---|---|
| `test_injection.py` | SEC-01, SEC-02, SEC-05 (в т.ч. регресс F-09 — render-пути диалога), P-SEC-01, P-SEC-05 |
| `test_admin_authz.py` | SEC-07 (id-type-confusion int/str, подстроковые id, positive control) |
| `test_secrets.py` | SEC-08 (3 сторожевых скана + поведение `config`, в т.ч. маскировка DSN-пароля — F-12) |
| `test_input_validation.py` | SEC-03, SEC-04, SEC-06 (+ отрицательный контроль детектора и регресс F-13), SEC-09 (в т.ч. лимиты стоп-слов — F-10), SEC-10, SEC-12, SEC-13 (в т.ч. глубоко вложенный JSON — F-11), SEC-14, P-SEC-02..P-SEC-04 |
| `support.py` | ленивый импорт, payload'ы, oracle тегов, RecordingSessionFactory (SQL, args+kwargs), нормализованный детектор `sql_leaks_for`, `MemoryRepo`/`memory_bot` |

Контрпримеры F-09..F-12 после фиксов software-engineer (27.10) переведены из
`xfail(strict=True)` в обычные тесты без ослабления assert'ов:
`test_SEC_05_dialog_render_paths_escape_profile_strings`,
`test_SEC_09_stop_words_are_bounded_in_count_and_length`,
`test_SEC_13_deeply_nested_preset_json_is_contained`,
`test_SEC_08_settings_repr_hides_database_password`.
Негативный контроль подтверждён: каждый тест остаётся красным, если дефект вернуть
monkeypatch'ем в памяти (f09 — `esc`→identity, f10 — лимиты→`10**9`, f11 —
`except ValueError` без `RecursionError`, f12 — дефолтный pydantic `__repr__`;
production-код при этом не меняется) — см. §1. Assert'ы и payload'ы не ослаблялись,
из тестов удалён только ставший ненужным `import pytest` (ruff F401).

### 4.2 Нормализация SQL-детектора (F-13)

Было: `payload in str(statement)` по позиционным аргументам `execute()` — (а) слепая
зона для `statement=` kwargs (Repo), (б) ложные срабатывания на односимвольных
payload'ах («O» в `INSERT INTO`, «_» в bind-плейсхолдерах).

Стало (`support.sql_leaks_for`): payload-прогон сравнивается с baseline-прогном
того же кода (уникальный маркер `BASELINE_MARKER`); утечка = текст запроса или их
число зависит от значения. Сканируются args И kwargs. Свойство: «SQL-текст не
зависит от недоверенных значений» — точнее подстрокового поиска и без ложных
срабатываний на скелете SQL.

Покрытие сохранено/усилено:
- `test_SEC_06_detector_catches_interpolated_sql[fstring|concat|format|percent]` —
  отрицательный контроль: намеренно уязвимый репозиторий (интерполяция, включая
  передачу через `statement=` kwargs) обязан дать утечки, включая `'; DROP TABLE …`;
- `test_SEC_06_detector_ignores_sql_skeleton_coincidences` — регресс F-13:
  «O», «_», `%(user_id)s`, `INTO`, `VALUES` и т.п. на реальном `Repo` — не утечка;
- `test_SEC_06_filter_values_never_reach_sql_text` + `P-SEC-04` (hypothesis,
  `derandomize=True`) — реальный `Repo` чист для всех SQL_PAYLOADS и любого текста.

### 4.3 Флуктуация при параллельных прогонах (не дефект кода)

При параллельном прогоне полного suite (qa-engineer) и `tests/security` на общем
`jobs_test` BotHarness-тесты флуктуируют: `UndefinedTableError: relation "presets"
does not exist` — гонка `drop_all/create_all` двух прогонов (BotHarness
пересоздаёт схему при каждом входе). Для QA gate — прогон suite строго
последовательно; долгосрочно (вне security-скоупа) — отдельная `_test`-БД на роль
или общий lock. Секьюрити-детерминированность от этого не зависит: флуктуируют
только БД-тесты, все сканы/детекторы — без БД.

## 5. Открытые вопросы к другим ролям

1. ~~**software-engineer** (F-09..F-12)~~ — **закрыто 27.10**: фиксы внесены
   (`esc()` в render-путях диалога, лимиты стоп-слов 50×100, `RecursionError`
   в `_parse_preset_command`, `mask_dsn()` в `Settings.__repr__`), контрпримеры
   переведены в обычные зелёные тесты (§4.1).
2. **business-analyst** (F-05 low, единственная открытая находка): прописать в
   `docs/spec/api.md` сигнатуры `BotHarness.send/sent` и
   `tests/html_check.check_html(text) -> list[str]` (threat-model §5.8–5.9).
3. ~~**product-manager / qa-engineer** (риски под F-09/F-10)~~ — **закрыто 27.10**:
   R53 (HTML-инъекция в render-путях диалога, F-09) и R54 (безлимитные списковые
   вводы/JSONB-рост, F-10) заведены в `docs/risk-register.md` (security-engineer,
   permission), статусы `covered`; next ID: R55. Статусы R7/R25/R38/R43..R48/
   R50..R52 обновлены на `covered` по существующим митигирующим тестам; R49 остаётся
   `open` (SEC-11 — скан, не автотест; постоянный CI dependency-scan — к devops-sre).
4. **qa-engineer**: учитывать флуктуацию §4.3 при параллельных прогонах на общем
   `jobs_test`; QA gate — при последовательном прогоне.

## 6. Вердикт готовности к QA gate

**Можно проходить QA gate**: открытых high/critical находок нет (итоговая таблица
открытых находок — §2, только F-05 low/доки). F-01/F-02/F-03 — зависимости закрыты
пинами и чистым `pip-audit`; F-04/F-06 закрыты кодом/конфигом; F-13 (слепая зона
детектора) закрыт ранее; F-09..F-12 закрыты фиксами software-engineer 27.10 —
контрпримеры стали постоянными зелёными тестами с подтверждённым негативным
контролем (§4.1). `pytest tests/security -q` → `94 passed`, `ruff check/format` —
чисто. Риски R53/R54 заведены и `covered`; открытых security-рисков high/critical
в реестре нет (R49 medium — зависимостный скан как процесс, не автотест, пины
актуальны). Остаток на QA gate: полный последовательный прогон suite (fluctuation
§4.3 — при параллельных прогонах на общем `jobs_test`) и решение по F-05 (low).

**Пометка I-2 (27.10):** вердикт выше относится к скоупу I-1. С добавлением
callback-канала (§7) `pytest tests/security -q` даёт `32 failed, 94 passed` —
красные НОВЫЕ тесты SEC-15/P-SEC-06 (production-код I-2 ещё не реализован,
`NotImplementedYet`), 94 теста I-1 остаются зелёными. Зелёный security-suite
и вердикт для I-2 выносится на QA gate I-2 после фиксов software-engineer.

## 7. Дополнение I-2 (27.10.2026): callback-канал инлайн-диалога — SEC-15

Скоуп: RBT (угроза SEC-15, граница TB-8 — `callback_query` как отдельный
недоверенный канал ввода), красные security-тесты callback-канала
(`tests/security/test_callbacks.py`), пин тестового входа `BotHarness.tap`/`answers`
(threat-model §5.8), риски R60..R62 (`docs/risk-register.md`). Production-код
callback-обработчика (I-2, software-engineer) на момент шага **не реализован** —
все новые тесты красные по паттерну `NotImplementedYet`, это ожидаемое состояние
перед TDD (red). Контракт: `docs/spec/api.md` §15.1, `docs/product/brief.md` §6.1,
сценарии S79..S88 (`tests/features/dialog_callbacks.feature`).

### 7.1 Выполненные команды (фактический вывод)

| Команда | Результат |
|---|---|
| `.venv/bin/python -m pytest tests/security -q` | `32 failed, 94 passed in 10.74s` — красный, как и ожидается до реализации I-2: все 32 падения — НОВЫЕ тесты `test_callbacks.py` (SEC-15 ×31 + P-SEC-06), причина единая — `support.NotImplementedYet: BotHarness.tap(data, user=None)/answers() ещё не реализованы (threat-model §5.8)`; все 94 старых теста зелёные |
| `.venv/bin/python -m pytest tests/security -q --ignore=tests/security/test_callbacks.py` | `94 passed in 4.89s` — старый security-контур I-1 не сломан |
| `ruff check tests/security` | `All checks passed!` |
| `ruff format --check tests/security` | `6 files already formatted` |
| grep `InlineKeyboard\|callback_data\|callback_query` по `app/` | 0 совпадений — callback-код ещё не появился (I-2 в работе); свидетельство см. §7.3 |
| grep `InlineKeyboard\|callback_data\|callback_query\|KeyboardButton` по `app/services/ app/storage/ app/collectors/` (модули дайджеста/рассылки/сбора) | 0 совпадений — **в модулях дайджеста кнопок нет** (Q1 в силе) |

### 7.2 SEC-15: что покрыто тестами (`tests/security/test_callbacks.py`)

Угроза SEC-15 (threat-model §3): подделка/флуд callback'ами — чужой user_id,
чужое/устаревшее состояние диалога, перебор значений, oversized data (≥64 байт),
инъекция в `value`, повторные тапы. Митигация (требования threat-model §3/§5.8):
грамматика `dlg:<step>:<value>` ≤64 байт + белые списки step/value, владелец
действия — только `callback_query.from`, ровно один немедленный
`answer_callback_query` на каждый callback (включая отказ и флуд), значения в HTML —
только через `esc`, callback-действия в антиспаме.

| Тест | Закрываемый аспект SEC-15 (риск) |
|---|---|
| `test_SEC_15_stale_callback_refused_and_state_unchanged` | кнопка не текущего шага → тост общего отказа, настройки/шаг не меняются; позитивный контроль — кнопка текущего шага применяется (R60) |
| `test_SEC_15_foreign_user_cannot_tap_into_another_dialog` | tap кнопкой чужого диалога / посторонним пользователем → отказ; состояние и настройки жертвы, атакующего и постороннего не меняются (R60, CWE-639) |
| `test_SEC_15_garbage_and_injection_callback_get_generic_refusal[26 payload'ов]` | мусор/HTML/SQL-инъекция в `value`, значения вне белого списка (`dlg:size:51`, `dlg:lang:de`, `dlg:preset:nonexistent`, `dlg:tz:page-0`), oversized ≥64 байт (в т.ч. 1 КБ), NUL/RTL/полноширинные → ровно один тост общего отказа, без крашей, без отражения payload в ответах, состояние не меняется (R61) |
| `test_SEC_15_every_callback_gets_exactly_one_answer` | каждый callback (валидный/устаревший/мусорный/oversized/пустой) → ровно один `answer_callback_query` — «часиков» нет ни на одном пути (R62, S79) |
| `test_SEC_15_callback_flood_does_not_bypass_antispam` | флуд 40 callback'ами упирается в антиспам (30 действий/мин → тихий мьют, AC-16), контрольный пользователь не мьютится; каждый tap флуда всё равно подтверждён ровно один раз (R62) |
| `test_SEC_15_malicious_preset_name_is_escaped_in_dialog` | вредоносное имя пресета (админ-ввод, S85) в диалоге: HTML-инъекция невозможна — нет сырой разметки в ответах, имя выводится только через `esc()`; метки кнопок — plain text (R61, пересечение SEC-05/R53) |
| `test_P_SEC_06_...` (hypothesis, `derandomize=True`, 200 примеров) | произвольный `callback_data` (unicode/NUL/бинарный мусор) → либо валидный шаг с белым списком (независимый oracle brief §6.1 в тесте), либо строго тост общего отказа; никогда — исключение/краш/инъекция; ровно один answer на callback (R60..R62) |

Пин тестового входа (threat-model §5.8): `BotHarness.tap(data, user=None)` +
`BotHarness.answers()` (ровно один элемент на callback); тесты ходят в бота только
через этот API (`support.BotSession.tap` → `CallbackOutcome(replies, answers)`),
низкоуровневый API `BotCore` не закреплён — за харнесом может стоять любой метод.
P-SEC-06 использует один `BotHarness`/одну схему на весь прогон (`support.CallbackFuzzer`)
и свежего пользователя на пример — антиспам/состояние диалога не влияют на свойство.

### 7.3 Свидетельство Q1 обновлено (снято устаревшее «нет InlineKeyboard в app»)

Свидетельство I-1 «в `app/` нет `InlineKeyboard`/`callback_data`/`callback_query`»
**снято как устаревшее**: с I-2 диалог использует инлайн-кнопки `dlg:<step>:<value>`
(api.md §15.1, решения §8.8). Новое свидетельство Q1 (в дайджесте кнопок нет):
grep `InlineKeyboard|callback_data|callback_query|KeyboardButton` **по модулям
дайджеста/рассылки/сбора** (`app/services/`, `app/storage/`, `app/collectors/`) →
0 совпадений (§7.1). Допустимая зона callback-кода — только диалог настроек
(`app/main.py`/хендлеры), форма `dlg:<step>:<value>`, ≤64 байт, белый список
значений. Устаревшие формулировки остаются в `docs/qa/verdict.md` §1,
`docs/qa/acceptance-map.md` §6.13 и `docs/spec/decisions.md` §8.8 — файлы чужие
(qa-engineer/business-analyst), обновить по образцу выше; текущая формулировка
зафиксирована threat-model (§2 TB-8, обновление I-2) и этим отчётом.

### 7.4 Открытые вопросы к другим ролям (I-2)

1. **software-engineer**: реализовать callback-обработчик по api.md §15.1 и
   `BotHarness.tap(data, user=None)` / `BotHarness.answers()` (threat-model §5.8) —
   без этого security-suite красный (32 теста). Требования SEC-15 обязательны:
   белые списки step/value, владелец — `callback_query.from`, ровно один
   немедленный answer на каждый callback (включая отказ/флуд), `esc` всех значений
   в HTML, учёт callback-действий в антиспаме.
2. **business-analyst** (дополнение к F-05 low): зафиксировать в `api.md` §15
   сигнатуры `tap`/`answers` (как ранее `send`/`sent` и `check_html`).
3. **qa-engineer**: обновить свидетельства Q1 (§7.3) в `docs/qa/verdict.md` и
   `docs/qa/acceptance-map.md`; статусы R60..R62 → `covered` после зелёного прогона;
   учесть флуктуацию §4.3 при параллельных прогонах (BotHarness-тесты I-2 — те же).

## 8. Финальный security review I-2 (28.10.2026): callback-канал реализован — SEC-15 covered

Скоуп: review production-кода I-2 (`app/bot/dialog.py`, `app/bot/core.py`
(`handle_callback`), `app/bot/handlers.py` (`callback_query`), `app/i18n.py`
(новые ключи), `app/storage/models.py` + `alembic/versions/0002_widen_preset_slug.py`)
по TB-8/SEC-15 и threat-model §5, повторные сканы, верификация свидетельств I-1
(не ослаблены ли гарантии). Код и чужие тесты не менялись.

### 8.1 Выполненные команды (фактический вывод)

| Команда | Результат |
|---|---|
| `.venv/bin/python -m pytest tests/security -q` | `126 passed in 6.81s` — зелёный весь security-suite (94 I-1 + 32 I-2: SEC-15 ×31 + P-SEC-06); красные тесты §7.1 закрыты реализацией |
| `.venv/bin/pip-audit -r requirements.txt` | `No known vulnerabilities found` (exit 0) |
| grep секретов (`bot_token=…`, `api_key=…`, `password=…`, DSN с паролем) по репо без `.venv`/`tests` | 0 реальных совпадений: только плейсхолдер `.env.example:2` `BOT_TOKEN=123456789:replace-with-real-token` (маркер `replace-with`); `git ls-files \| grep '^\.env$'` → `.env` не отслеживается (`.gitignore:153`) |
| grep запрещённого (`eval\|exec\|pickle\|marshal\|yaml.load\|shell=True\|os.system\|subprocess`) по `app/` | 0 реальных совпадений (сработали только docstring `app/services/scheduler.py:3` — «только MemoryJobStore (F-01…)» и его `.pyc`) |
| grep SQL-интерполяции (`text(f"…")`/`execute(f"…")`/`.format()`/`% …s`) по `app/` | 0 реальных совпадений: `normalize_text(f"…")` в `app/filters/rules.py:71,80,89` и `app/storage/repo.py:341` — не SQL; в `app/` вообще нет `text()`-запросов, все `session.execute(statement=…)` — ORM Core с bind-параметрами |
| grep `InlineKeyboard\|callback_data\|callback_query\|KeyboardButton` по `app/services/ app/storage/ app/collectors/` | 0 совпадений — **Q1 в силе: в модулях дайджеста/рассылки/сбора кнопок нет** (свидетельство §7.3 подтверждено после реализации I-2) |
| `ruff check tests/security` / `ruff format --check tests/security` | `All checks passed!` / `6 files already formatted` |

### 8.2 Статус SEC-15 и покрытие тестами

**SEC-15 — `covered`** (реализация + 32 зелёных теста `tests/security/test_callbacks.py`,
состав — §7.2; тесты не переписывались и не ослаблялись). По пунктам ревью:

| Проверка (TB-8/SEC-15) | Вердикт | Свидетельство |
|---|---|---|
| Владелец действия = `callback_query.from`; состояние per-user | ✅ подтверждено | `app/bot/handlers.py:53-62` (`callback.from_user.id` — единственный источник user_id); `DialogStore` — dict по user_id (`dialog.py:285-320`), кросс-пользовательских ссылок нет; тесты `…stale_callback…`, `…foreign_user_cannot_tap…` |
| Мусор/oversized/инъекции в `callback_data` | ✅ подтверждено | тотальный `parse_callback` (`None` на мусоре, `ValueError` невозможен; `CALLBACK_RE.fullmatch` + грамматика `[a-z0-9-]{1,32}` отсекает HTML/SQL/NUL/RTL/полноширинные и ≥64 байт); 26 payload'ов + P-SEC-06 (hypothesis, `derandomize=True`, 200 примеров) |
| Prompt-injection через имя пресета (админ-ввод) | ✅ подтверждено | `core.py:330-338` (`_preset_reply`): имена в HTML — только `esc(name)`; метки кнопок — plain text (`handlers.py:26-34`, `InlineKeyboardButton(text=…)` без parse_mode); тосты — константы i18n; тест `…malicious_preset_name_is_escaped…` |
| Ровно один `answer_callback_query` на КАЖДОМ пути (отказ, флуд) | ✅ подтверждено | единственный вызов sink — `core.py:109` (`_emit_answer`) до БД/антиспама (`core.py:110-114`); до него нет исключений: `parse_callback` тотален, ключи `dialog.outdated`/`dialog.preset_empty`/`prompt.preset` есть в обоих словарях (`i18n.py:48,58,59,117,128,129`), `lang` ∈ {ru,en} (валидация `profile_from_jsonb` `profile.py:126-128` + белые списки, `ValueError`→default `core.py:555-559`); тест `…every_callback_gets_exactly_one_answer` + флуд-тест |
| Белый список без обхода через `preset_code` (коллизии/подбор) | ✅ подтверждено (hardening — F-17) | обход невозможен: `_callback_allowed` требует `value in state.codes`, а `codes` строится только из списка пресетов БД (`core.py:329,359-378`); подбор кода не даёт выбрать несуществующий/чужой пресет (коды детерминированы, состояние per-user). Коллизии практически невыполнимы (sha256[:15] = 60 бит; birthday ≈2^30 при ~50 пресетах; канонический slug вида `h`+15 hex, совпадающий с хэш-кодом другого slug, — гринд ≈2^60) — см. F-17 |
| Пагинация (`page` вне диапазона) | ✅ подтверждено | `core.py:371-377`: `page-<k>` → `isdecimal` + `1..tz_page_count()`; `tz_keyboard` с out-of-range бросает `ValueError`, но недостижим — `state.page` только из валидированного значения (`core.py:445-446`, сброс в 1 при смене шага); `dlg:tz:page-0`/`page-99` в payload'ах — общий отказ |
| Состояние in-memory: утечка между пользователями | ✅ нет утечки (рост — F-16) | ключи — user_id из Telegram; `open` перезаписывает состояние пользователя, `close` удаляет; тесты с тремя пользователями (victim/attacker/stranger) зелёные |
| Миграция `0002_widen_preset_slug` — безопасность ALTER | ✅ данных не теряет | только расширение `VARCHAR(64→255)` — в PostgreSQL безопасно (без rewrite с 9.2, без truncation); `downgrade` сужает и на slug >64 падает `value too long` с откатом транзакции — тихого обрезания нет; свежие БД получают `String(255)` из моделей (`models.py:49`) — ALTER no-op; согласовано с `_SLUG_RE` (`core.py:44`, ≤255) |
| Антиспам-обход callback'ами | ✅ подтверждено | `allow()` вызывается на каждом callback (`core.py:110`), общий счётчик с текстовыми сообщениями (30/мин → мьют 10 мин); флуд-тест зелёный. Принятый трейд-офф (S79): замьюченный продолжает получать `answer` (без ответов/БД) — исходящий вызов на входящий callback, ограничен скоростью апдейтов Telegram (info, не находка) |
| I-1 не ослаблены | ✅ | Q1 — grep 0 совпадений (§8.1); `esc` тотален и в новых путях (`_preset_reply`/`_display`/`_format_label` — `core.py:331-338,575-591,611-623`); SQL — только bind-параметры (grep §8.1, детектор `sql_leaks_for` зелёный); лимиты F-10 сохранены (`_PRESETS_LIMIT=50` на мультивыбор, `core.py:102-108`) |

### 8.3 Новые находки (финальный review I-2)

| ID | Severity | CWE | Файл:строка | Описание | Рекомендация | Status |
|---|---|---|---|---|---|---|
| F-14 | low | CWE-20 (CWE-770) | `app/bot/core.py:218-223` (`_admin_preset_add`), `app/storage/repo.py:103-114`, `app/storage/models.py:50` | имя пресета (`name` = «всё до `{`») не ограничено по длине, а `name_ru` — `VARCHAR(128)`: имя >128 символов даёт `asyncpg.DataError: value too long` — необработанное исключение, админ не получает ответа (хендлер не ловит). Вход только админский (SEC-07) — влияние ограничено. Репродукция: `/admin_preset_add x ` + `"A"*200` + ` {}` | ограничить имя ≤128 символов с вежливым отказом (по образцу лимитов F-10) | **open → software-engineer** |
| F-15 | medium (L2×I2=4) | CWE-200 (CWE-754) | `app/bot/handlers.py:53-68` (`on_callback`), `app/bot/handlers.py:41-51` (`on_message`) | ответы диалога идут в чат нажатого сообщения без проверки `chat.type == "private"`: кнопка в группе (или у пересланного сообщения) публикует настройки нажавшего (пресеты/зарплата/таймзона/стоп-слова в сводке) в групповой чат — раскрытие персональных данных посторонним (обман «нажми кнопку»); `edit_text` по чужому/пересланному/старому сообщению — необработанный `TelegramBadRequest`, обрывает остальные ответы. Действие всегда применяется к самому нажавшему (`from_user`) — подмены чужих настроек нет. Репродукция: добавить бота в группу → `/start` → нажать кнопку → сводка в группу | ограничить диалог личными чатами (или отвечать в `from_user.id`); ловить `TelegramBadRequest` на `edit_text`; решить product-вопрос «личка-only» | **open → software-engineer** (рекомендуется до QA gate; формально gate блокируют только high/critical) |
| F-16 | low | CWE-770 | `app/bot/dialog.py:285-320` (`DialogStore._langs`), `app/bot/antispam.py:30-31` | in-memory словари `_langs`/`_stamps`/`_muted_until` растут по числу user_id без вытеснения (`close` чистит только `_states`) — медленный рост памяти при большом числе пользователей; рестарт чистит (R33 принято), но рантайм-чистки нет | вытеснять неактивные записи (TTL/размер) в `DialogStore`/`Antispam` | **open → software-engineer** (low, не блокирует) |
| F-17 | low | CWE-334 (CWE-328) | `app/bot/dialog.py:140-150` (`preset_code`), `app/bot/core.py:329` (`state.codes`) | `state.codes = {preset_code(slug): slug}` молча перезаписывает коллизию двух кодов → тап переключит «не тот» пресет (только собственная подписка пользователя; обход белого списка невозможен). Практически невыполнимо (60 бит, §8.2) — defensive hardening: детект коллизии при построении map (alert/fail-closed) и/или код `h`+31 hex (124 бита) в пределах грамматики 32 символов | см. описание | **open → software-engineer** (hardening, не блокирует) |

Тестов под F-14..F-17 сейчас нет намеренно: дефекты зафиксированы ревью, production
не правится security-engineer'ом; после фикса software-engineer'ом контрпримеры
заводятся как постоянные тесты `tests/security/` (TDD red→green; паттерн F-09..F-12).
*(обновлено §9: фиксы сделаны, постоянные тесты добавлены)*

### 8.4 Вердикт готовности к QA gate (I-2)

**Можно проходить QA gate I-2.** SEC-15 — `covered`, security-suite зелёный
(`126 passed`), открытых **high/critical находок нет**: F-15 — medium (рекомендован
фикс до gate, но по правилам dev-cycles gate блокируют только high/critical),
F-14/F-16/F-17 — low. Сканы чистые: `pip-audit` — 0 уязвимостей, секреты — только
плейсхолдеры, запрещённые конструкции и SQL-интерполяция — 0 реальных совпадений.
Свидетельства I-1 (Q1, esc, параметризация SQL) подтверждены после реализации I-2.
Остаток на gate: последовательный прогон полного suite (флуктуация §4.3), решение
по F-05 (low, доки) и распределение F-14..F-17 (владелец кода — software-engineer;
риски под F-15/F-16 в `docs/risk-register.md` заводят PM/QA, next ID: R63).

## 9. Верификация исправлений I-2-fix (28.10.2026): F-14..F-17 fixed — контрпримеры закреплены тестами

Скоуп: software-engineer исправил находки §8.3 (F-15 — диалог только в личном
чате, fail-closed на неподтверждённый чат, `TelegramBadRequest` обрабатывается;
F-14 — лимиты имени/slug пресета 128/255 с вежливым отказом до БД; F-16 — крыши
памяти `Antispam`/`DialogStore`; F-17 — расширение кода при коллизии,
неразрешимая → `ValueError`). Security-engineer: постоянные
security-тесты-контрпримеры (угол — атакующий вход, без дублей юнит-тестов
U-SEC-01..U-SEC-07), red-демонстрации чувствительности, обновление пина
threat-model §5.8 (chat-граница). Production-код и чужие тесты не менялись.

### 9.1 Выполненные команды (фактический вывод)

| Команда | Результат |
|---|---|
| `.venv/bin/python -m pytest tests/security -q` | `157 passed in 9.28s` — весь security-suite зелёный (126 прежних + 31 новый: F-15 ×4, F-14 ×19, F-16 ×3, F-17 ×5) |
| `ruff check tests/security` | `All checks passed!` |
| `ruff format --check tests/security` | `9 files already formatted` |
| red-демонстрация (scratch-скрипт в `sys.path` с `tests/security`; дофиксовое поведение возвращается monkeypatch'ем в памяти, production-код на диске не меняется) | **F-15** (`_is_private`≡True — как до фикса): tap в `supergroup` опубликовал шаг диалога в группу (`['Язык сохранён.', 'Выберите роли…']`) — постоянный тест `…never_publishes_settings` упал бы; **F-14** (`_preset_size_problem`≡None): имя 200 символов дошло до БД (`✅ Пресет evlp добавлен`, 1 SQL-запрос) — постоянный тест «БД не вызывается» упал бы (на реальном PG — `asyncpg.DataError`); **F-17**: коллизия кодов реальна (`preset_code(long) == preset_code("h"+sha256(long)[:15])`), наивная карта молча теряет slug (1 из 2) — это негативная контроль внутри `test_F17_crafted_slug_collision…`; **F-16**: без крыши структура растёт до 5200 > 4096 — постоянный тест упал бы |

### 9.2 Новые постоянные тесты (`tests/security/`, 31 тест)

| Тест | Находка | Закрываемый аспект (угол атакующего) |
|---|---|---|
| `test_chat_isolation.py::test_F15_group_callback_answers_silently_once_and_never_publishes_settings` | F-15 | tap из `group`/`supergroup`/`channel` (плюс все `CALLBACK_PAYLOADS`: мусор, инъекции, oversized) → ровно один молчаливый `answer`, в чат не уходит ничего (маркеры настроек жертвы), профиль не изменён; позитивная контроль — в личке маркеры видны |
| `test_chat_isolation.py::test_F15_group_chat_commands_are_ignored_without_side_effects` | F-15 | команды + HTML/SQL-инъекции + 10k-тексты из групповых типов и от админа молча игнорируются: нет публикаций, пользователь/пресеты не создаются |
| `test_chat_isolation.py::test_F15_unconfirmed_or_spoofed_chat_fails_closed` | F-15 | crafted update'ы: спуфинг `chat.type` (`"Private"`, `""`, `123`, `True`…), `chat=None`/`object()`, нет атрибута `chat`, нет `from_user` → fail-closed: ничего не публикуется, callback — не более одного молчаливого `answer`, без исключений |
| `test_chat_isolation.py::test_F15_victim_dialog_survives_group_attack_with_settings_intact` | F-15 | бомбардировка кнопками из всех групповых типов не трогает настройки/диалог жертвы (сверка сводки до/после) |
| `test_preset_hardening.py::test_F14_oversized_preset_name_refused_without_touching_database` (9 кейсов) | F-14 | имя 129/10k/полноширинные/эмодзи/NUL/мультитокен/RTL → вежливый отказ (один текст, без «✅», без внутренностей — CWE-209), **ноль SQL-запросов** |
| `test_preset_hardening.py::test_F14_invalid_preset_slug_refused_without_touching_database` (6 кейсов) | F-14 | slug 256/10k/не-ASCII/uppercase/`../../etc/passwd`/NUL → отказ, ноль SQL |
| `test_preset_hardening.py::test_F14_boundary_lengths_are_accepted_and_reach_database` (3 кейса) | F-14 | позитивная контроль: 128/255 ровно в лимите принимаются и доходят до БД (иначе детектор «БД не вызывается» вакуумен) |
| `test_preset_hardening.py::test_F14_non_admin_oversized_input_gets_no_reply_and_no_database_calls` | F-14 | не-админ с вредоносным вводом — молчаливый игнор, ноль SQL (лимиты не канал обхода SEC-07) |
| `test_preset_hardening.py::test_F17_crafted_slug_collision_is_resolved_not_overwritten` | F-17 | атакующий конструирует реальную коллизию (канонический slug `"h"+sha256(long)[:15]`) → карта `slug → код` биективна в обоих порядках, детерминирована, коды в грамматике и ≤64 байт; негативная контроль — наивная карта теряет slug |
| `test_preset_hardening.py::test_F17_unresolvable_collision_fails_closed_with_value_error` | F-17 | короткий И расширенный код заняты → `ValueError` (fail-closed), не молчаливая перезапись |
| `test_preset_hardening.py::test_F17_core_fails_closed_on_unresolvable_collision_without_wrong_toggle` | F-17 | ядро переживает коллизию без краша (без кнопок), tap по коду не переключает «не тот» пресет |
| `test_preset_hardening.py::test_F17_colliding_presets_toggle_their_own_slug_in_dialog` | F-17 | сквозной: пара коллизирующих пресетов добавлена админом → кнопки различимы, tap переключает СВОЙ slug, оба попадают в профиль |
| `test_preset_hardening.py::test_P_SEC_07_preset_codes_bijective_deterministic_in_grammar` | F-17 (PBT) | hypothesis (`derandomize`, 150 примеров): для любых slug коды биективны/детерминированы/в грамматике `[a-z0-9-]{1,32}` |
| `test_resource_limits.py::test_F16_spoofed_user_flood_keeps_memory_structures_bounded` | F-16 | флуд 5200 поддельными `user_id` (> 4096) через публичный вход: `_langs`/`_stamps`/`_muted_until` ≤ крыш, каждый callback подтверждён ровно один раз, после флуда бот жив |
| `test_resource_limits.py::test_F16_mute_map_roof_holds_under_multi_user_flood` | F-16 | флуд мьютами от 40 пользователей (крыша 16) → словари ограничены, посторонний не задет |
| `test_resource_limits.py::test_F16_dialog_state_is_replaced_on_reopen_and_removed_on_close` | F-16 | «залипание»: повторный `/start` заменяет состояние (не копит), завершённый шаг убирает состояние, диалог снова открывается |

Все тесты — постоянные контрпримеры (паттерн F-09..F-12): assert'ы не ослаблялись,
чувствительность подтверждена red-демо (§9.1) и встроенными позитивными/
негативными контролями. Дублей с юнит-тестами U-SEC-01..U-SEC-07 нет: там
заглушки ядра/прямые вызовы структур, здесь — атакующий вход (реальное ядро,
crafted update'ы, вредоносные payload'ы, чужие чаты) и SQL-уровень
(`RecordingSessionFactory` — «БД не вызывается» доказано нулём запросов).

### 9.3 Статусы находок I-2 (итоговая таблица)

| ID | Severity | CWE | Файл:строка (после фикса) | Статус |
|---|---|---|---|---|
| F-14 | low | CWE-20 (CWE-770) | `app/bot/core.py:52-53,679-690` (`_PRESET_NAME_LIMIT`/`_PRESET_SLUG_LIMIT`, `_preset_size_problem`) | **fixed (28.10, software-engineer)**: имя ≤128, slug ≤255, выход за лимит — вежливый отказ ДО БД; подтверждено 19 тестами F-14 (`test_preset_hardening.py`) |
| F-15 | medium (L2×I2=4) | CWE-200 (CWE-754) | `app/bot/handlers.py:45-51,81-114` (`_is_private`, `handle_message`, `handle_callback_query`) | **fixed (28.10, software-engineer)**: диалог только при `chat.type == "private"`, неподтверждённый чат — fail-closed; callback в группе → ровно один молчаливый `answer` без обработки; `TelegramBadRequest` ловится (`_safe_answer`/`_safe_send`/`_safe_edit`); подтверждено 4 тестами F-15 (`test_chat_isolation.py`) + U-SEC-01..U-SEC-03 |
| F-16 | low | CWE-770 | `app/bot/dialog.py:322-367` (`DialogStore`), `app/bot/antispam.py:23,63-82` | **fixed (28.10, software-engineer)**: крыши `MAX_LANGS=4096`/`MAX_USERS=4096` с вытеснением старого и `_prune` просроченного; подтверждено 3 тестами F-16 (`test_resource_limits.py`) + U-SEC-05/U-SEC-06 |
| F-17 | low | CWE-334 (CWE-328) | `app/bot/dialog.py:153-181` (`preset_codes`/`_extended_preset_code`), `app/bot/core.py:340-345` | **fixed (28.10, software-engineer)**: коллизия короткого кода → расширенный (`h`+31 hex), неразрешимая → `ValueError` (ядро — fail-closed); подтверждено 5 тестами F-17 + P-SEC-07 + U-SEC-07 |

**SEC-15 — `covered`** (статус §8.2 подтверждён после фиксов: 32 теста
`test_callbacks.py` + 4 новых F-15 на chat-границе; пин threat-model §5.8
дополнен chat-контрактом тестового входа). Публичных high/critical угроз без
митигации нет.

### 9.4 Новые остаточные наблюдения верификации (не блокируют QA gate)

| ID | Severity | CWE | Файл:строка | Описание | Рекомендация | Status |
|---|---|---|---|---|---|---|
| F-18 | low | CWE-770 | `app/bot/dialog.py:333,350` (`DialogStore._states`) | `_states` без крыши/TTL: флуд `/start` от N разных `user_id` (массовые фейк-аккаунты) копит N `DialogState` до рестарта (R33); `_langs`/антиспам закрыты крышами, `_states` — только заменой при `open` и `close`. Репродукция: 5200 × `core.handle("/start", uid)` → `len(_states) == 5200` | вытеснять неактивные состояния (TTL/крыша как у `_langs`) | **open → software-engineer** (low; контрпример станет постоянным тестом после фикса — паттерн F-09..F-12) |
| F-19 | low | CWE-20 (CWE-754) | `app/bot/core.py:222-231` (`_admin_preset_add`), `app/storage/repo.py:103-116` | имя пресета длиной ≤128 с NUL (`"\x00"`) проходит лимит F-14, но PostgreSQL TEXT не принимает `\x00` → `asyncpg.exceptions.CharacterNotInRepertoireError` (проверено на `jobs_test`) — необработанное исключение, админ не получает ответа (тот же фейл-мод, что F-14, иным входом). Репродукция: `/admin_preset_add evlp ` + `"A"*127 + "\x00"` + ` {}` | отклонять управляющие символы (кроме `\n`/`\t`) в имени с вежливым отказом (по образцу F-14) | **open → software-engineer** (low, вход админский) |

### 9.5 Открытые вопросы к другим ролям (I-2-fix)

- **software-engineer**: F-18/F-19 (low) — §9.4, воспроизводители выше; контракты
  U-SEC-01..U-SEC-07 подтверждены новыми тестами (расхождений нет).
- **PM/QA**: риски под F-15/F-16 (§8.4, next ID: R63) — заводить в риск-реестр
  по-прежнему актуально; F-18 — в той же зоне R33 (рестарт как митигация).
- **business-analyst**: F-05 остаётся (low, доки).

### 9.6 Вердикт (I-2-fix)

**Можно проходить QA gate.** F-14..F-17 — **fixed** с постоянными
security-тестами-контрпримерами (31 новый; `157 passed`, `ruff` чистый),
SEC-15 — **covered**, открытых **high/critical находок нет**. Новые остаточные
наблюдения F-18/F-19 — low (вход админский либо массовые фейк-аккаунты),
переданы software-engineer; тесты к ним намеренно не добавлены до фиксов
(процесс F-09..F-12: контрпример в ревью → фикс → постоянный тест).

---

## 10. Security review I-3 (28.10.2026): живая разметка коллекторов — недоверенный HTML (TB-1)

Автор: security-engineer. Дата: 28.10.2026. Скоуп: hotfix I-3 — коллекторы
переписаны под живую разметку источников (`CardLayout`/`parse_listing`/
`raise_if_blocked`, новые селекторы hh/habr с legacy-fallback, промо-отсечка D6,
`published_at` = момент сбора D5). Парсеры разбирают НЕДОВЕРЕННЫЙ внешний HTML
(TB-1) — ревью сосредоточено на этой границе.

### 10.1 Что ревьюил

- `app/collectors/base.py`: `CardLayout`, `parse_listing`/`parse_card`
  (`_split_anchor`, `_text`, `_salary`, `_salary_from_data_values`, `_date`),
  `raise_if_blocked` (детект challenge; на момент ревью — старый контракт
  «маркеры во всём теле, слабые — в видимом тексте» = decisions §9.4
  редакция 1, устарела; после фикса F-22 — контракт (б)-(е) решения арбитра
  28.10 = §9.4 редакция 2, §10.9),
  `canonicalize_url`/`clamp_text`.
- `app/collectors/hh.py`, `app/collectors/habr.py`: новые селекторы + fallback.
- `app/services/collect.py`: `now=`, классификация алертов на новых исключениях.
- Пути `Vacancy` → Telegram-рендер (`digest.render_card`/`_display_title`/
  `format_age`) — тотальность `esc`.
- Фикстуры `tests/data/{hh,habr}_live_list.html`, `{hh,habr}_challenge.html`;
  контракты `docs/spec/decisions.md` §9, `docs/spec/api.md` §6/§16.

### 10.2 Выполненные команды (фактический вывод)

| Команда | Результат |
|---|---|
| `.venv/bin/python -m pytest tests/security -q` | `168 passed in 9.73s` (157 прежних + 11 новых I-3; 0 failed / 0 xfail) |
| `ruff check tests/security && ruff format --check tests/security` | `All checks passed!` / `10 files already formatted` |
| `.venv/bin/pip-audit` (окружение `.venv`) | `Found 16 known vulnerabilities in 2 packages`: `pip 23.2.1` (PYSEC-2023-228/2026-1795/1796/2875/2876/196/3721, fix 23.3..26.2) и `pytest 9.0.1` (PYSEC-2026-1845, fix 9.0.3) — **только инструменты/dev-зависимости**, runtime-пакеты не затронуты |
| `.venv/bin/pip-audit -r requirements.txt` | `No known vulnerabilities found` (exit 0) — runtime-зависимости чистые |
| grep секретов (`(api[_-]?key\|secret\|token\|password\|credential)\s*[=:]…`, паттерн токенов/приватных ключей/AWS) по `app/ alembic/ tests/ Dockerfile docker-compose.yml *.ini *.toml` | 0 совпадений с реальными секретами; `docker-compose.yml:6` — `POSTGRES_PASSWORD: jobs` (известный dev-дефолт, F-06); `.env` не отслеживается git |
| grep запрещённых конструкций `eval(\|exec(\|pickle\|yaml.load\|marshal\|os.system\|subprocess\|shell=True` по `app/ alembic/` | 0 совпадений |
| grep SQL-интерполяции (`f"…SELECT/INSERT…"` у `text(`/`execute(`) | реальных совпадений нет; сработавшие строки — `normalize_text(f"…")` (`app/filters/rules.py:71,80,89`, `app/storage/repo.py:341`) — не SQL; raw SQL нет, ORM с bind-параметрами |
| негативный контроль новых тестов (3 мутации в памяти, production не менялся): `digest.esc`→identity, `canonicalize_url`→identity, `raise_if_blocked`→no-op | все 3 дают `RED (ok)` — тесты чувствительны |
| пробы недоверенного входа (скрипты в temp, локально) | см. §10.3–§10.4: воспроизводители F-20/F-21 подтверждены замерами |

### 10.3 Находки

| ID | Severity | CWE | Файл:строка | Описание | Рекомендация | Status |
|---|---|---|---|---|---|---|
| F-20 | **high** | CWE-1333 (CWE-400) | `app/collectors/base.py:40-44` (`_HIDDEN_RE`), `:217-220` (`LEGACY_*_PATTERN`); `app/collectors/hh.py:42,46`, `app/collectors/habr.py:40,44,48` (title/company `.*?`) | ReDoS: регулярные выражения разбора квадратичны на недоверенном HTML (TB-1). (1) `_HIDDEN_RE` (`<!--.*?-->` и др. с `re.DOTALL`) вызывается из `raise_if_blocked` на **каждом** ответе до разбора: тело с N незакрытыми `<!--` и без единого `-->` даёт O(n²) — 80 КБ → 5.2 с, 800 КБ → ~9 мин. (2) Карточные паттерны `.*?</a>`/`(.*?)</span>`: 5000 незакрытых `<a data-qa="serp-item__title">` в блоке карточки → 4.4 с, 20000 → 63 с. (3) `LEGACY_COMPANY_PATTERN` (`<[^>]*…`) на потоке `<` без `>`: 80000 → 34 с. Всё это **синхронный** CPU в event loop → зависание ВСЕГО бота (все хендлеры, рассылка, планировщик) без самовосстановления; триггер — одно вредоносное/антибот-тело от источника (challenge-страницы QRATOR/DDoS-Guard как раз обслуживают нас) | линейные алгоритмы вместо `.*?`+DOTALL по всему телу (или atomic/possessive-квантификация, `re`→`regex`-модуль с таймаутом), обязательный cap размера тела ответа (см. F-24), при необходимости — `html.parser`; замерить на 1.6 МБ патологическом входе | **fixed (28.10, software-engineer)**: квадратичные regex заменены линейными сканами (`_strip_comments`/`_marker_zones`/`_iter_tags`/`_extract_rule`, `app/collectors/base.py`), cap тела 5 МиБ (F-24); замеры до/после — §10.4; постоянные тесты U-COL-14 (`tests/unit/test_collectors_hardening_unit.py`) + `test_SEC_09_large_listing_parses_within_budget` |
| F-21 | medium | CWE-241 (CWE-20) | `app/collectors/base.py:378` (`_salary_from_data_values`: `int(value) for … if value.isdigit()`) | `str.isdigit()` истинно и для не-десятичных цифр: `<data value="²">₽</data> <data value="RUB">₽</data>` в карточке hh → `ValueError: invalid literal for int()…`; `<data value="` + `9`×4301 + `">…` → `ValueError: Exceeds the limit (4300 digits)`. Исключение выходит за контракт api.md §6 (P-BEN-01: только `ParseError`/`SourceBlocked`/`EmptyResult`/`SourceUnavailable`), роняет разбор **ВСЕЙ** выдачи (все карточки теряются) и классифицируется в `run_collect` как «источник недоступен» (неверная диагностика). В `app/domain/currency.py:_extract_amounts` та же задача решена корректно (Decimal + try/except) | `value.isdecimal()` (или try/except `ValueError` вокруг `int()`) по образцу `currency.py`; контрпримеры закрепить постоянными тестами после фикса | **fixed (28.10, software-engineer)**: `_safe_int` (`app/collectors/base.py:713-722`) — `isascii`/`isdecimal`/лимит 19 цифр + `except ValueError` (по образцу `currency.py`); мусорные `value` → зарплата `None`, разбор всей выдачи не падает; U-COL-15 |
| F-22 | medium | CWE-185 (CWE-670) | `app/collectors/base.py:35-39,176-193` (`raise_if_blocked`) | Классификация challenge-страниц неустойчива в обе стороны. **Ложные срабатывания** (сильные маркеры ищутся во ВСЁМ теле, включая комментарии/JSON/контент): комментарий `<!-- ddos-guard -->`, JSON-ключ `"smart-captcha"` в script, и главное — легитимный контент: компания/вакансия «Qrator» (реальный работодатель hh) → подстрока `qrator` → `SourceBlocked` и ПОСТОЯННАЯ потеря источника; фраза «just a moment» в тексте — то же. **Обходы** (тихого прохода нет — алерт будет, но категория неверна): маркер, разорванный комментарием (`Just a mome<!--x-->nt`), `Just a&nbsp;moment`, `SmartCaptcha` без дефиса (спасает только случайное совпадение слабого `captcha`). Противоречит требованию «маркеры в комментарии/JSON не дают ложного блока»; формально соответствует decisions §9.4 редакция 1 («во всём теле»; устарела — см. статус) — требовалось решение арбитра | нормализованное сравнение (снять HTML-комментарии, `html.unescape`, схлопнуть пробелы/nbsp) и сужение: сильные маркеры — в видимом тексте/`<title>`/URL атрибутов `src`/`href`; уточнить decisions §9.4 (первоначальная рекомендация; перекрыта решением арбитра 28.10 — см. статус) | **fixed (28.10, software-engineer; решено арбитром)**: решение арбитра принято 28.10 и реализовано дословно — контракт (б)-(е), нормализация (а): сильные маркеры только в `<script>`/`<link>`/cookie-атрибутах/`<title>`, слабые — только в `<title>`/`<h1>`, видимый текст (в т.ч. вакансия «Qrator») никогда не блокирует; обходы разорванными маркерами закрыты нормализацией (комментарии/entity/регистр/разделители). Проверено §10.9; U-COL-16 + SEC-09-тесты обновлены 28.10; уточнение текста decisions §9.4 — за business-analyst (§10.8; **выполнено 28.10: §9.4 переведён в редакцию 2** — см. синхронизацию в шапке) |
| F-23 | low | CWE-20 | `app/collectors/base.py:399-409` (`_date`), `app/storage/repo.py:307` (retention) | `published_at` из атрибута `datetime` не валидируется по диапазону: `9999-12-31T23:59:59+00:00` принимается как есть → (а) retention (`published_at < cutoff`) **никогда** не удаляет такие строки — обход retention и медленный рост БД; (б) сортировка `published_at desc` пинает их наверх дайджеста; (в) возраст приглушается к «сегодня» (`format_age`: будущее → 0 — само по себе безопасно). Мусорные даты отбрасываются корректно (ValueError → момент сбора, D5) | валидация диапазона (напр. `[now−10y, now+1d]`): выброс → момент сбора; контрпример закрепить тестом после фикса | **fixed (28.10, software-engineer)**: `_date` (`app/collectors/base.py:753-770`) — `parsed > now + сутки` → `None` (момент сбора, D5): retention/сортировка не обходятся; U-COL-17 |
| F-24 | low | CWE-400 (CWE-770) | `app/services/http.py:29-36` (`AiohttpClient.get`) | Размер тела ответа источника не ограничен (`await response.text()` целиком): гигантский ответ → рост памяти; усиливает F-20 (больше тело — дольше зависание). Таймаут транспорта есть, лимита размера нет (существовало до I-3) | cap размера тела (напр. 10 МБ) с классификацией как `SourceUnavailable`; частично закрывает F-20 | **fixed (28.10, software-engineer)**: `read_limited` + `MAX_BODY_BYTES = 5 МиБ` (`app/services/http.py:21-43`) — превышение → `SourceUnavailable` (отказ, не обрезка: обрезанный HTML дал бы ложный `ParseError`); U-COL-18 |
| F-25 | low | CWE-601 | `app/collectors/base.py:313` (промо-фильтр `href_fragment`), `app/collectors/hh.py:52` | Промо-фильтр D6 проверяет только подстроку `/vacancy/` в **пути** URL: `https://evil.example/vacancy/1` проходит отсечку и попадает в дайджест как ссылка (обход промо-отсечки вредоносным href). Не инъекция (URL канонизируется, `<>"'` закодированы, схемы javascript:/data: отброшены) и не SSRF (ссылки не скачиваются) — но при компрометации источника это фишинг-ссылка под видом вакансии | allowlist хостов источника (`hh.ru`/`career.habr.com`) при разборе карточек | **fixed (28.10, software-engineer)**: allowlist `allowed_hosts` в `CardLayout` (hh.ru + поддомены; career.habr.com/habr.com + поддомены — решения арбитра 28.10, decisions §9.7 D7), чужой хост — молча, как промо (не в кэше/дедупликации); страница только из чужих карточек → `ParseError` (не тихий `[]`); U-COL-19 + `test_SEC_12_promo_filter_and_dangerous_hrefs_never_reach_digest` обновлён 28.10 |

### 10.4 Воспроизводители (фактические замеры)

**F-20 (ReDoS)** — скрипты выполнялись локально против production-кода, без сети:

| Проба | Вход | Результат |
|---|---|---|
| `_HIDDEN_RE.sub(" ", "<!--" * N)` | 20 000 / 40 000 / 80 000 / 160 000 символов | 0.318 / 1.276 / 5.160 / 20.529 с — чистая квадратичность (×2 → ×4) |
| `raise_if_blocked("<!--" * N + "clean")` | 80 КБ | 5.164 с синхронно (блокирует event loop) |
| `parse_listing` на карточке с 5 000/10 000/20 000 незакрытых `<a data-qa="serp-item__title">` | ~40/60/80 КБ | 4.375 / 16.339 / 62.975 с — квадратичность карточных паттернов |
| `parse_listing` на карточке с потоком `<` без `>` | 20 000 / 40 000 / 80 000 | 2.149 / 8.569 / 34.285 с — квадратичность `LEGACY_COMPANY_PATTERN` |
| линейность на честном входе (фикстура hh_live_list ×21 ≈ 1.6 МБ) | 1.6 МБ | 0.025 с, 105 карточек — сам разбор линеен, проблема только в regex-узлах выше |

**F-21 (`int()`-краш)**:

```python
# карточка hh (живая схема) с data-value не-десятичной цифрой:
'<data value="²">₽</data> <data value="RUB">₽</data>'
# parse_listing(...) -> ValueError: invalid literal for int() with base 10: '²'
# то же: <data value="9"*4301> -> ValueError: Exceeds the limit (4300 digits)
```

**F-22 (challenge-детект)** — `raise_if_blocked(body)` (замеры ДО фикса, на
старом контракте decisions §9.4 редакция 1 «во всём теле»; устарела): `<!-- ddos-guard test -->` →
`SourceBlocked`; `{"smart-captcha": 1}` в `<script>` → `SourceBlocked`; текст
`Just a moment` в карточке → `SourceBlocked`; `Just a mome<!--x-->nt` → НЕ блок;
`Just a&nbsp;moment` → НЕ блок; `<script>HH={"k":"error.signup.captcha.invalid"}`
→ НЕ блок (корректно, слабые маркеры).

**F-23 (даты)**: habr-карточка с `datetime="9999-12-31T23:59:59+00:00"` →
`published_at=9999-12-31…` (принято), `format_age` = «сегодня»/`today`;
`datetime="2026-13-45T99:99:99"` → момент сбора (корректно).

**F-20 после фикса** — те же входы против исправленного кода (замеры
security-engineer 28.10, production не менялся; по данным отчёта
software-engineer I-3-fix на его стенде — 8.5 мин → 1.5 мс):

| Проба | Вход | Было (§10.4) | Стало (28.10) |
|---|---|---|---|
| `raise_if_blocked("<!--" * N + "clean")` | 80 КБ / 800 КБ | 5.164 с / ~8.5–9 мин | 0.1 / 0.7 мс |
| `parse_listing`, незакрытые `<a data-qa="serp-item__title">` | 5 000 / 20 000 | 4.375 / 62.975 с | 5.6 / 18.9 мс |
| `parse_listing`, поток `<` без `>` | 20 000 / 80 000 | 2.149 / 34.285 с | 0.9 / 1.2 мс |
| живая выдача fixture ×21 | 1.6 МБ | 0.025 с | 46.6 мс, 105 карточек |

Квадратичность устранена на всех трёх узлах; ускорение 3–5 порядков на
патологическом входе, честный вход в пределах бюджета 5 с.

**F-22 после фикса (решение арбитра 28.10, decisions §9.4 редакция 2,
контракт (б)-(е))** — `raise_if_blocked(body)`:
`<!-- ddos-guard -->` → НЕ блок (комментарий снят нормализацией);
`<title>Smart<!--x-->Captcha</title>`, `<title>Just a&nbsp;moment</title>` →
блок (обходы (а) закрыты); `{"k":"error.signup.captcha.invalid"}` в
`<script>` → НЕ блок (слабые — только `<title>`/`<h1>`); вакансия «Qrator» и
фраза «just a moment» в видимом тексте → НЕ блок (в); `<script
src="https://ddos-guard.net/x.js">`, cookie-атрибут `__qrator_captcha`,
`<title>Just a moment...</title>` → блок (б); HTTP 403/429 → `SourceBlocked` (д).

### 10.5 Проверено и чисто (без находок)

- **HTML-инъекция (SEC-01/SEC-05)**: `esc` тотален на путях `Vacancy` → рендер —
  `title` → `_display_title` → `esc`, `company`/`source`/`salary` → `esc`, `url` →
  `canonicalize_url` (без `<>"'`, пробелов и управляющих). Теги в полях срезаются
  `_text`, сущности раскрываются ДО `esc` — обратного пути нет. Закреплено
  11 новыми тестами + негативным контролем (`esc`→identity → red).
- **Опасные схемы URL (SEC-02/SEC-12)**: `javascript:`/`data:`/`file:`/`vbscript:`
  не переживают `canonicalize_url`; на живых схемах такие href отсекаются
  промо-фильтром, на legacy — дают канонический URL без схемы и без разметки.
- **Промо-отсечка (D6)**: `https://adsrv.hh.ru/click?…` пропускается; смешанная
  страница отдаёт только обычные карточки; обход чужим хостом закрыт (F-25
  fixed — allowlist).
- **Слабые маркеры капчи** в JSON/script/comment/template не дают ложного
  `SourceBlocked` (регрессия S94/U-COL-12 закреплена security-тестами).
- **Дата из атрибута (D5/S93)**: мусор → момент сбора, `published_at` всегда
  tz-aware (P-SEC-09), будущее → «сегодня» (кроме F-23 — retention/сортировка).
- **Гигантские входы**: 1.6 МБ живой выдачи — 25 мс; title 500 КБ → обрезка до
  200, company → 100, карточка ≤ 4096 (без `DigestError`).
- **Прототип-инъекция** — неприменима (Python, нет prototype chain).
- Секреты/запрещённые конструкции/SQL-интерполяция — чисто (§10.2).

### 10.6 Тесты (`tests/security/test_untrusted_html_parsers.py`, 11 новых)

| Тест | Угроза / закрываемый аспект |
|---|---|
| `test_SEC_01_parsed_fields_never_render_raw_markup` | SEC-01/SEC-05: payload из `HTML_PAYLOADS` в title/company разметки ВСЕХ 4 схем (живые+legacy, hh+habr) → рендер только из экранированных полей, allowlist-теги, ровно один `<b>` |
| `test_SEC_01_parsed_url_never_contains_markup_or_dangerous_schemes` | SEC-01/SEC-02: опасные/инъекционные href → URL без `<>"'`/пробелов/опасных схем, рендер безопасен |
| `test_SEC_12_promo_filter_and_dangerous_hrefs_never_reach_digest` | SEC-12/D6/F-25: промо-href и чужой хост молча мимо кэша (allowlist закреплён конфигурацией схем); страница только из промо/чужих → `ParseError` (§9.5/(е), не молчаливый `[]` и не `SourceBlocked`); опасные href (чужие хосты, подделка суффикса `hh.ru.evil.example`, «похожий» `evil-hh.ru`, `javascript:`/`data:`) не доходят до дайджеста |
| `test_SEC_09_challenge_fixtures_and_status_codes_raise_source_blocked` | SEC-09/S94: challenge-фикстуры и HTTP 403/429 → `SourceBlocked` до разбора |
| `test_SEC_09_hidden_captcha_markers_never_block_real_listing` | SEC-09/S94: «captcha»/капча-ключи в JSON/script/comment/style/template → НЕ блок |
| `test_SEC_09_visible_block_markers_and_strong_markers_raise_source_blocked` | SEC-09/S94: страница блокировки → `SourceBlocked` по контракту арбитра (б)/(г) (decisions §9.4 редакция 2; слабые «captcha»/«access denied» — `<title>`/`<h1>`; сильные — `<script>`/`<link>`/cookie/`<title>`, нормализация (а): разорванный маркер матчится); негативные контролы (в): видимый текст (в т.ч. вакансия «Qrator», «just a moment», старые тела `<p>Access Denied</p>`/`<img alt="Captcha">`) НИКОГДА не блокирует |
| `test_SEC_09_future_publication_date_clamps_to_today` | SEC-09/D5: будущая дата → возраст «сегодня»/`today`, без отрицательного возраста |
| `test_P_SEC_08_untrusted_markup_parse_renders_safely` (hypothesis, `derandomize`, 100) | P-SEC-08: произвольные текст полей/href живой разборки → либо ≥1 безопасная вакансия, либо ровно 1 из 4 исключений контракта |
| `test_P_SEC_09_publication_date_attribute_never_crashes` (hypothesis, `derandomize`, 100) | P-SEC-09: произвольное значение `datetime`-атрибута → без крашей, `published_at` всегда tz-aware |
| `test_SEC_09_large_listing_parses_within_budget` | SEC-09: ~1.6 МБ живой выдачи → 105 карточек за <5 с (замер 25 мс) |
| `test_SEC_09_giant_fields_stay_bounded_in_render` | SEC-09: гигантские title/company → обрезка, карточка ≤ 4096 |

Контрпримеры F-20/F-21/F-23 закреплены после фиксов постоянными тестами
U-COL-14/15/17 (`tests/unit/test_collectors_hardening_unit.py`, software-engineer);
на security-уровне — `test_SEC_09_large_listing_parses_within_budget` (F-20) и
обновлённые 28.10 SEC-09/SEC-12 (контракт F-22/F-25 по решению арбитра 28.10 — decisions §9.4 редакция 2 / §9.7 D7).

### 10.7 Остаточные наблюдения (не находки, не блокируют gate)

| ID | Что | Комментарий |
|---|---|---|
| O-1 | `digest.render_card:62-63`: `url` выводится без `esc` (только канонизация) | `&` из query переживает `canonicalize_url` и попадает в HTML-текст сырым. Это НЕ инъекция (`<>"'` закодированы, позиция — текст, не атрибут), но неизвестная Telegram-entity в `&…` может дать отказ отправки части дайджеста. Существовало до I-3; при желании — `esc(url)` или `&amp;` в канонизации (software-engineer) |
| O-2 | `tests/data/*_live_list.html` санитизированы (скрипты удалены, decisions §9.2) | Фикстуры не доказывают отсутствие сильных маркеров в скриптах ЖИВЫХ страниц — риск F-22 усиливается при дрейфе разметки; мониторинг алертов «блокировка/капча» обязателен |

### 10.8 Открытые вопросы к другим ролям (обновлено 28.10, после фиксов)

- **business-analyst**: ~~решение арбитра F-22 (контракт (б)-(е)) реализовано в
  коде, но `docs/spec/decisions.md` §9.4 всё ещё описывает старый контракт
  («маркеры ищутся во всём теле ответа») — уточнить §9.4 текстом решения
  арбитра (и связанные места api.md §6/§16)~~ — **выполнено 28.10**:
  decisions §9.4 переведён в **редакцию 2** (нормализация (а), контракт
  (б)-(е); редакция 1 «во всём теле» сохранена как история) и §9.7 D7 —
  allowlist хостов (F-25). Тесты SEC-09/SEC-12 ссылаются на §9.4 редакция 2
  (прямые ссылки на решение арбитра 28.10 сохранены).
- **product-manager / qa-engineer**: предложение строк рисков под F-20..F-25
  остаётся в силе (фиксы закрыты; риски — регрессии разбора/детекта при
  дрейфе разметки, O-2).
- **software-engineer**: F-20..F-25 — fixed, вопросов нет (замеры §10.4).

### 10.9 Верификация исправлений F-20..F-25 (28.10.2026, I-3-fix)

| Команда / проверка | Фактический результат |
|---|---|
| `.venv/bin/python -m pytest tests/security -q` (до правки тестов, на исправленном коде) | `2 failed, 166 passed` — красные `test_SEC_09_visible_block_markers_and_strong_markers_raise_source_blocked` и `test_SEC_12_promo_filter_and_dangerous_hrefs_never_reach_digest` закрепляли СТАРЫЙ контракт (сильные маркеры во всём теле — §9.4 редакция 1, устарела; чужой хост проходил в дайджест) |
| обновление двух тестов под контракт арбитра (б)-(е), decisions §9.4 редакция 2 | тела блокировок перенесены в реалистичные позиции ((г): `<title>`/`<h1>` для слабых; (б): `<script>`/`<title>`/`<link>`/cookie-атрибуты для сильных; (а): разорванные маркеры); суть сценария «страница блокировки → `SourceBlocked`» сохранена; негативные контролы **усилены**: старые тела `<p>Access Denied</p>`/`<img alt="Captcha">`/`<p>Please complete the captcha</p>` стали явными контролами «видимый текст → НЕ блок» (в), добавлены «Qrator»/«just a moment» в карточке, `<h2>Access Denied</h2>` (г), `<h1>Just a moment...</h1>` (б/в), `<!-- ddos-guard -->` (а); SEC-12: ассерт про `https://evil.example/vacancy/1` заменён на F-25-контракт (молча мимо кэша), добавлены смешанная страница промо+чужой+обычная, `ParseError` на страницах только из промо/чужих (усилено: раньше допускался тихий `[]`), опасные href (подделка суффикса хоста, `javascript:`/`data:`) и allowlist-конфигурация схем |
| `.venv/bin/python -m pytest tests/security -q` (после правки) | `168 passed in 9.87s` — 0 failed / 0 xfail |
| `ruff check tests/security && ruff format --check tests/security` | `All checks passed!` / `10 files already formatted` |
| негативный контроль (2 мутации в памяти, production-код не менялся) | MUTATION-1 (`raise_if_blocked` → no-op) — `1 failed` AssertionError («не классифицирована как SourceBlocked»); MUTATION-2 (`_host_allowed` → True всегда) — `1 failed` AssertionError (`https://evil.example/vacancy/1` прошёл отсечку) — оба обновлённых теста чувствительны |
| проверка challenge-фикстур под контракт (б)/(в) | `hh_challenge.html` → `SourceBlocked` (`challenge marker: ddos-guard`), `habr_challenge.html` → `SourceBlocked` (`challenge marker: qrator`) — обе через `<script>`-структуру; те же фикстуры без `<script>` (остались видимый текст и `<h1>Just a moment...</h1>`) — НЕ блок: триггер — структурные позиции, фикстуры конформны, правка не потребовалась |
| замеры F-20 на исправленном коде (те же воспроизводители) | §10.4: 0.1–46.6 мс вместо секунд/минут (8.5 мин → 0.7 мс на 800 КБ комментариях) |

Тесты SEC-09/SEC-12 обновлены под контракт, а не ослаблены: каждый бывший
позитивный кейс либо перенесён в позицию контракта (та же семантика
«страница блокировки → `SourceBlocked`»), либо стал явным негативным контролом
(запрет ложного блока — решение арбитра (в)); добавленные контролы только
усиливают проверки. Единственные тела, потерявшие ожидание блокировки, —
три старых `<p>/<img>`-кейса: они НЕ являлись страницами блокировки и по новому
контракту не блокируют (раскрыто выше и в тесте).

### 10.10 Вердикт готовности к QA gate (I-3, пересмотрен 28.10)

| ID | Severity | Статус (28.10.2026) |
|---|---|---|
| F-20 | **high** | **fixed** (software-engineer) — линейные алгоритмы вместо квадратичных regex + cap тела; замеры §10.4 (8.5 мин → 0.7 мс на 800 КБ; U-COL-14) |
| F-21 | medium | **fixed** (software-engineer) — `_safe_int` (isdecimal/лимит/try-except); мусорная `value` → зарплата `None` (U-COL-15) |
| F-22 | medium | **fixed — решено арбитром** (контракт (б)-(е) = decisions §9.4 **редакция 2**, реализован дословно): ложные блоки из видимого текста/комментариев устранены (в), обходы разорванными маркерами закрыты нормализацией (а), слабые маркеры ограничены `<title>`/`<h1>` (г), 403/429 → `SourceBlocked` (д) (U-COL-16 + SEC-09, §10.9) |
| F-23 | low | **fixed** (software-engineer) — дата из далёкого будущего → момент сбора, retention/сортировка не обходятся (U-COL-17) |
| F-24 | low | **fixed** (software-engineer) — cap тела 5 МиБ → `SourceUnavailable` (U-COL-18) |
| F-25 | low | **fixed** (software-engineer) — allowlist хостов (hh.ru + поддомены; career.habr.com/habr.com + поддомены; decisions §9.7 D7), чужой хост молча мимо кэша, страница только из чужих → `ParseError` (U-COL-19 + SEC-12) |

**Открытых high/critical находок нет.** F-20 (единственная high) — fixed с
подтверждёнными замерами и постоянными тестами; F-22 — решено арбитром и
закреплено тестами (§10.9). Открытых находок I-3 не осталось; из наблюдений
§10.7 действуют O-1 (low, `&` в URL без `esc` — не инъекция) и O-2 (мониторинг
алертов «блокировка/капча» при дрейфе разметки). Единственная открытая находка
по всему отчёту — F-05 (low, документационная, §2).

**Можно проходить QA gate.**
