"""Общая фабрика сессий ядра и отдельные метаданные таблиц Todo."""

from shtab_core.db import get_session_factory
from sqlalchemy.orm import DeclarativeBase

__all__ = ["Base", "get_session_factory"]


class Base(DeclarativeBase):
    pass
