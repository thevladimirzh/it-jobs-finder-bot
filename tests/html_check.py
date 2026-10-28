"""Проверка допустимых тегов Telegram HTML (threat-model §5.9, SEC-05).

Общий хелпер тестов: ``check_html(text) -> list[str]`` — пустой список означает,
что нарушений allowlist-тегов нет. Независимый oracle — ``tests/security/support.py``.
"""

from __future__ import annotations

from html.parser import HTMLParser

ALLOWED_TAGS = frozenset(
    {"b", "strong", "i", "em", "u", "s", "code", "pre", "a", "tg-spoiler", "blockquote"}
)
ALLOWED_ATTRS = {"a": frozenset({"href"})}
ALLOWED_HREF_SCHEMES = ("http://", "https://", "mailto:", "tg://")


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, {name: (value or "") for name, value in attrs}))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def check_html(text: str) -> list[str]:
    """Нарушения allowlist-тегов в готовом Telegram HTML (пусто — всё ок)."""
    parser = _Collector()
    parser.feed(text)
    parser.close()
    problems: list[str] = []
    for tag, attrs in parser.tags:
        if tag not in ALLOWED_TAGS:
            problems.append(f"forbidden tag <{tag}>")
            continue
        allowed_attrs = ALLOWED_ATTRS.get(tag, frozenset())
        for name, value in attrs.items():
            if name not in allowed_attrs:
                problems.append(f"forbidden attribute {name} on <{tag}>")
            elif name == "href" and not value.startswith(ALLOWED_HREF_SCHEMES):
                problems.append(f"unsafe href scheme in <{tag}>: {value[:40]!r}")
    return problems
