"""system settings

Revision ID: 0002_system_settings
Revises: 0001_initial
Create Date: 2026-11-05 09:00:00+00:00

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0002_system_settings"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULTS = [
    ("company_name", "Acme Helpdesk", "Name shown in the web interface header and login page"),
    ("max_open_tickets_per_employee", "20", "Max Open/In Progress tickets one employee may have at a time"),
    ("allow_employee_registration", "true", "Allow people to self-register as Employees (true/false)"),
]


def upgrade() -> None:
    table = op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=1000), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["users.id"], name=op.f("fk_system_settings_updated_by_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_settings")),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        table,
        [{"key": k, "value": v, "description": d, "updated_at": now, "updated_by_id": None} for k, v, d in DEFAULTS],
    )


def downgrade() -> None:
    op.drop_table("system_settings")
