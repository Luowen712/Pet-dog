"""archive orphan command_log / telemetry rows

把补不出 device_pk 的历史行先归档、再删除

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-17

文档映射：06 §310 的「0003 回填归档」→ 本文件（三步之三：孤儿归档）。
另两步是 0003（设备状态回填）和 0005（device_pk 回填）。

0005 只填得动"device_id 能在 device 表里找到"的行。剩下的 device_pk IS NULL 分两类：

  1. device_id 有值，但 device 表里没有这个编号 —— 设备早已删除（孤儿引用）
  2. device_id 本身就是 NULL —— 身份彻底缺失

这两类都补不出 device_pk，而 0008 要给 device_pk 加 NOT NULL 和外键。
留着它们：0007 验数会拦住（第 1、2 项就是查这两列的空值），0008 的约束
也建不起来；直接删掉又丢失证据。所以按 06 §311：
"历史无法证明 owner 的子行先归档 hash 核对再删除活跃源行"，禁止 CASCADE 默默删。

本迁移对 telemetry / command_log 各做两件事，顺序不可颠倒：
  a. INSERT 到 legacy_row_archive（含 payload 全字段 + sha256 摘要）
  b. DELETE 活跃表里已归档的那些行
先删后归档 = 数据永久丢失。

三个设计点：

**hash 不含 created_at。** SHA2(JSON_OBJECT(...), 256) 输出 64 位十六进制，正好
装进 row_hash VARCHAR(64)。只摘要业务字段，不含时间戳 —— 时间格式受会话时区影响，
跨连接算出来会不同，那样的 hash 没法用来核对。payload 里则保留 created_at，信息不丢。

**幂等靠 UNIQUE(source_table, source_pk)，不靠 hash。**
归档前 LEFT JOIN 归档表排除已存在的记录，重跑不会产生第二条只差 id 的重复归档；
archive 表上的 uq_legacy_row 是最后一道保险。

**downgrade 把行原样搬回活跃表。**
归档是搬运不是销毁，回退就该搬回去。JSON 里的 null 经 JSON_UNQUOTE 会变成字符串
'null'，所以每个字段都要套 NULLIF(...,'null')，否则回退后 device_id 会变成四个字母。
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------- 归档（upgrade）

ARCHIVE_TELEMETRY_SQL = """
INSERT INTO legacy_row_archive
       (source_table, source_pk, row_hash, payload, reason, archived_at)
SELECT 'telemetry',
       t.id,
       SHA2(JSON_OBJECT(
           'id',          t.id,
           'device_id',   t.device_id,
           'battery',     t.battery,
           'music_state', t.music_state,
           'action',      t.action,
           'raw',         t.raw,
           'be',          t.be,
           'session_id',  t.session_id
       ), 256),
       CAST(JSON_OBJECT(
           'id',          t.id,
           'device_id',   t.device_id,
           'battery',     t.battery,
           'music_state', t.music_state,
           'action',      t.action,
           'raw',         t.raw,
           'be',          t.be,
           'session_id',  t.session_id,
           'created_at',  t.created_at
       ) AS CHAR),
       CASE WHEN t.device_id IS NULL
            THEN 'missing_device_id'
            ELSE 'orphan_device_ref' END,
       NOW()
  FROM telemetry t
  LEFT JOIN legacy_row_archive a
         ON a.source_table = 'telemetry'
        AND a.source_pk   = t.id
 WHERE t.device_pk IS NULL
   AND a.id IS NULL
"""

ARCHIVE_COMMAND_LOG_SQL = """
INSERT INTO legacy_row_archive
       (source_table, source_pk, row_hash, payload, reason, archived_at)
SELECT 'command_log',
       c.id,
       SHA2(JSON_OBJECT(
           'id',            c.id,
           'device_id',     c.device_id,
           'msg_id',        c.msg_id,
           'cmd',           c.cmd,
           'action',        c.action,
           'param',         c.param,
           'status',        c.status,
           'seq',           c.seq,
           'source',        c.source,
           'actor_user_id', c.actor_user_id,
           'be',            c.be,
           'tv',            c.tv,
           'revision',      c.revision,
           'transport',     c.transport,
           'reason',        c.reason,
           'session_id',    c.session_id
       ), 256),
       CAST(JSON_OBJECT(
           'id',            c.id,
           'device_id',     c.device_id,
           'msg_id',        c.msg_id,
           'cmd',           c.cmd,
           'action',        c.action,
           'param',         c.param,
           'status',        c.status,
           'seq',           c.seq,
           'source',        c.source,
           'actor_user_id', c.actor_user_id,
           'be',            c.be,
           'tv',            c.tv,
           'revision',      c.revision,
           'transport',     c.transport,
           'reason',        c.reason,
           'session_id',    c.session_id,
           'created_at',    c.created_at,
           'finished_at',   c.finished_at
       ) AS CHAR),
       CASE WHEN c.device_id IS NULL
            THEN 'missing_device_id'
            ELSE 'orphan_device_ref' END,
       NOW()
  FROM command_log c
  LEFT JOIN legacy_row_archive a
         ON a.source_table = 'command_log'
        AND a.source_pk   = c.id
 WHERE c.device_pk IS NULL
   AND a.id IS NULL
"""

# ---------------------------------------------------------------- 删除（upgrade）

# 只删"归档表里确实有记录"的行。若 INSERT 中途失败，这段一行都不会匹配到，
# 不会出现"数据删了但没归档"的空窗。
DELETE_ARCHIVED_SQL = """
DELETE t
  FROM {table} t
  JOIN legacy_row_archive a
    ON a.source_table = '{table}'
   AND a.source_pk   = t.id
 WHERE t.device_pk IS NULL
"""

# ---------------------------------------------------------------- 恢复（downgrade）

# JSON_UNQUOTE 会把 JSON 的 null 变成字符串 'null'，必须用 NULLIF 变回 SQL NULL，
# 否则回退后 device_id 之类的列里躺着一串字母。
RESTORE_TELEMETRY_SQL = """
INSERT INTO telemetry
       (id, device_id, battery, music_state, action, raw, be, session_id, created_at)
SELECT CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.id')) AS SIGNED),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.device_id')), 'null'),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.battery')), 'null') AS SIGNED),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.music_state')), 'null') AS SIGNED),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.action')), 'null') AS SIGNED),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.raw')), 'null'),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.be')), 'null') AS SIGNED),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.session_id')), 'null'),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.created_at')), 'null')
  FROM legacy_row_archive
 WHERE source_table = 'telemetry'
"""

RESTORE_COMMAND_LOG_SQL = """
INSERT INTO command_log
       (id, device_id, msg_id, cmd, action, param, status, seq, source,
        actor_user_id, be, tv, revision, transport, reason, session_id,
        created_at, finished_at)
SELECT CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.id')) AS SIGNED),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.device_id')), 'null'),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.msg_id')), 'null'),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cmd')), 'null') AS SIGNED),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.action')), 'null') AS SIGNED),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.param')), 'null'),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.status')), 'null') AS SIGNED),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.seq')), 'null') AS SIGNED),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.source')), 'null'),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.actor_user_id')), 'null') AS SIGNED),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.be')), 'null') AS SIGNED),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.tv')), 'null') AS SIGNED),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.revision')), 'null') AS SIGNED),
       CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.transport')), 'null') AS SIGNED),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.reason')), 'null'),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.session_id')), 'null'),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.created_at')), 'null'),
       NULLIF(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.finished_at')), 'null')
  FROM legacy_row_archive
 WHERE source_table = 'command_log'
"""

DROP_ARCHIVE_SQL = """
DELETE FROM legacy_row_archive WHERE source_table = '{table}'
"""



def upgrade() -> None:
    """先归档再删除两类补不出 device_pk 的行。"""
    # 先归档 —— 顺序不能反，反了就是删完才发现没留证据
    op.execute(ARCHIVE_COMMAND_LOG_SQL)
    op.execute(ARCHIVE_TELEMETRY_SQL)
    # 再删 —— 只删归档表里确实存在的
    op.execute(DELETE_ARCHIVED_SQL.format(table="command_log"))
    op.execute(DELETE_ARCHIVED_SQL.format(table="telemetry"))



def downgrade() -> None:
    """把归档行原样搬回活跃表，再清掉归档记录。

    需要先删归档行再插回活跃表吗？不需要 —— 两张表没有外键关联，
    INSERT ... SELECT 读的是归档表，插的是活跃表，互不干扰。
    """
    op.execute(RESTORE_COMMAND_LOG_SQL)
    op.execute(RESTORE_TELEMETRY_SQL)
    op.execute(DROP_ARCHIVE_SQL.format(table="command_log"))
    op.execute(DROP_ARCHIVE_SQL.format(table="telemetry"))
