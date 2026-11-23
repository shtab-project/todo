"""The plugin's task data; users belong to the Shtab core."""

import uuid
from datetime import datetime
from enum import StrEnum

from shtab_core.models import User
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from shtab_todo.constants import TASK_STATUS_MAX_LENGTH, TASK_TITLE_MAX_LENGTH
from shtab_todo.db import Base


class TaskStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Workspace(Base):
    __tablename__ = "todo_workspaces"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(default=0)
    tasks: Mapped[list] = mapped_column(JSON, default=list)


class Task(Base):
    __tablename__ = "todo_tasks"
    __table_args__ = (
        CheckConstraint(
            "length(trim(title)) > 0", name="ck_todo_tasks_title_not_blank"
        ),
    )
    # SQLAlchemy reads this once at class creation; ClassVar clashes with its typing.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

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
