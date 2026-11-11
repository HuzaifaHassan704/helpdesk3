"""token_version: invalidate access tokens after a password change

Revision ID: 0006_token_version
Revises: 0005_login_attempts
Create Date: 2026-11-11 11:00:00+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_token_version"
down_revision: str | None = "0005_login_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), server_default=sa.text("0"), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("token_version")
