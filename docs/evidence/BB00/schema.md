# BB00 · 现有 Schema 清点（脱敏）

导出时间：2026-11-12 22:15
目标库：`pet_dog`（MySQL 8.0.46，InnoDB，utf8mb4 / utf8mb4_unicode_ci）
导出账号：`petdog@127.0.0.1`（仅 `pet_dog.*` 权限，只读用途）
导出方式：`information_schema.COLUMNS` / `TABLE_CONSTRAINTS` / `STATISTICS` + `SHOW CREATE TABLE`

> 本文不含任何密码哈希、token 或完整凭据。`user.password_hash` 只记录类型与是否可空。

## 1. 规模

| 项 | 数量 |
|---|---:|
| 表 | 6 |
| 列 | 42 |
| 主键 | 6 |
| 唯一约束 | 2（`device.device_id`、`user.username`） |
| 外键 | **0** |
| 索引条目 | 12（6 主键 + 2 唯一 + 4 普通） |

## 2. 列清单

### `user`

| # | 列 | 类型 | 可空 | 默认 | 键 |
|---:|---|---|---|---|---|
| 1 | id | int | NO | - | PRI, auto_increment |
| 2 | username | varchar(32) | NO | - | UNI |
| 3 | password_hash | varchar(128) | NO | - | - |
| 4 | role | varchar(16) | YES | NULL | - |
| 5 | created_at | datetime | YES | NULL | - |

### `device`

| # | 列 | 类型 | 可空 | 默认 | 键 |
|---:|---|---|---|---|---|
| 1 | id | int | NO | - | PRI, auto_increment |
| 2 | device_id | varchar(32) | NO | - | UNI |
| 3 | name | varchar(64) | YES | NULL | - |
| 4 | firmware | varchar(16) | YES | NULL | - |
| 5 | capability | int | YES | NULL | - |
| 6 | online | tinyint(1) | YES | NULL | - |
| 7 | last_seen | datetime | YES | NULL | - |
| 8 | owner_id | int | **YES** | NULL | 无索引、无外键 |

### `command_log`

| # | 列 | 类型 | 可空 | 默认 | 键 |
|---:|---|---|---|---|---|
| 1 | id | int | NO | - | PRI, auto_increment |
| 2 | device_id | varchar(32) | YES | NULL | MUL |
| 3 | msg_id | varchar(36) | YES | NULL | MUL（非唯一） |
| 4 | cmd | int | YES | NULL | - |
| 5 | action | int | YES | NULL | - |
| 6 | param | varchar(128) | YES | NULL | - |
| 7 | status | int | YES | NULL | - |
| 8 | seq | int | YES | NULL | - |
| 9 | source | varchar(16) | YES | NULL | - |
| 10 | created_at | datetime | YES | NULL | - |
| 11 | finished_at | datetime | YES | NULL | - |

### `telemetry`

| # | 列 | 类型 | 可空 | 默认 | 键 |
|---:|---|---|---|---|---|
| 1 | id | int | NO | - | PRI, auto_increment |
| 2 | device_id | varchar(32) | YES | NULL | MUL |
| 3 | battery | int | YES | NULL | - |
| 4 | music_state | int | YES | NULL | - |
| 5 | action | int | YES | NULL | - |
| 6 | raw | varchar(256) | YES | NULL | - |
| 7 | created_at | datetime | YES | NULL | MUL |

### `scene`

| # | 列 | 类型 | 可空 | 默认 | 键 |
|---:|---|---|---|---|---|
| 1 | id | int | NO | - | PRI, auto_increment |
| 2 | name | varchar(64) | YES | NULL | - |
| 3 | steps | text | YES | NULL | - |
| 4 | owner_id | int | YES | NULL | 无索引、无外键 |
| 5 | created_at | datetime | YES | NULL | - |

### `face_asset`

| # | 列 | 类型 | 可空 | 默认 | 键 |
|---:|---|---|---|---|---|
| 1 | id | int | NO | - | PRI, auto_increment |
| 2 | name | varchar(64) | YES | NULL | - |
| 3 | width | int | YES | NULL | - |
| 4 | height | int | YES | NULL | - |
| 5 | data | text | YES | NULL | - |
| 6 | created_at | datetime | YES | NULL | - |

## 3. 约束

| 表 | 约束名 | 类型 |
|---|---|---|
| command_log | PRIMARY | PRIMARY KEY |
| device | PRIMARY | PRIMARY KEY |
| device | device_id | UNIQUE |
| face_asset | PRIMARY | PRIMARY KEY |
| scene | PRIMARY | PRIMARY KEY |
| telemetry | PRIMARY | PRIMARY KEY |
| user | PRIMARY | PRIMARY KEY |
| user | username | UNIQUE |

**`CONSTRAINT_TYPE` 中不存在 `FOREIGN KEY`**：共 8 条约束，0 条外键。`backend/app/models.py` 未引入 `ForeignKey`，属设计上未建，非遗漏。

## 4. 索引

| 表 | 索引名 | 唯一 | 列 | 类型 |
|---|---|---|---|---|
| command_log | ix_command_log_device_id | 否 | device_id | BTREE |
| command_log | ix_command_log_msg_id | 否 | msg_id | BTREE |
| device | PRIMARY | 是 | id | BTREE |
| device | device_id | 是 | device_id | BTREE |
| face_asset | PRIMARY | 是 | id | BTREE |
| scene | PRIMARY | 是 | id | BTREE |
| telemetry | ix_telemetry_created_at | 否 | created_at | BTREE |
| telemetry | ix_telemetry_device_id | 否 | device_id | BTREE |
| telemetry | PRIMARY | 是 | id | BTREE |
| user | PRIMARY | 是 | id | BTREE |
| user | username | 是 | username | BTREE |

全部为**单列 BTREE**，没有任何联合索引（`SEQ_IN_INDEX` 最大值为 1）。

## 5. 结构问题清单（按阻塞程度）

### P1 归属与幂等缺数据库兜底

1. **`device.owner_id` 可空、无外键、无索引**
   归属过滤依赖 `owner_id == uid`，`NULL` 永远匹配不上，会产生"任何人查不到、但指令仍能下发"的设备。
   对应：S01（owner 外键）、N15（新写归属非空，最终 DB 直接拒绝 NULL）、BB01。
2. **`command_log.msg_id` 为普通索引且可空**
   MySQL 唯一索引允许多个 NULL，即使后续改 UNIQUE，空值仍不被拦。幂等键必须 `NOT NULL + UNIQUE`。
   对应：N14（同 key 并发 20 次只出一条记录）、BA03/BB01。
3. **`command_log.device_id` / `scene.owner_id` 可空且无外键**
   孤儿数据只能靠巡检发现，数据库不做拦截。

### P2 查询性能与默认值语义

4. **缺 `(device_id, created_at)` 联合索引**
   日志分页（按设备取最近指令）与遥测 24h 聚合都走"设备 + 时间"条件，现有两个独立单列索引只能命中其一，另一半条件靠回表过滤。影响 `GET /api/logs`、`GET /api/telemetry`。
5. **SQLAlchemy 的 `default=` 没有落进 DDL**
   `models.py` 中 `role=default("user")`、`owner_id=default(1)`、`capability=default(31)`、`status=default(1)` 全部只作用于 ORM 插入；`COLUMN_DEFAULT` 实测 42 列**全为 NULL**。
   任何绕过 ORM 的写入（`seed.py`、迁移脚本、手工 SQL）都会得到 NULL。若需要数据库兜底，须改 `server_default=`。

### P3 需记录决策而非直接改

6. **日志表外键策略**
   `command_log`、`telemetry` 是高频写入表，是否加外键需要在 BB01 明确决策：加（引用完整性优先）或不加（写入性能优先，配巡检）。本报告不预设结论，仅登记"当前无外键"这一事实。

## 6. 交 BB01 的迁移目标列

| 目标 | 涉及列 | 现有状态 |
|---|---|---|
| 归属非空 + 外键 | `device.owner_id` | 可空、无索引、无外键 |
| 归属非空 + 外键 | `scene.owner_id` | 可空、无索引、无外键 |
| 幂等键唯一 | `command_log.msg_id` | 可空、普通索引 |
| 联合索引 | `command_log(device_id, created_at)`、`telemetry(device_id, created_at)` | 不存在 |
| 数据库级默认值 | `user.role`、`device.capability`、`command_log.status` | 均无 DDL 默认值 |

---

原始导出：本文三份查询均可用 `docs/evidence/BB00/README.md` 第 4 节的 SQL 复现。
