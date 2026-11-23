"""Schemas of the Todo API."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, field_validator

Scope = Literal["private", "shared"]
Status = Literal["new", "in_progress", "done"]
Priority = Literal["critical", "normal", "light"]


class Assignee(BaseModel):
    id: UUID
    name: str
    username: str


class ChecklistItem(BaseModel):
    id: UUID
    text: str = Field(min_length=1, max_length=500)
    done: bool = False

    @field_validator("text")
    @classmethod
    def trim_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A checklist item cannot be blank")
        return value.strip()


class TaskData(BaseModel):
    id: UUID
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=100000)
    status: Status = "new"
    priority: Priority = "normal"
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
            raise ValueError("Duplicate checklist items")
        return value

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The title cannot be blank")
        return value.strip()


class TaskSummary(BaseModel):
    """A task without its description and checklist, for search results."""

    id: UUID
    title: str
    status: Status = "new"
    priority: Priority = "normal"
    assignee_id: UUID | None = None
    due_date: date | None = None


@dataclass(frozen=True)
class Health:
    plugin: str
    status: str = "ok"


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """A workspace as the client sees it: its revision and all of its tasks."""

    revision: int = 0
    tasks: list[TaskData] = field(default_factory=list)


class Changes(BaseModel):
    revision: int = Field(ge=0)
    upsert: list[TaskData] = Field(default_factory=list, max_length=5000)
    delete: list[UUID] = Field(default_factory=list, max_length=5000)


class Legacy(BaseModel):
    tasks: list[TaskData] = Field(max_length=5000)
