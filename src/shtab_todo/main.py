"""Точка подключения к FastAPI ядра; отдельное приложение не создаётся."""

from fastapi import APIRouter, FastAPI
from shtab_core.dependencies import CurrentUser

router = APIRouter(prefix="/api/plugins/todo", tags=["todo"])


@router.get("/health")
async def health(_: CurrentUser):
    """Подтверждение подключения backend, без хранилища задач."""
    return {"plugin": "todo", "status": "ok"}


def register(app: FastAPI) -> None:
    """Подключить роутер. Ручки задач будут добавлены следующим шагом."""
    app.include_router(router)
