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
from shtab_core.models import User


@pytest_asyncio.fixture
async def api():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(User.__table__.create)
        await connection.run_sync(lambda sync: Base.metadata.tables["todo_workspaces"].create(sync))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user = SimpleNamespace(id=uuid4(), is_admin=False, is_trusted=False)
    async with factory.begin() as session:
        session.add_all(
            [
                User(id=user.id, oidc_sub="owner", username="owner", name="Owner"),
                User(id=uuid4(), oidc_sub="colleague", username="colleague", name="Colleague"),
            ]
        )
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
async def test_assign_colleague_and_preserve_assignment_on_edit(api):
    client, _ = api
    response = await client.get("/api/plugins/todo/assignees")
    assert response.status_code == 200
    people = response.json()
    assert all(set(person) == {"id", "name", "username"} for person in people)
    colleague = next(person for person in people if person["username"] == "colleague")
    task = {"id": str(uuid4()), "title": "Assigned", "assignee_id": colleague["id"]}
    path = "/api/plugins/todo/workspace/shared"
    saved = await client.patch(path, json={"revision": 0, "upsert": [task]})
    assert saved.status_code == 200
    state = saved.json()
    assert state["tasks"][0]["assignee_id"] == colleague["id"]
    task.update(status="done")
    updated = await client.patch(path, json={"revision": state["revision"], "upsert": [task]})
    assert updated.status_code == 200
    assert updated.json()["tasks"][0]["assignee_id"] == colleague["id"]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["private", "shared"])
async def test_checklist_roundtrip_reorder_and_independent_status(api, scope):
    client, _ = api
    path = f"/api/plugins/todo/workspace/{scope}"
    first = {"id": str(uuid4()), "text": "  Первый пункт  ", "done": False}
    second = {"id": str(uuid4()), "text": "Второй пункт", "done": True}
    task = {"id": str(uuid4()), "title": "Список", "checklist": [first, second]}
    response = await client.patch(path, json={"revision": 0, "upsert": [task]})
    assert response.status_code == 200
    state = response.json()
    saved = state["tasks"][0]
    assert saved["checklist"][0]["text"] == "Первый пункт"
    assert (await client.get(path)).json() == state
    # Completing a task preserves unfinished items; old clients preserve the checklist.
    response = await client.patch(path, json={
        "revision": state["revision"],
        "upsert": [{"id": task["id"], "title": "Список", "status": "done"}],
    })
    state = response.json()
    assert state["tasks"][0]["checklist"] == saved["checklist"]
    assert not state["tasks"][0]["checklist"][0]["done"]
    # Reorder, edit and complete all items without completing the parent.
    task.update(status="new", checklist=[second, {**first, "text": "Изменён", "done": True}])
    response = await client.patch(path, json={"revision": state["revision"], "upsert": [task]})
    state = response.json()
    assert state["tasks"][0]["status"] == "new"
    assert state["tasks"][0]["checklist"] == task["checklist"]
    task["checklist"] = []
    response = await client.patch(path, json={"revision": state["revision"], "upsert": [task]})
    assert response.json()["tasks"][0]["checklist"] == []


@pytest.mark.asyncio
async def test_invalid_checklist_does_not_change_workspace(api):
    client, _ = api
    path = "/api/plugins/todo/workspace/private"
    item = {"id": str(uuid4()), "text": "Пункт", "done": False}
    for checklist in ([{**item, "text": "   "}], [item, item],
                      [{**item, "text": "x" * 501}], [item] * 201):
        response = await client.patch(path, json={
            "revision": 0, "upsert": [{"id": str(uuid4()), "title": "Список", "checklist": checklist}],
        })
        assert response.status_code == 422
    assert (await client.get(path)).json() == {"revision": 0, "tasks": []}


@pytest.mark.asyncio
async def test_deadline_time_roundtrip_and_legacy_edit(api):
    client, _ = api
    path = "/api/plugins/todo/workspace/private"
    task = {"id": str(uuid4()), "title": "К 18:00", "due_date": "2026-11-17",
            "due_at": "2026-11-17T15:00:00Z"}
    response = await client.patch(path, json={"revision": 0, "upsert": [task]})
    assert response.status_code == 200
    state = response.json()
    assert state["tasks"][0]["due_at"] == task["due_at"]
    # A date-only client must preserve the time when changing unrelated fields.
    task.pop("due_at")
    task["status"] = "done"
    response = await client.patch(path, json={"revision": state["revision"], "upsert": [task]})
    state = response.json()
    assert state["tasks"][0]["due_at"] == "2026-11-17T15:00:00Z"
    # Changing the date through an old client clears the stale precise deadline.
    task["due_date"] = "2026-11-18"
    response = await client.patch(path, json={"revision": state["revision"], "upsert": [task]})
    assert response.json()["tasks"][0]["due_at"] is None


@pytest.mark.asyncio
async def test_deadline_requires_timezone(api):
    client, _ = api
    response = await client.patch("/api/plugins/todo/workspace/private", json={
        "revision": 0, "upsert": [{"id": str(uuid4()), "title": "Срок",
                                    "due_at": "2026-11-17T18:00:00"}],
    })
    assert response.status_code == 422
