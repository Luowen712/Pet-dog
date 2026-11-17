"""backfill command_log / telemetry device_pk

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-17

文档映射：06 §310 的「0003 回填归档」→ 本文件（三步之二：device_pk 回填）。
另两步是 0003（设备状态回填）和 0006（孤儿归档）。

0004 只加了 device_pk 列，值是空的。本版把它从 device_id 反查填上。

两条 SQL 都带 WHERE device_pk IS NULL，保证可重入：
重跑不会把已填好的行再写一遍，也不会覆盖 0005 之后别的版本改过的值。

配不上的行（device_id 指向已删设备）保持 NULL，不猜。
按 06 §10：历史归属无证据不得补值，先留空让人看见，
再由 0006 归档进 legacy_row_archive、0007 验数统计后人工清点。
"""

from typing import Sequence, Union

from alembic import op

COMMAND_LOG_SQL = """
UPDATE command_log c
  JOIN device d ON d.device_id = c.device_id
   SET c.device_pk = d.id
 WHERE c.device_pk IS NULL
"""

TELEMETRY_SQL = """
UPDATE telemetry t
  JOIN device d ON d.device_id = t.device_id
   SET t.device_pk = d.id
 WHERE t.device_pk IS NULL
"""

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """按 device_id 反查 device.id，回填 command_log / telemetry 的 device_pk。"""
    op.execute(COMMAND_LOG_SQL)
    op.execute(TELEMETRY_SQL)


def downgrade() -> None:
    """把翻译结果擦掉，回到 0004 的“全空”状态。

    不做“回填成旧值”那种猜测——device_pk 本来就不存在于 0004，
    擦成 NULL 才是真正的 0004 状态。
    """
    op.execute("UPDATE command_log SET device_pk = NULL")
    op.execute("UPDATE telemetry SET device_pk = NULL")
