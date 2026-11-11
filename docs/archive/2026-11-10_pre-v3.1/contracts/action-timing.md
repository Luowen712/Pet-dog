# 动作时序与全局常量契约 v1.0

> **文档状态（2026-11-10）：既有契约，待T01同步V3。** 下方保留当前版本内容；与V3冲突的条目尚未修订，不得解释成已统一。具体项目、负责人和发布门禁见 [T01契约同步清单](T01_契约同步清单.md)。既有正文中的唯一依据指正式发布的契约职责，不表示本版本已通过V3对齐。

> **本文件是数值的唯一权威源。** 后端常量与固件常量都由本文件生成，禁止任何一方手写这些数字。
> owner：嵌入式负责人（填测量值） · 生成器：后端负责人 · 审阅：双方
> 生成命令：`python tools/gen_action_timing.py` → 产出 `backend/app/generated/action_timing.py` 与 `firmware/include/action_timing.h`
> CI：重新生成后 `git diff --exit-code`，不一致即失败。

---

## 0. 为什么要有这份文件

现在只有 `0x43 打招呼` 有实测时长（1600 ms，来自固件五步 hold_ms 之和）。
其余 16 个动作**没有任何测量数据**。

如果后端各写一个 `T_done`，固件按自己的实际时长跑，会出现两种必然的错：
1. 后端超时太短 → 动作还在动就被判 `unknown`，前端显示「结果不明」，实际成功了。
2. 后端超时太长 → 真卡死时用户要等十几秒才看到失败。

所以：**没有测量值的动作，就是不填数字**，由下文的安全网兜底，并把缺口暴露在表里。

---

## 1. 动作分类（决定谁能置终态）

| class | 含义 | `0x81` 之后 | 终态由谁产生 |
|---|---|---|---|
| `blocking` | 抢占舵机，动作期间不能做别的 | `accepted` | **`0x02`** → `done` |
| `led` | 只改 LED 状态，不动舵机 | **`done`** | `0x81` 本身就是终态 |
| `trigger` | 即发即忘（`0x06` 查询、`0x07` 表情） | 不建命令记录 | 无 |

> ⚠ **`led` 类必须在这里定死。** 固件对 LED **不会**发 `0x02`（它没有「执行完毕」的概念，收到即生效）。
> 若按 `blocking` 处理，开灯命令会永远停在 `accepted`，前端按钮一直转圈——这是最容易在联调第一天就被用户发现、却没人知道该改哪里的坑。
> 规则：**LED 类收到 `0x81` 即置 `done`**，不需要 `T_done` 计时器。
> `trigger` 类不建 `command_log` 记录，因此 `0x07 表情` 发出后前端**不能**显示命令进度——只有表情快照会变。

---

## 2. 动作表

| 码 | 名称 | class | 步数 | `max_duration_ms` | 测量状态 |
|---|---|---|---:|---:|---|
| `0x29` | 放松趴下 | blocking | ? | `null` | **未测量** |
| `0x30` | 蹲下 | blocking | ? | `null` | **未测量** |
| `0x31` | 站立 | blocking | ? | `null` | **未测量** |
| `0x32` | 趴下 | blocking | ? | `null` | **未测量** |
| `0x33` | 前进 | blocking | ? | `null` | **未测量** |
| `0x34` | 后退 | blocking | ? | `null` | **未测量** |
| `0x35` | 左转 | blocking | ? | `null` | **未测量** |
| `0x36` | 右转 | blocking | ? | `null` | **未测量** |
| `0x37` | 摇摆 | blocking | ? | `null` | **未测量** |
| `0x38` | 提速 | blocking | ? | `null` | **未测量** |
| `0x39` | 摇摆加速 | blocking | ? | `null` | **未测量** |
| `0x40` | 摇尾巴 | blocking | ? | `null` | **未测量** |
| `0x41` | 前跳 | blocking | ? | `null` | **未测量** |
| `0x42` | 后跳 | blocking | ? | `null` | **未测量** |
| `0x43` | 打招呼 | blocking | 5 | **1600** | 已测量（fw.txt:667 五步 hold_ms 之和） |
| `0x44` | 开灯 | led | 1 | `null` | 不适用 |
| `0x45` | 关灯 | led | 1 | `null` | 不适用 |
| `0x46` | 开呼吸灯 | led | 1 | `null` | 不适用（协议保留，接口层暂不开放，见 http-api.md §5.1） |
| `0x47` | 关呼吸灯 | led | 1 | `null` | 不适用（协议保留，接口层暂不开放，见 http-api.md §5.1） |
| `0x48` | 伸懒腰 | blocking | ? | `null` | **未测量** |
| `0x49` | 后腿拉伸 | blocking | ? | `null` | **未测量** |

「步数 ?」也是真实状态：固件目前只实现了 `act_hello`，其余 18 个在 `ACTION_TABLE` 里是注释占位。
**固件同学每实现一个动作，就在这里填一行。** 填完那一行，后端的超时才对该动作生效。

---

## 3. 超时公式

```
T_ack  = 600 ms                                  恒为 600，与动作无关
T_done = max_duration_ms + 600 ms                仅当 class=blocking 且 max_duration_ms 非 null
```

| 情形 | 计时器 | 到期结果 |
|---|---|---|
| `class=blocking` 且已测量 | `T_done = max_duration_ms + 600` | `unknown` |
| `class=blocking` 且未测量 | 不装 `T_done`，只装安全网 `T_DONE_HARD_CAP_MS = 30000` | `unknown` + 记一条 `contract_gap` 日志 |
| `class=led` | 只装 `T_ack`，收到 `0x81` 直接 `done` | `unknown` |
| `class=trigger` | 不装任何计时器 | 无记录 |

> `T_ACK_MS = 600 ms` 是**后端**判定「设备没受理」的唯一依据，与前端按钮 3 秒变红的展示反馈
> **无关**。前端不得自判超时，也不得把 3 秒写进任何契约性代码路径——那只是「让用户看到按钮还在转」
> 的乐观 UI，命令结论一律看 `command_log`。

**安全网不是测量值。** `T_DONE_HARD_CAP_MS=30000` 的唯一目的是让「固件崩了、`0x02` 永远不来」的命令最终能收敛，而不是替任何动作背书。
每次它触发，都要打一条 `contract_gap action=0x??` 日志——那是「该动作还没测时长」的提醒，不是故障。

---

## 4. 怎么测量（嵌入式执行，后端只需要结果）

1. 固件在 `Protocol_Dispatch` 收到 `0x01` 时记录 `t0 = HAL_GetTick()`，在 `SendAck(0x02, ...)` 前置位记录 `t1`。
2. 每个动作连续跑 20 次，记录 20 个 `t1-t0`。
3. `max_duration_ms` 取 **20 次最大值**，不是平均值。平均值会让一半的正常执行被判超时。
4. 电池电压取标称值（不要用快没电的电池测，舵机会变慢）。
5. 填进 §2 表格，跑一次生成器，把两个生成文件一起提交。

> 不要为了省事填一个「大概 3 秒」。3 秒对 `0x43` 是 2200ms 预算的两倍多，意味着真卡死时用户要等 3 秒才知道；而对某个 5 秒的长动作又必然误判超时。

---

## 5. 机器可读块（生成器唯一读取来源）

```yaml
version: "1.0"
constants:
  T_ACK_MS: 600
  T_DONE_MARGIN_MS: 600
  T_DONE_HARD_CAP_MS: 30000
  ACK_LATENCY_ACCEPT_MS: 400
  HEARTBEAT_INTERVAL_MS: 3000
  DEVICE_SILENCE_MS: 9000
  FRAME_GAP_MS: 20
  SEQ_RETIRE_MS: 30000
  MAX_DATA_LEN: 31
  MAX_FRAME_SIZE: 36
  WS_QUEUE_MAX: 128
actions:
  - { code: 0x29, name: "放松趴下", class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x30, name: "蹲下",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x31, name: "站立",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x32, name: "趴下",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x33, name: "前进",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x34, name: "后退",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x35, name: "左转",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x36, name: "右转",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x37, name: "摇摆",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x38, name: "提速",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x39, name: "摇摆加速", class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x40, name: "摇尾巴",   class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x41, name: "前跳",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x42, name: "后跳",     class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x43, name: "打招呼",   class: blocking, steps: 5,    max_duration_ms: 1600 }
  - { code: 0x44, name: "开灯",     class: led,      steps: 1,    max_duration_ms: null }
  - { code: 0x45, name: "关灯",     class: led,      steps: 1,    max_duration_ms: null }
  - { code: 0x46, name: "开呼吸灯", class: led,      steps: 1,    max_duration_ms: null }
  - { code: 0x47, name: "关呼吸灯", class: led,      steps: 1,    max_duration_ms: null }
  - { code: 0x48, name: "伸懒腰",   class: blocking, steps: null, max_duration_ms: null }
  - { code: 0x49, name: "后腿拉伸", class: blocking, steps: null, max_duration_ms: null }
```

---

## 6. 生成产物形状

`backend/app/generated/action_timing.py`（**不要手改**）：
```python
# generated from docs/contracts/action-timing.md — do not edit
T_ACK_MS = 600
T_DONE_MARGIN_MS = 600
T_DONE_HARD_CAP_MS = 30000
ACTION_CLASS = {0x29: "blocking", 0x44: "led", ...}
MAX_DURATION_MS = {0x43: 1600}   # 未测量的动作不在这个字典里
```

`firmware/include/action_timing.h`（**不要手改**）：
```c
/* generated from docs/contracts/action-timing.md — do not edit */
#define T_ACK_MS 600u
#define T_DONE_MARGIN_MS 600u
#define T_DONE_HARD_CAP_MS 30000u
#define HEARTBEAT_INTERVAL_MS 3000u
#define DEVICE_SILENCE_MS 9000u
#define FRAME_GAP_MS 20u
#define MAX_DATA_LEN 31u
#define MAX_FRAME_SIZE 36u
typedef enum { ACT_BLOCKING = 0, ACT_LED = 1 } ActionClass;
typedef struct { uint8_t code; ActionClass cls; uint16_t max_duration_ms; } ActionTiming;
static const ActionTiming ACTION_TIMING[] = { {0x43, ACT_BLOCKING, 1600}, ... };
```

固件用 `ACTION_TIMING` 做**稀疏查表**，禁止 `code - 0x29` 当下标（见 frame.md §6）。

---

## 7. 版本规则

- 填一个动作的 `max_duration_ms` = 修订号 +1，不算破坏性改动（两端重新生成即同步）。
- 改 `class`（尤其 blocking ↔ led）= 主版本号 +1，因为终态判定会变。
- 改 `constants` 里任何数值 = 次版本号 +1，并说明为什么原来的值不对。
- **禁止**只改生成文件不改本文件。CI 会重新生成并比对，改了生成文件必然失败。
