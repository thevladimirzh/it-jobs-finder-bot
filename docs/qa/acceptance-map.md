# Acceptance-карта покрытия — it-jobs-finder-bot (I-1–I-3)

Владелец: qa-engineer. Дата: 27.10.2026 (I-1, QA gate PASS); обновлено
27.10.2026 — итерация I-2 (red-этап: тесты написаны, production-код диалога
ещё не реализован); **итоговое обновление 28.10.2026 — QA gate I-2 PASS
(445 passed), все статусы §1–§2 green** (см. §0 «Финальный статус I-2»);
**28.10.2026 — итерация I-3 (hotfix прод-бага: живая разметка источников),
red-этап** (см. §0 «Статус итерации I-3»); **28.10.2026 — зелёный проход I-3:
467 passed, все статусы S90..S95 green, R74..R78 covered** (см. §0 «Финальный
статус I-3»; вердикт gate — отдельным шагом после security-review);
**28.10.2026 — I-3-fix (security review F-20..F-25): фикстура S94 приведена к
решению арбитра F-22 (маркеры в реалистичных структурных позициях), риски
R79..R84 заведены и covered** (см. §0 «Статус I-3-fix» и §3.3); **28.10.2026 —
I-3-fix-2: acceptance-закрепление контракта F-22/F-25 редакция 2 — сценарии
S96..S101** (`test_challenge_normalization.py`, `test_host_allowlist.py`;
см. §0 «Статус I-3-fix-2» и таблицу S96..S101 в §1); **28.10.2026 — QA gate I-3
PASS (519 passed, 0 failed, 0 skipped)** — см. §0 «Финальный статус QA gate I-3»
и `docs/qa/verdict.md` (секция I-3).
Назначение: связь «сценарий @S → acceptance-тест → риски R-* → статус» + полнота
митигации рисков и обязательства других ролей. Источники: `tests/features/*.feature`
(S1..S78), `docs/risk-register.md` (R1..R52), `docs/spec/api.md`, `docs/product/brief.md` §6.1.
Итерация I-2: `tests/features/dialog_callbacks.feature` (S79..S89), риски
R55..R69, brief §6.1 «Диалог на инлайн-кнопках (I-2)», api.md §15.1, decisions §8.

Статусы: **red** — тест написан и осознанно падает (production-код не реализован);
причина красноты — внятный `NotImplementedYet: «модуль app.* ещё не реализован»`
(или «фикстура tests/data/… ещё не добавлена»), НЕ ошибка сборки/импорта.

## 0. Итоги

**Финальный статус QA gate (27.10.2026, последовательный прогон в тихом окне):**
`.venv/bin/python -m pytest` → **329 passed in 57.53s, 0 failed, 0 xfail, 0 skipped**
(4 бывших xfail-контрпримера F-09..F-12 переведены security-engineer'ом в обычные
тесты после фиксов; +9 unit-тестов фиксов F-09..F-12: U-ESC-01/02, U-LIM-01/02,
U-JSON-01, U-CFG-02, U-COL-07/08 и др.);
`--collect-only -q` → **329 tests collected** (acceptance 176, security 94, unit 49,
e2e 7, smoke 3); `tests/e2e` отдельно — **7 passed** (против `jobs_test`, не скипались);
`tests/security` — **94 passed**; `ruff check . && ruff format --check .` — чисто.
Все статусы таблиц §1–§2 — **green**; финальные R-статусы — §9; вердикт —
`docs/qa/verdict.md` (**PASS**). Предыдущая цифра (история): 316 passed, 4 xfailed.
История правок acceptance-тестов после ревью — §7; компромисс обрезки `{title}` — §8.

- Acceptance-сценарии: **78/78** (S1..S78), тест-кейсы с параметризацией Examples: **156**.
- Property-тесты: **20** (P-COL-01/02, P-SAL-01/02, P-AGE-01, P-DIG-01/03/04, P-TEX-01,
  P-UX-01/02, P-SES-01, P-SEL-01/02, P-SEND-01, P-BTN-01, P-DED-01, P-SCH-01, P-AS-01,
  P-I18N-01) — `tests/acceptance/test_properties.py`.
- ~~Краснота~~ (этап до реализации, история §5): `pytest tests/acceptance -q` → **176 failed**,
  причина каждого падения — `NotImplementedYet` (см. §5); ошибок синтаксиса/импорта/самих тестов нет.
- Один тест ↔ один сценарий (для Scenario Outline — `@pytest.mark.parametrize` по
  строкам Examples); чёрный ящик через публичное API `app.*` из `docs/spec/api.md`.

### Статус итерации I-2 (red-этап, 27.10.2026)

Прогон `.venv/bin/python -m pytest tests/acceptance -q` → **56 failed,
140 passed**; причина каждой красноты — `NotImplementedYet` («BotHarness.press
ещё не реализован», «модуль app.bot.dialog ещё не реализован»), НЕ ошибки
импорта/синтаксиса. Красные: новые S79..S89 (18 кейсов с параметризацией
S88) + P-DLG-01/02 (4 property-теста) + легитимно обновлённые под кнопочный
диалог (decisions §8, ожидаемая переделка, не регрессия): S1, S4, S5, S7,
S45–S50 (setup), S52/S53 (setup), S63/S64 (setup), S68–S70 (setup),
P-BTN-01 (setup). `.venv/bin/python -m pytest --collect-only -q` →
**381 tests collected** (acceptance 196, security 126, unit 49, e2e 7, smoke 3);
`ruff check tests/acceptance` и `ruff format --check tests/acceptance` — чисто.
Свидетельства I-1 «в `app/` нет InlineKeyboard» — см. §6.13: устарело для
диалога, в силе для дайджеста (Q1).

### Финальный статус I-2 (QA gate, 28.10.2026)

Прогон `.venv/bin/python -m pytest` → **445 passed in 68.18s, 0 failed,
0 xfail, 0 skipped** (после зелёного прохода реализации I-2 + усиления
acceptance-тестов на gate — вердикт §8); `--collect-only -q` → **445 tests
collected** (acceptance 196, security 157, unit 82, e2e 7, smoke 3);
`ruff check . && ruff format --check .` — чисто (`All checks passed!`,
`88 files already formatted`). Все статусы таблиц §1–§2 — **green**
(89/89 сценариев S1..S89, 0 немапленных; property P-DLG-01/02 зелёные);
финальные R-статусы — §9; вердикт — `docs/qa/verdict.md` (**PASS**).
Красная история I-2 (56 failed, `NotImplementedYet`) — блок выше.

### Статус итерации I-3 (red-этап, 28.10.2026)

Прод-баг I-3: коллекторы hh.ru и Habr Career бросали `ParseError` в проде —
вёрстка источников сменилась (H1 подтверждена живыми образцами 28.10; H2
«challenge с прод-IP» отклонена). **Корень бага — «фикстуры самосогласованы с
парсером»**: тестовые фикстуры `tests/data/*_list.html` были синтетическими и
проверяли только сами себя; тесты I-1/I-2 были зелёными при мёртвом парсере.
Лечится политикой фикстур решений §9.2 (фикстуры коллекторов — ТОЛЬКО
санитизированные живые образцы с шапкой «URL + дата съёмки»; синтетика «на
глаз» запрещена; старые синтетические файлы остаются регрессионными данными
нормализации — шапки помечает software-engineer).

Прогон `.venv/bin/python -m pytest tests/acceptance -q` (28.10.2026) →
**9 failed, 196 passed in 65.33s**: красные — только новые S90..S95 (9 кейсов
с параметризацией S94), причины красноты осмысленные:
`NotImplementedYet: «фикстура tests/data/{hh,habr}_live_list.html ещё не
добавлена (владелец — software-engineer)»` (S90/S91/S93) либо текущий парсер
на живых маркерах даёт `ParseError`/`EmptyResult` — ровно симптом прод-бага
(S92, S94×4, S95). **Все 196 прежних тестов остались зелёными**, включая
регрессионные S8..S18 на старых синтетических фикстурах (отдельный прогон
`test_collection_normalization.py` → 27 passed). `--collect-only -q` →
**454 tests collected** (445 + 9 новых); `ruff check tests/acceptance` и
`ruff format --check` — чисто.

Тест «проходит слишком рано»: **не выявлен** — каждая новая краснота проверена
по причине (фикстуры/симптом прод-бага). Специально усилены против преждевременной
зелёности: маркеры S94 вынесены за первые 4096 байт тела (padding живой
challenge-страницы; при контракте редакции 1 «детект во всём теле» это не давало
случайной зелёности `smart-captcha`; КОНТРАКТ СМЕНИЛСЯ — сейчас действует
редакция 2 «нормализация тела + структурные позиции», §0 «Статус I-3-fix-2»);
S95 содержит оба контейнерных маркера (старый + новый), иначе на
текущем коде оба пути дают одинаковый `ParseError` и граница §9.5 не изолируется
(сейчас S95 красен именно регрессией R78: `EmptyResult('hh.ru: no vacancy cards')`
вместо `ParseError`).

**Задание software-engineer (фикстуры, решений §9.2; шапка каждого файла:
источник/URL выдачи + дата съёмки образца 28.10.2026 + что санитизировано):**
- `tests/data/hh_live_list.html`, `tests/data/habr_live_list.html` — санитизированные
  живые образцы выдачи (staging: `diag-i3/hh.html`, `diag-i3/habr.html`);
- `tests/data/hh_challenge.html`, `tests/data/habr_challenge.html` — живые
  challenge-образцы по маркерам ddos-guard / qrator (smart-captcha / «Just a moment»
  живых образцов нет — H2 отклонена, кейсы маркерные);
- **S90 (gap, owner BA/software-engineer):** шаг «зарплата карточки
  "100 000 – 150 000 ₽" → min=100000, max=150000, currency=RUB» взят дословно
  из фактов живой разметки; на образце 28.10 такая зарплата есть ТОЛЬКО у
  промо-карточки (`adsrv.hh.ru/click`, «Финансовый менеджер»), которую D6/S92
  велит пропускать. `hh_live_list.html` обязан содержать обычную (не промо)
  карточку с этой зарплатой (иначе шаг S90 невыполним); альтернатива — BA
  переписывает шаг 4 S90 на зарплату обычной карточки образца
  (напр. «210 000 – 300 000 ₽» → min=210000, max=300000, RUB) — правка
  feature-файла за business-analyst.
- U-COL-09..U-COL-13 (unit-обязательства I-3, реестр R74..R78): fallback-цепочки
  старых/новых маркеров (контейнер/карточка/заголовок/компания/зарплата), D6-промо,
  D5-fallback даты на время сбора, детект challenge (контракт §9.4; с тех пор
  уточнён до редакции 2 «нормализация + структурные позиции») + 403/429 →
  `SourceBlocked`, граница `ParseError`/`EmptyResult`.

### Финальный статус I-3 (зелёный проход, 28.10.2026)

Прогон `.venv/bin/python -m pytest` → **467 passed in 78.57s, 0 failed, 0 xfail,
0 skipped**; `ruff check . && ruff format --check .` — чисто (`All checks passed!`,
`89 files already formatted`). Все S90..S95 — **green** (9 кейсов с параметризацией
S94), R74..R78 — **covered** (§3.2). Production-код в этом цикле не менялся.

**Точечные правки обвязки `tests/acceptance/test_live_markup.py` (28.10, qa-engineer;
без ослабления assert'ов, production не тронут, другие тесты не тронуты; история — §7):**
1. Хелпер `_run_collect` принимал фиксированный `now=NOW` и не принимал параметр
   `now` → `TypeError` в S93. Добавлен параметр `now: datetime = NOW` с пробросом
   в `run_collect` (по образцу `test_alerts_degradation.py`). S93 при этом проверяет
   инъекцию часов «сбор в момент T»: `published_at == NOW`, возраст «сегодня»/«today».
2. S92 сравнивал `sorted(title for v in repo.vacancies)` с ожиданиями hh, но тест
   подключает валидный второй источник (habr), и api.md §10 требует пополнять общий
   кэш всеми источниками. Добавлен фильтр по источнику (как в S93/S95); остальные
   проверки S92 (added==2, промо мимо кэша, нет adsrv-URL, нет алертов, дедуп-ключ
   промо не «сожжён») не тронуты.

### Статус I-3-fix (security review F-20..F-25, 28.10.2026)

Security review закрыл F-20 (ReDoS, high; 8.5 мин → 1.5 мс) и F-21..F-25 фиксами
software-engineer. Побочный эффект F-22 (решение арбитра: сильные маркеры
challenge — только в структурных позициях `<script>`/`<link>`/cookie-атрибуты/
`<title>` после нормализации; видимый текст карточек вакансий не триггерит
`SourceBlocked` никогда) — фикстура `_challenge_page` S94 клала маркер в видимый
текст `<div id="challenge-content">`, что перестало быть реалистичным
challenge-входом (живые проверки: ddos-guard ставит `window.ddos_guard_challenge`
в `<script>`, qrator — cookie `__qrator_captcha`).

**Правка фикстуры S94 (28.10, qa-engineer; ассерты не ослаблялись, production и
чужие тесты не тронуты):** маркер помещён в реалистичную структурную позицию
(`CHALLENGE_STRUCTURES`): ddos-guard — `<script>` с challenge-конфигом,
qrator — `document.cookie = "__qrator_captcha=…"`, smart-captcha — `<script>` +
cookie-атрибут (как U-COL-16), «Just a moment» — `<title>Just a moment...</title>`;
маркер сохранён за пределами первых 4096 байт тела (padding живой страницы;
действующий контракт детекта — решения §9.4 редакция 2 «нормализация тела +
структурные позиции», редакция 1 «во всём теле» устарела). Все прежние
ассерты сохранены: `SourceBlocked`, отчёт `blocked`, алерт «блокировка/капча»
(ровно один), алерт «ошибка разбора разметки» не отправляется; для ddos-guard/
qrator дополнительно живые challenge-образцы `tests/data/{hh,habr}_challenge.html`.

Прогоны 28.10.2026 (реальный вывод):
- `.venv/bin/python -m pytest tests/acceptance -q` → **205 passed, 0 failed**
  (S94 — 4 кейса зелёные);
- `.venv/bin/python -m pytest` → **498 passed, 0 failed** (ожидавшиеся чужие
  падения SEC-09-visible/SEC-12 к моменту прогона закрыты параллельным фиксом
  security-engineer — `tests/security/test_untrusted_html_parsers.py` → 2 passed);
- `ruff check tests/acceptance` и `ruff format --check tests/acceptance` — чисто
  (`All checks passed!`, `19 files already formatted`).

Статусы: все S90..S95 — **green**; R74..R78 — `covered` (§3.2); R79..R84 (F-20..F-25)
заведены в реестре и **covered** (§3.3).

**Сверка AC-2/AC-3 (brief §3) со свидетельствами S90..S95 (подготовка к gate;
вердикт — отдельным шагом после security-review):**
- **AC-2** «коллекторы hh и Habr Career из HTML-фикстур `tests/data/` дают
  нормализованные вакансии (title, company, salary, url, source, published_at);
  битая разметка → `ParseError`; блокировка/капча → `SourceBlocked`; сеть в тестах
  не используется (FakeClient)» → **подтверждён**: S90 (hh: title/company/salary
  100000–150000 RUB/канонический url/source, без алертов), S91 (habr: обе карточки,
  `salary=None` без зарплаты, относительная ссылка → career.habr.com, published_at
  из даты карточки), S93 (published_at = момент сбора при отсутствии даты), S95
  (битая разметка при живом «скелете» → `ParseError`), S94 (challenge-маркер →
  `SourceBlocked`, 4 кейса + живые challenge-образцы), сеть — FakeClient (S73/R41).
- **AC-3** «пустой разбор не возвращается молча: пустой результат → сигнал и алерт
  админу по шаблону §6.1» → **подтверждён**: S11 (EmptyResult → алерт, шаблон §6.1)
  + S95 (граница `ParseError`/`EmptyResult` — пустой/битый разбор не маскируется
  молчаливым пустым списком) + S94 (алерт «блокировка/капча») + S92 (негативная
  проверка: алертов нет только когда кэш пополнен). Прежние свидетельства S9/S12
  остаются в силе.

### Статус I-3-fix-2 (закрепление контракта F-22/F-25 редакция 2, 28.10.2026)

BA добавил сценарии S96..S101 (`tests/features/collection_normalization.feature`)
под уточнённый контракт: decisions §9.4 редакция 2 (нормализация тела перед
матчингом + сильные маркеры только в структурных позициях; видимый текст
НЕ блокирует никогда; слабые — `<title>`/`<h1>`) и §9.7 D7 (allowlist хостов
URL). Реализация готова (unit U-COL-16/U-COL-19, security P-SEC-08/SEC-12 —
зелёные); acceptance-тесты — регрессионное закрепление поверх готового кода
(red-этап по определению неприменим).

Новые тесты (qa-engineer; 1↔1 сценарий, Scenario Outline → parametrize по
Examples, имена с ID; чёрный ящик через `app.collectors` + `run_collect`,
точные строки алертов brief §6.1):
- `test_challenge_normalization.py` — S96 (6 rows), S97 (4 rows), S98 (4 rows);
- `test_host_allowlist.py` — S99 (4 rows), S100, S101 (2 rows).

Прогоны 28.10.2026 (реальный вывод):
- `.venv/bin/python -m pytest tests/acceptance/test_challenge_normalization.py
  tests/acceptance/test_host_allowlist.py` → **21 passed**;
- `.venv/bin/python -m pytest` → **519 passed, 0 failed in 70.83s** (498 + 21);
- `ruff check . && ruff format --check .` — чисто (`All checks passed!`,
  `93 files already formatted`).

Тест «проходит слишком рано»: проверен дискриминационной пробой старого
контракта (выбросочный скрипт, production не менялся): под редакцию 1
«детект во всём теле» **красные 6/6 кейсов S96**; под контракт без allowlist
хостов (F-25 до фикса) — **красные 4/4 S99 и S100**; под слишком строгий
allowlist (точный хост без поддоменов) — красен `S101[spb.hh.ru]` (строка
`S101[habr.com]` зелёная и в этом режиме: `habr.com` — сам хост allowlist,
поддоменную границу несёт именно строка `spb.hh.ru` — принято, Examples
покрывают обе ветви). S97 красен без нормализации тела (комментарии/entity/
регистр) — фактически закреплён unit U-COL-16.

### Финальный статус QA gate I-3 (28.10.2026)

Прогон `.venv/bin/python -m pytest` → **519 passed in 76.70s, 0 failed,
0 xfail, 0 skipped** (e2e 7 passed — не скипались); `--collect-only -q` →
**519 tests collected** (acceptance 226, security 168, unit 115, e2e 7,
smoke 3); S90..S101 отдельным прогоном (`test_live_markup.py` +
`test_challenge_normalization.py` + `test_host_allowlist.py`) → **30 passed**;
`ruff check . && ruff format --check .` — чисто (`All checks passed!`,
`93 files already formatted`). Все статусы §1–§3 — **green/covered**
(101/101 сценариев S1..S101); миграции 0001/0002 идемпотентны (двойной
`alembic upgrade head` → rc 0, no-op; `alembic current` → `0002_widen_preset_slug
(head)`); запрещённые конструкции в `app/` — 0 совпадений; планировщик — только
`MemoryJobStore`. Вердикт — `docs/qa/verdict.md`, секция I-3 (**PASS**).
Остаток (не блокер): перепривязка тегов `@R77/@R79/@R80` у S96..S101 →
`@R81`/`@R84` — owner business-analyst (см. ниже и вердикт §7.1).

Статусы: все S96..S101 — **green** (21 кейс); R81/R84 — `covered` усилением
acceptance-слоя (§3.3, реестр). Открытый вопрос (owner BA): теги feature-файла
`@R77/@R79/@R80` у S96..S101 — провизорные и теперь КОНФЛИКТУЮТ с реальными
строками реестра R79 (ReDoS) / R80 (зарплаты): перепривязать на `@R81`
(S96..S98) и `@R84` (S99..S101) — правки feature-файлов за business-analyst
(решения §9.6).

## 1. Сценарии S1..S78 → тесты → риски

| Сценарий | Тест (tests/acceptance/) | Риски | Статус |
|---|---|---|---|
| @S1 | test_onboarding_settings.py::test_s01_new_user_full_onboarding_saves_schedule | R18, R55 | green |
| @S2 | test_onboarding_settings.py::test_s02_no_schedule_no_digest_single_reminder | R18 | green |
| @S3 | test_onboarding_settings.py::test_s03_invalid_digest_time_rejected (5 rows) | R15 | green |
| @S4 | test_onboarding_settings.py::test_s04_invalid_timezone_rejected (5 rows) | R15, R69 | green |
| @S5 | test_onboarding_settings.py::test_s05_digest_size_chosen_by_button (4 rows) | R27, R59 | green |
| @S6 | test_onboarding_settings.py::test_s06_invalid_min_salary_rejected (4 rows) | R15, R22 | green |
| @S7 | test_onboarding_settings.py::test_s07_settings_change_presets_stops_and_language | R20, R15, R55 | green |
| @S8 | test_collection_normalization.py::test_s08_normalizes_fixture_vacancies | R2, R40 | green |
| @S9 | test_collection_normalization.py::test_s09_broken_markup_raises_parse_error_with_alert | R2 | green |
| @S10 | test_collection_normalization.py::test_s10_blocked_source_raises_source_blocked_with_alert | R1 | green |
| @S11 | test_collection_normalization.py::test_s11_empty_parse_raises_empty_result_with_alert | R40, R2 | green |
| @S12 | test_collection_normalization.py::test_s12_unavailable_source_alerts_and_cache_stays_usable | R1, R35 | green |
| @S13 | test_collection_normalization.py::test_s13_duplicate_canonical_url_saved_once (4 rows) | R12 | green |
| @S14 | test_collection_normalization.py::test_s14_duplicate_by_title_and_company_saved_once | R12 | green |
| @S15 | test_collection_normalization.py::test_s15_broken_fixture_artifacts_raise_parse_error (4 rows) | R28, R2 | green |
| @S16 | test_collection_normalization.py::test_s16_salary_boundary_values_normalized (11 rows) | R22 | green |
| @S17 | test_collection_normalization.py::test_s17_heavy_page_parse_keeps_event_loop_responsive | R35, R31 | green |
| @S18 | test_collection_normalization.py::test_s18_huge_hostile_text_survives_render_path | R25, R7 | green |
| @S19 | test_filters_presets.py::test_s19_seed_migration_creates_exactly_seven_presets | R21 | green |
| @S20 | test_filters_presets.py::test_s20_subscriptions_and_tweaks_affect_selection | R8, R13 | green |
| @S21 | test_filters_presets.py::test_s21_min_salary_cross_currency_decision (4 rows) | R8 | green |
| @S22 | test_filters_presets.py::test_s22_vacancy_without_salary_passes_min_filter | R8 | green |
| @S23 | test_filters_presets.py::test_s23_stop_words_filter_title_and_company (5 rows) | R13 | green |
| @S24 | test_filters_presets.py::test_s24_must_stack_required_nice_stack_boosts_score | R13 | green |
| @S25 | test_filters_presets.py::test_s25_digest_sorted_by_score_then_recency | R8 | green |
| @S26 | test_filters_presets.py::test_s26_backend_other_preset_has_name_and_description | R21 | green |
| @S27 | test_digest_splitting.py::test_s27_card_format_ru_verbatim | R10, R36 | green |
| @S28 | test_digest_splitting.py::test_s28_card_format_en_verbatim | R10, R20 | green |
| @S29 | test_digest_splitting.py::test_s29_salary_line_formats_verbatim (9 rows) | R10 | green |
| @S30 | test_digest_splitting.py::test_s30_age_line_boundaries (9 rows) | R23 | green |
| @S31 | test_digest_splitting.py::test_s31_digest_header_count_and_numbering | R10, R36 | green |
| @S32 | test_digest_splitting.py::test_s32_digest_split_at_card_boundaries | R4 | green |
| @S33 | test_digest_splitting.py::test_s33_long_title_truncated_safely | R24, R4 | green |
| @S34 | test_digest_splitting.py::test_s34_external_text_escaped_in_card | R7, R25 | green |
| @S35 | test_digest_splitting.py::test_s35_vacancy_delivered_to_user_at_most_once | R3 | green |
| @S36 | test_digest_splitting.py::test_s36_empty_digest_message_verbatim | R11 | green |
| @S37 | test_digest_splitting.py::test_s37_digest_size_default_and_bounds | R27 | green |
| @S38 | test_schedule_dst.py::test_s38_digest_at_selected_local_time_once_per_slot | R6 | green |
| @S39 | test_schedule_dst.py::test_s39_spring_forward_gap_sends_exactly_one_digest | R6 | green |
| @S40 | test_schedule_dst.py::test_s40_fall_back_overlap_sends_exactly_one_digest | R6 | green |
| @S41 | test_schedule_dst.py::test_s41_catchup_within_three_hours | R6, R11 | green |
| @S42 | test_schedule_dst.py::test_s42_no_catchup_after_three_hours | R6 | green |
| @S43 | test_schedule_dst.py::test_s43_restart_mid_dispatch_no_duplicate_delivery | R32, R3 | green |
| @S44 | test_schedule_dst.py::test_s44_concurrent_collect_and_digest_without_races | R32, R31 | green |
| @S45 | test_feedback_commands.py::test_s45_like_command_replies_and_records_stat | R5 | green |
| @S46 | test_feedback_commands.py::test_s46_dislike_and_bookmark_verbatim (2 rows) | R5 | green |
| @S47 | test_feedback_commands.py::test_s47_invalid_number_verbatim_error_no_stat (7 rows) | R26, R15 | green |
| @S48 | test_feedback_commands.py::test_s48_feedback_does_not_affect_selection | R5 | green |
| @S49 | test_feedback_commands.py::test_s49_repeated_action_overwrites_previous | R26, R5 | green |
| @S50 | test_feedback_commands.py::test_s50_numbering_works_across_digest_parts | R5, R4 | green |
| @S51 | test_admin_commands.py::test_s51_admin_collect_runs_and_reports_counts | R1, R40 | green |
| @S52 | test_admin_commands.py::test_s52_admin_preset_crud | R21, R27 | green |
| @S53 | test_admin_commands.py::test_s53_admin_stats_users_and_feedback_counters | R5, R17 | green |
| @S54 | test_admin_commands.py::test_s54_admin_health_shows_source_statuses | R1, R2 | green |
| @S55 | test_admin_commands.py::test_s55_admin_commands_silent_for_non_admin (8 rows) | R17 | green |
| @S56 | test_alerts_degradation.py::test_s56_alert_template_verbatim (8 rows) | R1, R2, R40 | green |
| @S57 | test_alerts_degradation.py::test_s57_alerts_aggregated_within_hour_window | R16 | green |
| @S58 | test_alerts_degradation.py::test_s58_degraded_source_still_delivers_digest | R1, R11 | green |
| @S59 | test_alerts_degradation.py::test_s59_dispatch_throttled_with_flood_retries | R9 | green |
| @S60 | test_alerts_degradation.py::test_s60_dispatch_failure_does_not_break_queue | R42 | green |
| @S61 | test_retention.py::test_s61_cleanup_removes_strictly_older_than_30_days | R19 | green |
| @S62 | test_retention.py::test_s62_cleanup_removes_undelivered_vacancies | R19 | green |
| @S63 | test_i18n.py::test_s63_user_strings_in_selected_language (2 rows) | R20 | green |
| @S64 | test_i18n.py::test_s64_language_switch_affects_only_new_messages | R20 | green |
| @S65 | test_i18n.py::test_s65_ru_and_en_dictionaries_have_key_parity | R39 | green |
| @S66 | test_i18n.py::test_s66_alerts_are_always_russian | R20, R38 | green |
| @S67 | test_antispam.py::test_s67_over_limit_actions_muted_silently | R14 | green |
| @S68 | test_antispam.py::test_s68_legitimate_flow_below_limit | R14 | green |
| @S69 | test_antispam.py::test_s69_mute_expires_after_ten_minutes | R33, R14 | green |
| @S70 | test_antispam.py::test_s70_mass_abuse_does_not_degrade_legit_users | R17 | green |
| @S71 | test_antispam.py::test_s71_restart_resets_mute_state | R33 | green |
| @S72 | test_infra_guards.py::test_s72_non_test_database_url_rejected_before_any_test | R29 | green |
| @S73 | test_infra_guards.py::test_s73_collectors_never_open_network_connections | R41 | green |
| @S74 | test_infra_guards.py::test_s74_db_sessions_not_held_during_http | R31 | green |
| @S75 | test_infra_guards.py::test_s75_digest_job_finishes_within_a_minute_at_scale | R34 | green |
| @S76 | test_infra_guards.py::test_s76_alembic_upgrade_on_clean_db_matches_models | R37 | green |
| @S77 | test_infra_guards.py::test_s77_missing_bot_token_fails_startup_explicitly | R30 | green |
| @S78 | test_infra_guards.py::test_s78_all_output_paths_escape_external_text | R38, R7 | green |
| @S79 | test_dialog_callbacks.py::test_s79_every_callback_answered_immediately | R56, R67 | green |
| @S80 | test_dialog_callbacks.py::test_s80_stale_callback_polite_refusal | R57, R26, R64 | green |
| @S81 | test_dialog_callbacks.py::test_s81_foreign_callback_polite_refusal | R57, R26 | green |
| @S82 | test_dialog_callbacks.py::test_s82_preset_multiselect_toggles_and_saves_on_done | R58, R63 | green |
| @S83 | test_dialog_callbacks.py::test_s83_done_without_selection_refuses | R58 | green |
| @S84 | test_dialog_callbacks.py::test_s84_callback_data_within_64_bytes_everywhere | R59 | green |
| @S85 | test_dialog_callbacks.py::test_s85_hostile_preset_name_is_escaped | R53, R7 | green |
| @S86 | test_dialog_callbacks.py::test_s86_language_button_saves_and_applies | R20, R55 | green |
| @S87 | test_dialog_callbacks.py::test_s87_step_transitions_and_interruption_keep_saved_settings | R55, R64, R18 | green |
| @S88 | test_dialog_callbacks.py::test_s88_forged_callback_polite_refusal (9 rows) | R26, R59, R61 | green |
| @S89 | test_dialog_callbacks.py::test_s89_city_pagination_and_manual_offset | R66, R69, R15 | green |

I-3 (живая разметка источников, `tests/acceptance/test_live_markup.py`; статус —
зелёный проход 28.10.2026, см. §0 «Финальный статус I-3»; красная история —
§0 «Статус итерации I-3»):

| Сценарий | Тест (tests/acceptance/) | Риски | Статус |
|---|---|---|---|
| @S90 | test_live_markup.py::test_s90_live_hh_markup_parses_into_vacancies | R74, R78 | green (фикстура hh_live_list.html; шаг зарплаты — gap закрыт, §0) |
| @S91 | test_live_markup.py::test_s91_live_habr_markup_parses_including_card_without_salary | R74, R78 | green (фикстура habr_live_list.html) |
| @S92 | test_live_markup.py::test_s92_promo_card_skipped_and_not_cached | R75 | green (живые маркеры hh: промо мимо кэша и дедупа) |
| @S93 | test_live_markup.py::test_s93_missing_publish_date_falls_back_to_collection_time | R76 | green (published_at = NOW, «сегодня»/«today») |
| @S94 | test_live_markup.py::test_s94_challenge_marker_classified_as_blocked (4 rows: ddos-guard, qrator, smart-captcha, Just a moment) | R77, R81 | green (SourceBlocked + алерт «блокировка/капча»; ddos-guard/qrator — живые challenge-фикстуры; фикстура `_challenge_page` исправлена 28.10 под F-22 — маркеры в структурных позициях, §0 «Статус I-3-fix») |
| @S95 | test_live_markup.py::test_s95_unparseable_cards_with_skeleton_raise_parse_error | R78 | green (граница `ParseError`/`EmptyResult` — регрессия R78 закрыта) |

I-3-fix-2 (контракт F-22/F-25 редакция 2, decisions §9.4 ред. 2 и §9.7 D7;
`tests/acceptance/test_challenge_normalization.py` и
`tests/acceptance/test_host_allowlist.py`; статус — §0 «Статус I-3-fix-2»):

| Сценарий | Тест (tests/acceptance/) | Риски | Статус |
|---|---|---|---|
| @S96 | test_challenge_normalization.py::test_s96_marker_outside_structural_position_never_blocks (6 rows: Qrator/заголовок, just a moment/описание, qrator/видимый текст, captcha/описание, access denied/видимый текст, captcha/JSON в `<script>`) | R81 | green (видимый текст/JSON-состояние никогда не блокируют: вакансии возвращаются и сохраняются, без алертов) |
| @S97 | test_challenge_normalization.py::test_s97_obfuscated_challenge_marker_still_detected (4 rows: SmartCaptcha, sm\<!--x--\>art-captcha, just&nbsp;a&nbsp;moment, ddos&#45;guard) | R81 | green (нормализация тела: разорванный/переиначенный маркер в структурной позиции → SourceBlocked + алерт «блокировка/капча») |
| @S98 | test_challenge_normalization.py::test_s98_weak_marker_blocks_only_in_title_or_h1 (4 rows: captcha/access denied × `<title>`/`<h1>`) | R81 | green (слабые маркеры — только `<title>`/`<h1>`) |
| @S99 | test_host_allowlist.py::test_s99_foreign_host_card_skipped_silently (4 rows по Examples: evil.example/career.habr.com для hh, evil.example/hh.ru для Habr) | R84 | green (чужой хост мимо кэша и дедупа, без алерта; в кэше — только 2 обычные карточки) |
| @S100 | test_host_allowlist.py::test_s100_only_foreign_host_cards_raise_parse_error | R84 | green (`ParseError` + алерт «ошибка разбора разметки», не `EmptyResult`, кэш пуст) |
| @S101 | test_host_allowlist.py::test_s101_subdomain_card_url_allowed (2 rows: spb.hh.ru, habr.com) | R84 | green (хост источника или поддомен → канонический URL в кэше, без алертов) |

Соответствие планируемых A-ID из реестра (перекрёстная таблица финальных имён):
A-COL-02↔S8, A-COL-03↔S10, A-COL-04↔S13/S14, A-COL-05↔S11/S51; A-DIG-01↔S27/S31,
A-DIG-02↔S34, A-DIG-03↔S31, A-DIG-04↔S32, A-DIG-05↔S35, A-DIG-06↔S45–S50,
A-DIG-07↔S36; A-FLT-02↔S21/S22/S25, A-FLT-03↔S23/S24; A-ALERT-01↔S56 (hh.ru),
A-ALERT-02↔S56 (ParseError), A-ALERT-03↔S57; A-DEGR-01↔S58; A-SCH-01↔S38,
A-SCH-02↔S39/S40, A-SCH-03↔S41/S42, A-SCH-04↔S36; A-SEND-01↔S59, A-SEND-02↔S60;
A-BTN-01↔S47/S49; A-UX-01↔S3/S4/S6, A-UX-02↔S2, A-UX-03↔S5; A-AS-01↔S67/S69,
A-AS-02↔S70; A-RET-01↔S61/S62; A-I18N-01↔S63–S66; A-PRESET-01↔S19/S26;
A-CFG-01↔S77; A-GUARD-01↔S73, A-GUARD-02↔S72.
I-2 (A-DLG-*): A-DLG-01↔S1 (RU) и S86 (EN), A-DLG-02↔S7/S89, A-DLG-03↔S79,
A-DLG-04↔S80, A-DLG-05↔S81, A-DLG-06↔S82/S83, A-DLG-08↔S3/S4/S6/S89;
A-DLG-09..A-DLG-12 (двойной тап/гонки, флуд callback'ами, интенсивный edit,
текст на кнопочном шаге) — планируются (см. §3.1 и реестр R63..R69).
I-3 (A-LIVE-*): A-LIVE-01↔S90, A-LIVE-02↔S91, A-LIVE-03↔S92, A-LIVE-04↔S93,
A-LIVE-05↔S94 (4 кейса + живые challenge-образцы), A-LIVE-06↔S95;
I-3-fix-2: A-LIVE-07↔S96, A-LIVE-08↔S97, A-LIVE-09↔S98, A-LIVE-10↔S99,
A-LIVE-11↔S100, A-LIVE-12↔S101;
U-COL-09..U-COL-13 — unit-обязательства software-engineer (реестр R74..R78).

## 2. Property-тесты (hypothesis, derandomize=True — фиксированный seed)

| ID | Тест (test_properties.py) | Риски | Статус |
|---|---|---|---|
| P-COL-01 | test_P_COL_01_collect_never_empty_never_unexpected_error | R1, R2, R40 | green |
| P-COL-02 | test_P_COL_02_fixture_artifacts_never_crash | R28 | green |
| P-SAL-01 | test_P_SAL_01_parse_and_format_salary_are_total | R8 | green |
| P-SAL-02 | test_P_SAL_02_boundary_amounts_normalize_safely | R22 | green |
| P-AGE-01 | test_P_AGE_01_age_forms_are_invariant | R23 | green |
| P-DIG-01 | test_P_DIG_01_digest_parts_bounded_and_split_on_card_boundaries | R4 | green |
| P-DIG-03 | test_P_DIG_03_truncate_title_never_breaks_html | R24 | green |
| P-DIG-04 | test_P_DIG_04_output_templates_byte_exact | R10, R36 | green |
| P-TEX-01 | test_P_TEX_01_esc_never_crashes_never_adds_markup | R7, R25 | green |
| P-UX-01 | test_P_UX_01_input_parsers_give_value_or_valueerror | R15 | green |
| P-UX-02 | test_P_UX_02_digest_size_bounds | R27 | green |
| P-SES-01 | test_P_SES_01_no_http_while_db_session_open | R31 | green |
| P-SEL-01 | test_P_SEL_01_delivery_at_most_once_per_user | R3 | green |
| P-SEL-02 | test_P_SEL_02_slot_processed_at_most_once | R32 | green |
| P-SEND-01 | test_P_SEND_01_dispatch_accounting_invariants | R9, R42 | green |
| P-BTN-01 | test_P_BTN_01_feedback_commands_total | R5, R26 | green |
| P-DED-01 | test_P_DED_01_canonical_url_and_normalize_text_invariants | R12 | green |
| P-SCH-01 | test_P_SCH_01_local_slot_and_key_invariants | R6 | green |
| P-AS-01 | test_P_AS_01_antispam_never_mutes_below_limit | R14 | green |
| P-I18N-01 | test_P_I18N_01_lang_dicts_parity_and_totality | R39 | green |
| P-DLG-01 | test_P_DLG_01_callback_data_round_trip_within_64_bytes + test_P_DLG_01_parse_is_total_and_whitelisted + test_P_DLG_01_encode_either_conforms_or_rejects (3 аспекта одного свойства) | R58, R59, R66 | green |
| P-DLG-02 | test_P_DLG_02_garbage_callback_polite_refusal_never_crashes | R56, R57, R63, R65, R66, R67 | green |

P-BTN-01 переписан под актуальный контракт (решение Q1): **в дайджесте кнопок
нет**, обратная связь — команды `/like|/dislike|/bookmark <n>` (актуализация
свидетельства — §6.13: `callback_data` с I-2 есть в диалоге настроек). Security-свойства
P-SEC-01..P-SEC-05 принадлежат security-engineer (tests/security) и здесь не дублируются.
P-SEL-01/02, P-SES-01 идут на модели Repo (InMemoryRepo/ProbeSessionFactory):
под тестом — логика `select_digest`/`check_schedules`/`run_collect`; гарантии
самого хранилища закрываются U-SEL-*/E2E-* (§3).

I-2 (диалог): P-DLG-01 — round-trip `encode_callback`/`parse_callback`
(форма `dlg:<step>:<value>`, ASCII, ≤ 64 байт, белый список шагов/грамматики;
контракт `app.bot.dialog` — §6.15; три функции-аспекта одного свойства),
P-DLG-02 — любой мусорный callback через BotHarness: вежливый отказ, ровно
один немедленный answer, без исключений и изменений состояния (hypothesis,
`derandomize=True`; мусор включает битые `dlg:tz:page-*`, NUL/RTL/суррогаты,
переполнение ≥64 байт). Соотношение с планом строк R55..R59: P-DLG-01 покрывает
планировавшийся P-DLG-03 (длина/грамматика), P-DLG-02 — планировавшийся
P-DLG-02; «клавиатура каждого шага содержит все допустимые значения»
(планировавшийся P-DLG-01) закрыто сценариями S82/S84/S89.

## 3. Полнота митигации high/medium рисков

Каждый риск score ≥ 3 имеет как минимум один acceptance/property/security-тест
(полная реализация по правилу глубины dev-cycles — scenario + unit [+ property]
для high — требует unit-тестов software-engineer, §4).

| Риск | Score | Acceptance / Property (qa) | Security | Unit / E2E (обязательства) |
|---|---|---|---|---|
| R1 | 9 | S10, S12, S51, S54, S56, S58, P-COL-01 | — | U-COL-03 |
| R2 | 6 | S8, S9, S15, S54, S56, P-COL-01 | — | U-COL-02 |
| R3 | 6 | S35, S43, P-SEL-01 | — | U-SEL-02 |
| R4 | 6 | S32, S33, S50, P-DIG-01, P-DIG-03 | — | U-DIG-03 |
| R5 | 6 | S45–S50, S53, P-BTN-01 | — | U-BTN-02 |
| R6 | 6 | S38–S42, P-SCH-01 | — | U-SCH-01 |
| R7 | 6 | S18, S34, S78, P-TEX-01 | SEC-01, SEC-02 | U-TEX-01 |
| R8 | 6 | S20–S22, S25, P-SAL-01 | — | U-SAL-01, U-SAL-02 |
| R9 | 6 | S59, P-SEND-01 | — | U-SEND-01 |
| R10 | 6 | S27–S29, S31, P-DIG-04 | — | — (шаблоны зафиксированы brief §6.1) |
| R31 | 6 | S17, S44, S74, P-SES-01 | — | U-SES-01, E2E-CONC-01 |
| R32 | 6 | S43, S44, P-SEL-02 | — | U-SEL-03, E2E-CONC-02 |
| R40 | 6 | S8, S11, S51, S56, P-COL-01 | — | U-COL-04 |
| R43 | 6 | (P-TEX-01 косвенно) | SEC-01/02/05, P-SEC-01/05 | U-TEX-03 (см. R38) |
| R44 | 6 | — | SEC-06, P-SEC-04 | — |
| R45 | 6 | S55 (наблюдаемое поведение) | SEC-07 | — |
| R46 | 6 | — | SEC-08 | — |
| R11 | 4 | S36, S41, S58 | — | U-DIG-06 |
| R12 | 4 | S13, S14, P-DED-01 | — | U-DED-01 |
| R13 | 4 | S20, S23, S24 | — | U-FLT-02 |
| R14 | 4 | S67–S69, P-AS-01 | — | U-AS-01 |
| R15 | 4 | S3, S4, S6, S47, P-UX-01 | SEC-09 | U-UX-01 |
| R16 | 4 | S57 | — | U-ALERT-01 |
| R17 | 4 | S53, S55, S70 | SEC-03, SEC-10 | U-AS-03 |
| R18 | 4 | S1, S2 | — | U-UX-03 |
| R22 | 4 | S6, S16, P-SAL-02 | — | U-SAL-03 |
| R23 | 4 | S30, P-AGE-01 | — | U-AGE-01 |
| R24 | 4 | S33, P-DIG-03 | — | U-DIG-05 |
| R25 | 4 | S18, S34, P-TEX-01 | SEC-09, P-SEC-01 | U-TEX-02 |
| R26 | 4 | S47, S49, P-BTN-01 | SEC-04 | U-BTN-01 |
| R27 | 4 | S5, S37, P-UX-02 | SEC-09 | U-UX-02 |
| R28 | 4 | S15, P-COL-02 | — | U-COL-05 |
| R29 | 3 | S72 | — | E2E-GUARD-01 |
| R30 | 4 | S77 | — | U-CFG-01 |
| R34 | 4 | S75 | — | U-SEL-04, E2E-PERF-01 |
| R35 | 4 | S12, S17 | — | U-COL-06, E2E-PERF-02 |
| R36 | 4 | S27, S31, P-DIG-04 | — | — |
| R37 | 4 | S76 | — | E2E-MIG-01 |
| R38 | 4 | S66, S78 | SEC-05 | U-TEX-03 |
| R41 | 4 | S73 | — | — (guard в тестовой обвязке) |
| R42 | 4 | S60, P-SEND-01 | — | U-SEND-02 |
| R47 | 4 | S18, P-TEX-01 | SEC-09, P-SEC-01/02/05 | — |
| R48 | 4 | S67–S70, P-BTN-01, P-AS-01 | SEC-03/04/10 | — |
| R49 | 4 | — | SEC-11 (dependency-scan, отложен — см. docs/security/report.md) | devops-sre (CI) |
| R50 | 4 | — | SEC-12, P-SEC-03 | — |
| R51 | 4 | — | SEC-13, P-SEC-02 | — |

Низкие (score ≤ 2) также покрыты: R19 (S61/S62), R20 (S63/S64/S66), R21 (S19/S26),
R33 (S69/S71), R39 (S65, P-I18N-01), R52 (SEC-14). R5 (resolved решением Q1) —
остаточный риск команд закрыт S45–S50 + P-BTN-01 (+ E2E-BTN-01).

### 3.1 Полнота митигации рисков I-2 (R55..R69)

Риски кнопочного диалога (brief §4.3, AC-21..AC-24). Acceptance/property-тесты
qa-engineer написаны (red-этап); unit U-DLG-* — обязательства software-engineer;
SEC-15/P-SEC-06 — security-engineer (`tests/security/`, R60..R62 реестра).

| Риск | Score | Acceptance / Property (qa) | Security | Unit / доп. (обязательства) |
|---|---|---|---|---|
| R55 | 6 | S1, S7, S86, S89 (A-DLG-01/02/08), P-DLG-01 | — | U-DLG-01 |
| R56 | 4 | S79 (A-DLG-03), P-DLG-02 | — | U-DLG-02 |
| R57 | 6 | S80, S81 (A-DLG-04/05), P-DLG-02 | SEC-15 (строка R60) | U-DLG-03 |
| R58 | 4 | S82, S83 (A-DLG-06), P-DLG-02 | — | U-DLG-04 |
| R59 | 4 | S84, P-DLG-01 | SEC-15 (строка R61) | U-DLG-05 |
| R63 | 4 | S82, S80/S81, P-DLG-02 | — | U-DLG-06, A-DLG-09 (планир.) |
| R64 | 4 | S87, S80, P-DLG-02 | — | — |
| R65 | 4 | S67, S70, P-DLG-02 | SEC-15 (строка R62) | U-DLG-07, A-DLG-10 (планир.) |
| R66 | 4 | S89, S88, P-DLG-02 | — | — |
| R67 | 4 | S79, P-DLG-02 | — | U-DLG-08 (планир.) |
| R68 | 4 | S82, P-DLG-02 | — | U-DLG-09, A-DLG-11 (планир.) |
| R69 | 6 | S87, S89, S88, S3/S4/S6 (A-DLG-08), P-DLG-02 | — | A-DLG-12 (планир.; сценарий AC-24 у BA — §6.16) |

R60..R62 (security-строки реестра) митигируются SEC-15/P-SEC-06
(security-engineer); их поведенческое дублирование на уровне acceptance —
S80/S81 (чужой/устаревший callback), S84/S85 (инъекция/экранирование),
S88/P-DLG-02 (мусор), S67/S70 (лимиты).

**Финальные статусы I-2 (QA gate 28.10):** R55..R62 — `covered`, R63..R69 —
`covered` (R69 — с пометкой по глубины: ветка «текст на кнопочном шаге»
реализована и проверена, постоянного теста нет — A-DLG-12 → I-3); R70 (F-15) —
`covered`, R71 (F-16) — `covered`, R72 (F-18) — `accepted`, R73 (F-19) —
`open` (обе low, бэклог I-3). Дрифт ID юнит-обязательств: плановые U-DLG-03/05
фактически закрыты U-DLG-01/02/05, U-DLG-06/07 реализованы, U-DLG-08/09 —
частично U-SEC-03, полностью → I-3. Подробности — реестр, блок
«Примечания QA gate I-2».

### 3.2 Полнота митигации рисков I-3 (R74..R78)

Риски живой разметки источников (prod-баг I-3). Acceptance-тесты qa-engineer
написаны (red-этап 28.10, `tests/acceptance/test_live_markup.py`); unit
U-COL-09..U-COL-13 — обязательства software-engineer; фикстуры живых образцов
(`tests/data/*_live_list.html`, `*_challenge.html`) — тоже software-engineer
(политика решений §9.2, шапка файла обязательна).

| Риск | Score | Acceptance / Property (qa) | Security | Unit / доп. (обязательства) |
|---|---|---|---|---|
| R74 | 9 | S90, S91 (A-LIVE-01/02), S95 (A-LIVE-06), P-COL-01 | — | U-COL-09 (fallback-цепочки маркеров), фикстуры живых образцов |
| R75 | 4 | S92 (A-LIVE-03), P-DED-01 | — | U-COL-10 (D6: промо-карточка пропускается) |
| R76 | 4 | S93 (A-LIVE-04), P-AGE-01 | — | U-COL-11 (D5: дата → время сбора) |
| R77 | 6 | S94 (A-LIVE-05, 4 кейса + живые challenge-образцы) | — | U-COL-12 (детект challenge во всём теле, 403/429) |
| R78 | 6 | S90, S91 (живые фикстуры вместо самосогласованных), S95 (A-LIVE-06), S94, S92 | — | U-COL-13 (граница `ParseError`/`EmptyResult`), шапки старых синтетических фикстур — regression-only |

Финальные статусы (зелёный проход 28.10.2026, 467 passed): все R74..R78 —
`covered` — acceptance S90..S95 зелёные, unit U-COL-09..U-COL-13 и фикстуры
живых образцов реализованы (software-engineer), property P-COL-01/P-DED-01/
P-AGE-01 зелёные.

### 3.3 Полнота митигации рисков I-3-fix (R79..R84, findings F-20..F-25)

Риски security review hardening коллекторов (I-3-fix). Митигирующие тесты
написаны и зелёные: unit U-COL-14..U-COL-19 (`tests/unit/test_collectors_hardening_unit.py`,
software-engineer; внутри U-COL-15/U-COL-17 — property-циклы на произвольных
значениях), property P-SEC-08/P-SEC-09 (hypothesis, `derandomize=True`,
`tests/security/test_untrusted_html_parsers.py`, security-engineer), acceptance
A-LIVE-* (S90..S95, `tests/acceptance/test_live_markup.py`, qa-engineer).

| Риск | Score | Acceptance / Property (qa) | Security | Unit / доп. (обязательства) |
|---|---|---|---|---|
| R79 (F-20) | 9 | A-LIVE-01/02/05 (S90/S91/S94 — живая разметка и challenge-образцы разбираются в мс) | P-SEC-08, P-SEC-09 (произвольные payload → без крашей/квадратики) | U-COL-14 (патологические тела < 1.0s) |
| R80 (F-21) | 4 | A-LIVE-01 (S90 — зарплата из `<data value>`) | — | U-COL-15 (мусорные/гигантские `value` → контрактная ошибка или `salary=None`, границы int64) |
| R81 (F-22) | 6 | A-LIVE-05 (S94 ×4 + живые challenge-образцы; фикстура — структурные позиции, §0 «Статус I-3-fix»), A-LIVE-07/08/09 (S96..S98 — видимый текст/JSON не блокирует, разорванные маркеры детектятся, слабые — `<title>`/`<h1>`; §0 «Статус I-3-fix-2») | P-SEC-08 (произвольный текст в видимых полях → вакансии или контрактная ошибка, без ложного блока) | U-COL-16 (разорванные маркеры в структурных позициях блокируют; видимый текст — никогда; слабые — `<title>`/`<h1>`) |
| R82 (F-23) | 4 | A-LIVE-04 (S93 — `published_at` = момент сбора) | P-SEC-09 (произвольный datetime-атрибут → без крашей, tz-aware) | U-COL-17 (будущее > now+сутки и мусор → момент сбора) |
| R83 (F-24) | 4 | A-DEGR-01 (S56/S58 — `SourceUnavailable` → алерт «источник недоступен») | — | U-COL-18 (cap 5 МиБ → отказ `SourceUnavailable`, ограниченное чтение `AiohttpClient.get`) |
| R84 (F-25) | 4 | A-LIVE-03 (S92 — промо/чужой URL мимо кэша и дедупа), A-LIVE-10/11/12 (S99..S101 — чужой хост молча, страница из чужих → `ParseError`, поддомены разрешены; §0 «Статус I-3-fix-2») | SEC-12 (dangerous hrefs — security-engineer) | U-COL-19 (allowlist хостов hh/Habr; чужой хост — пропуск молча) |

Финальные статусы (прогон 28.10.2026, `pytest tests/acceptance` → 205 passed,
полный `pytest` → 498 passed): все R79..R84 — `covered`; глубина «high =
scenario + unit + property» выполнена для R79 (U-COL-14 + P-SEC-08/09 + S90..S94)
и R81 (U-COL-16 + P-SEC-08 + S94). Замечание: cap-триггер R83 проверен unit-слоем
(U-COL-18); scenario-слой — классификация `SourceUnavailable` (S56/S58).

## 4. Обязательства software-engineer (только unit — U-*)

Правило глубины: high-риски требуют scenario + unit + property, medium —
scenario + unit. Ниже — все U-ID из реестра; их пишет software-engineer в
`tests/unit/` (TDD), они ещё не существуют и обязательны к зелёному QA gate:

- **U-COL-02, U-COL-03, U-COL-04, U-COL-05, U-COL-06** — парсеры: вёрстка,
  SourceBlocked, EmptyResult (не молчать), файловые артефакты, тяжёлые страницы.
- **U-DIG-03, U-DIG-05, U-DIG-06** — разбивка ≤4096, обрезка {title}, пустой дайджест.
- **U-SCH-01** — слоты/DST (local_slot/slot_key).
- **U-SAL-01, U-SAL-02, U-SAL-03** — сравнение зарплат, курсы, граничные значения.
- **U-AGE-01** — границы возраста 0/1/2+.
- **U-SEL-02, U-SEL-03, U-SEL-04** — at-most-once доставки, claim_slot, производительность выборки.
- **U-TEX-01, U-TEX-02, U-TEX-03** — esc/esc_attr, гигантский текст, обязательность esc на путях вывода.
- **U-FLT-02** — семантика must/nice/stop-слов.
- **U-AS-01, U-AS-02, U-AS-03** — лимиты/мьют, in-memory счётчики, злоупотребления.
- **U-ALERT-01** — агрегация алертов (окно 1 час, счётчик подавленных).
- **U-RET-01** — retention-граница «строго старше 30 дней».
- **U-UX-01, U-UX-02, U-UX-03** — валидация ввода, границы digest_size 1..50, незавершённый /start.
- **U-SEND-01, U-SEND-02** — троттлинг/ретраи FloodWait, изоляция ошибок получателей.
- **U-BTN-01, U-BTN-02** — валидация n команд обратной связи, upsert feedback.
- **U-DED-01** — дедупликация (canonical_url / dedup_key).
- **U-CFG-01** — падение при неполной конфигурации env.
- **U-I18N-01** — паритет ключей RU/EN (дублирует P-I18N-01 на unit-уровне, как в реестре).
- **U-SES-01** — короткие сессии Repo (без HTTP внутри).

E2E-обязательства (tests/e2e, software-engineer): E2E-GUARD-01, E2E-CONC-01,
E2E-CONC-02, E2E-PERF-01, E2E-PERF-02, E2E-MIG-01, E2E-BTN-01.

## 5. Краснота: причины падений (факт, этап до реализации — история)

`pytest tests/acceptance -q` → 176 failed. Сплошная причина — `NotImplementedYet`:
- «модуль tests.e2e.helpers ещё не реализован» (BotHarness) — 56 кейсов;
- «модуль app.services.* ещё не реализован» (digest/select/scheduler/collect/dispatch) — 40+;
- «модуль app.domain.* ещё не реализован» (currency/profile) — 33;
- «модуль app.collectors ещё не реализован» — 17; «app.filters.rules» — 8;
  «app.config» — 6; «app.textutil» — 4; «app.i18n» — 2;
- «фикстура tests/data/{hh,habr}_empty.html ещё не добавлена» — 9.
Ни одного падения из-за синтаксиса, импорта, фикстур pytest или ошибок самих тестов.

## 6. Договорённости и открытые вопросы (для BA / software-engineer)

Зафиксировано здесь, т.к. спека (api.md) в этих местах молчит; тесты задают
наблюдаемый контракт. Расхождения фиксировать в `docs/spec/decisions.md` (R36):

1. **BotHarness (tests/e2e/helpers.py, threat-model §5.8) — обязательный API:**
   `send(text, user_id=...)` / `sent()` (закреплено §5.8) **+ расширения**:
   `seed_vacancies(vacancies)` (положить вакансии в кэш бота),
   `deliver_digest(user_id=...) -> messages` (доставить очередной дайджест сейчас),
   `set_client(client)` (подмена HTTP-клиента; S54). Без них сценарии «получил
   дайджест» (S45–S50, S63, S68–S70) невоспроизводимы через минимальный `send/sent`.
   BotHarness обязан использовать только тестовый HTTP-клиент (без сети, R41) и
   тестовую БД.
2. **Протокол диалога настроек (S1–S7):** `/settings` показывает текущие
   настройки; `/settings time|tz|size|salary|preset|stop|lang` открывают шаг,
   значение — следующим сообщением; выбор языка при `/start` — `lang:{code}`
   (текстовая форма для BotHarness). Формат ответа `/settings` не зафиксирован —
   тесты проверяют подстроки.
3. **Формат `/admin_stats` / `/admin_health` не зафиксирован** — тесты парсят
   строки с метками `like|dislike|bookmark` и источниками; BA зафиксировать формат.
4. **Repo: нет метода перечисления пользователей** (api.md §9), хотя
   `check_schedules` обязан обходить подписчиков — требуется `list_users()`
   (InMemoryRepo его предоставляет).
5. **Repo.record_parse_run не принимает `now`** — метки времени сбора пишутся
   «серверным» временем, а окно алертов считается от инжектированного `now`;
   S57 намеренно якорится на реальное время. Уточнить контракт.
6. **Слот после DST-«дыры»** (S39): «первый существующий момент после дыры» —
   тест проверяет «не раньше 03:00 локального времени»; ровно 03:00 или 03:30
   (сдвиг 02:30) — зафиксировать владельцу.
7. **Ошибка FloodWait** — duck-typing: исключение с атрибутом `retry_after`
   (как aiogram `TelegramRetryAfter`); зафиксировать тип в api.md §13.
8. **Антиспам берёт время из `time.monotonic()`/`time.time()`** (S69 управляет
   временем их подменой); альтернатива — injectable clock в api.md.
9. **Фикстуры `tests/data/`** (владелец — software-engineer): `hh_list.html`,
   `habr_list.html` (валидные списки вакансий), `hh_empty.html`, `habr_empty.html`
   (валидный скелет страницы без карточек). Отсутствие фикстуры = внятный красный.
10. **S15/S16/S18** — отображение сценария на контракт: артефакты «файлов»
    моделируются текстовыми телами ответов (коллекторы файлы не читают);
    нормализация зарплаты (S16) проверяется через `parse_salary` (HTML-структура
    источника не зафиксирована); S18 — через путь рендер/`esc` (ограничение длины
    company/description при нормализации BA не зафиксировано).
11. **S72**: subprocess-запуск «чистой команды» ограничен модулем
    `tests/test_smoke.py` (полный `pytest` в подпроцессе ушёл бы в рекурсию);
    guard (`tests/conftest.py`, обязательство devops/software) обязан срабатывать
    до выполнения любых тестов.
12. **Фильтры**: пустые поля `PresetFilter` (role="", must=[]) трактуются как
    «всё проходит» — это используется в тестовых фильтрах; зафиксировать в api.md §7.
13. **Свидетельство I-1 «в `app/` нет `InlineKeyboard`/`callback_data`» устарело
    для ДИАЛОГА** (decisions §8.8): с I-2 диалог использует инлайн-кнопки
    `dlg:<step>:<value>`. **В силе для ДАЙДЖЕСТА (Q1):** в `app/services/digest.py`
    и рассылке inline-кнопок нет, обратная связь — команды. Рекомендуемая
    формулировка свидетельства — decisions §8.8 п.2.
14. **BotHarness I-2** (`tests/e2e/helpers.py`, владелец — software-engineer):
    `press(callback_data, *, user_id) -> list[str]`, `keyboard() ->
    list[(метка, callback_data)]`, `events() -> [("answer", CallbackAnswer) |
    ("send"|"edit", text)]` — точный контракт в докстринге `tests/acceptance/dialog.py`.
    **Реализован (I-2):** acceptance-тесты S79..S89 и обновлённые
    S1/S4/S5/S7/S45–S50/S52/S53/S63/S64/S68–S70, P-BTN-01, P-DLG-02 — зелёные
    (QA gate 28.10, 445 passed).
15. **`app.bot.dialog`** (владелец — software-engineer; требуется P-DLG-01):
    `encode_callback(step, value) -> str` (ValueError вне грамматики) и
    `parse_callback(data) -> tuple[str, str] | None` (тотален: None либо белый
    список шагов + грамматика значения). Семантическая валидация значений
    (size ∈ {5,10,20,50}, известные коды пресетов) — в обработчике callback
    (S88/P-DLG-02). api.md §15.1 место реализации не фиксирует — контракт
    модуля предложен qa-engineer, подтвердить software-engineer/BA.
    **Реализован (`app/bot/dialog.py`, I-2):** P-DLG-01 (3 аспекта) и
    U-DLG-01/02/05 зелёные.
16. **Gap к BA (актуален, I-3):** AC-24 «текст на кнопочном шаге не применяется — бот
    переотправляет подсказку шага с клавиатурой» (кроме шага `tz`) реализован
    (`app/bot/core.py:500`) и проверен разовым QA-скриптом 28.10 (тексты
    `python-backend`/`lang:ru`/`15` на кнопочных шагах не применяются,
    переотправляется подсказка с клавиатурой; профиль не меняется), но
    сценарного теста нет: митигация R69 — планируемый A-DLG-12. Нужен сценарий
    business-analyst (строка переотправки — подсказка шага из brief §6.1) —
    затем тест qa-engineer. То же — пункт AC-21 «прежний текстовый ввод
    упразднён».
17. **Теги `@R60..@R62` в feature-файлах провизорные** и НЕ равны строкам
    R60..R62 реестра (заняты security-строками security-engineer'а; технические
    строки qa-engineer — R63..R69) — перепривязку тегов выполняет
    business-analyst (см. предупреждение в `docs/risk-register.md`).
18. **Формат сообщений шагов** (подтверждение + следующий шаг одним сообщением
    или разными) спека не фиксирует — тесты проверяют подтверждения точными
    строками brief §6.1, заголовки шагов — подстроками.

## 7. Правки acceptance-тестов после ревью арбитра (27.10.2026)

Прогон `.venv/bin/python -m pytest` до правок: 302 passed, **9 failed** — все 9
падений были дефектами самих acceptance-тестов (production соответствует спеке;
решение арбитра — brief §6.1 / decisions.md побеждают). Правки (без ослабления
проверок, без skip/xfail; production-код не менялся):

1. **@S30 (6 кейсов параметризации)** — знаковая ошибка: `published_at = NOW -
   timedelta(hours=delta_hours)` при `delta_hours < 0` давало БУДУЩЕЕ для
   «вчера/2 дн./5 дн.». Параметризация приведена к примерам @S30
   (`digest_splitting.feature`): сдвиг > 0 — в прошлое («вчера» = 24 ч,
   «2 дн.» = 48 ч, «5 дн.» = 120 ч), «в будущем (смещение tz)» = −3 ч →
   «сегодня»/`today`. Обоснование: decisions §5.6 (будущее → k = 0 → «сегодня»),
   brief §6.1 (`{age}`), Examples @S30.
2. **@S33** — тест брал `parts[0].split("\n", 1)[0]` и требовал `1. <b>…`,
   но первая часть начинается с заголовка «🔥 Подборка вакансий — …» (brief
   §6.1 «Сообщение дайджеста (первая часть)»; то же требуют S31/S32/S38).
   Исправлено: строка карточки ищется после заголовка (первая строка вида
   `{n}. <b>`); добавлена проверка точного заголовка `🔥 Подборка вакансий —
   14.03.2026 (1)`. Остальные проверки (≤200 code points, «…», целостность
   сущностей, ≤4096) не тронуты.
3. **P-SEL-01, P-SEL-02, S38–S42** — недосев фикстуры: `InMemoryRepo` без
   пресетов всегда даёт пустой список кандидатов (api.md §9: «фильтр хотя бы
   одного подписанного пресета»). В setup добавлены пресет и подписка
   (permissive-фильтр, как в S35/S43/S44): S38–S42 — в общий `_seed_vacancy`
   (общая фикстура; проверки не менялись), P-SEL-01/P-SEL-02 — в setup теста.
   Подписка — `make_profile()` (`presets=["python-backend"]`).
4. Ослаблений assert'ов, skip/xfail не добавлялось (проверено grep: 0 вхождений
   в изменённых файлах; изменения только аддитивные + исправления по п.1–2).

**Наблюдение (flaky, не дефект продукта):** при параллельной работе агентов
общая тестовая БД `jobs_test` используется несколькими прогонами одновременно —
`s75`/`s76` (и ранее `test_secrets.py`) в отдельных прогонах падали сигнатурами
межпроцессной гонки (FK `digest_slots_user_id_fkey`, `table "digest_slots" does
not exist`, `duplicate key ... "presets_pkey"` при `alembic upgrade head`);
в тихом окне весь набор зелёный (316 passed). Рекомендация владельцу
инфраструктуры (devops-sre): изоляция БД на прогон (суффикс run-id) или
сериализация прогонов.

### Правки обвязки test_live_markup.py (28.10.2026, I-3)

Прогон `.venv/bin/python -m pytest` до правок: 465 passed, **2 failed** — оба
падения были дефектами обвязки acceptance-тестов (production доказуемо корректен:
с исправленной обвязкой все проверки зелёные без изменений кода). Правки
(без ослабления assert'ов, без skip/xfail; production-код и другие тесты
не менялись):

1. **@S93** — `TypeError: _run_collect() got an unexpected keyword argument
   'now'`: хелпер `_run_collect` не принимал `now` (по образцу
   `test_alerts_degradation.py:82`). Добавлен параметр `now: datetime = NOW`
   с пробросом в `run_collect`; проверки S93 (`published_at == NOW`,
   «сегодня»/«today») не менялись.
2. **@S92** — сравнение `sorted(title for v in repo.vacancies)` с ожиданиями hh
   не учитывало валидный второй источник (habr), который тест сам подключает и
   который по api.md §10 пополняет общий кэш. Добавлен фильтр по источнику
   `[v for v in repo.vacancies if v.source == SOURCE_HH]` (как в S93/S95);
   остальные проверки S92 не тронуты.
3. Ослаблений assert'ов, skip/xfail не добавлялось (правки только в двух
   указанных местах; фильтр по источнику делает проверку S92 корректной, а не
   мягче — лишние вакансии второго источника больше не ломают ожидание hh).

## 8. Компромисс обрезки `{title}` (R24 / P-DIG-03) — зафиксировано

Реализация (software-engineer, `app/services/digest.py`): обрезка применяется к
экранированному заголовку длиной **> 800 code points** (`TITLE_TRIGGER`) и режет
до **200 code points** с «…» (`TITLE_LIMIT`, механика — decisions §5.7: по
экранированному тексту, без разрыва сущностей, итог ≤ 200 включая «…»).

Покрытие тестами: **@S33** (триггер на примере feature: заголовок 400 символов с
HTML-сущностями → 900 экр. code points > 800 → обрезан до 200 с «…», часть ≤4096,
сущности целы); **P-DIG-03** (механика `truncate_title`: ≤200, «…», сущности,
валидный HTML, короткие не трогаются); **P-DIG-04** (заголовки ≤ ~700 экр. символов
не обрезаются — карточка байт-в-байт по шаблону brief §6.1); S18 (гигантский текст).

Соответствие спеке: наблюдаемое поведение совпадает с примером @S33 и
brief §6.1 («Если одна карточка не влезает — `{title}` обрезается до 200
символов с `…`» — гарантия выполняется: после обрезки карточка короткая).
**Открытый вопрос к BA** (не блокирует, не противоречие): триггер обрезки в
brief §6.1 сформулирован условием «если карточка не влезает», а порог
`TITLE_TRIGGER = 800` — реализация; пример @S33 требует обрезки и для карточки,
которая влезает. Зафиксировать порог (или правило «title > 800 экр. → 200») в
decisions §5.7. Сопутствующее наблюдение: «остальные поля гарантированно короткие»
(decisions §5.7) нормализацией не ограничены (см. §6.10) — карточка с гигантским
`{company}` не обрезается и даёт `DigestError` (сообщение не отправляется —
безопасный отказ, но не «обрезка title»); наблюдение для BA/software-engineer.
*(Обновление BA 27.10: вопросы §8 и §6.10 урегулированы в `decisions.md` §7 п.1 —
компромисс узаконен, `company`/`description` клампятся до 100 code points на
нормализации (`clamp_text`, `U-COL-07/08`).)*

## 9. Финальные R-статусы (I-1 — QA gate 27.10.2026; I-2 — 28.10.2026)

Статусы проставлены qa-engineer по прогону 27.10 (`329 passed`, §0) и отражены
в `docs/risk-register.md`. Легенда: **covered** — митигирующие тесты написаны и
проходят; **accepted-residual** — принятое остаточное ограничение (митигация не
является автотестом); **resolved** — закрыт решением владельца.

| Группа | Риски | Статус |
|---|---|---|
| High (score ≥ 6) | R1, R2, R3, R4, R6, R7, R8, R9, R10, R31, R32, R40, R43, R44, R45, R46 | covered |
| Medium | R11, R12, R14, R15, R16, R17, R18, R22–R30, R34–R38, R41, R42, R47, R48, R50, R51, R53, R54 | covered |
| Medium (с пометкой) | R13 | covered (unit-слой U-FLT-02 отложен в I-2 — вердикт §7.3; сценарный уровень S20/S23/S24 зелёный) |
| Medium (остаток) | R49 (уязвимые зависимости) | accepted-residual (SEC-11 — процессный скан `pip-audit`, не автотест; пины чисты; постоянный CI dependency-scan вне объёма I-1, owner devops-sre → I-2) |
| Low | R19, R20, R21, R33, R39, R52 | covered |
| Решение владельца | R5 | resolved (Q1; остаток команд — S45–S50 + P-BTN-01 + E2E-BTN-01) |

Итог (I-1): 0 рисков в `open`; high/critical security-находок нет (F-05 low — доки,
owner BA, вердикт §7.1). Неблокирующие остатки и их владельцы — `docs/qa/verdict.md` §7.

### I-2 (QA gate 28.10.2026, 445 passed)

| Группа | Риски | Статус |
|---|---|---|
| High I-2 | R55, R57, R69 | covered (R69 — с пометкой: ветка «текст на кнопочном шаге» реализована (core.py:500), постоянного теста нет — A-DLG-12 → I-3; глубина как scenario + property) |
| Medium I-2 (диалог) | R56, R58, R59, R63, R64, R65, R66, R67, R68 | covered |
| Medium I-2 (callback-канал, security) | R60, R61, R62 | covered (SEC-15 + P-SEC-06 зелёные; F-14..F-17 fixed с постоянными контрпримерами) |
| Medium I-2 (F-15) | R70 | covered (fixed 28.10 «диалог только в личке», fail-closed; 4 теста `test_F15_*`) |
| Low I-2 (F-16) | R71 | covered (fixed 28.10, крыши памяти; 3 теста `test_F16_*` + U-SEC-06) |
| Low I-2 (F-18) | R72 | accepted (остаток `_states` без TTL — бэклог I-3, owner software-engineer + security-engineer) |
| Low I-2 (F-19) | R73 | open (NUL в имени пресета → asyncpg-ошибка — бэклог I-3, owner software-engineer + security-engineer) |

### I-3 (QA gate 28.10.2026, 519 passed)

| Группа | Риски | Статус |
|---|---|---|
| High I-3 (живая разметка) | R74, R77, R78 | covered (глубина scenario + unit + property: S90..S95 + U-COL-09/12/13 + P-COL-01; R77 дополнительно P-SEC-08) |
| Medium I-3 (живая разметка) | R75, R76 | covered (S92/S93 + U-COL-10/11 + P-DED-01/P-AGE-01) |
| High I-3-fix (F-20) | R79 | covered (S90/S91/S94 + U-COL-14 + P-SEC-08/09; замеры 8.5 мин → 0.7 мс — report §10.4) |
| Medium I-3-fix (F-21/F-23/F-24) | R80, R82, R83 | covered (S90/S93/S56/S58 + U-COL-15/17/18 + P-SEC-09) |
| High I-3-fix (F-22) | R81 | covered (S94 + S96..S98 + U-COL-16 + P-SEC-08) |
| Medium I-3-fix (F-25) | R84 | covered (S92 + S99..S101 + U-COL-19 + SEC-12) |

Итог (I-3): `open` по I-3 — нет; все R74..R84 — `covered`; high/critical
security-находок нет (F-20 fixed с замерами; F-05 low — документационная,
owner BA). Остатки и владельцы — `docs/qa/verdict.md`, секция I-3 §7
(основной: перепривязка тегов `@R77/@R79/@R80` у S96..S101 → `@R81`/`@R84`,
owner business-analyst). R73 (low, I-2) остаётся `open` — бэклог
(software-engineer + security-engineer).
