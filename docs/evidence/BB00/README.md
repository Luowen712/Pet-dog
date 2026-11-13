# BB00 · 真实数据与现有路由清点

| 项 | 内容 |
|---|---|
| 任务卡 | BB00（`docs/plan/02_后端执行计划.md` §3） |
| 卡内预算 | 4h |
| 执行人 | 后端B |
| 执行日期 | 2026-11-12 |
| 环境 | Windows 11 · Python 3.14.6 · MySQL 8.0.46 · venv `backend/.venv` |
| 数据库 | 正式库 `pet_dog`（只读清点）· 隔离测试库 `pet_dog_test_bb00` |

## 1. 结论摘要

1. **schema 缺少归属与幂等的数据库兜底**：`device.owner_id` 可空且无外键；`command_log.msg_id` 只是普通索引。数据库层无法阻止"设备无主"和"同一 msg_id 落两条"。详见 `schema.md` §5 P1。
2. **真实数据推翻了两个想当然的假设**：`user` 表并非"只有 2 行"（清点时 4 行，清理临时账号后 3 行）；`AUTO_INCREMENT` 已到 14，有 10 个 id 空洞；两台设备全部挂在 `owner_id = 1`，其余两个账号名下没有任何设备（已确认为预期）。详见 `rows.md`。
3. **隔离测试环境可用**：`pytest` 在 `pet_dog_test_bb00` 上跑通 7 条测试，正式库各表行数前后不变（`user` 4 / `device` 2 / `telemetry` 3 / `command_log` 0）。
4. **现有返回体与 V3.1 契约有 6 处偏差**：`Device` 缺 3 个字段、`DeviceStatus` 缺 4 个字段、两处未知值回填 `0`（违反"不可回填0"）、两处错误码未登记。详见 §5.2。其中"回填 0"会导致页面显示 0% 电量和 0.00V 假读数。

## 2. 产物索引

| 文件 | 内容 |
|---|---|
| `schema.md` | 6 表 42 列、8 约束、12 索引；结构问题清单与交 BB01 的迁移目标列 |
| `rows.md` | 行数、AUTO_INCREMENT 差异、账号清单、设备归属、孤儿与重复检查（含巡检 SQL） |
| `samples/` | 9 个接口返回样例（token 已打码）+ 契约偏差清单，见 §5.2 |
| `baseline.log` | `pytest` 首次跑通的输出（见 §4） |

## 3. 隔离测试环境（G0 证据）

`backend/tests/conftest.py` 在 **import 任何 app 模块之前** 改写环境变量，把 `DB_URL` 指向 `pet_dog_test_bb00`：

1. `os.environ["DB_URL"]` 覆盖 `.env`（pydantic-settings 优先级：环境变量 > .env）
2. 断言 `settings.DB_URL` 实际读到的值含 `pet_dog_test`，否则立即失败
3. 再 import `app.db` / `app.models`，`drop_all` + `create_all` 只作用于测试库

**为什么建库权限收归 root**：`petdog` 账号只有 `pet_dog.*` 的权限（`SHOW GRANTS` 实测：`USAGE ON *.*` + `ALL ON pet_dog.*`），无权 `CREATE DATABASE`。测试库由 root 一次性创建并授权：

```sql
CREATE DATABASE IF NOT EXISTS pet_dog_test_bb00
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON pet_dog_test_bb00.* TO 'petdog'@'127.0.0.1';
```

应用账号不持有建库权限，是刻意的：测试代码只负责建表/清表，删库能力不交给运行时账号。

隔离验证结果：

| 对象 | 测试前 | 测试后 |
|---|---|---|
| `pet_dog.user` | 4 | 4 |
| `pet_dog.device` | 2 | 2 |
| `pet_dog.telemetry` | 3 | 3 |
| `pet_dog.command_log` | 0 | 0 |
| `pet_dog_test_bb00` 表数 | 0 | 6（`user`/`device`/`command_log`/`telemetry`/`scene`/`face_asset`） |

> 上表是隔离验证当时的快照。此后按 §7 清理了 `zz_dev_check`，`pet_dog.user` 现为 3 行。

## 4. 复现命令

```powershell
cd C:\Users\z\Desktop\Pet-dog\backend
.venv\Scripts\python.exe -m pytest -q
```

期望：`7 passed`（`test_presence.py` 5 条 + `test_bb00_baseline.py` 2 条）。

Schema 三份查询（脱敏，不含密码哈希）：

```sql
-- 列
SELECT TABLE_NAME, ORDINAL_POSITION, COLUMN_NAME, COLUMN_TYPE,
       IS_NULLABLE, COLUMN_DEFAULT, COLUMN_KEY, EXTRA
FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='pet_dog'
ORDER BY TABLE_NAME, ORDINAL_POSITION;

-- 约束
SELECT TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE
FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA='pet_dog'
ORDER BY TABLE_NAME, CONSTRAINT_TYPE;

-- 索引
SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, INDEX_TYPE
FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='pet_dog'
ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;
```

## 5. 现有路由与未实现清单

**已实现（12 条）**

| 方法 | 路径 | 文件 |
|---|---|---|
| GET | `/api/health` | `main.py` |
| POST | `/api/auth/login` | `routers/auth.py` |
| POST | `/api/auth/register` | `routers/auth.py` |
| GET | `/api/auth/me` | `routers/auth.py` |
| GET | `/api/devices` | `routers/devices.py` |
| GET | `/api/devices/{id}` | `routers/devices.py` |
| PATCH | `/api/devices/{id}` | `routers/devices.py` |
| GET | `/api/devices/{id}/status` | `routers/devices.py` |
| POST | `/api/devices/{id}/music` | `routers/devices.py` |
| POST | `/api/devices/heartbeat` | `routers/devices.py` |
| GET | `/api/faces` | `routers/faces.py` |
| GET | `/api/setup/status` | `routers/setup.py` |

**未实现（0 条代码）**：`POST /api/commands/send`、`GET /api/commands/{id}`、`POST /api/events/ticket`、`POST /api/faces`、`POST /api/faces/current`、`DELETE /api/faces/{id}`、`GET /api/logs`、`GET /api/telemetry`、`GET /api/weather`、`GET /api/scenes`、`POST /api/scenes`、`PUT /api/scenes/{id}`、`DELETE /api/scenes/{id}`、`POST /api/scenes/{id}/run`、`WS /ws/device`。

**注意**：其中天气、音乐、日志分页、遥测曲线、场景编排在 V3.1 中属 X/D 包（`05` 台账："关闭入口和调用；不实现"），不构成本期缺口。核心缺口是 `commands/*`、`events/ticket`、`/ws/device` 与归属认领。

### 5.1 采样方式

`backend/scripts/sample_bb00.py`：用 `TestClient` 在正式库上**只读**跑 9 个请求，返回体落盘到 `samples/*.json`，`token` 字段打码。复现：

```powershell
cd C:\Users\z\Desktop\Pet-dog\backend
.venv\Scripts\python.exe scripts\sample_bb00.py
```

| 样例文件 | 请求 | 结果 |
|---|---|---|
| `health-200.json` | `GET /api/health` | 200，`{status:"ok", mode:"serial"}` |
| `setup-status-200.json` | `GET /api/setup/status` | 200，`{setup_required:false}` |
| `faces-list-200.json` | `GET /api/faces` | 200，7 个内置表情 |
| `devices-list-200.json` | `GET /api/devices` | 200，2 台（`罗文志`/`备用桌宠`） |
| `devices-detail-200.json` | `GET /api/devices/1` | 200 |
| `devices-status-200.json` | `GET /api/devices/1/status` | 200 |
| `devices-list-401.json` | `GET /api/devices` 无 token | 401 + `code 40100` |
| `login-40001.json` | `POST /api/auth/login` 错密码 | HTTP 200 + `code 40001` |
| `register-40002.json` | `POST /api/auth/register` 用户名过短 | HTTP 200 + `code 40002` |

`login` 成功样例未采：需要演示账号明文密码，按"不把口令写进仓库"的原则，本卡不采，改为在联调时由页面验证。

### 5.2 实测返回体与 `06` 契约的偏差（本步主要产出）

对照 `docs/plan/06_跨组接口与状态规则.md` 第 39/40/44 行：

| # | 对象 | 契约要求 | 实测 | 影响 |
|---|---|---|---|---|
| 1 | `Device` | "增加 `binding_state`、`control_state`、`supported_actions:number[]`" | 三个字段**全部缺失** | 前端无法判断设备能否接收控制，只能靠 `online` 猜 —— 正是契约强调的"在线不代表可控制" |
| 2 | `DeviceStatus` | "增加 `online`、`control_state`、`session_id`、`state_revision`" | 四个字段**全部缺失** | 状态页无法区分 `offline` 与 `ready`；旧 HTTP 覆盖新状态的问题无法靠 `state_revision` 拦截 |
| 3 | `Device.battery`（设备 2） | "battery 可 null"，"UI 显示 null 为 '—'，不可回填 0" | 返回 `0`（该设备 0 条 telemetry，`latest_battery()` 兜底成 0） | 页面显示 0%，用户以为电量耗尽，实际是无数据 |
| 4 | `DeviceStatus.voltage` | "未知业务字段 null" | 返回 `0.0` | 同上，0.00V 是假读数 |
| 5 | 未带 token | 只定义 "身份无效 HTTP401+40101" | 返回 `40100 未登录` | 契约未覆盖该分支；需在 `06` 补一行，或统一为 40101 |
| 6 | 密码错误 | 业务错误清单为 40000/40002/40400/40900 | 返回 `40001` | `40001` 未登记，前端按码分支时会漏 |

第 1–4 项属**实现缺口**（BB02/BB03 范围内修）；第 5–6 项属**契约缺口**（需卢确认后补 `06`），本卡只登记不修改。

`voltage` 回填 0 这一项要特别提一句：前端 `pet.voltage.toFixed(2)` 在 `null` 时会抛异常，所以后端不敢返 null 是可以理解的 —— 但这属于"用错误的数据规避前端 bug"。正确顺序是前端先把 `null` 渲染成"—"，后端再放开 null。

## 6. 已登记的技术债

| 位置 | 问题 | 影响 | 归属 |
|---|---|---|---|
| `backend/app/main.py` 第 14 行 | `Base.metadata.create_all(bind=engine)` 在模块级执行，import 即建表 | 任何 import `app.main` 的脚本都会碰数据库；测试只能靠"先改环境变量"绕过 | BA02（移入 lifespan）/ BB01 |
| `backend/app/models.py` | `ForeignKey` 未引入；`default=` 未落 DDL | 归属与幂等无数据库兜底；DDL 无默认值 | BB01 |
| `backend/app/config.py` | `JWT_SECRET` 默认值 `change-me-in-dotenv` | 忘配 `.env` 时可被伪造 token | BB02 |

## 7. 账号与归属确认结果（已闭环）

负责人 2026-11-12 22:24 确认：

| # | 问题 | 结论 |
|---|---|---|
| 1 | `admin`（id=1）是否为唯一管理员 | **是**，唯一管理员 |
| 2 | `zz_dev_check`（id=10）是否清理 | **清掉**，已于 22:25 执行 `DELETE`（先备份、先验关联为 0） |
| 3 | 两台设备全挂 `owner_id=1` 是否符合预期 | **正常**，无需分配；非 admin 账号看到空列表属预期 |
| 4 | id 2–6、8–9、11、13 是删除还是从未创建 | **未能确证**：`binlog=ON` 但 `petdog` 无 `REPLICATION CLIENT` 权限；已按时间线给出推断并登记影响评估（无影响），详见 `rows.md` §2.2 |

清理后账号现状：`admin`(1) / `zhoujiaxin`(7) / `mzx`(12)，共 3 个。

删除备份：`%TEMP%\pet_dog_user_id10_backup_20261112_222518.sql`（含密码哈希，**不入库**）。

## 8. 本卡状态

| 步骤 | 状态 | 产物 |
|---|---|---|
| 1 导出列/索引/约束/行数/孤儿/重复 msg_id | 完成（孤儿与重复项因 `command_log` 0 行无法验证，已如实标注） | `schema.md`、`rows.md` |
| 2 演示账号与真实用户清单 | 完成（4 问已答，`zz_dev_check` 已清） | `rows.md` §2、§7 |
| 3 记录已有接口返回样例并标出未实现项 | 完成（9 个样例 + 6 处契约偏差） | `samples/`、§5.2 |
| 4 脱敏 schema 交 BA | 文档已备，尚未在群里交接 | `schema.md` |
| 5 依赖 + 测试骨架 | 完成（7 passed） | `requirements*.txt`、`tests/`、`baseline.log` |

**完成判据自检**

- G0 隔离库证据登记到 `05` §5 → 已登记
- 任何迁移目标列可追到当前 schema → `schema.md` §4「交 BB01 的迁移目标列」
- 没有未知数据被默默塞给新管理员 → 账号 3 个已逐个定性；两台设备归 admin 已确认

**剩余动作**：步骤 4 向 BA 交接（群内发 `schema.md`），以及步骤 6 的 6 处契约偏差需卢确认归属（2 处契约缺口、4 处实现缺口）。
