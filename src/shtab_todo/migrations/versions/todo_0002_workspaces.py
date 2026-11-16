"""Private and shared task workspaces."""

import sqlalchemy as sa
from alembic import op

revision = "todo_0002"
down_revision = "todo_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "todo_workspaces",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("tasks", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("todo_workspaces")
