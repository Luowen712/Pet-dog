# Pet-dog · STM32 智能桌面宠物

当前执行版本 **3.1：核心闭环优先，扩展按进度纳入**。计划不等于已实现能力，SIM与HW验收分别记录。

## 组员开工入口

直接阅读 [docs/plan/00_执行入口.md](docs/plan/00_执行入口.md)，按角色领取任务：

- [总计划与交付门禁](docs/plan/01_总计划与交付门禁.md)
- [后端A/B执行计划](docs/plan/02_后端执行计划.md)
- [前端执行计划](docs/plan/03_前端执行计划.md)
- [固件A/硬件B执行计划](docs/plan/04_嵌入式执行计划.md)
- [需求追踪与验收台账](docs/plan/05_需求追踪与验收台账.md)
- [跨组接口与状态规则](docs/plan/06_跨组接口与状态规则.md)

plan只保留这七份执行文件。原Word、V3和旧契约已移入[历史归档](docs/archive/2026-11-10_pre-v3.1/)，不与当前计划并行执行。
J00已按共享规则把机器契约落到 [docs/contracts](docs/contracts/README.md)：`openapi.yaml`（20 条路径 / 22 个响应 schema）+ 22 个 HTTP、8 个 WS、12 个帧样例。它们必须与06一致，校验命令 `backend\.venv\Scripts\python.exe backend\tools\check_contracts.py`（ERROR 退出码1）。

## 仓库结构

| 目录 | 内容 |
|---|---|
| backend/ | FastAPI、MySQL、归属权限、设备会话与事件 |
| frontend/ | 现有Vue页面、组件、API、store和WS客户端 |
| firmware/ | 固件工程、协议、动作、表情与状态 |
| hardware/ | 接线、供电、校准、装配和PCB |
| docs/plan/ | 当前权威执行文档 |
| docs/contracts/ | 机器契约：openapi.yaml、HTTP/WS/帧样例、check_contracts.py |
| docs/archive/ | 历史计划/契约/研究参考，不作为施工指令 |

## 协作规则

保留现有页面、组件、票据和对账骨架，增量修复状态与权限问题；不重新建前端工程，不无故搬目录或升级依赖。
main保持可演示版本，dev用于集成，个人功能分支合入前由接收人review和运行测试。
跨端字段只在06修改，再同步schema和三端实现。不要让旧Word的示例口令、动作索引和ACK成功语义重新进入代码。
实际部署命令由实现后的新环境验证决定；任务计划中待新增的CLI和测试不得宣传成当前已能运行。

## 许可证

原开源项目为 GPL 3.0，本项目沿用。仅供学习与课程使用，不做商用。
