"""Create the service tickets table."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tickets",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "priority",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'medium'"),
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_tickets_title_not_blank",
        ),
        sa.CheckConstraint(
            "length(description) <= 5000",
            name="ck_tickets_description_length",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="ck_tickets_priority",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved')",
            name="ck_tickets_status",
        ),
        schema="app",
    )
    op.create_index(
        "ix_tickets_status_created_at",
        "tickets",
        ["status", "created_at"],
        schema="app",
    )


def downgrade():
    op.drop_index("ix_tickets_status_created_at", schema="app")
    op.drop_table("tickets", schema="app")
