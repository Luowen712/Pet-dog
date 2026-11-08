# WebSocket 事件契约 v1.0

> **本文件是前端与后端之间实时通道的唯一依据。** 后端推什么、前端怎么解释，只看这里。
> owner：后端负责人 · 审阅：前端负责人
> 配套：`frame.md`（串口帧）、`openapi.yaml`（HTTP 接口）、`error-codes.md`（错误码）

---

## 0. 一句话原则

**WS 只推「已经发生的事实」，丢线之后靠快照重建，不靠补发。**

推论三条：
1. 事件是**事实通知**，不是**状态本身**。前端把事件当增量，把快照当基线。
2. 断线期间丢掉的终态 ack **不会**补发。重连必须走 §7 的对账流程。
3. 后端不得因为「前端可能没收到」而重发事件——重发会让前端把同一个 done 处理两次。

---

## 1. 建连与鉴权

### 1.1 为什么不能把 JWT 放 URL

浏览器的 `new WebSocket(url)` **不允许**自定义请求头，所以带不上 `Authorization: Bearer`。
现有实现退而把长期 JWT 塞进查询参数（`/ws/device?token=<JWT>`）。后果：

- URL 会进 Nginx/uvicorn 的 access log、反向代理日志、浏览器历史、抓包记录；
- 一个 24 小时有效的 token 一旦落进日志，等于长期凭证泄漏；
- 前端重连时 URL 不变，日志里会重复记录同一个 token。

### 1.2 一次性票据流程

```
① 前端  POST /api/events/ticket   （带 Authorization: Bearer <JWT>）
          body: { "deviceId": 1 }
   ← 200  data: { "ticket": "<32 字节随机串>", "expiresInSec": 30 }

② 前端  new WebSocket("/ws/device?deviceId=1&ticket=<ticket>")

③ 后端  校验 ticket：存在 && 未过期（≤30s）&& 未使用过 && userId 与 deviceId 匹配
        通过 → 立即从票据池删除（一次性）
        不通过 → 以 4003 关闭，不升级连接
```

**票据规则：**

| 项 | 值 |
|---|---|
| 有效期 | 30 秒 |
| 使用次数 | 1 次（建连即焚） |
| 绑定 | `(userId, deviceId)`，不可跨用户、不可跨设备 |
| 存储 | 进程内存 `dict[ticket] -> (userId, deviceId, expireAt)` |
| 清理 | 每次签发时扫一遍过期项；进程重启即全部失效 |

> ⚠ 存内存意味着**必须单进程**。多 worker 时票据签发在 A 进程、建连落在 B 进程就会 4003。
> 这与 `frame.md` 要求串口唯一所有者是同一条约束的两种表现，不是两个问题。

### 1.3 关闭码

| code | 含义 | 前端该做什么 |
|---:|---|---|
| `1000` | 正常关闭（用户主动断开 / 页面卸载） | 不重连 |
| `4001` | 缺少或格式错误的参数 | 不重连，报错并检查代码 |
| `4003` | ticket 无效 / 过期 / 已使用 | **重新取 ticket 后重连**（不要复用旧 ticket） |
| `4009` | 同一用户对同一设备的连接数超限（上限 3） | 提示「该设备已在其他窗口打开」，退避 5s 后重连 |
| `1011` | 服务端内部错误 / 队列溢出 | 退避重连（1→2→4→8→10s 封顶，沿用现有实现） |

---

## 2. 消息格式

一律 **JSON 文本帧**（`ws.send(json.dumps(...))`）。二进制帧不使用，收到即忽略。

```json
{
  "event": "command",
  "eventId": "0193f0a1-7c3e-7c1a-9b2f-2f6d1c0a9e11",
  "ts": 1762500000123,
  "deviceId": 1,
  "data": { }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `event` | string | 是 | 事件名，见 §3 |
| `eventId` | string(uuid) | 是 | 事件唯一 id。前端用它去重，后端日志用它追踪 |
| `ts` | int64 | 是 | **事件发生时刻**（不是发送时刻）的服务端毫秒时间戳 |
| `deviceId` | int | 是 | 归属设备 |
| `data` | object | 是 | 事件负载；无负载时为 `{}`，**不要省略** |

> 现有实现的事件是扁平的 `{ event, data }`，没有 `eventId/ts/deviceId`。
> 加这三个字段是**向后兼容**的（前端现有代码只读 `event` 和 `data`，多余字段不影响运行），
> 所以可以先后端加上、前端再用，不需要两端同时上线。

---

## 3. 事件表

| `event` | 何时推 | 可丢 | 前端必须做什么 |
|---|---|---:|---|
| `snapshot` | **建连成功后立刻推一帧**，之后不再推 | 否 | 用它整体覆盖本地状态 |
| `state` | 收到 `0x03` 状态快照帧 | 是（可合并） | 更新电量/电压/动作/表情/音乐/天气 |
| `command` | 命令状态发生任何变化 | 否 | 按 `cmdId` 更新该条命令记录 |
| `link` | 设备 online 状态翻转，或串口打开/关闭 | 否 | 显示在线/离线 |
| `music` | 收到 `0x0B` 音乐状态帧 | 是 | 更新音乐 UI |
| `weather` | 服务端天气抓取结果变化 | 是 | 更新天气展示（与设备无关） |
| `scene` | 场景执行进度变化 | 否 | 更新场景运行进度 |
| `ping` | 服务端每 30 s 一次 | 是 | 刷新看门狗；**不产生任何 UI 变化** |

> **`ack` 事件已更名为 `command`。** 原因：`0x81` 在帧协议里叫「受理应答」，
> 而这条事件承载的是 pending→accepted→done→unknown 的全部变化。
> 让两个不同的东西共用一个名字，联调时必然有人说错。
> 改名成本：`frontend/src/types/index.ts` 的 `WsEvent` 联合类型 + `stores/pet.ts` 的
> `switch (event.event)` 分支，共 2 处，约 3 行。

---

## 4. 各事件负载

### 4.1 `snapshot`（建连首帧）

```json
{
  "event": "snapshot",
  "data": {
    "device": { "online": true, "lastFrameAt": "2026-11-08T11:20:03.221Z" },
    "state": {
      "battery": 82, "voltageMv": 3980, "action": 49,
      "expression": 2, "musicState": 0, "track": 0,
      "weatherCode": 3, "temperatureC": 12, "updatedAt": "2026-11-08T11:20:01.000Z"
    },
    "activeCommands": [
      { "cmdId": "6f1f...", "action": 67, "status": "accepted", "transport": "ok", "seq": 7 }
    ],
    "scene": { "runId": null, "running": false, "step": 0, "total": 0 }
  }
}
```

**`snapshot` 是唯一权威基线。** 前端收到后：清空本地命令 pending 表，按 `activeCommands` 重建；
状态字段整体覆盖，不做合并。缺失字段（`null`）表示「还不知道」，前端显示 `--` 而不是 0。

> 为什么 `activeCommands` 只放未终结的命令：已终结的命令在 HTTP 的 `/api/commands/active`
> 和日志里能查到，塞进快照会让首帧随历史增长而变大，最终变成一个分页接口。

### 4.2 `command`

```json
{
  "event": "command",
  "data": {
    "cmdId": "6f1f2c1e-8d1a-4c3b-9e77-0a1b2c3d4e5f",
    "seq": 7,
    "action": 67,
    "status": "done",
    "transport": "ok",
    "errorCode": null,
    "elapsedMs": 1632
  }
}
```

| 字段 | 说明 |
|---|---|
| `cmdId` | **前端唯一主键**。同一命令的所有事件 `cmdId` 相同 |
| `seq` | 后端分配的串口序号，仅用于日志排查。**前端不得用 seq 做 key**（1 字节、会回绕） |
| `status` | `pending / accepted / done / rejected / unknown / superseded`，语义见 `frame.md` §9 |
| `transport` | `ok / write_failed / partial_write` |
| `errorCode` | 仅 `rejected` 时非 null，取值见 `error-codes.md` |
| `elapsedMs` | 从落库到当前状态的毫秒数，仅用于展示「耗时」，前端不据此判超时 |

**同一条命令会推多条 `command` 事件**（pending 可能不推，accepted/done 至少两条）。
每次都是**全量字段**，不是增量补丁——前端直接覆盖该 `cmdId` 的记录即可。

### 4.3 `state`

```json
{ "event": "state", "data": {
  "battery": 82, "voltageMv": 3980, "action": 49, "expression": 2,
  "musicState": 0, "track": 0, "weatherCode": 3, "temperatureC": 12,
  "updatedAt": "2026-11-08T11:20:01.000Z"
} }
```

- 来源是 `0x03` 帧，字段可能因 `LEN<9` 而缺；缺的字段**不出现在 JSON 里**（而不是给 0）。
- 后端按帧到达即推，但**允许合并**（见 §5）。
- `action` 是**设备当前执行的动作码**，不是「最后一次下发的动作」。用户在页面上点了按钮但设备还没动起来时，两者不同。

### 4.4 `link`

```json
{ "event": "link", "data": { "online": false, "reason": "device_silence", "sinceMs": 9012 } }
```

| `reason` | 触发条件 |
|---|---|
| `device_silence` | 9 s 未收到任何有效上行帧 |
| `port_closed` | 后端串口打开失败或被关闭 |
| `device_resumed` | 沉默后重新收到上行帧 |

> `online` 与「串口是否打开」「心跳是否在发」是三件独立的事，见 `frame.md` §8.2。
> 一个常见误判：串口开着、心跳在发，但设备一个字节都不回——这时设备是 offline 的。

### 4.5 `music` / `weather`

```json
{ "event": "music",   "data": { "musicState": 1, "track": 3 } }
{ "event": "weather", "data": { "code": 3, "text": "阴", "temp": 12, "updatedAt": "..." } }
```

`music` 由 `0x0B` 触发，是**设备上报**；`weather` 由服务端抓取触发，与设备无关。
两者都**不是**命令回执：用户点了「播放」，命令成功与否看 `command` 事件，音乐 UI 只能等 `music` 事件变。

### 4.6 `scene`

```json
{ "event": "scene", "data": {
  "runId": "b21c...", "sceneId": 4, "state": "running",
  "step": 2, "total": 3, "cmdId": "6f1f..."
} }
```

`state`: `running / finished / aborted`。
`aborted` 表示某一步没有得到 `done`（可能是 `unknown`），场景**不会重试**——重试会把动作做两遍。

### 4.7 `ping`

```json
{ "event": "ping", "data": { "serverTime": 1762500000123 } }
```

服务端每 30 s 发一次。前端设一个 75 s 看门狗：75 s 内没收到**任何**消息就主动 `close()` 并走重连。

> 浏览器拿不到 WebSocket 的 ping/pong 控制帧，所以 TCP 层的死连接（例如笔记本休眠后）
> 在浏览器看来仍是 `OPEN`，`onclose` 永远不触发。没有应用层 ping 就会卡在假死状态。

---

## 5. 顺序与合并

### 5.1 顺序

- 单条连接内，事件按 `hub.publish()` 的调用顺序 FIFO 发出。
- 后端可能有多个生产者（串口读循环、命令服务、场景执行器），它们都在同一个事件循环里 publish，
  所以顺序等于**事件循环的调度顺序**，不需要额外加锁。
- **不需要**跨连接保证顺序。

### 5.2 合并

| 事件 | 可合并 | 规则 |
|---|---:|---|
| `state` | 是 | 队列里已有未发出的 `state` 时，**用新的替换旧的那一条**，不追加 |
| `music` | 是 | 同上 |
| `weather` | 是 | 同上 |
| `command` | **否** | 每条都必须送达，否则前端会漏掉一个状态跃迁 |
| `link` | **否** | 翻转是离散事实 |
| `scene` | **否** | 进度跳跃会让前端卡在中间步 |
| `snapshot` | 否 | 只在建连时出现 |

> `state` 可以合并，是因为它是**幂等快照**：丢掉中间值不影响最终显示。
> `command` 不能合并，是因为 `accepted → done` 和 `pending → done` 对用户意味着不同的等待体验。

---

## 6. 背压与丢弃

每个连接一个独立 `asyncio.Queue(maxsize=128)`，由**独立的发送任务**消费，业务代码只 `put_nowait`。

| 队列满时的行为 |
|---|
| `state` / `music` / `weather` / `ping` → 丢弃最旧的一条，放入新的 |
| `command` / `link` / `scene` → **不允许丢**：立刻以 `1011` 关闭该连接，让前端重连并用 `snapshot` 对账 |

**为什么用「关闭」而不是「阻塞」：**

如果在 `put` 上 `await`，一个慢客户端会拖住串口读循环——串口读循环一停，
设备发来的 `0x02` 就堆在驱动缓冲区里，最终溢出丢帧，所有命令都超时。
**一个浏览器的网速绝不能影响设备链路。**

---

## 7. 断线重连对账（必须实现）

```
① 取 ticket       POST /api/events/ticket  { deviceId }
② 建连            ws://.../ws/device?deviceId=..&ticket=..
③ 收到 snapshot   覆盖本地状态 + 用 activeCommands 重建 pending 表
④ 补命令状态       对每个本地仍显示 pending/accepted 的 cmdId：
                   GET /api/commands/{cmdId}（只补 snapshot 里没有的）
⑤ 恢复实时         此后只用事件，不轮询
```

**第 ④ 步不能省。** 场景：用户点「打招呼」，WS 在 `accepted` 之后断了，
`done` 事件在断线期间产生并丢失，重连后 `activeCommands` 里没有它（它已终结）。
只有 `GET /api/commands/{cmdId}` 能告诉前端「那条其实已经成功了」。

**第 ④ 步也不能无限做。** 只对「前端记录里状态不是终态」的 cmdId 调用，最多 20 条；
超过说明前端状态管理已经坏了，应该整页刷新而不是补 100 个请求。

---

## 8. 与现有代码的差异清单（照此改，不要凭印象）

| # | 现状 | 契约要求 | 改哪里 | 代价 |
|---|---|---|---|---|
| D1 | `utils/ws.ts` 用 `/ws/device?token=<JWT>&device_id=` | 改为 `?deviceId=&ticket=`，建连前先取 ticket | `ws.ts`（buildUrl + connect）+ 新增 `api/event.ts` | 中：多一次 HTTP 请求，重连逻辑要串起来 |
| D2 | `types/index.ts` `WsEvent` 用 `ack` | 改为 `command`，字段换 `cmdId/status/transport/errorCode/elapsedMs` | `types/index.ts`、`stores/pet.ts` | 小：约 3 行 |
| D3 | `stores/pet.ts` `TIMEOUT_MS=3000` 前端自判超时 | **删掉计时器**，超时只由后端判定 | `stores/pet.ts` | 中：删代码比加代码更需要确认没别人依赖 |
| D4 | `stores/pet.ts` pending 表按 `seq` 索引 | 改为按 `cmdId` 索引 | `api/command.ts`（返回 cmdId）、`stores/pet.ts` | 中：命令主键换了，所有查表点都要过一遍 |
| D5 | 无 `snapshot` / `scene` / `ping` 事件 | 后端新增三个事件 | 后端 `link/hub.py`；前端 `ws.ts` 看门狗 | 小 |
| D6 | 无重连对账 | §7 五步 | `stores/pet.ts` | 中：需要一个「对账中」的 UI 状态 |

> **D3 和 D4 是同一个根因**：前端把「命令」当成「一次 HTTP 请求」来管。
> 契约里命令是一个**有生命周期的实体**，主键是 `cmdId`，状态由后端单方判定。
> 这两条不改，联调时会出现「后端说 done、前端说 TIMEOUT」的对话，而这种 bug 极难复现。

---

## 9. 版本

- 新增事件、新增字段 = 次版本号 +1，前端不认识的字段直接忽略。
- 删除事件、改字段语义、改 `cmdId` 主键地位 = 主版本号 +1，两端同时上线。
- **禁止**用「前端忽略就行」来掩盖破坏性改动——前端忽略的是一个它本来就在用的字段时，它不会报错，只会显示错。
