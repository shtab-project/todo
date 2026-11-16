"""Exercise authorization and concurrency through the HTTP boundary."""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from shtab_todo.db import Base
from shtab_todo.workspace import router
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shtab_core.db import get_session_factory
from shtab_core.dependencies import current_user


@pytest_asyncio.fixture
async def api():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.tables["todo_workspaces"].create(sync))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user = SimpleNamespace(id=uuid4(), is_admin=False, is_trusted=False)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_session_factory] = lambda: factory
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, user
    await engine.dispose()


@pytest.mark.asyncio
async def test_personal_isolation_and_shared_visibility(api):
    client, user = api
    task = {"id": str(uuid4()), "title": "Deadline", "due_date": "2026-11-20"}
    for scope in ("private", "shared"):
        path = f"/api/plugins/todo/workspace/{scope}"
        response = await client.patch(path, json={"revision": 0, "upsert": [task]})
        assert response.status_code == 200
        assert response.json()["tasks"][0]["due_date"] == "2026-11-20"
    user.id = uuid4()
    assert (await client.get("/api/plugins/todo/workspace/private")).json()["tasks"] == []
    assert len((await client.get("/api/plugins/todo/workspace/shared")).json()["tasks"]) == 1


@pytest.mark.asyncio
async def test_conflict_preserves_task_and_import_is_idempotent(api):
    client, _ = api
    task = {"id": str(uuid4()), "title": "Import"}
    first = (await client.post("/api/plugins/todo/import", json={"tasks": [task]})).json()
    second = (await client.post("/api/plugins/todo/import", json={"tasks": [task]})).json()
    assert first == second
    path = "/api/plugins/todo/workspace/private"
    stale = await client.patch(path, json={"revision": 0, "delete": [task["id"]]})
    assert stale.status_code == 409
    assert (await client.get(path)).json() == first
    invalid = await client.patch(
        path,
        json={
            "revision": first["revision"],
            "upsert": [{**task, "due_date": "2026-02-30"}],
        },
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["author", "stranger", "admin", "trusted"])
async def test_delete_permissions(api, role):
    client, user = api
    author = user.id
    path = "/api/plugins/todo/workspace/shared"
    task = {"id": str(uuid4()), "title": "Permissions"}
    state = (await client.patch(path, json={"revision": 0, "upsert": [task]})).json()
    if role != "author":
        user.id = uuid4()
    user.is_admin = role == "admin"
    user.is_trusted = role == "trusted"
    forged = await client.patch(
        path,
        json={
            "revision": state["revision"],
            "upsert": [{**task, "author_id": str(user.id)}],
        },
    )
    state = forged.json()
    assert state["tasks"][0]["author_id"] == str(author)
    deleted = await client.patch(path, json={"revision": state["revision"], "delete": [task["id"]]})
    if role == "stranger":
        assert deleted.status_code == 403
        assert (await client.get(path)).json() == state
    else:
        assert deleted.status_code == 200
        assert deleted.json()["tasks"] == []
