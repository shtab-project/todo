"""Versioned task workspaces: private per user, shared per installation."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from shtab_core.dependencies import CurrentUser
from shtab_core.models import User
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shtab_todo.dependencies import ReadSession, WriteSession
from shtab_todo.models import Workspace
from shtab_todo.schemas import (
    Assignee,
    Changes,
    Legacy,
    Scope,
    TaskData,
    WorkspaceSnapshot,
)

router = APIRouter(prefix="/api/plugins/todo", tags=["todo"])
MAX_TASKS = 5000

# Fields the assignee of someone else's task may not change; the status they may.
PROTECTED_FIELDS: set[str] = set(
    {
        "title",
        "description",
        "priority",
        "assignee_id",
        "checklist",
        "due_date",
        "due_at",
    }
)

Authorize = Callable[[TaskData, TaskData], None]


@router.get("/assignees", response_model=list[Assignee])
async def list_assignees(_: CurrentUser, session: ReadSession):
    rows = await session.execute(
        select(User.id, User.name, User.username).order_by(User.name, User.username)
    )
    return [
        Assignee(id=user_id, name=name, username=username)
        for user_id, name, username in rows
    ]


def can_manage(user: User, task: TaskData) -> bool:
    """The author, admins and trusted users may edit and delete a task."""
    return user.is_admin or user.is_trusted or task.author_id == user.id


def only_status_changed(previous: TaskData, value: TaskData) -> bool:
    return previous.model_dump(include=PROTECTED_FIELDS) == value.model_dump(
        include=PROTECTED_FIELDS
    )


def authorize_change(user: User, previous: TaskData, value: TaskData) -> None:
    """Managers may change anything; the assignee may change only the status."""
    if can_manage(user, previous):
        return
    if previous.assignee_id == user.id and only_status_changed(previous, value):
        return
    raise HTTPException(
        403,
        "Only the author, an admin or a trusted user can change a task; "
        "the assignee can change only its status",
    )


def workspace_key(user_id: UUID, scope: Scope) -> str:
    return str(user_id) if scope == "private" else "shared"


async def lock_workspace(session: AsyncSession, key: str) -> Workspace:
    await session.execute(
        insert(Workspace).values(key=key, revision=0, tasks=[]).on_conflict_do_nothing()
    )
    return (
        await session.scalars(
            select(Workspace).where(Workspace.key == key).with_for_update()
        )
    ).one()


def snapshot(row: Workspace | None) -> WorkspaceSnapshot:
    """Stored JSON tasks as typed TaskData; old tasks get the default priority."""
    if not row:
        return WorkspaceSnapshot()
    return WorkspaceSnapshot(
        revision=row.revision,
        tasks=[TaskData.model_validate(task) for task in row.tasks],
    )


def merged(
    task: TaskData,
    previous: TaskData | None,
    user_id: UUID,
    now: datetime,
    importing: bool,
) -> TaskData:
    """`task` as it will be stored: fields the client left out keep their values."""
    sent = task.model_fields_set
    keep_due_at = previous and previous.due_date == task.due_date
    return task.model_copy(
        update={
            "due_at": task.due_at
            if not previous or "due_at" in sent
            else (previous.due_at if keep_due_at else None),
            "checklist": task.checklist
            if not previous or "checklist" in sent
            else previous.checklist,
            "priority": task.priority
            if not previous or "priority" in sent
            else previous.priority,
            "author_id": previous.author_id if previous else user_id,
            "created_at": previous.created_at
            if previous
            else (task.created_at if importing and task.created_at else now),
            "updated_at": task.updated_at if importing and task.updated_at else now,
        }
    )


async def apply(
    session: AsyncSession,
    row: Workspace,
    tasks: list[TaskData],
    user_id: UUID,
    deleted: list[UUID] | None = None,
    importing: bool = False,
    authorize: Authorize | None = None,
) -> None:
    if len({task.id for task in tasks}) != len(tasks):
        raise HTTPException(422, "Duplicate tasks")
    assignees = {task.assignee_id for task in tasks if task.assignee_id}
    if assignees:
        known = set(
            await session.scalars(select(User.id).where(User.id.in_(assignees)))
        )
        if known != assignees:
            raise HTTPException(422, "Assignee not found")
    current = {task.id: task for task in snapshot(row).tasks}
    for task_id in deleted or []:
        current.pop(task_id, None)
    now = datetime.now(UTC)
    changed = bool(deleted)
    for task in tasks:
        previous = current.get(task.id)
        if importing and previous:
            continue
        value = merged(task, previous, user_id, now, importing)
        if previous and authorize:
            authorize(previous, value)
        current[value.id] = value
        changed = True
    if len(current) > MAX_TASKS:
        raise HTTPException(422, "Too many tasks")
    if changed:
        row.tasks = [task.model_dump(mode="json") for task in current.values()]
        row.revision += 1


@router.get("/workspace/{scope}", response_model=WorkspaceSnapshot)
async def read_workspace(scope: Scope, user: CurrentUser, session: ReadSession):
    return snapshot(await session.get(Workspace, workspace_key(user.id, scope)))


@router.patch("/workspace/{scope}", response_model=WorkspaceSnapshot)
async def save_workspace(
    scope: Scope, changes: Changes, user: CurrentUser, session: WriteSession
):
    row = await lock_workspace(session, workspace_key(user.id, scope))
    if row.revision != changes.revision:
        raise HTTPException(
            409, "Tasks have changed. Refresh the section and try again."
        )
    deleted = set(changes.delete)
    if any(
        task.id in deleted and not can_manage(user, task)
        for task in snapshot(row).tasks
    ):
        raise HTTPException(
            403, "Only the author, an admin or a trusted user can delete a task"
        )

    await apply(
        session,
        row,
        changes.upsert,
        user.id,
        changes.delete,
        authorize=lambda previous, value: authorize_change(user, previous, value),
    )
    return snapshot(row)


@router.post("/import", response_model=WorkspaceSnapshot)
async def import_legacy(payload: Legacy, user: CurrentUser, session: WriteSession):
    row = await lock_workspace(session, workspace_key(user.id, "private"))
    await apply(session, row, payload.tasks, user.id, importing=True)
    return snapshot(row)
