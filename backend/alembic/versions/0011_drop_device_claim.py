"""Cancel pairing-code flow: drop device_claim in favor of direct BLE scan & connect."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("device_claim")


def downgrade() -> None:
    op.create_table(
        "device_claim",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_pk", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_pk"], ["device.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["consumed_by_user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("device_pk", name="uq_device_claim_device"),
        sa.PrimaryKeyConstraint("id"),
    )
