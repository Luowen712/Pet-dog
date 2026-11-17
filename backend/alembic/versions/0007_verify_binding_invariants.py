"""verify binding invariants before contract

加约束之前的只读验数：一个字的 DML 都不写，只 SELECT + 判断。

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-17

文档映射：06 §310 的「0004 验证」→ 本文件（文档编号 +3 才是文件名）。

0008 要给 device_pk 加 NOT NULL 与外键、给 device 加 I1 的 CHECK。
如果不先验，约束失败时你只会看到一句 "Cannot add foreign key constraint"，
不知道是哪张表、哪几行、错在哪。

本版把"现在加约束会不会失败"提前算一遍：每项查出 0 行才放行，
查到 n 行就 raise RuntimeError 中止迁移，并且**不记录这条 revision** ——
下次重跑会从这里继续，不会跳过，也不会半途留下 0008 的约束。

十一项检查（依据 06 §313「检查每张活跃表外键、NOT NULL目标、唯一key、归档hash和数据计数」）：

1. command_log.device_pk 无空值     —— 0008 的 NOT NULL 前置
2. telemetry.device_pk 无空值       —— 同上
3. command_log.device_pk 都指向存在的设备 —— 0008 的外键前置
4. telemetry.device_pk 都指向存在的设备   —— 同上
5. command_log.actor_user_id 都指向存在的用户 —— 0008 的外键前置
6. device.owner_id 都指向存在的用户       —— 同上
7. device.owner_id 无重复           —— 0008 的 UNIQUE(owner_id) 前置
8. device_claim.device_pk 无重复    —— 0008 的 UNIQUE(device_pk) 前置
9. device 的归属与状态自洽（I1）    —— 0008 的 CHECK 前置
10. device 的 status / handover_state 无野值
11. legacy_row_archive 的 hash 是 64 位小写十六进制、payload 非空

第 7、8 项最容易被忽略：唯一键和 NOT NULL 不一样，它不会因为"数据看起来对"
就通过。只要有两行 owner_id 相同，ALTER TABLE ADD UNIQUE 立刻报 1062，
而且报错只说 "Duplicate entry '1'"，不说是哪张表哪两行。

第 9 项的 I1 内容（06 §270）：
    (owner_id IS NULL     AND status <> 'bound')
 OR (owner_id IS NOT NULL AND status  = 'bound')
人话：没主人的设备不能是 bound，有主人的设备必须是 bound。
外面套一层 NOT(...) 数出来的就是"自己不满足自己"的行。

第 7 项是归档防篡改的实际落地方式：sha256 出来必然是 64 位小写十六进制，
格式不对说明归档被改过，或者当初算 hash 的算法写错了。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 每项 = (查出不符合要求的行数的 SQL, 检查项名称, 失败说明)。期望行数全部为 0。
# 名称和说明分开，是因为通过时要说"无空值"、失败时要说"有空值"，
# 混用一个字符串打印出来会自相矛盾。
CHECKS: list[tuple[str, str, str]] = [
    (
        "SELECT COUNT(*) FROM command_log WHERE device_pk IS NULL",
        "command_log.device_pk 无空值",
        "command_log.device_pk 有空值，0008 无法加 NOT NULL",
    ),
    (
        "SELECT COUNT(*) FROM telemetry WHERE device_pk IS NULL",
        "telemetry.device_pk 无空值",
        "telemetry.device_pk 有空值，0008 无法加 NOT NULL",
    ),
    (
        """
        SELECT COUNT(*) FROM command_log c
          LEFT JOIN device d ON d.id = c.device_pk
         WHERE c.device_pk IS NOT NULL
           AND d.id IS NULL
        """,
        "command_log.device_pk 均指向存在的设备",
        "command_log.device_pk 指向不存在的设备，0008 无法加外键",
    ),
    (
        """
        SELECT COUNT(*) FROM telemetry t
          LEFT JOIN device d ON d.id = t.device_pk
         WHERE t.device_pk IS NOT NULL
           AND d.id IS NULL
        """,
        "telemetry.device_pk 均指向存在的设备",
        "telemetry.device_pk 指向不存在的设备，0008 无法加外键",
    ),
    (
        """
        SELECT COUNT(*) FROM command_log c
          LEFT JOIN user u ON u.id = c.actor_user_id
         WHERE c.actor_user_id IS NOT NULL
           AND u.id IS NULL
        """,
        "command_log.actor_user_id 均指向存在的用户",
        "command_log.actor_user_id 指向不存在的用户，0008 无法加外键",
    ),
    (
        """
        SELECT COUNT(*) FROM device d
          LEFT JOIN user u ON u.id = d.owner_id
         WHERE d.owner_id IS NOT NULL
           AND u.id IS NULL
        """,
        "device.owner_id 均指向存在的用户",
        "device.owner_id 指向不存在的用户，0008 无法加外键",
    ),
    (
        """
        SELECT COUNT(*) FROM (
            SELECT owner_id FROM device
             WHERE owner_id IS NOT NULL
             GROUP BY owner_id HAVING COUNT(*) > 1
        ) t
        """,
        "device.owner_id 无重复（一账号至多一台）",
        "device.owner_id 有重复，一账号挂着多台设备，0008 无法加 UNIQUE(owner_id)",
    ),
    (
        """
        SELECT COUNT(*) FROM (
            SELECT device_pk FROM device_claim
             GROUP BY device_pk HAVING COUNT(*) > 1
        ) t
        """,
        "device_claim.device_pk 无重复（一设备至多一条配对码）",
        "device_claim.device_pk 有重复，0008 无法加 UNIQUE(device_pk)",
    ),
    (
        """
        SELECT COUNT(*) FROM device
         WHERE NOT ( (owner_id IS NULL     AND status <> 'bound')
                  OR (owner_id IS NOT NULL AND status  = 'bound') )
        """,
        "device 的 owner_id 与 status 自洽（I1）",
        "device 的 owner_id 与 status 矛盾（违反 I1），0008 无法加 CHECK",
    ),
    (
        """
        SELECT COUNT(*) FROM device
         WHERE status NOT IN ('claimable', 'bound', 'retired')
            OR handover_state NOT IN ('required', 'ready')
        """,
        "device 的 status / handover_state 无野值",
        "device 的 status / handover_state 出现未定义的枚举值",
    ),
    (
        """
        SELECT COUNT(*) FROM legacy_row_archive
         WHERE row_hash IS NULL
            OR CHAR_LENGTH(row_hash) <> 64
            OR row_hash NOT REGEXP '^[0-9a-f]{64}$'
            OR payload IS NULL
            OR payload = ''
        """,
        "legacy_row_archive 的 hash 格式与 payload 完整",
        "legacy_row_archive 的 hash 不是 64 位小写十六进制，或 payload 为空",
    ),
]


def _count(bind, sql: str) -> int:
    """执行只读查询，返回单行单列的数字。"""
    return int(bind.execute(sa.text(sql)).scalar_one())


def _assert_zero(bind, sql: str, label: str, fail_msg: str) -> None:
    """查出不符合要求的行数；不是 0 就带着数字中止，让人知道去查什么。"""
    n = _count(bind, sql)
    if n:
        raise RuntimeError(
            f"[验数失败] {fail_msg}：查到 {n} 行不满足。\n"
            f"        迁移已中止，未写入 0007，修好后重跑即可。\n"
            f"        定位用的 SQL：\n{sql.strip()}"
        )
    print(f"[验数通过] {label}")


def upgrade() -> None:
    """执行全部只读检查，全过才允许进 0008。"""
    bind = op.get_bind()
    for sql, label, fail_msg in CHECKS:
        _assert_zero(bind, sql, label, fail_msg)
    print(f"[验数] {len(CHECKS)} 项检查全部通过，可以进入 0008 加约束")


def downgrade() -> None:
    """只读检查，没有改动任何数据，因此无可回退。"""
    pass
