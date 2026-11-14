# Pet-dog · STM32 智能桌面宠物

当前执行版本 **3.1：核心闭环优先，扩展按进度纳入**。计划不等于已实现能力，SIM 与 HW 验收分别记录。

## 组员开工入口

直接阅读 [docs/plan/00_执行入口.md](docs/plan/00_执行入口.md)，按角色领取任务：

- [总计划与交付门禁](docs/plan/01_总计划与交付门禁.md)
- [后端A/B执行计划](docs/plan/02_后端执行计划.md)
- [前端执行计划](docs/plan/03_前端执行计划.md)
- [固件A/硬件B执行计划](docs/plan/04_嵌入式执行计划.md)
- [需求追踪与验收台账](docs/plan/05_需求追踪与验收台账.md)
- [跨组接口与状态规则](docs/plan/06_跨组接口与状态规则.md)

plan只保留这七份执行文件。原Word、V3和旧契约已移入[历史归档](docs/archive/2026-11-10_pre-v3.1/)，不与当前计划并行执行。
J00已按共享规则把机器契约落到 [docs/contracts](docs/contracts/README.md)：`openapi.yaml`（20 条路径 / 21 个操作 / 32 个 schema、WS 端点登记 1 条）+ 22 个 HTTP 样例、8 个 WS 样例、12 个帧向量。它们必须与06一致，校验命令 `backend\.venv\Scripts\python.exe backend\tools\check_contracts.py`（ERROR 退出码1）。

## 环境要求

| 组件 | 版本（本机已验证） | 说明 |
|---|---|---|
| Python | 3.14.6 | 后端虚拟环境 `backend/.venv`，不进仓库，每台机器自己建 |
| MySQL | 8.0.46 | 库与账号字符集都必须是 utf8mb4 |
| Node.js | 26.12.1 | 前端 |
| pnpm | 12.18.0 | 仓库锁文件是 `frontend/pnpm-lock.yaml`，请用 pnpm 而非 npm 安装 |

## 首次启动 · 后端

### 1. 建库建账号（用 root 执行一次）

```sql
CREATE DATABASE IF NOT EXISTS pet_dog
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS pet_dog_test_bb00
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'petdog'@'localhost' IDENTIFIED BY 'petdog';
GRANT ALL PRIVILEGES ON pet_dog.*            TO 'petdog'@'localhost';
GRANT ALL PRIVILEGES ON pet_dog_test_bb00.*  TO 'petdog'@'localhost';
FLUSH PRIVILEGES;
```

**为什么分成两个库**：`pet_dog` 是正式库，`pet_dog_test_bb00` 是 pytest 的沙地——测试会 `drop_all` 掉整个库的表，指向正式库跑一次就把数据清空了。
**为什么账号只绑 localhost**：`petdog` 只有这两个库的权限（`SHOW GRANTS` 是 `USAGE ON *.*` + 两条 `ALL PRIVILEGES`），建库能力收归 root。应用账号不持有删库权限是刻意的。
本机 `skip_name_resolve=OFF`，连 `127.0.0.1` 也会被还原成 `petdog@localhost`；若把该参数改成 ON，账号要改成 `'petdog'@'127.0.0.1'`。

### 2. 装依赖

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`requirements.txt` 是运行时依赖，`requirements-dev.txt` 额外带 pytest 与 httpx。**版本全部固定**，不要顺手升级。

### 3. 建表

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

建表由 Alembic 迁移负责，`main.py` 与 `seed.py` 里的 `Base.metadata.create_all` 已删除。新增表结构一律写 `backend/alembic/versions/` 下的迁移脚本，不手改数据库。
（`backend/tests/conftest.py` 仍用 `drop_all` + `create_all` 重建测试库的沙地，那是测试专用，不是建表途径。）

### 4. 造管理员

```powershell
.\.venv\Scripts\python.exe seed.py
```

幂等：已有 admin 就跳过。产出账号 `admin` / `admin123`，与登录页「一键填入」填的值一致。

### 5. 起服务

```powershell
.\.venv\Scripts\python.exe run.py
```

- 接口文档：<http://127.0.0.1:8000/docs>（本地 swagger-ui，不依赖外网）
- 健康检查：<http://127.0.0.1:8000/api/health>
- `run.py` 带 `reload=True`，改代码自动重启

> **所有后端命令都要在 `backend/` 目录下执行**。`app` 是包内相对导入，从仓库根直接 `python -c "import app"` 会报 `ModuleNotFoundError: No module named 'app'`；`backend/.env` 也是按当前工作目录找的，目录不对会静默读不到。

## 首次启动 · 前端

```powershell
cd frontend
pnpm install
pnpm dev
```

打开 <http://localhost:5173>。Vite 把 `/api` 与 `/ws` 代理到 `127.0.0.1:8000`，所以两个服务要同时起。
`frontend/.env.development` 里 `VITE_USE_MOCK=false` 表示连真实后端；改成 `true` 可脱离后端用内置 Mock 浏览页面。前端细节见 [frontend/README.md](frontend/README.md)。

## 日常命令

| 做什么 | 命令（仓库根） |
|---|---|
| 起后端 | `cd backend; .\.venv\Scripts\python.exe run.py` |
| 起前端 | `cd frontend; pnpm dev` |
| 后端测试 | `cd backend; .\.venv\Scripts\python.exe -m pytest -q` |
| 前端测试 | `cd frontend; pnpm test` |
| 前端构建 | `cd frontend; pnpm build` |
| 契约校验 | `backend\.venv\Scripts\python.exe backend\tools\check_contracts.py` |
| 迁移状态 | `cd backend; .\.venv\Scripts\python.exe -m alembic current` |
| 模型与库是否漂移 | `cd backend; .\.venv\Scripts\python.exe -m alembic check` |
| 造演示设备（开发期） | `cd backend; .\.venv\Scripts\python.exe seed_devices.py` |

测试跑在 `pet_dog_test_bb00` 上，`backend/tests/conftest.py` 在 import 任何 app 模块之前改写 `DB_URL`，并有三道断言拦住"误连正式库"。

## 仓库结构

| 目录 | 内容 |
|---|---|
| backend/ | FastAPI、MySQL、Alembic 迁移、归属权限、设备会话与事件 |
| frontend/ | 现有Vue页面、组件、API、store和WS客户端 |
| firmware/ | 固件工程、协议、动作、表情与状态 |
| hardware/ | 接线、供电、校准、装配和PCB |
| docs/plan/ | 当前权威执行文档 |
| docs/contracts/ | 机器契约：openapi.yaml、HTTP/WS/帧样例、check_contracts.py |
| docs/evidence/ | 按任务ID归档的验收证据（如 BB00 隔离测试环境） |
| docs/archive/ | 历史计划/契约/研究参考，不作为施工指令 |

## 当前实现进度（2026-11-14）

| 端 | 状态 |
|---|---|
| 后端 HTTP | 契约 20 条路径 / 21 个操作中已实现 13 条路径（14 个操作）：认证 6（注册/登录/登出/资料/改密/注销）、设备 4（列表、详情+改名、状态、假心跳）、表情列表、运维状态、health |
| 契约外接口 | `POST /api/devices/{id}/music` 代码已实现但 `openapi.yaml` 未收录，需补进 06 与契约或下线，否则校验脚本发现不了这类反向偏差 |
| 后端缺 | `/api/devices/claimable`、`/api/devices/claim`、`/api/devices/{id}/binding`、`/api/commands/send`、`/api/commands/{id}`、`/api/events/ticket`、`/api/faces/current` |
| WebSocket | `/ws/device` 未实现（前端 `ws.ts` 已在请求 `/api/events/ticket`） |
| 数据库 | 六表 + `alembic_version`，基线迁移 `0001` 已 stamp；归属约束、设备认领等表尚未建 |
| 固件 / 硬件 | 仅占位，EA/EB 任务未开工 |
| 前端 | 7 个页面可构建可测试（`pnpm build`、`pnpm test` 均通过），数据源已切到真实接口 |

带 `DEV_HEARTBEAT` 的假心跳（`POST /api/devices/heartbeat` + `backend/tools/sim_heartbeat.py`）只用于开发期让设备显示在线，它由 `backend/.env` 的 `DEV_HEARTBEAT=True` 打开，默认为关；真实心跳打通后连同脚本一起删除（见 plan/06 §11）。

## 协作规则

保留现有页面、组件、票据和对账骨架，增量修复状态与权限问题；不重新建前端工程，不无故搬目录或升级依赖。
main保持可演示版本，dev用于集成，个人功能分支合入前由接收人review和运行测试。
跨端字段只在06修改，再同步schema和三端实现。不要让旧Word的示例口令、动作索引和ACK成功语义重新进入代码。
实际部署命令由实现后的新环境验证决定；任务计划中待新增的CLI和测试不得宣传成当前已能运行。

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| `ModuleNotFoundError: No module named 'app'` | 不在 `backend/` 目录下执行。先 `cd backend` |
| `Table 'pet_dog.user' doesn't exist`（错误码 1146） | 没跑迁移。先 `alembic upgrade head`，再 `seed.py` |
| 迁移报 `Table 'xxx' already exists`（1050） | 该库已有表但没有版本号。旧库用 `alembic stamp head` 盖章，不要 `upgrade` |
| `Target database is not up to date` | `versions/` 里有库中未执行的迁移，先 `alembic upgrade head` |
| 启动成功但接口报 `Can't connect to MySQL server` | MySQL 服务没起。建表已交给迁移，所以进程能起来，但任何查库的接口都会失败 |
| 终端中文乱码 | PowerShell 执行 `chcp 65001`；mysql 客户端加 `--default-character-set=utf8mb4` |
| 改了 `backend/app/models.py` 但表没变 | 迁移不会自动生成。`alembic revision --autogenerate -m "说明"` 生成草稿后**逐行核对**再 `upgrade` |

`backend/.env`（本机密钥与开关）与 `frontend/.env.local` 都不进仓库，见 `.gitignore`；`frontend/.env.development` / `.env.production` / `.env.test` 三份是进仓库的公共配置。
`JWT_SECRET` 的默认值只是占位，部署前必须在 `backend/.env` 里换掉。`backend/.env` 里的键名与 `backend/app/config.py` 的字段同名（如 `DEV_HEARTBEAT=True`）。

## 许可证

原开源项目为 GPL 3.0，本项目沿用。仅供学习与课程使用，不做商用。
