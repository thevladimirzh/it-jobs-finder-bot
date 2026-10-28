"""Начальная схема + сид 7 пресетов ролей (AC-5).

Revision ID: 0001_initial
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.storage.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

PRESETS = (
    (
        "python-backend",
        "Python Backend",
        "Python Backend",
        "Python, Django, FastAPI, backend-сервисы",
        {"role": "python", "must": ["python"], "nice": ["django", "fastapi", "postgres"]},
    ),
    (
        "frontend",
        "Frontend",
        "Frontend",
        "JavaScript, TypeScript, React, Vue, вёрстка",
        {"role": "frontend", "must": ["frontend"], "nice": ["react", "typescript", "vue"]},
    ),
    (
        "devops-sre",
        "DevOps/SRE",
        "DevOps/SRE",
        "DevOps, SRE, Kubernetes, Docker, инфраструктура",
        {"role": "devops", "must": ["devops"], "nice": ["kubernetes", "docker", "sre"]},
    ),
    (
        "data-ml",
        "Data/ML",
        "Data/ML",
        "Data Science, ML, аналитика, пайплайны данных",
        {"role": "data", "must": ["data"], "nice": ["ml", "machine learning", "python"]},
    ),
    (
        "qa",
        "QA",
        "QA",
        "Тестирование, автотесты, QA-инженер",
        {"role": "qa", "must": ["qa"], "nice": ["автоматизир", "selenium", "pytest"]},
    ),
    (
        "mobile",
        "Mobile",
        "Mobile",
        "Android, iOS, кроссплатформенная разработка",
        {"role": "mobile", "must": ["mobile"], "nice": ["android", "ios", "flutter", "kotlin"]},
    ),
    (
        "backend-other",
        "Другие backend-языки",
        "Other backend languages",
        "Go, Java, Kotlin, Ruby, PHP, Scala, C++ и другие backend-языки",
        {
            "role": "backend",
            "must": ["backend"],
            "nice": ["go", "java", "kotlin", "ruby", "php", "scala", "c++"],
        },
    ),
)


def _filter_json(raw: dict) -> dict:
    """JSONB-фильтр пресета со всеми полями контракта api.md §7."""
    return {
        "role": raw.get("role", ""),
        "must": raw.get("must", []),
        "nice": raw.get("nice", []),
        "grades": [],
        "min_salary": None,
        "work_format": None,
        "location": None,
        "stop_words": [],
        "employment": None,
    }


def upgrade() -> None:
    # Схема выводится из моделей app/storage/models.py (контракт api.md §8):
    # так schema drift между моделями и миграцией невозможен.
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.bulk_insert(
        sa.table(
            "presets",
            sa.column("slug", sa.String),
            sa.column("name_ru", sa.String),
            sa.column("name_en", sa.String),
            sa.column("description", sa.Text),
            sa.column("filter", sa.JSON),
            sa.column("is_active", sa.Boolean),
        ),
        [
            {
                "slug": slug,
                "name_ru": name_ru,
                "name_en": name_en,
                "description": description,
                "filter": _filter_json(raw_filter),
                "is_active": True,
            }
            for slug, name_ru, name_en, description, raw_filter in PRESETS
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
