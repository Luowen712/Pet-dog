"""backfill device binding state

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-16

文档映射：06 §310 的「0003 回填归档」→ 本文件（三步之一：设备状态回填）。
另两步是 0005（device_pk 回填）和 0006（孤儿归档）。

0002 给 device 加了 be / status / handover_state / bound_at，非空列必须有
DDL 默认值才能加到有数据的表上，所以存量行当时拿到的是占位值：
status='claimable'、handover_state='required'、be=0、bound_at=NULL。

但"有主却标着可认领"是矛盾状态，0008 的 CHECK 会直接拒绝：
    (owner_id IS NULL     AND status <> 'bound')
 OR (owner_id IS NOT NULL AND status  = 'bound')

本版按 owner_id 是否为空把存量行纠正到自洽状态，不改写归属本身：
- owner_id 有值 → 已有主人，status='bound'，handover 已完成='ready'
- owner_id 为空 → 可认领，status='claimable'，handover 仍需人工净化='required'
- status='retired' 的行一律跳过：退役设备不能被重新拉回可认领

归属真伪（owner 指向的 user 是否存在）不在本版判断 —— 按 06 §10，
那是 0007 验数的工作，验不过就中止迁移并人工清点，不在这里猜。

可重入：所有条件都带"当前值不符合预期"的前置判断，重复执行不改动已正确的行，
也不会把 bound_at 刷成新的时间戳。
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BOUND_SQL = """
UPDATE device
   SET status         = 'bound',
       handover_state = 'ready',
       bound_at       = COALESCE(bound_at, last_seen, CURRENT_TIMESTAMP)
 WHERE owner_id IS NOT NULL
   AND status <> 'retired'
   AND (status <> 'bound' OR handover_state <> 'ready' OR bound_at IS NULL)
"""

UNBOUND_SQL = """
UPDATE device
   SET status         = 'claimable',
       handover_state = 'required',
       bound_at       = NULL
 WHERE owner_id IS NULL
   AND status <> 'retired'
   AND (status <> 'claimable' OR handover_state <> 'required' OR bound_at IS NOT NULL)
"""


def upgrade() -> None:
    """按 owner_id 回填存量设备的绑定状态。"""
    op.execute(BOUND_SQL)
    op.execute(UNBOUND_SQL)


def downgrade() -> None:
    """纯数据回填，没有 DDL 可退，因此不提供回退。

    真正要回退到 0002 时，0002 的 downgrade 会把这几列整列删掉，
    status 等值随之消失，所以这里不做任何"猜一个旧值写回去"的动作——
    那只会把「这行原本是 bound 还是 claimable」的信息彻底覆盖掉。
    """
    pass
