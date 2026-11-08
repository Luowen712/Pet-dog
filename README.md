# Pet-dog · STM32 智能桌面宠物

一个巴掌大的四足桌面机器人：会站、走、转、跳、摇尾巴，屏幕上有表情，下半屏显示时间和天气，身上有喇叭能放音乐，可以对着它说话，也可以从网页上远程操作。

主控是 STM32F103C8T6。在原开源项目的基础上，加了 Python 后端和 Vue3 网页控制台，变成一套完整的三层系统。

## 仓库里有什么

| 目录 | 放什么 | 谁负责 |
|---|---|---|
| `firmware/` | STM32 固件：Keil 工程、PWM 驱动、串口协议、动作表、字库 | 嵌入式 |
| `hardware/` | 原理图、PCB、BOM、外壳模型、装配说明 | 嵌入式 |
| `backend/` | Python 后端：FastAPI 服务、串口链路、MySQL、天气与校时 | 后端 |
| `frontend/` | Vue3 网页控制台：登录、设备、监控台、日志、遥测 | 前端 |
| `docs/plan/` | 计划文档（分工方案、三条线逐日计划、答辩方案、功能汇总表、市场调研） | 全员 |
| `docs/contracts/` | **接口契约唯一真源**：`http-api.md`（人读）、`openapi.yaml`（机器可读）、`frame.md`（串口帧）、`events.md`（WS 事件）、`error-codes.md`（错误码）、`action-timing.md`（超时数值） | 全员 |

空的目录里放了一个 `.gitkeep`，只是为了让目录能进仓库（git 不跟踪空目录）。你往里面放第一个真文件之后，可以把它删掉。

## 怎么开始

```bash
git clone https://github.com/Luowen712/Pet-dog.git
cd pet-dog
```

拉下来之后先别急着写代码，按你负责的线读 `docs/plan/` 里对应的那份计划文档：

- 做前端：`docs/plan/前端线开发计划_V2.0.docx`
- 做后端：`docs/plan/后端线开发计划_V2.0.docx`
- 做嵌入式：`docs/plan/嵌入式线开发计划_V2.0.docx`
- 谁都该看一遍：`docs/plan/项目分工与实施方案_V2.0.docx`、`docs/plan/项目目标架构与团队分工.md`

后端那份文档第 7 章是照着抄就能跑的完整代码，第三章是开工前要装的东西。第一次搭环境按第三章走一遍，遇到问题查第五章。

开工检查：起后端之前先确认 MySQL 服务在跑、库连得上。它没起来，后端只会丢一堆红字：

```sql
-- 在 mysql -uroot -p 里执行一次
CREATE DATABASE IF NOT EXISTS pet_dog DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

建账号、连接串与依赖清单在后端文档 7.4 节。

## 分支约定

- `main`：能跑通的版本，随时可以拿来演示。只有周合并时才往这里推。
- `dev`：日常开发的主分支，所有人最后都合到这里。
- `feature/xxx`：自己临时开的分支，做完提 PR 到 `dev`。

一个人在自己的分支上随便改，别直接往 `main` 推。

## 接口先定，再各写各的

三条线能同时开工，靠的是接口先定死：

- 前端和后端之间：HTTP 路径、字段名、返回体 `{code, message, data, timestamp}`——见 `docs/contracts/openapi.yaml` 与 `docs/contracts/http-api.md`
- 后端和固件之间：串口短帧 `AA 55 LEN CMD DATA SUM`，命令码见 `docs/contracts/frame.md`
- 实时通道：WebSocket 五种事件，见 `docs/contracts/events.md`
- 错误码：业务码 / 设备码 / 传输三态分三个域，见 `docs/contracts/error-codes.md`

字段名或命令码要改，先在群里说一声，改完文档再改代码。这一条比什么都重要——联调时九成的扯皮都出在这里。

**契约只有一套**：`docs/contracts/`。任何其它地方的接口描述（包括各线计划文档里的示例）与它冲突时，以它为准，并顺手把那份文档改掉。

## 许可证

原开源项目为 GPL 3.0，本项目沿用。仅供学习与课程使用，不做商用。
