# BB00 · 数据现状清点（脱敏）

导出时间：2026-11-12 22:15；清理 `zz_dev_check` 后复核：2026-11-12 22:25
目标库：`pet_dog`
说明：不含密码哈希、token；`username` 只用于登记"谁是演示账号"，不用于认证。

## 1. 各表行数

| 表 | 行数（`COUNT(*)`） | AUTO_INCREMENT | 判断 |
|---|---:|---:|---|
| user | 3 | 14 | 下一个 id 为 14，最大已用 id 为 13；历史上有过删除 |
| device | 2 | 3 | 与行数一致，无删除痕迹 |
| command_log | 0 | - | 空表，从未写入 |
| telemetry | 3 | 6 | 历史上有过删除 |
| scene | 0 | - | 空表 |
| face_asset | 0 | - | 空表 |

**关于 `TABLE_ROWS` 的一个实证**：查 `information_schema.TABLES` 时 `user` 的 `TABLE_ROWS` 显示 **2**，而 `SELECT COUNT(*)` 是 **3**。InnoDB 的 `TABLE_ROWS` 是采样估算值，不准确。**本卡所有行数一律用 `COUNT(*)`，不采用 `TABLE_ROWS`。**

**AUTO_INCREMENT 与行数不一致的含义**：`user` 自增到 14 而只剩 3 行。其中 1 个空洞是本次清理 `zz_dev_check`（id=10）造成的，其余为历史删除。这直接否掉两种想当然的假设：

- 不能假定"演示账号就是 id=1 和 id=2"
- 不能假定"id 连续、可以按 id 顺序枚举用户"

对应 `02_后端执行计划.md` BB00 第 2 步原文："不假定只有两行或 owner=1 都合法"。

## 2. 账号清单（3 个，已确认）

| id | username | role | created_at | 性质 |
|---:|---|---|---|---|
| 1 | admin | admin | 2026-11-05 08:33:39 | **唯一管理员**（负责人确认） |
| 7 | zhoujiaxin | user | 2026-11-10 15:30:35 | 项目成员个人账号 |
| 12 | mzx | user | 2026-11-11 12:37:24 | 项目成员个人账号 |

### 2.1 已执行的清理

| 操作 | 对象 | 时间 | 结果 |
|---|---|---|---|
| `DELETE FROM user WHERE id=10 AND username='zz_dev_check'` | `zz_dev_check`（id=10，`role=user`） | 2026-11-12 22:25 | 删除 1 行；删除前确认其名下 `device`/`scene` 均为 0 条；删除前整行已用 `mysqldump --where="id=10"` 备份 |

依据：负责人确认"是开发期临时账号，清掉"。删除前关联检查结果：`device` 0 条、`scene` 0 条 —— 不存在孤儿。

备份文件位置：`%TEMP%\pet_dog_user_id10_backup_20261112_222518.sql`（含密码哈希，**不得入库**，仅本地恢复用）。

### 2.2 已确认的结论

1. `admin`（id=1）是**唯一管理员**，不需要再新增管理员账号。
2. `zz_dev_check`（id=10）已清理，不是长期账号。
3. **两台设备都归 admin 是预期行为**，不需要分给其他账号 —— 因此"用 `zhoujiaxin` 登录看到空列表"属于正常现象，不是缺陷。
4. id 2–6、8–9、11、13 的历史删除原因**未能确证**：`binlog` 虽为 `ON`，但 `petdog` 账号没有 `REPLICATION CLIENT` 权限，`SHOW BINARY LOGS` 被拒。

对第 4 点的推断与依据（**写出推断而非结论，避免误导**）：

| 现有 id | created_at | 与其间的空洞 |
|---:|---|---|
| 1 | 2026-11-05 08:33 | — |
| 7 | 2026-11-10 15:30 | 2–6（5 个） |
| 12 | 2026-11-11 12:37 | 8–9、11（3 个） |

`id=7` 与后续 id 间隔最长，2–6 很可能是早期注册接口联调产物；`id=8/9/11` 集中在 11-10 15:30 至 11-11 12:37 之间，与 `zz_dev_check`（11-10 16:17）同属开发调试窗口。

若需确证，由 root 执行（当前账号无权，本卡不代跑）：

```sql
SHOW BINARY LOGS;
SHOW BINLOG EVENTS IN '<binlog 文件名>' LIMIT 200;
```

**影响评估：无。** 现有 3 行账号均为有效账号，`device.owner_id` 与 `scene.owner_id` 无指向空洞 id 的引用（第 4 节已验）。历史空洞只影响"按 id 枚举"这类错误做法，不影响数据完整性。

## 3. 设备归属

| id | device_id | name | owner_id | online | last_seen |
|---:|---|---|---:|---|---|
| 1 | PET-0001-ABCD | 罗文志 | 1 | 1 | 2026-11-11 18:36:11 |
| 2 | PET-0002-EFGH | 备用桌宠 | 1 | 0 | 2026-11-11 18:30:52 |

**结论：两台设备的 `owner_id` 都是 1（admin），且已确认为预期行为。** 其余两个账号（7、12）名下没有任何设备。

这意味着：

- 演示时若用 `zhoujiaxin` 或 `mzx` 登录，设备列表会是空的 —— **不是接口坏了，是归属就是这么写的**
- `owner_id` 允许 NULL 的风险在此有了对照物：现在的 2 行恰好都有值，但结构上没有任何东西阻止第 3 行写成 NULL

## 4. 孤儿引用与重复 msg_id

| 检查项 | 结果 | 说明 |
|---|---|---|
| `command_log` → 不存在的 `device_id` | **无法验证** | 表 0 行 |
| `telemetry` → 不存在的 `device_id` | 0 条 | 3 行全部指向 `PET-0001-ABCD`，命中真实设备 |
| 设备归属指向不存在的用户 | 0 条 | 2 台设备均指向 `user.id = 1` |
| 归属为 NULL 的设备 | 0 条 | 当前无 NULL，但结构上允许（见 schema.md P1-1） |
| 重复 `msg_id` | **无法验证** | 表 0 行 |

**必须如实记录为"待复验"，不能写"通过"。** 真实指令产生数据后需重跑第 5 节 SQL，并把结果补进本表。

## 5. 巡检 SQL（留存备用）

```sql
-- 孤儿：指令日志指向不存在的设备
SELECT c.id, c.msg_id, c.device_id
FROM command_log c
LEFT JOIN device d ON c.device_id = d.device_id
WHERE d.device_id IS NULL;

-- 孤儿：遥测指向不存在的设备
SELECT t.id, t.device_id
FROM telemetry t
LEFT JOIN device d ON t.device_id = d.device_id
WHERE d.device_id IS NULL;

-- 孤儿：设备归属指向不存在的用户（NULL 归类为孤儿）
SELECT d.id, d.device_id, d.owner_id
FROM device d
LEFT JOIN `user` u ON d.owner_id = u.id
WHERE u.id IS NULL;

-- 重复幂等键
SELECT msg_id, COUNT(*) AS n
FROM command_log
GROUP BY msg_id
HAVING n > 1;

-- 归属为空的设备
SELECT id, device_id FROM device WHERE owner_id IS NULL;
```
