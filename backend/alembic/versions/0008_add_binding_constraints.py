"""contract: add foreign keys, unique keys and the I1 check

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-17

文档映射：06 §310 的「0005 约束」→ 本文件（文档编号 +3 才是文件名）。

整条链的最后一步：把前面 0004~0007 攒下来的"意图"真正钉成约束。

前七版的分工：
    0002 建新表（含新表自己的外键）
    0004 给存量表加列（device_pk / owner_id 等，全是可空、无约束）
    0005 回填 device_pk（能查到的填上）
    0006 归档并删除查不到归属的行（孤儿不许留在活跃表）
    0007 只读验数（11 项，全过才放行）
    0008 就是本版：加约束（contract）

本版新增 7 项约束，全部来自 06 §10 的归属四约束表 + 外键顺序要求：

    device                     uq_device_owner   UNIQUE(owner_id)        一账号至多一台
    device                     fk_device_owner   FK owner_id -> user.id  可空，RESTRICT
    device                     ck_device_owner_status  CHECK(I1)         有主必 bound
    command_log                fk_command_log_device      FK device_pk -> device.id
    command_log                fk_command_log_actor_user  FK actor_user_id -> user.id
    telemetry                  fk_telemetry_device        FK device_pk -> device.id
    device_claim               uq_device_claim_device    UNIQUE(device_pk)

外加把 command_log.device_pk / telemetry.device_pk 收紧成 NOT NULL。

三条设计决定，答辩会被问：

1. 先建 UNIQUE 再建外键。
   MySQL 建外键时会找列上已有的索引来复用，找不到才自己建一个。
   如果先建外键，owner_id 上会先出现一个 fk 专用索引，再加 UNIQUE 就变成
   "两个索引管同一列"，白占空间还拖慢写入。反过来先 UNIQUE，外键直接复用它。

2. CHECK 用显式 ALTER TABLE 写，不用 op.create_check_constraint。
   Alembic 对 MySQL 的 CHECK 支持一直是半成品：建得出来，但 downgrade 走的
   DROP CONSTRAINT 语法在 MySQL 上不成立（MySQL 只认 DROP CHECK / DROP CONSTRAINT
   并且对版本有要求）。与其猜方言，不如自己写死语句，回退时也写同样的显式语句。

3. 回退顺序必须是"先删外键、再删唯一键"。
   外键依赖那个唯一索引，先删索引会报 1553
   (Cannot drop index 'uq_device_owner': needed in a foreign key constraint)。
   这是 MySQL 特有的坑，在 Postgres 上不会遇到。

⚠️ 正式库已知冲突（执行前必须人工处置，代码不能替人做这个决定）：
   pet_dog 的 device 表现有 2 行，owner_id 都是 1
   （id=1 PET-0001-ABCD、id=2 PET-0002-EFGH），违反"一账号至多一台"。
   直接跑本版会被 1062 Duplicate entry '1' 挡住，这正是 0007 第 7 项验数要拦的。
   处置方式必须由人确认（把多出来的设备退回未绑定，还是改规则放宽），
   不要在这个迁移里写"自动把第二台置空"这种猜测式改写。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# I1：有主必 bound，无主必非 bound。
# 和 0007 第 9 项验数用的是同一个表达式——验数说"现在满足"，
# CHECK 说"以后也必须满足"，两处必须是同一句话，否则验数就白验了。
I1_EXPR = (
    "(owner_id IS NULL AND status <> 'bound') "
    "OR (owner_id IS NOT NULL AND status = 'bound')"
)



def upgrade() -> None:
    """把归属四约束 + device_pk 外键/NOT NULL 落成真实 DDL。"""

    # ---------- device：归属四约束里的三条 ----------
    # ① 一账号至多一台设备（允许 NULL 重复，所以未绑定设备不受限）
    op.create_unique_constraint("uq_device_owner", "device", ["owner_id"])

    # ② 归属可空外键。目标行被删时 RESTRICT：不许 CASCADE 把设备一起删掉，
    #    设备是硬件资产，删用户不等于设备消失，必须先显式解绑。
    op.create_foreign_key(
        "fk_device_owner",
        "device",
        "user",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # ③ 状态与归属自洽
    op.execute(
        f"ALTER TABLE device "
        f"ADD CONSTRAINT ck_device_owner_status CHECK ({I1_EXPR})"
    )

    # ---------- command_log：外键 + NOT NULL ----------
    # 顺序：先建外键（此时列里已无 NULL，0007 验过），再收紧成 NOT NULL。
    op.create_foreign_key(
        "fk_command_log_device",
        "command_log",
        "device",
        ["device_pk"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_command_log_actor_user",
        "command_log",
        "user",
        ["actor_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # MySQL 改可空性必须带 existing_type，否则 Alembic 不知道该 MODIFY 成什么类型。
    op.alter_column(
        "command_log", "device_pk", existing_type=sa.Integer(), nullable=False
    )

    # ---------- telemetry：同上 ----------
    op.create_foreign_key(
        "fk_telemetry_device",
        "telemetry",
        "device",
        ["device_pk"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.alter_column(
        "telemetry", "device_pk", existing_type=sa.Integer(), nullable=False
    )

    # ---------- device_claim：一设备至多一条配对码 ----------
    op.create_unique_constraint(
        "uq_device_claim_device", "device_claim", ["device_pk"]
    )



def downgrade() -> None:
    """严格逆序：先拆后建的。

    每一对 create/drop 的约束名必须一字不差，否则 MySQL 会含糊地报
    "check that column/key exists"，看不出是哪一条漏了。

    实测踩到的两个 1553（Cannot drop index ...: needed in a foreign key
    constraint），处理方式不一样，是本函数最值得看的地方：

    · device 好办：先 drop CONSTRAINT fk_device_owner，外键没了，
      uq_device_owner 就能正常删。
    · device_claim 不好办：它的外键 device_claim_ibfk_1 是 0002 建的，
      属于 0007 的状态，不能为了回退把它删掉。而加 UNIQUE 时 MySQL 已经把
      原来那个给外键用的普通索引删了、让外键改指向新 UNIQUE 索引，
      所以这里必须用一条 ALTER 同时"删唯一索引 + 补一条普通索引"，
      让外键在整条语句结束时仍有索引可依。分成两条语句必然 1553。

    另外，MySQL 删外键不会连带删掉它当初自动建的索引，所以 command_log /
    telemetry 在 drop_constraint 之后还要显式 drop_index，
    否则回退结果比 0007 多两个空索引，compare_metadata 会报 diff。
    """

    # ---------- device_claim ----------
    # 一条语句里换索引，中途没有任何时刻外键处于"无索引可依"的状态。
    op.execute(
        "ALTER TABLE device_claim "
        "DROP INDEX uq_device_claim_device, "
        "ADD INDEX ix_device_claim_device_pk (device_pk)"
    )

    # ---------- telemetry ----------
    # 先放开 NOT NULL，再删外键。反过来的话，删外键那一刻列还是 NOT NULL，
    # 虽然能删成功，但如果后面想插回测试数据会被 NOT NULL 挡住，查问题时很绕。
    op.alter_column(
        "telemetry", "device_pk", existing_type=sa.Integer(), nullable=True
    )
    op.drop_constraint("fk_telemetry_device", "telemetry", type_="foreignkey")
    op.drop_index("fk_telemetry_device", table_name="telemetry")

    # ---------- command_log ----------
    op.alter_column(
        "command_log", "device_pk", existing_type=sa.Integer(), nullable=True
    )
    op.drop_constraint(
        "fk_command_log_actor_user", "command_log", type_="foreignkey"
    )
    op.drop_index("fk_command_log_actor_user", table_name="command_log")
    op.drop_constraint("fk_command_log_device", "command_log", type_="foreignkey")
    op.drop_index("fk_command_log_device", table_name="command_log")

    # ---------- device ----------
    # 顺序要害：先删 CHECK、再删外键、最后删唯一键。
    # 唯一键被外键引用着，先删唯一键会报 1553。
    op.execute("ALTER TABLE device DROP CHECK ck_device_owner_status")
    op.drop_constraint("fk_device_owner", "device", type_="foreignkey")
    op.drop_constraint("uq_device_owner", "device", type_="unique")
