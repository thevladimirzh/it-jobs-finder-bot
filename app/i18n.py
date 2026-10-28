"""Словари RU/EN (api.md §3): точные строки brief §6.1 и decisions §4.

``t(key, lang, **params)`` — подстановка ``{param}`` без исключений на
отсутствующих параметрах (неизвестные плейсхолдеры остаются как есть);
``KeyError`` — только для отсутствующего ключа (R39, P-I18N-01).
"""

from __future__ import annotations

from typing import Literal

Lang = Literal["ru", "en"]

# Точные строки (копируются дословно): brief §6.1, decisions §1/§4.
_RU: dict[str, str] = {
    "feedback.ok.like": "\U0001f44d Учтено",
    "feedback.ok.dislike": "\U0001f44e Учтено",
    "feedback.ok.bookmark": "\U0001f516 Сохранено",
    "feedback.error": (
        "Не понял номер. Отправьте номер карточки из последнего дайджеста (например: /like 3)."
    ),
    "digest.empty": "\U0001f525 Новых вакансий нет",
    "digest.header": "\U0001f525 Подборка вакансий \u2014 {date} ({count})",
    "salary.none": "Зарплата не указана",
    "salary.from": "от {amount} {currency}",
    "salary.to": "до {amount} {currency}",
    "salary.range": "{minimum} \u2013 {maximum} {currency}",
    "age.today": "сегодня",
    "age.yesterday": "вчера",
    "age.days": "{k} дн.",
    "error.bad_time": "Не понял время. Отправьте в формате ЧЧ:ММ (например: 09:30).",
    "error.bad_tz": (
        "Не понял таймзону. Выберите город из списка или укажите смещение UTC (например: UTC+3)."
    ),
    "error.bad_salary": "Не понял зарплату. Отправьте целое число (например: 150000).",
    "reminder.finish_setup": (
        "Чтобы получать подборку, завершите настройку: выберите время дайджеста "
        "и таймзону (/settings)."
    ),
    "alert.template": "\u26a0\ufe0f Сбор {source}: {reason}",
    "start.welcome": (
        "Привет! Я присылаю подборку IT-вакансий.\n"
        "Hi! I will send you a daily IT jobs digest.\n"
        "Выберите язык / Choose your language:"
    ),
    "start.done": "Готово! Подборка придёт в выбранное время.",
    "prompt.lang": "Выберите язык:",
    "prompt.preset": (
        "Выберите роли — можно несколько. Выбранные отмечены ✅. Когда закончите, нажмите «Готово»."
    ),
    "prompt.format": "Формат работы:",
    "prompt.time": "Отправьте время дайджеста в формате ЧЧ:ММ (например: 09:30).",
    "prompt.tz": "Выберите город или укажите смещение UTC вручную:",
    "prompt.tz_manual": "Введите смещение UTC (например: UTC+3).",
    "prompt.size": "Размер дайджеста:",
    "prompt.salary": "Отправьте минимальную зарплату в рублях (например: 150000).",
    "prompt.stop": "Отправьте стоп-слово для фильтрации вакансий.",
    "dialog.outdated": "Эта кнопка устарела. Откройте настройки заново (/settings).",
    "dialog.preset_empty": "Выберите хотя бы один пресет.",
    "preset.done_label": "Готово",
    "tz.manual_label": "Указать UTC offset вручную",
    "format.remote": "Удалёнка",
    "format.hybrid": "Гибрид",
    "format.office": "Офис",
    "format.any": "Не важно",
    "saved.lang": "Язык сохранён.",
    "saved.preset": "Подписка сохранена.",
    "saved.format": "Формат работы сохранён.",
    "saved.time": "Время дайджеста сохранено.",
    "saved.tz": "Таймзона сохранена.",
    "saved.size": "Размер дайджеста сохранён.",
    "saved.salary": "Минимальная зарплата сохранена.",
    "saved.stop": "Стоп-слово сохранено.",
    "settings.title": "Настройки:",
    "settings.lang": "Язык",
    "settings.presets": "Пресеты",
    "settings.min_salary": "Мин. зарплата",
    "settings.work_format": "Формат работы",
    "settings.stop_words": "Стоп-слова",
    "settings.size": "Размер дайджеста",
    "settings.time": "Время",
    "settings.tz": "Таймзона",
}

_EN: dict[str, str] = {
    "feedback.ok.like": "\U0001f44d Noted",
    "feedback.ok.dislike": "\U0001f44e Noted",
    "feedback.ok.bookmark": "\U0001f516 Saved",
    "feedback.error": (
        "I didn't get the number. Send the card number from your latest digest (e.g. /like 3)."
    ),
    "digest.empty": "\U0001f525 No new vacancies",
    "digest.header": "\U0001f525 Job digest \u2014 {date} ({count})",
    "salary.none": "Salary not specified",
    "salary.from": "from {amount} {currency}",
    "salary.to": "up to {amount} {currency}",
    "salary.range": "{minimum} \u2013 {maximum} {currency}",
    "age.today": "today",
    "age.yesterday": "yesterday",
    "age.days": "{k} days",
    "error.bad_time": "I didn't get the time. Send it as HH:MM (e.g. 09:30).",
    "error.bad_tz": (
        "I didn't get the timezone. Pick a city from the list or send a UTC offset (e.g. UTC+3)."
    ),
    "error.bad_salary": "I didn't get the salary. Send a whole number (e.g. 150000).",
    "reminder.finish_setup": (
        "To get your digest, finish setup: choose digest time and timezone (/settings)."
    ),
    "alert.template": "\u26a0\ufe0f Сбор {source}: {reason}",  # алерты всегда RU (§7.10)
    "start.welcome": (
        "Привет! Я присылаю подборку IT-вакансий.\n"
        "Hi! I will send you a daily IT jobs digest.\n"
        "Выберите язык / Choose your language:"
    ),
    "start.done": "All set! Your digest will arrive at the chosen time.",
    "prompt.lang": "Choose a language:",
    "prompt.preset": (
        "Pick roles — you can choose several. Selected roles are marked ✅. "
        'Press "Done" when you are finished.'
    ),
    "prompt.format": "Work format:",
    "prompt.time": "Send the digest time as HH:MM (e.g. 09:30).",
    "prompt.tz": "Pick a city or set a UTC offset manually:",
    "prompt.tz_manual": "Send a UTC offset (e.g. UTC+3).",
    "prompt.size": "Digest size:",
    "prompt.salary": "Send the minimum salary in rubles (e.g. 150000).",
    "prompt.stop": "Send a stop word to filter vacancies.",
    "dialog.outdated": "This button is outdated. Open settings again (/settings).",
    "dialog.preset_empty": "Pick at least one preset.",
    "preset.done_label": "Done",
    "tz.manual_label": "Set UTC offset manually",
    "format.remote": "Remote",
    "format.hybrid": "Hybrid",
    "format.office": "Office",
    "format.any": "Any",
    "saved.lang": "Language saved.",
    "saved.preset": "Subscription saved.",
    "saved.format": "Work format saved.",
    "saved.time": "Digest time saved.",
    "saved.tz": "Timezone saved.",
    "saved.size": "Digest size saved.",
    "saved.salary": "Minimum salary saved.",
    "saved.stop": "Stop word saved.",
    "settings.title": "Settings:",
    "settings.lang": "Language",
    "settings.presets": "Presets",
    "settings.min_salary": "Min salary",
    "settings.work_format": "Work format",
    "settings.stop_words": "Stop words",
    "settings.size": "Digest size",
    "settings.time": "Time",
    "settings.tz": "Timezone",
}

_DICTS: dict[str, dict[str, str]] = {"ru": _RU, "en": _EN}


def t(key: str, lang: Lang, **params: object) -> str:
    """Строка-шаблон с подстановкой ``{param}``; ``KeyError`` — нет такого ключа."""
    template = _DICTS[lang][key]
    for name, value in params.items():
        template = template.replace("{" + name + "}", str(value))
    return template


def keys(lang: Lang) -> frozenset[str]:
    """Ключи словаря языка (паритет RU/EN — P-I18N-01)."""
    return frozenset(_DICTS[lang])
