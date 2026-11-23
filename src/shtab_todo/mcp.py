"""MCP tools of the Todo plugin: find, read, create tasks and move them."""

from datetime import date
from typing import Annotated
from uuid import UUID

from mcp.types import ToolAnnotations
from pydantic import Field, StringConstraints
from shtab_core.mcp_auth import require_mcp_user_id
from shtab_core.mcp_gateway import PluginTools

from shtab_todo.constants import TASK_TITLE_MAX_LENGTH
from shtab_todo.schemas import Priority, Scope, Status, TaskData, TaskSummary
from shtab_todo.services import TaskDraft, TodoService

# Stripped before the length check, so a blank title fails as a clear argument error.
Title = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=TASK_TITLE_MAX_LENGTH
    ),
]
Limit = Annotated[int, Field(ge=1, le=100)]

READER = ToolAnnotations(read_only_hint=True, open_world_hint=False)
CREATOR = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
MOVER = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def register_tools(tools: PluginTools) -> None:
    def service() -> TodoService:
        return TodoService(tools.session_factory())

    @tools.tool("list", annotations=READER)
    async def list_tasks(
        scope: Scope = "private",
        status: Status | None = None,
        query: str = "",
        limit: Limit = 50,
    ) -> list[TaskSummary]:
        """Find tasks by title, optionally by status. Returns tasks without descriptions.

        `private` is the caller's own list, `shared` is the organization's.
        """
        return await service().list_tasks(
            require_mcp_user_id(), scope, status, query, limit
        )

    @tools.tool("get", annotations=READER)
    async def get_task(task_id: UUID, scope: Scope = "private") -> TaskData:
        """Read one task with its description and checklist."""
        return await service().get(require_mcp_user_id(), scope, task_id)

    @tools.tool("create", annotations=CREATOR)
    async def create_task(
        title: Title,
        description: str = "",
        scope: Scope = "private",
        priority: Priority = "normal",
        due_date: date | None = None,
    ) -> TaskData:
        """Create a task. The description supports Markdown."""
        draft = TaskDraft(
            title=title, description=description, priority=priority, due_date=due_date
        )
        return await service().create(require_mcp_user_id(), scope, draft)

    @tools.tool("set_status", annotations=MOVER)
    async def set_status(
        task_id: UUID, status: Status, scope: Scope = "private"
    ) -> TaskData:
        """Move a task to `new`, `in_progress` or `done`.

        The author, admins and trusted users may move any task; the assignee may
        move a task they are assigned to.
        """
        return await service().set_status(require_mcp_user_id(), scope, task_id, status)
