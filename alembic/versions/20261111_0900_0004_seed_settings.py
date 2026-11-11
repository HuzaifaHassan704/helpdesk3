"""seed the remaining built-in settings

Revision ID: 0004_seed_settings
Revises: 0003_enhancements
Create Date: 2026-11-11 09:00:00+00:00

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0004_seed_settings"
down_revision: str | None = "0003_enhancements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEEDS = [
    ("auto_assign_on_create", "false", "Give new tickets to the least-loaded active agent (true/false)"),
    ("sla_hours_urgent", "4", "Hours until an Urgent ticket is due (1-8760)"),
    ("sla_hours_high", "8", "Hours until a High ticket is due (1-8760)"),
    ("sla_hours_medium", "24", "Hours until a Medium ticket is due (1-8760)"),
    ("sla_hours_low", "72", "Hours until a Low ticket is due (1-8760)"),
]

settings_table = sa.table(
    "system_settings",
    sa.column("key", sa.String),
    sa.column("value", sa.String),
    sa.column("description", sa.String),
    sa.column("updated_at", sa.DateTime(timezone=True)),
    sa.column("updated_by_id", sa.Integer),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {r[0] for r in bind.execute(sa.select(settings_table.c.key))}  # keep values an admin already typed in
    now = datetime.now(UTC)
    rows = [
        {"key": k, "value": v, "description": d, "updated_at": now, "updated_by_id": None}
        for k, v, d in SEEDS
        if k not in existing
    ]
    if rows:
        op.bulk_insert(settings_table, rows)


def downgrade() -> None:
    keys = [k for k, _, _ in SEEDS]
    op.execute(
        settings_table.delete().where(settings_table.c.key.in_(keys), settings_table.c.updated_by_id.is_(None))
    )
