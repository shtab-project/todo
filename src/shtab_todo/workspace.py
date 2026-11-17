"""Versioned task workspaces: private per user, shared per installation."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, field_validator
from sqlalchemy import JSON, Integer, String, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from shtab_core.db import get_session_factory
from shtab_core.dependencies import CurrentUser
from shtab_core.models import User
from shtab_todo.db import Base

router = APIRouter(prefix="/api/plugins/todo", tags=["todo"])
Factory = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
Scope = Literal["private", "shared"]


class Assignee(BaseModel):
    id: UUID
    name: str
    username: str


@router.get("/assignees", response_model=list[Assignee])
async def list_assignees(_: CurrentUser, factory: Factory):
    async with factory() as session:
        rows = await session.execute(
            select(User.id, User.name, User.username).order_by(User.name, User.username)
        )
        return [dict(row._mapping) for row in rows]


class Workspace(Base):
    __tablename__ = "todo_workspaces"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    tasks: Mapped[list] = mapped_column(JSON, default=list)


class ChecklistItem(BaseModel):
    id: UUID
    text: str = Field(min_length=1, max_length=500)
    done: bool = False

    @field_validator("text")
    @classmethod
    def trim_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Пункт чек-листа не может быть пустым")
        return value.strip()


class TaskData(BaseModel):
    id: UUID
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=100000)
    status: Literal["new", "in_progress", "done"] = "new"
    assignee_id: UUID | None = None
    checklist: list[ChecklistItem] = Field(default_factory=list, max_length=200)
    due_date: date | None = None
    due_at: AwareDatetime | None = None
    author_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("checklist")
    @classmethod
    def unique_items(cls, value: list[ChecklistItem]) -> list[ChecklistItem]:
        if len({item.id for item in value}) != len(value):
            raise ValueError("Повторяющиеся пункты чек-листа")
        return value

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Название не может быть пустым")
        return value.strip()


class Changes(BaseModel):
    revision: int = Field(ge=0)
    upsert: list[TaskData] = Field(default_factory=list, max_length=5000)
    delete: list[UUID] = Field(default_factory=list, max_length=5000)


class Legacy(BaseModel):
    tasks: list[TaskData] = Field(max_length=5000)


async def workspace(session: AsyncSession, user_id: UUID, scope: Scope) -> Workspace:
    key = str(user_id) if scope == "private" else "shared"
    await session.execute(
        insert(Workspace).values(key=key, revision=0, tasks=[]).on_conflict_do_nothing()
    )
    return (
        await session.scalars(select(Workspace).where(Workspace.key == key).with_for_update())
    ).one()


def snapshot(row: Workspace) -> dict:
    return {"revision": row.revision, "tasks": row.tasks}


async def apply(
    session: AsyncSession,
    row: Workspace,
    tasks: list[TaskData],
    user_id: UUID,
    deleted: list[UUID] | None = None,
    importing: bool = False,
) -> None:
    if len({task.id for task in tasks}) != len(tasks):
        raise HTTPException(422, "Повторяющиеся задачи")
    assignees = {task.assignee_id for task in tasks if task.assignee_id}
    if assignees:
        known = set(await session.scalars(select(User.id).where(User.id.in_(assignees))))
        if known != assignees:
            raise HTTPException(422, "Исполнитель не найден")
    current = {task["id"]: task for task in row.tasks}
    for task_id in deleted or []:
        current.pop(str(task_id), None)
    now = datetime.now(UTC).isoformat()
    changed = bool(deleted)
    for task in tasks:
        previous = current.get(str(task.id))
        if importing and previous:
            continue
        value = task.model_dump(mode="json")
        if previous and "due_at" not in task.model_fields_set:
            value["due_at"] = (
                previous.get("due_at") if value["due_date"] == previous.get("due_date") else None
            )
        if previous and "checklist" not in task.model_fields_set:
            value["checklist"] = previous.get("checklist", [])
        value["author_id"] = previous["author_id"] if previous else str(user_id)
        value["created_at"] = (
            previous["created_at"]
            if previous
            else (value["created_at"] if importing and value["created_at"] else now)
        )
        value["updated_at"] = value["updated_at"] if importing and value["updated_at"] else now
        current[value["id"]] = value
        changed = True
    if len(current) > 5000:
        raise HTTPException(422, "Слишком много задач")
    if changed:
        row.tasks = list(current.values())
        row.revision += 1


@router.get("/workspace/{scope}")
async def read_workspace(scope: Scope, user: CurrentUser, factory: Factory):
    async with factory.begin() as session:
        return snapshot(await workspace(session, user.id, scope))


@router.patch("/workspace/{scope}")
async def save_workspace(scope: Scope, changes: Changes, user: CurrentUser, factory: Factory):
    async with factory.begin() as session:
        row = await workspace(session, user.id, scope)
        if row.revision != changes.revision:
            raise HTTPException(409, "Задачи изменились. Обновите раздел и повторите действие.")
        deleted = {str(task_id) for task_id in changes.delete}
        if not (user.is_admin or user.is_trusted) and any(
            task["id"] in deleted and task["author_id"] != str(user.id) for task in row.tasks
        ):
            raise HTTPException(
                403, "Удалять задачу может автор, администратор или доверенный пользователь"
            )
        await apply(session, row, changes.upsert, user.id, changes.delete)
        return snapshot(row)


@router.post("/import")
async def import_legacy(payload: Legacy, user: CurrentUser, factory: Factory):
    async with factory.begin() as session:
        row = await workspace(session, user.id, "private")
        await apply(session, row, payload.tasks, user.id, importing=True)
        return snapshot(row)
