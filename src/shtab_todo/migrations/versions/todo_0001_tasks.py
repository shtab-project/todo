"""Initial task storage. Revision ID: todo_0001."""

import sqlalchemy as sa
from alembic import op

revision = "todo_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "todo_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "length(trim(title)) > 0", name="ck_todo_tasks_title_not_blank"
        ),
        sa.CheckConstraint(
            "status IN ('new', 'in_progress', 'done')", name="ck_todo_tasks_status"
        ),
    )
    op.create_index("ix_todo_tasks_status", "todo_tasks", ["status"])
    op.create_index("ix_todo_tasks_author_id", "todo_tasks", ["author_id"])
    op.create_index("ix_todo_tasks_assignee_id", "todo_tasks", ["assignee_id"])


def downgrade() -> None:
    op.drop_table("todo_tasks")
