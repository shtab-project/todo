"""Данные задач плагина; пользователи принадлежат ядру Shtab."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from shtab_core.models import User
from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from shtab_todo.constants import TASK_STATUS_MAX_LENGTH, TASK_TITLE_MAX_LENGTH
from shtab_todo.db import Base


class TaskStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Task(Base):
    __tablename__ = "todo_tasks"
    __table_args__ = (
        CheckConstraint(
            "length(trim(title)) > 0", name="ck_todo_tasks_title_not_blank"
        ),
    )
    __mapper_args__: ClassVar[dict[str, bool]] = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    title: Mapped[str] = mapped_column(String(TASK_TITLE_MAX_LENGTH))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[TaskStatus] = mapped_column(
        Enum(
            TaskStatus,
            values_callable=lambda statuses: [status.value for status in statuses],
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            length=TASK_STATUS_MAX_LENGTH,
            name="ck_todo_tasks_status",
        ),
        default=TaskStatus.NEW,
        server_default=TaskStatus.NEW.value,
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(User.__table__.c.id, ondelete="RESTRICT"), index=True
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(User.__table__.c.id, ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
