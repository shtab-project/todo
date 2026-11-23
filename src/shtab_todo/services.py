"""Task scenarios for the MCP tools, on top of the versioned workspaces."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from mcp.server.mcpserver.exceptions import ToolError
from shtab_core.models import User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from shtab_todo.models import Workspace
from shtab_todo.schemas import Priority, Scope, Status, TaskData, TaskSummary
from shtab_todo.workspace import (
    apply,
    authorize_change,
    lock_workspace,
    snapshot,
    workspace_key,
)


@contextmanager
def tool_errors() -> Iterator[None]:
    """Report workspace rule violations to the MCP client as tool errors."""
    try:
        yield
    except HTTPException as exc:
        raise ToolError(str(exc.detail)) from exc


def find(tasks: list[TaskData], task_id: UUID) -> TaskData:
    task = next((task for task in tasks if task.id == task_id), None)
    if not task:
        raise ToolError("Task not found")
    return task


@dataclass(frozen=True)
class TaskDraft:
    title: str
    description: str = ""
    priority: Priority = "normal"
    due_date: date | None = None


@dataclass
class TodoService:
    session_factory: async_sessionmaker[AsyncSession]

    async def _read(self, user_id: UUID, scope: Scope) -> list[TaskData]:
        async with self.session_factory() as session:
            row = await session.get(Workspace, workspace_key(user_id, scope))

        return snapshot(row).tasks

    async def list_tasks(
        self,
        user_id: UUID,
        scope: Scope,
        status: Status | None,
        query: str,
        limit: int,
    ) -> list[TaskSummary]:
        needle = query.casefold()
        found = [
            TaskSummary.model_validate(task, from_attributes=True)
            for task in await self._read(user_id, scope)
            if (not status or task.status == status) and needle in task.title.casefold()
        ]
        return found[:limit]

    async def get(self, user_id: UUID, scope: Scope, task_id: UUID) -> TaskData:
        return find(await self._read(user_id, scope), task_id)

    async def create(self, user_id: UUID, scope: Scope, draft: TaskDraft) -> TaskData:
        task = TaskData(
            id=uuid7(),
            title=draft.title,
            description=draft.description,
            priority=draft.priority,
            due_date=draft.due_date,
        )

        async with self.session_factory.begin() as session:
            row = await lock_workspace(session, workspace_key(user_id, scope))
            with tool_errors():
                await apply(session, row, [task], user_id)
            stored = find(snapshot(row).tasks, task.id)

        return stored

    async def set_status(
        self, user_id: UUID, scope: Scope, task_id: UUID, status: Status
    ) -> TaskData:
        async with self.session_factory.begin() as session:
            user = await session.get(User, user_id)
            if not user:
                raise ToolError("User not found")
            row = await lock_workspace(session, workspace_key(user_id, scope))
            moved = find(snapshot(row).tasks, task_id).model_copy(
                update={"status": status}
            )
            with tool_errors():
                await apply(
                    session,
                    row,
                    [moved],
                    user_id,
                    authorize=lambda previous, value: authorize_change(
                        user, previous, value
                    ),
                )
            stored = find(snapshot(row).tasks, task_id)

        return stored
