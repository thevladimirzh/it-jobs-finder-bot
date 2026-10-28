"""SQLAlchemy 2 модели (api.md §8): ``Base.metadata`` — источник схемы для
``alembic/env.py`` и тестового ``drop_all``/``create_all``."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.currency import Salary


def now_utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Декларативная база моделей хранилища."""


class UserRow(Base):
    """Пользователь Telegram (chat_id), профиль — JSONB (api.md §5)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lang: Mapped[str] = mapped_column(String(2), nullable=False, default="ru")
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc
    )


class PresetRow(Base):
    """Пресет ролей: JSONB-фильтр + имена RU/EN (AC-5)."""

    __tablename__ = "presets"

    slug: Mapped[str] = mapped_column(String(255), primary_key=True)
    name_ru: Mapped[str] = mapped_column(String(128), nullable=False)
    name_en: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    filter: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def filter_json(self) -> dict:
        return self.filter


class VacancyRow(Base):
    """Вакансия в кэше; дедуп — по каноническому URL и нормализованным полям."""

    __tablename__ = "vacancies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    company: Mapped[str] = mapped_column(String(1024), nullable=False)
    salary_min: Mapped[int | None] = mapped_column(BigInteger)
    salary_max: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc
    )

    @property
    def url(self) -> str:
        return self.canonical_url

    @property
    def salary(self) -> Salary | None:
        if self.currency is None:
            return None
        return Salary(min=self.salary_min, max=self.salary_max, currency=self.currency)


class DeliveryRow(Base):
    """Журнал доставок (user_id, vacancy_id) — at-most-once (Q2, R3)."""

    __tablename__ = "deliveries"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    vacancy_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vacancies.id", ondelete="CASCADE"), primary_key=True
    )
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc
    )


class FeedbackRow(Base):
    """Обратная связь пользователя по карточке (upsert, decisions §5.5)."""

    __tablename__ = "feedback"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    vacancy_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vacancies.id", ondelete="CASCADE"), primary_key=True
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc
    )


class DigestSlotRow(Base):
    """Отработанные слоты расписания — защита от повторов (R32)."""

    __tablename__ = "digest_slots"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    slot_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc
    )


class ParseRunRow(Base):
    """Журнал сборов: статус парсера, добавлено, алерты/подавления (R1, R16)."""

    __tablename__ = "parse_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alert_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suppressed_alerts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc
    )
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc
    )
