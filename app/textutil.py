"""Экранирование внешнего/пользовательского текста для Telegram HTML (api.md §2).

``esc``/``esc_attr`` не бросают исключений ни на каком входе (R25) и обратимы:
``html.unescape(esc(t)) == t`` (threat-model §5.1, P-TEX-01/P-SEC-01).
"""

from __future__ import annotations

import html


def esc(text: str) -> str:
    """Экранирует ``&`` ``<`` ``>`` для HTML-текста Telegram."""
    return html.escape(str(text), quote=False)


def esc_attr(text: str) -> str:
    """Как :func:`esc`, дополнительно экранирует ``"`` и ``'`` для атрибутов."""
    return html.escape(str(text), quote=True)
