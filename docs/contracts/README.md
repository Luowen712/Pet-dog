# 接口产物目录

当前权威规则是[plan/06_跨组接口与状态规则.md](../plan/06_跨组接口与状态规则.md)，版本3.1。

旧六份契约和T01清单已经整体移到[历史契约](../archive/2026-11-10_pre-v3.1/contracts/)，避免同一接口同时存在多种执行口径。

联合任务J00（BA00牵头，BB00、FE00、EA01参与）在此生成，产物已落盘：

- `openapi.yaml` —— 本期核心端点的机器投影，含正常/错误/授权 schema、WS 握手与关闭码登记、`x-impl-status` 实现进度与未决项 `x-open-questions`；
- `fixtures/http/` —— HTTP 响应样例（22 个，覆盖成功、业务错误、身份/限流/内部失败、开发期假心跳）；
- `fixtures/ws/` —— WS 事件样例与关闭码总表（8 个）；
- `fixtures/frames/` —— 串口帧向量与边界用例（12 个，SUM 可独立重算）；
- 校验脚本是 `backend/tools/check_contracts.py`（归属见 plan/01 的角色权责表；路径以本行为准，不写 `tools/check_contracts.py`）。

运行：

```
backend\.venv\Scripts\python.exe backend\tools\check_contracts.py
```

有 ERROR 退出码 1；`--strict` 时 WARN 也算失败；`--verbose` 逐条打印。脚本只做静态比对，不启动后端、不连数据库，依赖仅 PyYAML。

产物不得自行定义与06不同的状态、字段或时序。变更先改06，再同步机器schema和用例。
