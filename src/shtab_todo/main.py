"""Mounts the Todo routes into the core FastAPI app; no app of its own."""

from fastapi import APIRouter, FastAPI
from shtab_core.dependencies import CurrentUser

from shtab_todo.schemas import Health
from shtab_todo.workspace import router as workspace_router

router = APIRouter(prefix="/api/plugins/todo", tags=["todo"])


@router.get("/health", response_model=Health)
async def health(_: CurrentUser):
    """Confirms the backend is mounted."""
    return Health(plugin="todo")


def register(app: FastAPI) -> None:
    app.include_router(router)
    app.include_router(workspace_router)
