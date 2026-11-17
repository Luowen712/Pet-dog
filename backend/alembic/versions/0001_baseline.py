"""baseline: 最初的 6 张业务表

Revision ID: 0001
Revises: 无（整条链的根）
Create Date: 2026-11-13 21:55

文档映射：06 §310 的「0001 基线」→ 本文件，一一对应。

内容：user / device / command_log / telemetry / scene / face_asset 六张表。
此时的缺口正是后面七个文件存在的理由：
  device       只有 8 列，缺 be / status / handover_state / bound_at  → 0002
  user         只有 7 列，缺 deleted_at                                → 0004
  command_log  缺 device_pk / actor_user_id / be / tv / 等 8 列        → 0004
  telemetry    缺 device_pk / be / session_id                          → 0004
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0001"

# 接在谁的后面
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 下发过的每条命令
    op.create_table(
        "command_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=32), nullable=True),
        sa.Column("msg_id", sa.String(length=36), nullable=True),
        sa.Column("cmd", sa.Integer(), nullable=True),
        sa.Column("action", sa.Integer(), nullable=True),
        sa.Column("param", sa.String(length=128), nullable=True),
        sa.Column("status", sa.Integer(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_command_log_device_id"), "command_log", ["device_id"], unique=False
    )

    op.create_index(
        op.f("ix_command_log_msg_id"), "command_log", ["msg_id"], unique=False
    )
    # 设备（硬件资产），device_id 是业务编号
    op.create_table(
        "device",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("firmware", sa.String(length=16), nullable=True),
        sa.Column("capability", sa.Integer(), nullable=True),
        sa.Column("online", sa.Boolean(), nullable=True),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
    )
    # 表情素材
    op.create_table(
        "face_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("data", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # 场景（一串动作）
    op.create_table(
        "scene",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("steps", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # 设备上报的电量/状态
    op.create_table(
        "telemetry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=32), nullable=True),
        sa.Column("battery", sa.Integer(), nullable=True),
        sa.Column("music_state", sa.Integer(), nullable=True),
        sa.Column("action", sa.Integer(), nullable=True),
        sa.Column("raw", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_telemetry_created_at"), "telemetry", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_telemetry_device_id"), "telemetry", ["device_id"], unique=False
    )

    # 账号、密码哈希、角色、令牌版本
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column(
            "token_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("user")
    op.drop_index(op.f("ix_telemetry_device_id"), table_name="telemetry")
    op.drop_index(op.f("ix_telemetry_created_at"), table_name="telemetry")
    op.drop_table("telemetry")
    op.drop_table("scene")
    op.drop_table("face_asset")
    op.drop_table("device")
    op.drop_index(op.f("ix_command_log_msg_id"), table_name="command_log")
    op.drop_index(op.f("ix_command_log_device_id"), table_name="command_log")
    op.drop_table("command_log")
