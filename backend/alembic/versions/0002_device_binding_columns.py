"""device binding columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16

只做一件事：给 device 表加 4 列（be / status / handover_state / bound_at）。
不建表、不建约束 —— 归属约束按 06 §10 排在 0005，回填在 0003，验数在 0004。

三个非空列都带 server_default：正式库在 0001 时已有 2 台设备，
不带默认值的 ADD COLUMN NOT NULL 会在有数据的表上直接失败。
"""

from re import S
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "device",
        sa.Column("be", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "device",
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'claimable'"),
            nullable=False,
        ),
    )
    op.add_column(
        "device",
        sa.Column(
            "handover_state",
            sa.String(length=16),
            server_default=sa.text("'required'"),
            nullable=False,
        ),
    )
    op.add_column("device", sa.Column("bound_at", sa.DateTime(), nullable=True))

    op.create_table(
        "device_claim",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_pk", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_pk"], ["device.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["consumed_by_user_id"], ["user.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("device_pk", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_pk"], ["device.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_created_at"), "audit", ["created_at"], unique=False)

    op.create_table(
        "legacy_row_archive",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_table", sa.String(length=32), nullable=False),
        sa.Column("source_pk", sa.Integer(), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_table", "source_pk", name="uq_legacy_row"),
    )

    op.create_table(
        "device_session_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_pk", sa.Integer(), nullable=False),
        sa.Column("be", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column("last_seq", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_pk"], ["device.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("device_session_record")
    op.drop_table("legacy_row_archive")
    op.drop_table("audit")
    op.drop_table("device_claim")
    op.drop_column("device", "bound_at")
    op.drop_column("device", "handover_state")
    op.drop_column("device", "status")
    op.drop_column("device", "be")
