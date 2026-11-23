"""The core's shared session factory and Todo's own table metadata."""

from shtab_core.db import get_session_factory
from sqlalchemy.orm import DeclarativeBase

__all__ = ["Base", "get_session_factory"]


class Base(DeclarativeBase):
    pass
