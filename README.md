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

## 本机联调（Windows，无需更改原库）

先按下方步骤安装 Python 依赖。已安装 MySQL Server 8.0 的机器，可从仓库根运行：

~~~powershell
cd backend
.\.venv\Scripts\python.exe run_sim.py
~~~

另开终端在 frontend 下运行 pnpm dev。浏览器访问 http://127.0.0.1:5173 ，使用账号 simulator；随机密码仅在本机 %LOCALAPPDATA%\PetDog\sim-v1\login.txt。模拟库、密钥均在该用户目录，不使用正式库或 pytest 库。后端只监听 127.0.0.1:8000，独立 MySQL 监听 127.0.0.1:33317；若端口占用，不抢占进程。前台 Ctrl+C 或另开终端在 backend 下运行 .\.venv\Scripts\python.exe run_sim.py --stop 即可正常停止。再次启动保留本机演示数据。

这里走真实 HTTP、WebSocket、数据库及帧解析器，只替换设备端。loop:// 仅回显字节，不产生设备 ACK；纯前端 Mock 不验证这些链路。

## 首次启动 · 后端（指定 MySQL）

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

### 3. 配置与迁移

在 backend 下复制 .env.example 为 .env，已有配置请保留。填写 DB_URL，并生成至少 32 字符的随机值作为 JWT_SECRET（已取消配对码与 CLAIM_SECRET）。低功耗蓝牙（ECB02H2）联调设 SERIAL_PORT=ble（前端直接扫描点选连接，默认 GATT UUID 为 FFF0/FFF1/FFF2，可按实际模块批次覆写）；无板软件联调设 SERIAL_PORT=sim；有线串口固定多设备时设置 SERIAL_DEVICE_PK。

~~~powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic heads
~~~

全新空库可直接运行 alembic upgrade head。有数据的旧库先停写、备份并验证可还原，在副本上检查重复 owner_id、逐版迁移并对比账号、设备、遥测及命令行数；确认归属策略后再操作原库。0007/0008 要求一个账号最多一台；不要自动解绑、删除设备或用 stamp head 跳过迁移。0010 为命令幂等键增加唯一约束；0011 随取消配对码删除 device_claim 表；有重复历史 key 时需先人工核对。

### 4. 建管理员（应用停机时）

~~~powershell
.\.venv\Scripts\python.exe cli.py create-admin myadmin
~~~

按提示设置密码，不使用演示种子的固定凭据。

### 5. 起服务

```powershell
.\.venv\Scripts\python.exe run.py
```

- 接口文档：<http://127.0.0.1:8000/docs>（本地 swagger-ui，不依赖外网）
- 健康检查：<http://127.0.0.1:8000/api/health>
- 默认不开热重载，单 worker；只在开发调试时显式设 `PETDOG_RELOAD=1`。

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

## 已接通的核心链路

真实后端支持认证、低功耗蓝牙（ECB02H2）扫描直连与归属管理（取消 6 位配对码）、设备状态、内置表情设置、命令提交与对账、一次性 WS 票据和事件推送。动作的受理和完成是不同的回执；结果不明不自动重发。真机动作只有取得板上时序证据后才应加入允许列表。本期不提供音乐、天气、日志看板和场景扩展接口。

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
| 缺表或版本不匹配 | 核对实际库名、current 与 heads。区分空库初始化和旧库迁移，见上。 |
| 迁移报已有表（1050） | 停止迁移，核对备份与实际 schema；不要直接 stamp head。 |
| 版本落后 | 先在副本演练并验数，再安排停机迁移。 |
| 无法连接 MySQL | 检查 MySQL 监听、连接串和账号授权；拿不到实例锁时后端应拒绝启动。 |
| 终端中文乱码 | PowerShell 执行 `chcp 65001`；mysql 客户端加 `--default-character-set=utf8mb4` |
| 改了 `backend/app/models.py` 但表没变 | 迁移不会自动生成。`alembic revision --autogenerate -m "说明"` 生成草稿后**逐行核对**再 `upgrade` |

`backend/.env`（本机密钥与开关）与 `frontend/.env.local` 都不进仓库，见 `.gitignore`；`frontend/.env.development` / `.env.production` / `.env.test` 三份是进仓库的公共配置。
`JWT_SECRET` 没有可用默认值。不要把密钥、数据库连接串或 SIM 登录文件提交到仓库。

## 许可证

原开源项目为 GPL 3.0，本项目沿用。仅供学习与课程使用，不做商用。
