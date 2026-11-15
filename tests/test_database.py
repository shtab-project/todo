import uuid
from datetime import UTC, datetime
from io import StringIO

import pytest
from alembic import command
from shtab_core.db import Base as CoreBase
from shtab_core.models import User
from shtab_todo.db import Base, get_session_factory
from shtab_todo.migrate import migration_config
from shtab_todo.models import Task, TaskStatus
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        CoreBase.metadata.create_all(connection)
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32))"
        )
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('0003')")
        config = migration_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def session(database):
    with Session(database, expire_on_commit=False) as session:
        yield session


def user(session, subject):
    account = User(oidc_sub=subject, username=subject, name=subject)
    session.add(account)
    session.commit()
    return account


def test_task_defaults_and_update_timestamp(session):
    author = user(session, "author")
    task = Task(
        title="Первая задача",
        author_id=author.id,
        updated_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    session.add(task)
    session.commit()
    assert task.id.version == 7
    assert task.status is TaskStatus.NEW
    assert task.description == "" and task.assignee_id is None
    assert task.created_at is not None
    task.title = "Изменённая задача"
    task.status = TaskStatus.IN_PROGRESS
    session.commit()
    assert task.updated_at.year > 2000
    session.expire_all()
    assert session.get(Task, task.id).status is TaskStatus.IN_PROGRESS


@pytest.mark.parametrize("column, value", [("title", "   "), ("status", "unknown")])
def test_database_rejects_invalid_task(session, column, value):
    author = user(session, "author")
    session.add(Task(title="Task", author_id=author.id))
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(
            text(f"UPDATE todo_tasks SET {column} = :value"), {"value": value}
        )
    session.rollback()


def test_author_must_exist(session):
    session.add(Task(title="Task", author_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_assignee_keeps_task_and_author_cannot_be_deleted(session):
    author = user(session, "author")
    assignee = user(session, "assignee")
    task = Task(title="Task", author_id=author.id, assignee_id=assignee.id)
    session.add(task)
    session.commit()
    task_id = task.id
    session.delete(assignee)
    session.commit()
    session.expire_all()
    assert session.get(Task, task_id).assignee_id is None
    session.delete(author)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert session.get(Task, task_id) is not None


def test_migration_matches_models_and_downgrade_preserves_core(database):
    assert "todo_tasks" not in CoreBase.metadata.tables
    assert set(Base.metadata.tables) == {"todo_tasks"}
    with database.begin() as connection:
        config = migration_config()
        config.attributes["connection"] = connection
        command.check(config)
        command.upgrade(config, "head")
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version_todo"))
            == "todo_0001"
        )
        command.downgrade(config, "base")
        assert "todo_tasks" not in inspect(connection).get_table_names()
        assert "users" in inspect(connection).get_table_names()
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003"
        )


def test_postgresql_migration_sql(monkeypatch):
    from shtab_core.config import settings

    monkeypatch.setattr(
        settings, "database_url", "postgresql+asyncpg://test:test@localhost/test"
    )
    config = migration_config()
    config.output_buffer = StringIO()
    command.upgrade(config, "head", sql=True)
    sql = config.output_buffer.getvalue()
    assert "CREATE TABLE todo_tasks" in sql
    assert "REFERENCES users (id) ON DELETE RESTRICT" in sql
    assert "REFERENCES users (id) ON DELETE SET NULL" in sql
    assert "alembic_version_todo" in sql


def test_shared_session_factory():
    from shtab_core.db import get_session_factory as core_factory

    assert get_session_factory() is core_factory()
