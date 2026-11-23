"""Todo MCP tools through a real MCP server and the core's PluginTools."""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.types import CallToolResult
from shtab_core.db import get_session_factory
from shtab_core.mcp_gateway import PluginTools
from shtab_core.models import User
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shtab_todo.db import Base
from shtab_todo.mcp import register_tools

OWNER, COLLEAGUE = uuid4(), uuid4()


@pytest_asyncio.fixture
async def server():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: User.metadata.tables["users"].create(sync)
        )
        await connection.run_sync(
            lambda sync: Base.metadata.tables["todo_workspaces"].create(sync)
        )

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory.begin() as session:
        session.add_all(
            [
                User(id=OWNER, oidc_sub="owner", username="owner", name="Owner"),
                User(id=COLLEAGUE, oidc_sub="other", username="other", name="Other"),
            ]
        )

    app = FastAPI()
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.state.mcp_tool_names = set()
    mcp = MCPServer("test")
    register_tools(PluginTools(mcp, app, "todo"))
    yield mcp
    await engine.dispose()


async def call(
    server: MCPServer, user_id: UUID, name: str, **arguments
) -> CallToolResult:
    """Call a tool as `user_id`, the way the bearer middleware would."""
    access = AccessToken(token="t", client_id="test", subject=str(user_id), scopes=[])
    token = auth_context_var.set(AuthenticatedUser(access))
    try:
        result = await server.call_tool(name, arguments)
    finally:
        auth_context_var.reset(token)
    assert isinstance(result, CallToolResult)
    return result


async def fails(server: MCPServer, user_id: UUID, name: str, **arguments) -> str:
    """Call a tool that must fail with a reason the model can read."""
    with pytest.raises(ToolError) as error:
        await call(server, user_id, name, **arguments)
    assert not isinstance(error.value, UnexpectedToolError)
    return str(error.value)


async def test_tools_are_registered_under_the_plugin_prefix(server):
    names = {tool.name for tool in await server.list_tools()}
    assert names == {"todo_list", "todo_get", "todo_create", "todo_set_status"}


async def test_create_find_read_and_move_a_task(server):
    created = await call(server, OWNER, "todo_create", title="  Ship MCP  ")
    assert not created.is_error
    task = created.structured_content
    assert task["title"] == "Ship MCP" and task["author_id"] == str(OWNER)

    found = await call(server, OWNER, "todo_list", query="ship")
    assert [item["id"] for item in found.structured_content["result"]] == [task["id"]]
    done = await call(server, OWNER, "todo_list", status="done")
    assert done.structured_content["result"] == []

    read = await call(server, OWNER, "todo_get", task_id=task["id"])
    assert read.structured_content["id"] == task["id"]

    moved = await call(
        server, OWNER, "todo_set_status", task_id=task["id"], status="done"
    )
    assert moved.structured_content["status"] == "done"


async def test_private_tasks_stay_private(server):
    task = (await call(server, OWNER, "todo_create", title="Mine")).structured_content
    listed = await call(server, COLLEAGUE, "todo_list")
    assert listed.structured_content["result"] == []
    assert "Task not found" in await fails(
        server, COLLEAGUE, "todo_get", task_id=task["id"]
    )


async def test_only_managers_or_assignee_may_move_shared_tasks(server):
    task = (
        await call(server, OWNER, "todo_create", title="Shared", scope="shared")
    ).structured_content
    reason = await fails(
        server,
        COLLEAGUE,
        "todo_set_status",
        task_id=task["id"],
        status="done",
        scope="shared",
    )
    assert "the assignee can change only its status" in reason
    still = await call(server, OWNER, "todo_get", task_id=task["id"], scope="shared")
    assert still.structured_content["status"] == "new"


@pytest.mark.parametrize("title", ["", "   "])
async def test_blank_titles_are_rejected(server, title):
    await fails(server, OWNER, "todo_create", title=title)
