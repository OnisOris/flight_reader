"""Вспомогательные элементы конфигурации базы данных для SQLAlchemy."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from flight_reader.settings import get_settings


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


_settings = get_settings()
_engine = create_engine(
    _settings.database_url,
    echo=_settings.db_echo,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    """Зависимость FastAPI, предоставляющая сессию SQLAlchemy."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_engine():
    """Возвращает движок (полезно для фоновых задач или CLI)."""
    return _engine


def init_db() -> None:
    """Создает таблицы базы данных, если они отсутствуют."""

    # Импортируем модели, чтобы они зарегистрировались в метаданных.
    import flight_reader.db_models  # noqa: F401

    Base.metadata.create_all(bind=_engine)
