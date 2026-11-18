"""expand: device 补 4 列 + 新建 4 张绑定相关表

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16

本文件做两件事：

1. device 加 4 列：be / status / handover_state / bound_at。
   三个非空列都带 server_default —— 正式库在 0001 时已有 2 台设备，
   不带默认值的 ADD COLUMN ... NOT NULL 会直接报 1364
   (Field doesn't have a default value)。
   注意 server_default 只是给存量行一个占位值，不代表业务真相：
   status 一律填成 'claimable' 之后，有主的设备会变成"有主却可认领"的
   矛盾状态，0003 会按 owner_id 把它们纠正回来。

2. 新建 4 张表（配 1 个索引）：
   device_claim           配对码，一次性消费，带尝试次数与锁定时间
   audit                  审计流水
   legacy_row_archive     无法证明归属的历史行归档（含 sha256，防篡改）
   device_session_record  WebSocket 会话记录（be / session_id / last_seq）
   audit.created_at 建索引，因为审计查询永远按时间倒序翻。

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ==================== device：绑定状态 4 列 ====================
    # 这 4 列合起来回答三件事：设备归谁（owner_id，0001 已有）、
    # 现在能不能被认领（status）、换主时的交接做完没有（handover_state）、
    # 以及这次归属从哪一刻开始（bound_at + be）。

    op.add_column(
        "device",
        sa.Column("be", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "device",
        #   claimable  无主，可被配对码认领
        #   bound      有主，正在服务某个账号
        #   retired    已退役，不再参与认领与下发
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'claimable'"),
            nullable=False,
        ),
    )
    op.add_column(
        "device",
        #   required  还需净化（清上一位主人的表情、场景、缓存）
        #   ready     交接完成，可以交给下一位主人
        sa.Column(
            "handover_state",
            sa.String(length=16),
            server_default=sa.text("'required'"),
            nullable=False,
        ),
    )
    # 绑定时刻，可空 —— 未绑定设备没有这个概念。
    op.add_column("device", sa.Column("bound_at", sa.DateTime(), nullable=True))

    # ==================== device_claim：配对码 ====================
    # 一台设备一条记录，配对码用完即弃（consumed_at 非空即失效）。
    # 只存 code_hash 不存明文：库被拖走也拿不到能直接用的配对码。
    op.create_table(
        "device_claim",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_pk", sa.Integer(), nullable=False),
        # 6 位配对码的 sha256（64 位十六进制）
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        # 过期时刻，过了就作废，防止旧码被翻出来重放
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        # 已经猜错几次。6 位数字不限制次数就能被穷举，
        # 累计到阈值后配合 locked_until 锁定。
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        # 锁定到这个时刻为止：连续输错后在这之前一律拒绝，即使码是对的。
        # 可空 = 当前未锁定。
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        # 被用掉的时刻。非空即代表这条码已消费，不能再去认领第二台设备。
        # 不直接删行，是为了留下"谁在什么时候用掉了哪条码"的证据。
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        # user.id —— 被谁用掉。可空，仅在 consumed_at 非空时有意义。
        sa.Column("consumed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        # 设备被删时不连带删码，必须先显式清理（硬件资产不许被静默带走证据）
        sa.ForeignKeyConstraint(["device_pk"], ["device.id"], ondelete="RESTRICT"),
        # 账号被删时同理：RESTRICT 而不是 SET NULL，审计线索不许被抹掉
        sa.ForeignKeyConstraint(
            ["consumed_by_user_id"], ["user.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ==================== audit：审计流水 ====================
    op.create_table(
        "audit",
        sa.Column("id", sa.Integer(), nullable=False),
        # 操作人。可空 —— 设备自发或系统定时任务没有"人"这个主体。
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        # 相关设备。可空 —— 账号级动作（登录、改密、注销）不涉及具体设备。
        # 两个外键都可空，是因为审计要记"设备动作"和"账号动作"两类，
        # 不能为了凑非空而编造主体。
        sa.Column("device_pk", sa.Integer(), nullable=True),
        # 动作名，如 login / claim / unbind / account_delete。
        # 用字符串不用枚举：动作会随业务增长，加值不该要求改表结构。
        sa.Column("action", sa.String(length=32), nullable=False),
        # 详情（谁对哪台设备做了什么、结果如何），给人看的自由文本
        sa.Column("detail", sa.String(length=255), nullable=True),
        # 发生时刻，下面单独建索引
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_pk"], ["device.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    # 审计查询永远是"最近 N 条"，按时间倒序翻页，必须有索引，
    # 否则表一大就是全表扫描 + filesort。
    op.create_index(op.f("ix_audit_created_at"), "audit", ["created_at"], unique=False)

    # ==================== legacy_row_archive：孤儿归档 ====================
    # 归属无法证明的历史行，先整行搬到这里，再从活跃表删掉。
    op.create_table(
        "legacy_row_archive",
        sa.Column("id", sa.Integer(), nullable=False),
        # 原始表名（command_log / telemetry），说明这行从哪搬来的
        sa.Column("source_table", sa.String(length=32), nullable=False),
        # 原始表里那行的主键值，配合 source_table 定位"原来是谁"
        sa.Column("source_pk", sa.Integer(), nullable=False),
        # 业务字段的 SHA-256（64 位小写十六进制），用来证明归档内容没被改过。
        # 刻意不含 created_at：时间格式受会话时区影响，跨连接算出来会不同，
        # 那样的 hash 没法用来核对。payload 里仍保留 created_at，信息不丢。
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        # 整行快照（JSON 字符串，含 created_at 等全部字段）。
        # 有它才能在 downgrade 时原样搬回活跃表 —— 归档是搬运，不是销毁。
        sa.Column("payload", sa.Text(), nullable=True),
        # 归档原因，两种取值：
        #   orphan_device_ref   device_id 有值但查不到对应设备（设备已删）
        #   missing_device_id   device_id 本身就是 NULL（当初就没记身份）
        # 留原因是为了事后分清这两种完全不同的历史，别混成一句"脏数据"。
        sa.Column("reason", sa.String(length=64), nullable=True),
        # 归档时刻
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        # 幂等的关键：重跑迁移时同一行只归档一次，
        # 不会生成两条只有 id 不同的重复记录。
        # 名字 uq_legacy_row 是显式给的，不靠命名约定推导 —— 0006 的
        # LEFT JOIN 靠它排除已归档行。
        sa.UniqueConstraint("source_table", "source_pk", name="uq_legacy_row"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ==================== device_session_record：会话记录 ====================
    # 每次复位 / 链路重建都开一个新 session，用来回答
    # "这条上报属于哪一次连接、哪一代绑定"，防止重启前的老快照污染新主人。
    op.create_table(
        "device_session_record",
        sa.Column("id", sa.Integer(), nullable=False),
        # 哪台设备。新表为空，可以直接建非空外键。
        sa.Column("device_pk", sa.Integer(), nullable=False),
        # 会话所属的绑定纪元，与 device.be 对齐：换主后 be+1，
        # 旧会话的记录自然被隔离在新纪元之外。
        sa.Column("be", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # 会话 ID（UUID，36 字符）。长度必须和 0004 给 command_log /
        # telemetry 补的 session_id 逐字对齐，否则将来想建外键会报 3780
        # （引用列与被引用列类型不兼容）。
        sa.Column("session_id", sa.String(length=36), nullable=False),
        # 会话状态：open（进行中）/ closed（正常结束）/ unknown（异常中断）。
        # 后端重启时把遗留的 open 改成 unknown，而不是假装它还活着。
        sa.Column(
            "state",
            sa.String(length=16),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        # 这个会话最后处理到的序号。必须落库，不能只放内存 ——
        # 后端一重启就忘了发到第几号，设备会把迟到的响应当成新指令。
        sa.Column("last_seq", sa.Integer(), nullable=True),
        # 会话开始时刻
        sa.Column("started_at", sa.DateTime(), nullable=True),
        # 会话结束时刻，可空 = 还没结束
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_pk"], ["device.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("device_session_record")
    op.drop_table("legacy_row_archive")
    op.drop_table("audit")
    op.drop_table("device_claim")
    # 删列顺序与 upgrade 相反
    op.drop_column("device", "bound_at")
    op.drop_column("device", "handover_state")
    op.drop_column("device", "status")
    op.drop_column("device", "be")
