"""Кнопочный диалог настроек (I-2): callback_data, клавиатуры, состояние.

Контракт — ``docs/spec/api.md`` §15.1, ``docs/spec/decisions.md`` §8 и
``docs/product/brief.md`` §6.1 («Диалог на инлайн-кнопках (I-2)»):

- ``callback_data`` = ``dlg:<step>:<value>`` (ASCII), ≤ 64 байт (лимит Telegram);
  ``step`` — из белого списка шагов, ``value`` — код ``[a-z0-9-]{1,32}``;
  пользовательский/внешний текст в callback_data не попадает никогда;
- ``encode_callback``/``parse_callback`` — форма и тотальный парсер (ValueError
  вне грамматики / ``None`` на мусоре); семантическая валидация значений
  (size ∈ {5,10,20,50}, известные коды пресетов) — в обработчике callback;
- длинные slug пресетов кодируются коротким кодом (decisions §8.2) — пресет
  остаётся выбираемым, callback_data не растёт;
- города таймзоны (30 шт., brief §6.1) постранично: ≤ 10 городов на странице
  плюс навигация ``dlg:tz:page-<k>`` и кнопка ручного offset;
- метки кнопок — plain text (не HTML); значения в HTML-тексте сообщений идут
  через ``app.textutil.esc`` (R7/R53) — в вызывающем коде;
- состояние диалога — in-memory, per-user (decisions §8.6; R33 — сброс при
  рестарте процесса). Каждый завершённый шаг пишет в профиль немедленно,
  подписка на пресеты — только по «Готово».
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import Any

from app.i18n import Lang, t

#: Форма callback_data (brief §6.1): ``dlg:<step>:<value>``.
CALLBACK_RE = re.compile(r"dlg:(lang|preset|format|tz|size):([a-z0-9-]{1,32})")
VALUE_RE = re.compile(r"[a-z0-9-]{1,32}")
MAX_CALLBACK_BYTES = 64

#: Белый список шагов callback (brief §6.1).
STEPS: tuple[str, ...] = ("lang", "preset", "format", "tz", "size")

#: Порядок шагов онбординга (decisions §8.6): после tz идёт текстовый шаг time.
CHAIN: tuple[str, ...] = ("lang", "preset", "format", "tz", "time", "size")

#: Текстовые шаги (ввод текстом остаётся только для них, AC-24).
TEXT_STEPS: tuple[str, ...] = ("time", "tz", "salary", "stop")

#: Все шаги, открываемые ``/settings <шаг>``.
ALL_STEPS: tuple[str, ...] = ("lang", "preset", "format", "tz", "time", "size", "salary", "stop")

# Белые списки значений по шагам (семантика значений — обработчик, S88).
LANG_VALUES: tuple[str, ...] = ("ru", "en")
FORMAT_VALUES: tuple[str, ...] = ("remote", "hybrid", "office", "any")
SIZE_VALUES: tuple[str, ...] = ("5", "10", "20", "50")
PRESET_DONE = "done"

SELECTED_PREFIX = "✅ "  # префикс метки выбранного пресета (brief §6.1)
NAV_PREV_LABEL = "⬅️"
NAV_NEXT_LABEL = "➡️"
LANG_LABELS: Mapping[str, str] = {"ru": "Русский", "en": "English"}

#: Кнопки-города таймзоны: slug, метка RU, метка EN, IANA-зона (brief §6.1).
CITIES: tuple[tuple[str, str, str, str], ...] = (
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

TZ_PAGE_SIZE = 10  # не более 10 городов на странице (decisions §8.6)
TZ_MANUAL = "manual"

# Кнопка (метка, callback_data) и клавиатура как ряды кнопок.
Button = tuple[str, str]
Keyboard = tuple[tuple[Button, ...], ...]


# ---------------------------------------------------------------------------
# callback_data: encode/parse (P-DLG-01) и короткие коды пресетов
# ---------------------------------------------------------------------------


def encode_callback(step: str, value: str) -> str:
    """``dlg:<step>:<value>`` для известного шага; иначе ``ValueError``.

    Форма значения — грамматика ``[a-z0-9-]{1,32}``; encode либо возвращает
    конформную строку (round-trip с :func:`parse_callback`), либо бросает
    ``ValueError`` — ничего «среднего» (P-DLG-01).
    """
    if step not in STEPS:
        raise ValueError(f"unknown callback step: {step!r}")
    if not isinstance(value, str) or VALUE_RE.fullmatch(value) is None:
        raise ValueError(f"callback value outside grammar: {value!r}")
    data = f"dlg:{step}:{value}"
    if not data.isascii() or len(data.encode("ascii")) > MAX_CALLBACK_BYTES:
        raise ValueError(f"callback_data over {MAX_CALLBACK_BYTES} bytes: {data!r}")
    return data


def parse_callback(data: str) -> tuple[str, str] | None:
    """Разбор callback_data: ``(step, value)`` либо ``None``; никогда не падает.

    Тотальность (P-DLG-01): возвращается только белый список шагов и грамматика
    значения; семантику значений проверяет обработчик callback (S88/P-DLG-02).
    """
    if not isinstance(data, str):
        return None
    match = CALLBACK_RE.fullmatch(data)
    if match is None:
        return None
    return match.group(1), match.group(2)


def preset_code(slug: str) -> str:
    """Короткий код значения пресета для callback_data (decisions §8.2).

    Канонические slug (``python-backend`` и т.п.) используются как есть;
    длинные slug кодируются стабильным коротким кодом (sha256), который
    возвращается в белый список значений шага ``preset``.
    """
    if isinstance(slug, str) and VALUE_RE.fullmatch(slug):
        return slug
    digest = hashlib.sha256(str(slug).encode("utf-8")).hexdigest()[:15]
    return f"h{digest}"


def _extended_preset_code(slug: str) -> str:
    """Расширенный код пресета (F-17): ``h`` + 31 hex при коллизии коротких кодов."""
    digest = hashlib.sha256(str(slug).encode("utf-8")).hexdigest()[:31]
    return f"h{digest}"


def preset_codes(slugs: Iterable[str]) -> dict[str, str]:
    """Код каждого slug без молчаливых коллизий (F-17): ``slug → код``.

    Коллизия кодов (два разных slug → один код) не перезаписывается молча:
    коллизующий slug получает расширенный код (:func:`_extended_preset_code`);
    неразрешимая коллизия — ``ValueError`` (явный отказ, fail-closed).
    Детерминировано: одинаковый список slug даёт одинаковые коды.
    """
    by_slug: dict[str, str] = {}
    used: dict[str, str] = {}  # код → slug
    for slug in slugs:
        if slug in by_slug:
            continue
        code = preset_code(slug)
        owner = used.get(code)
        if owner is not None and owner != slug:
            code = _extended_preset_code(slug)
            owner = used.get(code)
            if owner is not None and owner != slug:
                raise ValueError(f"preset code collision: {slug!r} vs {owner!r}")
        used[code] = slug
        by_slug[slug] = code
    return by_slug


# ---------------------------------------------------------------------------
# Клавиатуры шагов (метки — plain text; значения — только коды)
# ---------------------------------------------------------------------------


def lang_keyboard() -> Keyboard:
    return tuple(((label, encode_callback("lang", code)),) for code, label in LANG_LABELS.items())


def preset_label(preset: Any, lang: Lang) -> str:
    """Метка пресета: ``name_en`` для EN (иначе ``name_ru``), без HTML-обработки."""
    if lang == "en":
        name_en = getattr(preset, "name_en", "") or ""
        if name_en:
            return str(name_en)
    name = getattr(preset, "name_ru", None) or getattr(preset, "name", None)
    return str(name) if name else str(getattr(preset, "slug", ""))


def preset_keyboard(
    presets: Sequence[tuple[str, str]],
    selected: AbstractSet[str] = frozenset(),
    lang: Lang = "ru",
    codes: Mapping[str, str] | None = None,
) -> Keyboard:
    """Мультивыбор пресетов: ✅ у отмеченных + кнопка «Готово»/«Done».

    ``codes`` (``slug → код``, :func:`preset_codes`) — коды без коллизий
    (F-17); без них код вычисляется :func:`preset_code`.
    """
    rows: list[tuple[Button, ...]] = []
    for slug, label in presets:
        shown = f"{SELECTED_PREFIX}{label}" if slug in selected else label
        code = codes[slug] if codes is not None and slug in codes else preset_code(slug)
        rows.append(((shown, encode_callback("preset", code)),))
    rows.append(((t("preset.done_label", lang), encode_callback("preset", PRESET_DONE)),))
    return tuple(rows)


def format_keyboard(lang: Lang) -> Keyboard:
    return tuple(
        ((t(f"format.{code}", lang), encode_callback("format", code)),) for code in FORMAT_VALUES
    )


def size_keyboard() -> Keyboard:
    return tuple(((value, encode_callback("size", value)),) for value in SIZE_VALUES)


def tz_page_count() -> int:
    return (len(CITIES) + TZ_PAGE_SIZE - 1) // TZ_PAGE_SIZE


def city_zone(slug: str) -> str | None:
    """IANA-зона города по slug (``None`` — города нет в белом списке)."""
    for city_slug, _ru, _en, zone in CITIES:
        if city_slug == slug:
            return zone
    return None


def tz_keyboard(lang: Lang, page: int) -> Keyboard:
    """Страница городов: ≤10 кнопок-городов + навигация + ручной offset."""
    total = tz_page_count()
    if not 1 <= page <= total:
        raise ValueError(f"tz page out of range: {page!r}")
    rows: list[tuple[Button, ...]] = []
    for city_slug, ru, en, _zone in CITIES[(page - 1) * TZ_PAGE_SIZE : page * TZ_PAGE_SIZE]:
        label = ru if lang == "ru" else en
        rows.append(((label, encode_callback("tz", city_slug)),))
    nav: list[Button] = []
    if page > 1:
        nav.append((NAV_PREV_LABEL, encode_callback("tz", f"page-{page - 1}")))
    if page < total:
        nav.append((NAV_NEXT_LABEL, encode_callback("tz", f"page-{page + 1}")))
    if nav:
        rows.append(tuple(nav))
    rows.append(((t("tz.manual_label", lang), encode_callback("tz", TZ_MANUAL)),))
    return tuple(rows)


# ---------------------------------------------------------------------------
# Исходящие сообщения и подтверждения callback
# ---------------------------------------------------------------------------


class Reply(str):
    """Исходящее сообщение: готовый Telegram HTML + клавиатура + признак правки.

    Наследник ``str``: текст ответа — сам объект (совместим с контрактом
    ``handle -> list[str]`` api.md §15 и нормализацией BotHarness ``.text``).
    """

    keyboard: Keyboard
    edit: bool

    def __new__(
        cls,
        text: str,
        *,
        keyboard: Sequence[Sequence[Button]] = (),
        edit: bool = False,
    ) -> Reply:
        obj = super().__new__(cls, text)
        obj.keyboard = tuple(tuple(row) for row in keyboard)
        obj.edit = edit
        return obj

    @property
    def text(self) -> str:
        return str(self)


@dataclass(frozen=True)
class CallbackAnswer:
    """``answer_callback_query``: пустой текст = подтверждение без тоста."""

    text: str = ""
    show_alert: bool = False


# ---------------------------------------------------------------------------
# Состояние диалога (in-memory, per-user; decisions §8.6)
# ---------------------------------------------------------------------------


@dataclass
class DialogState:
    """Текущий шаг пользователя + накопленный мультивыбор пресетов."""

    step: str
    mode: str = "single"  # "onboarding" (/start) | "single" (/settings <шаг>)
    lang: Lang = "ru"
    selected: set[str] = field(default_factory=set)  # slug-и (не коды!)
    page: int = 1  # текущая страница городов (шаг tz)
    codes: dict[str, str] = field(default_factory=dict)  # код callback → slug пресета


class DialogStore:
    """Состояние диалогов в памяти процесса (R33: сброс при рестарте — принято).

    Память ограничена (F-16, CWE-770): ``_langs`` не растёт бесконечно —
    при переполнении вытесняются самые старые записи (порядок обновления).
    """

    #: Крыша числа запомненных языков (F-16).
    MAX_LANGS = 4096

    def __init__(self, max_langs: int = MAX_LANGS) -> None:
        self._states: dict[Any, DialogState] = {}
        self._langs: dict[Any, Lang] = {}
        self._max_langs = max_langs

    def get(self, user_id: Any) -> DialogState | None:
        return self._states.get(user_id)

    def open(
        self,
        user_id: Any,
        step: str,
        *,
        mode: str = "single",
        lang: Lang = "ru",
        selected: Iterable[str] = (),
    ) -> DialogState:
        state = DialogState(step=step, mode=mode, lang=lang, selected=set(selected))
        self._states[user_id] = state
        self.note_lang(user_id, lang)
        return state

    def close(self, user_id: Any) -> None:
        self._states.pop(user_id, None)

    def note_lang(self, user_id: Any, lang: Lang) -> None:
        """Запомнить язык пользователя (для тостов отказа без обращения к БД)."""
        if user_id not in self._langs and self._langs and len(self._langs) >= self._max_langs:
            self._langs.pop(next(iter(self._langs)))  # вытеснение самого старого (F-16)
        self._langs[user_id] = lang

    def lang_of(self, user_id: Any) -> Lang:
        state = self._states.get(user_id)
        if state is not None:
            return state.lang
        return self._langs.get(user_id, "ru")
