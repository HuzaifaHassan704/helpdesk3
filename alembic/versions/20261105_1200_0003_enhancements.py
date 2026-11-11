"""ticket history, SLA due dates, login lockout

Revision ID: 0003_enhancements
Revises: 0002_system_settings
Create Date: 2026-11-05 12:00:00+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_enhancements"
down_revision: str | None = "0002_system_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name=op.f("fk_ticket_events_actor_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_events_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_events")),
    )
    op.create_index(op.f("ix_ticket_events_ticket_id"), "ticket_events", ["ticket_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ticket_events_ticket_id"), table_name="ticket_events")
    op.drop_table("ticket_events")
    with op.batch_alter_table("tickets") as batch:
        batch.drop_column("due_at")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_count")
