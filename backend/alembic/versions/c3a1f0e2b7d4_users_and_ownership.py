"""users, login sessions and per-user ownership

Revision ID: c3a1f0e2b7d4
Revises: bd60d90d22a9
Create Date: 2026-10-19 21:00:00

Existing rows are assigned to the built-in ``local`` user, so a single-user
installation keeps all of its documents and conversations.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3a1f0e2b7d4"
down_revision: str | Sequence[str] | None = "bd60d90d22a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Lets batch mode find the unnamed UNIQUE(sha256) that SQLite created in the first migration.
NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.execute(
        "INSERT INTO users (id, email, password_hash, is_admin, created_at) "
        "VALUES ('local', 'local@localhost', '', 1, CURRENT_TIMESTAMP)"
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    with op.batch_alter_table("documents", naming_convention=NAMING) as b:
        b.add_column(sa.Column("owner_id", sa.String(length=32), nullable=False, server_default="local"))
        b.drop_constraint("uq_documents_sha256", type_="unique")
        b.create_unique_constraint("uq_documents_owner_sha256", ["owner_id", "sha256"])
        b.create_foreign_key("fk_documents_owner", "users", ["owner_id"], ["id"], ondelete="CASCADE")
        b.create_index("ix_documents_owner_id", ["owner_id"])
    with op.batch_alter_table("conversations") as b:
        b.add_column(sa.Column("owner_id", sa.String(length=32), nullable=False, server_default="local"))
        b.create_foreign_key("fk_conversations_owner", "users", ["owner_id"], ["id"], ondelete="CASCADE")
        b.create_index("ix_conversations_owner_id", ["owner_id"])
    with op.batch_alter_table("query_logs") as b:
        b.add_column(sa.Column("owner_id", sa.String(length=32), nullable=True))
        b.create_foreign_key("fk_query_logs_owner", "users", ["owner_id"], ["id"], ondelete="CASCADE")
        b.create_index("ix_query_logs_owner_id", ["owner_id"])
    op.execute("UPDATE query_logs SET owner_id = 'local'")


def downgrade() -> None:
    with op.batch_alter_table("query_logs") as b:
        b.drop_index("ix_query_logs_owner_id")
        b.drop_constraint("fk_query_logs_owner", type_="foreignkey")
        b.drop_column("owner_id")
    with op.batch_alter_table("conversations") as b:
        b.drop_index("ix_conversations_owner_id")
        b.drop_constraint("fk_conversations_owner", type_="foreignkey")
        b.drop_column("owner_id")
    with op.batch_alter_table("documents") as b:
        b.drop_index("ix_documents_owner_id")
        b.drop_constraint("fk_documents_owner", type_="foreignkey")
        b.drop_constraint("uq_documents_owner_sha256", type_="unique")
        b.drop_column("owner_id")
        b.create_unique_constraint("uq_documents_sha256", ["sha256"])
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
