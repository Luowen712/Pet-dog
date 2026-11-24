"""add legacy table binding columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17

文档映射：06 §310 的「0002 新增」→ 本文件（第二部分：遗留表的 12 列）。
文档没有单列这一批，因为原设计是「0002 一次性加完」；实际拆成两批，
第一批是 0002 的 device 4 列，第二批就是本文件的 12 列。

按 06 §「首版停机迁移」补齐遗留表的配套列（06 文档 306-307 行）：

    user        1 列：deleted_at
    command_log 8 列：device_pk / actor_user_id / be / tv / revision /
                      transport / reason / session_id
    telemetry   3 列：device_pk / be / session_id

本迁移只做 DDL，不加外键、不写数据，两个原因：

1. 存量 command_log / telemetry 的 device_id 可能指向已删除的设备（孤儿行）。
   此刻建 FK 会直接失败，所以 device_pk 先以可空列落地：
   回填在 0005，孤儿行归档在 0006，验数在 0007，
   FK 与 NOT NULL 留到验过零孤儿之后的 0008（contract 阶段）。

2. MySQL 的 ALTER TABLE 会隐式提交，Alembic 的 transaction 包不住 DDL。
   把"加列"和"回填"塞进同一个 revision，一旦回填中途失败，列已经落库而版本号
   没记上，重跑就报 1060 Duplicate column。DDL 与 DML 必须分开。

be / tv / revision 三个非空列必须同时写 default 与 server_default：
只写 default 只是 ORM 层的事，不进 DDL；向已有数据的表 ADD COLUMN NOT NULL
且无 DDL 默认值，MySQL 直接报 1364 (Field doesn't have a default value)。

session_id 用 String(36)，与 device_session_record.session_id 的长度逐字对齐，
否则将来建外键会报 3780（引用列与被引用列类型不兼容）。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    """Upgrade schema."""
    # ---- command_log：8 列 ----
    # device_pk 可空：孤儿行先留空，等 0006 验完再收紧为 NOT NULL + FK
    op.add_column("command_log", sa.Column("device_pk", sa.Integer(), nullable=True))
    # actor_user_id 可空：设备自发的命令没有操作人
    op.add_column("command_log", sa.Column("actor_user_id", sa.Integer(), nullable=True))
    # be / tv / revision 记录命令发起时的绑定纪元、身份版本、状态版本，用于事后判定有效性
    op.add_column(
        "command_log",
        sa.Column("be", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "command_log",
        sa.Column("tv", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "command_log",
        sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    # transport 可空：null=尚未尝试，0 全写，1 确定未写，2 可能部分写
    op.add_column("command_log", sa.Column("transport", sa.Integer(), nullable=True))
    op.add_column("command_log", sa.Column("reason", sa.String(length=128), nullable=True))
    op.add_column("command_log", sa.Column("session_id", sa.String(length=36), nullable=True))

    # ---- telemetry：3 列 ----
    op.add_column("telemetry", sa.Column("device_pk", sa.Integer(), nullable=True))
    op.add_column(
        "telemetry",
        sa.Column("be", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("telemetry", sa.Column("session_id", sa.String(length=36), nullable=True))

    # ---- user：1 列 ----
    # deleted_at 只记软删除时间；账号状态仍以 status(active/revoking/revoked) 为准
    op.add_column("user", sa.Column("deleted_at", sa.DateTime(), nullable=True))



def downgrade() -> None:
    """按 upgrade 的逆序删列。

    本迁移没有加约束和索引，所以逐列 drop_column 即可；
    逆序不是为了正确性（列之间无依赖），而是为了让回退路径和升级路径镜像，
    将来有人往 upgrade 尾部追加依赖顺序的 DDL 时不会踩坑。
    """
    op.drop_column("user", "deleted_at")

    op.drop_column("telemetry", "session_id")
    op.drop_column("telemetry", "be")
    op.drop_column("telemetry", "device_pk")

    op.drop_column("command_log", "session_id")
    op.drop_column("command_log", "reason")
    op.drop_column("command_log", "transport")
    op.drop_column("command_log", "revision")
    op.drop_column("command_log", "tv")
    op.drop_column("command_log", "be")
    op.drop_column("command_log", "actor_user_id")
    op.drop_column("command_log", "device_pk")
