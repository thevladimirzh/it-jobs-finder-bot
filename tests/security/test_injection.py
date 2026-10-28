"""HTML-инъекция недоверенного текста источника в Telegram-сообщения.

Угрозы: SEC-01 (title/company/description), SEC-02 (URL/атрибуты), SEC-05 (регрессия
экранирования — все пути вывода), свойства P-SEC-01 и P-SEC-05 (hypothesis, фиксированный
seed). Модель угроз: docs/security/threat-model.md §3. Контракт: docs/spec/api.md §2, §6, §12,
шаблоны — docs/product/brief.md §6.1. Текст карточки собирается из экранированных полей
(`app.textutil.esc`/`esc_attr`), ровно один тег <b> — заголовок.

Тесты красные, пока production-код не реализован (ленивый импорт — см. support.load).
"""

from __future__ import annotations

import html
from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st
from support import (
    HTML_PAYLOADS,
    app_settings,
    assert_no_raw_markup,
    found_tags,
    load_attr,
    memory_bot,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
PUBLISHED = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
SAFE_URL = "https://hh.ru/vacancy/123"


def _vacancy(title: str, company: str, description: str, url: str = SAFE_URL):
    vacancy_cls = load_attr("app.collectors", "Vacancy")
    return vacancy_cls(
        title=title,
        company=company,
        salary=None,
        url=url,
        source="hh.ru",
        published_at=PUBLISHED,
        description=description,
    )


def _render_card(vacancy, lang: str) -> str:
    render_card = load_attr("app.services.digest", "render_card")
    return render_card(n=1, vacancy=vacancy, lang=lang, now=NOW)


# --- SEC-01 -----------------------------------------------------------------


def test_SEC_01_payload_in_title_company_description_never_appears_raw() -> None:
    """SEC-01: <script>/<b>/& из источника не попадают в Telegram-текст сырыми."""
    esc = load_attr("app.textutil", "esc")
    for payload in HTML_PAYLOADS:
        vacancy = _vacancy(title=payload, company=payload, description=payload)
        for lang in ("ru", "en"):
            text = _render_card(vacancy, lang)
            assert esc(payload) in text, (
                f"SEC-01: поле вакансии не экранировано через esc (lang={lang}, "
                f"payload={payload!r}): {text!r}"
            )
            assert "<script" not in text.lower(), (
                f"SEC-01: сырая разметка <script> в сообщении: {text!r}"
            )
            assert "<iframe" not in text.lower(), f"SEC-01: сырой <iframe>: {text!r}"
            assert "<img" not in text.lower(), f"SEC-01: сырой <img>: {text!r}"
            assert_no_raw_markup(text, f"SEC-01 карточка lang={lang} payload={payload!r}")


def test_SEC_01_card_contains_exactly_one_bold_tag() -> None:
    """SEC-01: тег <b> в карточке ровно один (заголовок по шаблону brief §6.1)."""
    for payload in HTML_PAYLOADS:
        vacancy = _vacancy(title=payload, company=payload, description=payload)
        text = _render_card(vacancy, "ru")
        assert text.count("<b>") == 1, f"SEC-01: лишние теги <b> в карточке: {text!r}"
        assert text.count("</b>") == 1, f"SEC-01: лишние теги </b> в карточке: {text!r}"
        assert set(found_tags(text)) <= {"b"}, f"SEC-01: недопустимые теги: {found_tags(text)}"


# --- SEC-02 -----------------------------------------------------------------


def test_SEC_02_url_payloads_cannot_inject_tags_or_schemes() -> None:
    """SEC-02: URL вакансии не может сломать HTML или дать javascript:/file:-схему."""
    canonicalize_url = load_attr("app.collectors", "canonicalize_url")
    dangerous = [
        '" onmouseover="alert(1)',
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        'https://evil.example/"><a href="http://evil.example/">x</a>',
        "http://169.254.169.254/latest/meta-data/",
        "vbscript:msgbox(1)",
    ]
    for raw in dangerous:
        canonical = canonicalize_url(raw)
        assert isinstance(canonical, str), f"SEC-02: canonicalize_url вернул не str: {raw!r}"
        for bad_char in ('"', "'", "<", ">", "\x00"):
            assert bad_char not in canonical, (
                f"SEC-02: {bad_char!r} в каноническом URL {canonical!r} (вход {raw!r}) — "
                "инъекция в неэкранируемое поле {url} шаблона карточки"
            )
        assert not any(ch.isspace() or ord(ch) < 0x20 for ch in canonical), (
            f"SEC-02: пробел/управляющий символ в каноническом URL {canonical!r}"
        )
        lowered = canonical.lower()
        for scheme in ("javascript:", "data:", "file:", "vbscript:"):
            assert not lowered.startswith(scheme), (
                f"SEC-02: опасная схема {scheme} в каноническом URL {canonical!r}"
            )
        # и сам рендер карточки с таким URL не добавляет тегов
        vacancy = _vacancy(title="t", company="c", description="", url=canonical)
        text = _render_card(vacancy, "ru")
        assert_no_raw_markup(text, f"SEC-02 карточка с url={canonical!r}")
        assert set(found_tags(text)) <= {"b"}, (
            f"SEC-02: URL создал теги в сообщении: {found_tags(text)}; {text!r}"
        )


def test_SEC_02_esc_attr_cannot_be_broken_out_of_attribute() -> None:
    """SEC-02: esc_attr экранирует кавычки — payload не выходит из атрибута href."""
    esc_attr = load_attr("app.textutil", "esc_attr")
    for payload in HTML_PAYLOADS:
        out = esc_attr(payload)
        for bad_char in ('"', "<", ">"):
            assert bad_char not in out, (
                f"SEC-02: {bad_char!r} осталось в esc_attr({payload!r}) = {out!r} — "
                "возможен выход из атрибута"
            )


# --- SEC-05 -----------------------------------------------------------------


def test_SEC_05_every_render_path_escapes_external_text() -> None:
    """SEC-05: регрессия экранирования — все render-пути api.md §12 безопасны."""
    esc = load_attr("app.textutil", "esc")
    render_header = load_attr("app.services.digest", "render_header")
    render_empty = load_attr("app.services.digest", "render_empty")
    truncate_title = load_attr("app.services.digest", "truncate_title")

    for lang in ("ru", "en"):
        texts = [
            render_header(count=2, on_date=NOW.date(), lang=lang),
            render_empty(lang=lang),
        ]
        for text in texts:
            assert_no_raw_markup(text, f"SEC-05 базовый рендер lang={lang}")
        for payload in HTML_PAYLOADS:
            vacancy = _vacancy(title=payload, company=payload, description=payload)
            text = _render_card(vacancy, lang)
            assert_no_raw_markup(text, f"SEC-05 карточка lang={lang} payload={payload!r}")
            # обрезка заголовка работает по экранированному тексту и не рвёт разметку
            cut = truncate_title(esc(payload))
            assert_no_raw_markup(cut, f"SEC-05 truncate_title payload={payload!r}")
            assert len(cut) <= 200, f"SEC-05: truncate_title вернул {len(cut)} символов"


def test_SEC_05_html_check_helper_rejects_injected_tags() -> None:
    """SEC-05: общий хелпер tests/html_check.py (контракт threat-model §5.9)."""
    check_html = load_attr("tests.html_check", "check_html")
    assert check_html("<b>ok</b>") == [], "SEC-05: html_check ругается на легитимный тег"
    assert check_html("обычный текст &amp; сущность") == []
    for payload in ("<script>alert(1)</script>", '<a href="javascript:alert(1)">x</a>'):
        assert check_html(payload), f"SEC-05: html_check пропустил {payload!r}"


async def test_SEC_05_dialog_render_paths_escape_profile_strings() -> None:
    """SEC-05: ответы /settings и /admin_preset_list экранируют строки профиля."""
    esc = load_attr("app.textutil", "esc")
    core = memory_bot()
    uid = 600_001
    payload = '</b><a href="http://evil.example/">CLICK ME'

    # стоп-слово из пользовательского ввода отражается в /settings
    await core.handle("/start", uid)
    await core.handle("/settings stop", uid)
    await core.handle(payload, uid)
    replies = await core.handle("/settings", uid)
    assert replies, "SEC-05: /settings не ответил"
    joined = "\n".join(replies)
    esc_attr = load_attr("app.textutil", "esc_attr")
    assert esc(payload) in joined or esc_attr(payload) in joined, (
        f"SEC-05: стоп-слово отражается только в экранированном виде: {joined!r}"
    )
    for reply in replies:
        assert payload not in reply, f"SEC-05: сырой пользовательский текст в /settings: {reply!r}"
        assert_no_raw_markup(reply, f"SEC-05 /settings payload={payload!r}")

    # имя пресета из админского ввода отражается в /admin_preset_list
    admin_id = app_settings().admin_id
    name_payload = '<a href="http://evil.example/">X'
    await core.handle(f"/admin_preset_add evil {name_payload} {{}}", user_id=admin_id)
    admin_replies = await core.handle("/admin_preset_list", user_id=admin_id)
    assert admin_replies, "SEC-05: /admin_preset_list не ответил"
    for reply in admin_replies:
        assert name_payload not in reply, (
            f"SEC-05: сырой текст name_ru в /admin_preset_list: {reply!r}"
        )
        assert_no_raw_markup(reply, "SEC-05 /admin_preset_list")


# --- P-SEC-01 / P-SEC-05 (hypothesis, фиксированный seed) --------------------


@settings(derandomize=True, max_examples=200, deadline=None)
@given(st.text(max_size=300))
def test_P_SEC_01_esc_never_introduces_markup(text: str) -> None:
    """P-SEC-01: esc/esc_attr не добавляют разметки и обратимы для любого текста."""
    esc = load_attr("app.textutil", "esc")
    esc_attr = load_attr("app.textutil", "esc_attr")
    out = esc(text)
    assert "<" not in out and ">" not in out, f"P-SEC-01: сырые угловые скобки в esc({text!r})"
    assert html.unescape(out) == text, f"P-SEC-01: esc теряет данные для {text!r}"
    out_attr = esc_attr(text)
    for bad_char in ('"', "<", ">"):
        assert bad_char not in out_attr, (
            f"P-SEC-01: esc_attr не экранирует {bad_char!r} для {text!r} -> {out_attr!r}"
        )


@settings(derandomize=True, max_examples=100, deadline=None)
@given(
    title=st.text(max_size=300),
    company=st.text(max_size=300),
    url=st.text(max_size=300),
)
def test_P_SEC_05_render_card_never_adds_markup(title: str, company: str, url: str) -> None:
    """P-SEC-05: карточка не падает и не создаёт тегов для любого текста полей."""
    vacancy = _vacancy(title=title, company=company, description=title, url=url)
    for lang in ("ru", "en"):
        text = _render_card(vacancy, lang)
        assert_no_raw_markup(text, f"P-SEC-05 карточка lang={lang}")
        assert set(found_tags(text)) <= {"b"}, (
            f"P-SEC-05: недопустимые теги {found_tags(text)} для title={title!r}"
        )
        assert text.count("<b>") == text.count("</b>") <= 1, (
            f"P-SEC-05: разбалансированные теги <b> в {text!r}"
        )
