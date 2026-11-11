"""per-IP login throttling replaces the per-account lockout

Revision ID: 0005_login_attempts
Revises: 0004_seed_settings
Create Date: 2026-11-11 10:00:00+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_login_attempts"
down_revision: str | None = "0004_seed_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("email_hash", "ip_address", name=op.f("pk_login_attempts")),
    )
    op.create_index(op.f("ix_login_attempts_updated_at"), "login_attempts", ["updated_at"])
    with op.batch_alter_table("users") as batch:
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_count")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False))
        batch.add_column(sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.drop_index(op.f("ix_login_attempts_updated_at"), table_name="login_attempts")
    op.drop_table("login_attempts")
