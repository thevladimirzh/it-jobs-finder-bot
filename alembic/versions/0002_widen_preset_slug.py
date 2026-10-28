"""Расширение ``presets.slug`` до 255 символов (I-2, S84/decisions §8.2).

Slug пресета из админского ввода может быть длинным (тест S84 — 100 символов);
для callback_data он кодируется коротким кодом (``app.bot.dialog.preset_code``),
но в БД slug хранится целиком — колонка расширяется до VARCHAR(255).

Revision ID: 0002_widen_preset_slug
Revises: 0001_initial
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_widen_preset_slug"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "presets",
        "slug",
        type_=sa.String(255),
        existing_type=sa.String(64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "presets",
        "slug",
        type_=sa.String(64),
        existing_type=sa.String(255),
        existing_nullable=False,
    )
