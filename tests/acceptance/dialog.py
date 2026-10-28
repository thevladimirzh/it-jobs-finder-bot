"""Кнопочный диалог настроек (I-2): точные строки и обвязка acceptance-тестов.

Владелец: qa-engineer. Источник истины по строкам и кнопкам —
``docs/product/brief.md`` §6.1 «Диалог на инлайн-кнопках (I-2)» (копируются
дословно); механика callback — ``docs/spec/api.md`` §15.1 и
``docs/spec/decisions.md`` §8; сценарии — ``tests/features/dialog_callbacks.feature``
(S79..S89) и ``tests/features/onboarding_settings.feature`` (S1..S7).

Контракт обвязки BotHarness для I-2 (договорённость QA↔SE, фиксируется в
``docs/qa/acceptance-map.md`` §6.2; реализует software-engineer в
``tests/e2e/helpers.py``):

- ``press(callback_data, *, user_id) -> list[str]`` — доставить callback_query;
  возвращает тексты отправленных/отредактированных сообщений (toast в них
  не входит);
- ``keyboard() -> list[tuple[str, str]]`` — кнопки ``(метка, callback_data)``
  последнего отправленного/отредактированного сообщения (пусто, если нет
  клавиатуры);
- ``events() -> list[tuple[str, Any]]`` — упорядоченный журнал событий сессии:
  ``("answer", CallbackAnswer(text, show_alert))`` / ``("send", text)`` /
  ``("edit", text)``; payload события ``answer`` — объект с атрибутами
  ``.text``/``.show_alert`` либо кортеж ``(text, show_alert)``.

Пока методы BotHarness не реализованы, помощники падают внятным
``NotImplementedYet`` (краснота — не ошибкой импорта/атрибута).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from fakes import send_text
from support import NotImplementedYet

# ---------------------------------------------------------------------------
# Точные строки (brief §6.1 «Диалог на инлайн-кнопках (I-2)») — дословно
# ---------------------------------------------------------------------------

GREETING = (
    "Привет! Я присылаю подборку IT-вакансий.\n"
    "Hi! I will send you a daily IT jobs digest.\n"
    "Выберите язык / Choose your language:"
)

LANG_HEADER = {"ru": "Выберите язык:", "en": "Choose a language:"}
LANG_SAVED = {"ru": "Язык сохранён.", "en": "Language saved."}

PRESET_HEADER = {
    "ru": "Выберите роли — можно несколько. Выбранные отмечены ✅. "
    "Когда закончите, нажмите «Готово».",
    "en": "Pick roles — you can choose several. Selected roles are marked ✅. "
    'Press "Done" when you are finished.',
}
PRESET_SAVED = {"ru": "Подписка сохранена.", "en": "Subscription saved."}
PRESET_EMPTY = {"ru": "Выберите хотя бы один пресет.", "en": "Pick at least one preset."}

FORMAT_HEADER = {"ru": "Формат работы:", "en": "Work format:"}
FORMAT_SAVED = {"ru": "Формат работы сохранён.", "en": "Work format saved."}

TZ_HEADER = {
    "ru": "Выберите город или укажите смещение UTC вручную:",
    "en": "Pick a city or set a UTC offset manually:",
}
TZ_MANUAL_PROMPT = {
    "ru": "Введите смещение UTC (например: UTC+3).",
    "en": "Send a UTC offset (e.g. UTC+3).",
}
TZ_SAVED = {"ru": "Таймзона сохранена.", "en": "Timezone saved."}

TIME_HEADER_RU = "Отправьте время дайджеста в формате ЧЧ:ММ (например: 09:30)."
PROMPT_SALARY_RU = "Отправьте минимальную зарплату в рублях (например: 150000)."
PROMPT_STOP_RU = "Отправьте стоп-слово для фильтрации вакансий."
TIME_SAVED = {"ru": "Время дайджеста сохранено.", "en": "Digest time saved."}

SIZE_HEADER = {"ru": "Размер дайджеста:", "en": "Digest size:"}
SIZE_SAVED = {"ru": "Размер дайджеста сохранён.", "en": "Digest size saved."}

DONE_ONBOARDING = {
    "ru": "Готово! Подборка придёт в выбранное время.",
    "en": "All set! Your digest will arrive at the chosen time.",
}

OUTDATED = {
    "ru": "Эта кнопка устарела. Откройте настройки заново (/settings).",
    "en": "This button is outdated. Open settings again (/settings).",
}

# ---------------------------------------------------------------------------
# Кнопки (brief §6.1): метка → callback_data
# ---------------------------------------------------------------------------

LANG_BUTTONS = {"Русский": "dlg:lang:ru", "English": "dlg:lang:en"}

PRESET_BUTTONS_RU = {
    "Python Backend": "dlg:preset:python-backend",
    "Frontend": "dlg:preset:frontend",
    "DevOps/SRE": "dlg:preset:devops-sre",
    "Data/ML": "dlg:preset:data-ml",
    "QA": "dlg:preset:qa",
    "Mobile": "dlg:preset:mobile",
    "Другие backend-языки": "dlg:preset:backend-other",
    "Готово": "dlg:preset:done",
}
PRESET_BUTTONS_EN = {
    "Python Backend": "dlg:preset:python-backend",
    "Frontend": "dlg:preset:frontend",
    "DevOps/SRE": "dlg:preset:devops-sre",
    "Data/ML": "dlg:preset:data-ml",
    "QA": "dlg:preset:qa",
    "Mobile": "dlg:preset:mobile",
    "Other backend languages": "dlg:preset:backend-other",
    "Done": "dlg:preset:done",
}

FORMAT_BUTTONS_RU = {
    "Удалёнка": "dlg:format:remote",
    "Гибрид": "dlg:format:hybrid",
    "Офис": "dlg:format:office",
    "Не важно": "dlg:format:any",
}
FORMAT_BUTTONS_EN = {
    "Remote": "dlg:format:remote",
    "Hybrid": "dlg:format:hybrid",
    "Office": "dlg:format:office",
    "Any": "dlg:format:any",
}

SIZE_BUTTONS = {"5": "dlg:size:5", "10": "dlg:size:10", "20": "dlg:size:20", "50": "dlg:size:50"}

TZ_MANUAL_LABEL = {"ru": "Указать UTC offset вручную", "en": "Set UTC offset manually"}
NAV_NEXT_LABEL = "➡️"
NAV_PREV_LABEL = "⬅️"

SELECTED_PREFIX = "✅ "  # префикс метки выбранного пресета

# Кнопки-города: slug, RU, EN, IANA (brief §6.1, таблица шага `tz`)
CITIES = (
    ("msk", "Москва", "Moscow", "Europe/Moscow"),
    ("spb", "Санкт-Петербург", "Saint Petersburg", "Europe/Moscow"),
    ("ekb", "Екатеринбург", "Yekaterinburg", "Asia/Yekaterinburg"),
    ("nsk", "Новосибирск", "Novosibirsk", "Asia/Novosibirsk"),
    ("kzn", "Казань", "Kazan", "Europe/Moscow"),
    ("nnv", "Нижний Новгород", "Nizhny Novgorod", "Europe/Moscow"),
    ("chel", "Челябинск", "Chelyabinsk", "Asia/Yekaterinburg"),
    ("sam", "Самара", "Samara", "Europe/Samara"),
    ("omsk", "Омск", "Omsk", "Asia/Omsk"),
    ("rnd", "Ростов-на-Дону", "Rostov-on-Don", "Europe/Moscow"),
    ("ufa", "Уфа", "Ufa", "Asia/Yekaterinburg"),
    ("krs", "Красноярск", "Krasnoyarsk", "Asia/Krasnoyarsk"),
    ("vrn", "Воронеж", "Voronezh", "Europe/Moscow"),
    ("perm", "Пермь", "Perm", "Asia/Yekaterinburg"),
    ("volg", "Волгоград", "Volgograd", "Europe/Volgograd"),
    ("krd", "Краснодар", "Krasnodar", "Europe/Moscow"),
    ("sar", "Саратов", "Saratov", "Europe/Saratov"),
    ("tum", "Тюмень", "Tyumen", "Asia/Yekaterinburg"),
    ("tol", "Тольятти", "Tolyatti", "Europe/Samara"),
    ("izh", "Ижевск", "Izhevsk", "Europe/Samara"),
    ("bar", "Барнаул", "Barnaul", "Asia/Barnaul"),
    ("uln", "Ульяновск", "Ulyanovsk", "Europe/Ulyanovsk"),
    ("irk", "Иркутск", "Irkutsk", "Asia/Irkutsk"),
    ("khb", "Хабаровск", "Khabarovsk", "Asia/Vladivostok"),
    ("vvo", "Владивосток", "Vladivostok", "Asia/Vladivostok"),
    ("yar", "Ярославль", "Yaroslavl", "Europe/Moscow"),
    ("tom", "Томск", "Tomsk", "Asia/Tomsk"),
    ("mns", "Минск", "Minsk", "Europe/Minsk"),
    ("ala", "Алматы", "Almaty", "Asia/Almaty"),
    ("tas", "Ташкент", "Tashkent", "Asia/Tashkent"),
)

CITY_LABELS_RU = tuple(city[1] for city in CITIES)
CITY_SLUGS = tuple(city[0] for city in CITIES)

# Шаг кнопочного диалога пройден — число пользовательских действий полного
# онбординга (S68 сверяет их с лимитом антиспама): /start + 6 нажатий + текст.
ONBOARDING_ACTION_COUNT = 8


# ---------------------------------------------------------------------------
# Состояние пользователя (Repo, api.md §9) — наблюдаемое «настройки не меняются»
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UserState:
    """Снимок настроек пользователя: язык + JSONB-профиль (dict)."""

    lang: str
    profile: dict[str, Any]


async def user_state(harness: Any, user_id: Any) -> UserState | None:
    """Настройки пользователя из Repo (публичный API BotHarness, api.md §9)."""
    user = await harness.repo.get_user(user_id)
    if user is None:
        return None
    profile = user.profile or {}
    return UserState(lang=user.lang, profile=dict(profile))


# ---------------------------------------------------------------------------
# Обвязка BotHarness I-2 (контракт — см. докстринг модуля)
# ---------------------------------------------------------------------------


def _method(harness: Any, name: str) -> Any:
    method = getattr(harness, name, None)
    if method is None:
        raise NotImplementedYet(
            f"BotHarness.{name} ещё не реализован "
            f"(контракт I-2: docs/qa/acceptance-map.md §6.2, владелец — software-engineer)"
        )
    return method


async def _normalize(messages: Any) -> list[str]:
    if inspect.isawaitable(messages):
        messages = await messages
    return [message.text if hasattr(message, "text") else str(message) for message in messages]


async def press(harness: Any, callback_data: str, *, user_id: Any) -> list[str]:
    """Нажать инлайн-кнопку: callback_query → тексты сообщений (без toast)."""
    result = _method(harness, "press")(callback_data, user_id=user_id)
    return await _normalize(result)


def keyboard(harness: Any) -> list[tuple[str, str]]:
    """Кнопки (метка, callback_data) последнего сообщения с клавиатурой."""
    return list(_method(harness, "keyboard")())


def events(harness: Any) -> list[tuple[str, Any]]:
    """Упорядоченный журнал событий сессии: answer / send / edit."""
    return list(_method(harness, "events")())


def answer_of(payload: Any) -> tuple[str, bool]:
    """(text, show_alert) события ``answer``: объект CallbackAnswer либо кортеж."""
    if isinstance(payload, tuple):
        return str(payload[0]), bool(payload[1])
    return str(payload.text), bool(payload.show_alert)


def answers_in(trail: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """Подмножество событий ``answer`` из журнала."""
    return [event for event in trail if event[0] == "answer"]


def selected(label: str) -> str:
    """Метка выбранного пресета (prefix ✅ + метка кнопки, brief §6.1)."""
    return f"{SELECTED_PREFIX}{label}"


# ---------------------------------------------------------------------------
# Шаги диалога (публичный вход: команды + callback-нажатия)
# ---------------------------------------------------------------------------


async def open_step(harness: Any, user_id: Any, step: str) -> list[str]:
    """Открыть шаг настроек командой ``/settings <шаг>`` (минимальная
    навигация, brief §7.17)."""
    return await send_text(harness, user_id, f"/settings {step}")


async def onboard(
    harness: Any,
    user_id: Any,
    *,
    lang: str = "ru",
    presets: tuple[str, ...] = ("python-backend",),
    work_format: str = "any",
    city: str = "msk",
    digest_time: str = "09:30",
    size: str = "10",
) -> list[str]:
    """Полный кнопочный онбординг (S1/AC-21): lang → preset (мультивыбор +
    «Готово») → format → tz (город) → time (текст) → size. Возвращает тексты
    последнего шага (финал — «Готово! Подборка придёт в выбранное время.»)."""
    replies = await send_text(harness, user_id, "/start")
    replies += await press(harness, f"dlg:lang:{lang}", user_id=user_id)
    for slug in presets:
        replies += await press(harness, f"dlg:preset:{slug}", user_id=user_id)
    replies += await press(harness, "dlg:preset:done", user_id=user_id)
    replies += await press(harness, f"dlg:format:{work_format}", user_id=user_id)
    replies += await press(harness, f"dlg:tz:{city}", user_id=user_id)
    replies += await send_text(harness, user_id, digest_time)
    replies += await press(harness, f"dlg:size:{size}", user_id=user_id)
    return replies
