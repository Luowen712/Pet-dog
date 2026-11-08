# STM32 智能桌面宠物 · 前后端接口契约 V1.1

| 项目 | 内容 |
|---|---|
| 文档编号 | PET-API-V1.1 |
| 版本 / 日期 | V1.1 / 2026-11-08 |
| 面向 | 后端（FastAPI）实现方为主，前端对照 |
| 依据 | `frontend/src/api/*.ts`、`frontend/src/types/index.ts`、`frontend/src/mock/`、`frontend/src/utils/ws.ts` |
| 规模 | 22 个 HTTP 接口 + 1 条 WebSocket（共 23 条） |
| 本版改动 | 新增注册 `POST /api/auth/register`、设备改名 `PATCH /api/devices/{id}`；`WeatherInfo` 增加可选 `location` / `source`；明确表情 `preview` 必须匿名可 GET；新增 §2.1「页面已实现、后端待落地」清单 |
| 配套文件 | `docs/openapi.yaml`（可直接导入 Apifox / Swagger Editor / Postman） |

---

## 0. 这份文件是什么，怎么用

前端网页已经写完了，字段名、路径、返回体全都在 TypeScript 类型里定死了。所以这份文档不是「设计稿」，是**从代码里反向导出的契约**——后端照着实现，前端一行都不用改。

三条规矩：

1. **路径和字段名以本文件为准**，不以口头讨论为准。前端改一个字段要动 `types/index.ts`、`api/*.ts`、`mock/index.ts` 三处，成本比后端改一行高得多。
2. **真要改，先改本文件和 `openapi.yaml`，再各自改代码**，两边同时动。这是 README「接口先定，再各写各的」那一节的具体执行方式。
3. 联调时 `http://127.0.0.1:8000/docs` 是**运行时**的权威（看服务到底起了哪些路由）；但如果 `/docs` 里的字段名和本文件不一致，那是 bug，按本文件改。

文件只有两个，一起发给后端同学：

- `docs/STM32智能桌面宠物_前后端接口契约_V1.1.md`（本文，人看）
- `docs/openapi.yaml`（机器可读，导入 Apifox 后可以直接生成 Mock、发请求、导测试）

---

## 目录

1. 全局约定
2. 接口总表（23 条）
   - 2.1 页面已实现、落地必须靠后端/固件的能力
3. 逐条接口（HTTP 22 条）
4. WebSocket `/ws/device`
5. 枚举表（动作码 / 表情 / 天气 / 音乐 / 日志状态）
6. REST ↔ 串口 对照
7. 错误码
8. 两条最容易翻车的时序要求
9. 前端联调步骤与自查表
10. 后端可自定、不影响前端的部分
11. 附录：对象字段定义

---

## 1. 全局约定

### 1.1 基址与代理

| 项 | 值 | 说明 |
|---|---|---|
| 前端 baseURL | `/api` | `frontend/src/utils/request.ts` |
| 开发端口 | 前端 5173，后端 8000 | `vite.config.ts` 里 `/api` 与 `/ws` 已配好代理 |
| 后端路由前缀 | **必须带 `/api`** | 前端写 `request({url:'/devices'})`，实际请求 `/api/devices` |
| WebSocket | `ws://127.0.0.1:8000/ws/device` | **不在 `/api` 下**，单独一条路由 |

也就是说，后端最终对外长这样：

```
http://127.0.0.1:8000/api/health
http://127.0.0.1:8000/api/auth/login
http://127.0.0.1:8000/api/devices
...
ws://127.0.0.1:8000/ws/device?token=xxx&device_id=1
```

配路由时写 `APIRouter(prefix="/api/auth")` 或者 `include_router(..., prefix="/api")` 都行，只要最终路径对得上。**前缀少写一个 `/api`，前端全部 404。**

### 1.2 统一返回外壳（所有 `/api` 接口）

```json
{
  "code": 0,
  "message": "ok",
  "data": { },
  "timestamp": 1762587000000
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `code` | int | 是 | `0` 表示成功；非 0 表示失败，取值见第 7 章 |
| `message` | string | 是 | 中文、可直接展示给用户。失败时前端把这个字符串原样弹出来，别塞英文堆栈 |
| `data` | any | 是 | 业务数据。没有数据时给 `null` 或 `{}`，**不要省略这个键** |
| `timestamp` | int | 是 | 毫秒时间戳（前端目前不用，但类型里声明了，别缺） |

前端拆壳逻辑在 `request.ts` 第 63-67 行：`code === 0` 就返回 `data`，否则抛 `ApiError(code, message)` 并弹 toast。所以**页面组件永远只拿到 `data`**。

### 1.3 HTTP 状态码：只有 401 会跳登录页

这条是最容易踩的，单独列。

- **业务失败**（密码错、参数错、资源不存在）→ HTTP **200** + `code` 非 0。前端会弹 `message`，页面留在原地。
- **登录态失效**（token 过期、token 伪造、没带 token）→ 必须 HTTP **401**。前端 `request.ts` 第 74-77 行只有看到 HTTP 401 才会清 localStorage、跳 `/login`。
- 如果 401 的语义用 HTTP 200 + `code: 40101` 返回，前端只会弹一句「登录已过期」，**不会跳登录页**，用户会卡在满屏报错的页面里。所以：`code: 40101` 必须和 HTTP 401 一起出现。
- 5xx 也可以，但前端只会显示「请求失败（HTTP 500）」，看不出原因。内部错误建议 200 + `code: 50000` + 中文 `message`，方便答辩演示。

### 1.4 时间格式

统一 ISO 8601 且**带时区**：`2026-11-08T15:30:00+08:00` 或 `2026-11-08T07:30:00Z`。

前端用 `new Date(字符串)` 解析后格式化（`utils/format.ts`）。不要返回 `"2026-11-08 15:30:00"` 这种空格分隔的格式——Chrome 能过，某些内核会解析成 `Invalid Date`，图表 X 轴会变成 `NaN`。

需要「多久以前」的字段（`last_heartbeat`）也返回绝对时间，前端自己算相对时间。

### 1.5 类型约定

- 字段名统一 **snake_case**（`last_heartbeat`、`music_state`、`cost_ms`、`device_id`），因为前端 TS 类型就是这么写的，改驼峰要改 7 个文件。
- `battery`、`temp`、`cost_ms`、`seq`、`volume` 一律**整数**；`voltage` 用浮点、保留两位（`3.92`）。
- **不要用字符串装数字**（`"78"`）。前端直接拿去做 ECharts 和比较运算，字符串会画出空图。
- 布尔值用 `true/false`，不要 `0/1`（`online`、`builtin`、`accepted`）。
- 主键 `id` 用整数自增。

### 1.6 认证

| 项 | 值 |
|---|---|
| 登录后携带 | 请求头 `Authorization: Bearer <token>` |
| 前端存储 | localStorage，键名 `petdog_token`（`utils/session.ts`） |
| WebSocket | 走 query：`?token=<encodeURIComponent(token)>` |
| 无刷新机制 | 前端没有 refresh token，过期只能重新登录 |

### 1.7 超时

| 项 | 值 | 说明 |
|---|---|---|
| axios 超时 | **10 秒** | 超过就报「网络异常」，所以任何接口都别阻塞超过 10 秒 |
| 动作 ack 超时 | **3 秒** | 前端自己计时，3 秒没收到 WS `ack` 就把按钮标红。见第 8 章 |

### 1.8 分页

`page` 从 **1** 开始（不是 0），`size` 默认 10。返回：

```json
{ "items": [], "total": 0, "page": 1, "size": 10 }
```

`total` 是**过滤后的总数**，不是当前页条数。

---

## 2. 接口总表（23 条）

| # | 方法 | 路径 | 用途 | 用到它的页面 | 鉴权 |
|---|---|---|---|---|---|
| 1 | GET | `/api/health` | 健康检查（前端不调，联调自检用） | — | 否 |
| 2 | POST | `/api/auth/login` | 登录换 token | 登录页 | 否 |
| 3 | POST | `/api/auth/register` | 注册账号（V1.1 新增） | 登录页 | 否 |
| 4 | GET | `/api/auth/me` | 查当前用户 | 布局头部 | 是 |
| 5 | GET | `/api/devices` | 设备列表 | 设备页、日志页、看板 | 是 |
| 6 | GET | `/api/devices/{id}` | 单台设备（前端暂未调用，预留） | — | 是 |
| 7 | PATCH | `/api/devices/{id}` | 修改桌宠名字（V1.1 新增） | 设备页 | 是 |
| 8 | GET | `/api/devices/{id}/status` | 状态快照（进监控台时拉一次） | 监控台 | 是 |
| 9 | POST | `/api/devices/{id}/music` | 音乐控制 | 监控台音乐面板 | 是 |
| 10 | POST | `/api/commands/send` | 下发一个动作 | 监控台、场景执行 | 是 |
| 11 | GET | `/api/faces` | 表情列表 | 表情页、监控台 | 是 |
| 12 | POST | `/api/faces` | 上传自定义表情（multipart） | 表情页 | 是 |
| 13 | POST | `/api/faces/current` | 切换当前表情 | 表情页、监控台 | 是 |
| 14 | DELETE | `/api/faces/{id}` | 删除自定义表情 | 表情页 | 是 |
| 15 | GET | `/api/logs` | 指令日志（分页 + 过滤） | 日志页、看板 | 是 |
| 16 | GET | `/api/telemetry` | 近 24 小时电量遥测 | 看板 | 是 |
| 17 | GET | `/api/weather` | 当前天气 | 监控台、时钟卡 | 是 |
| 18 | GET | `/api/scenes` | 场景列表 | 场景页 | 是 |
| 19 | POST | `/api/scenes` | 新建场景 | 场景页 | 是 |
| 20 | PUT | `/api/scenes/{id}` | 修改场景 | 场景页 | 是 |
| 21 | DELETE | `/api/scenes/{id}` | 删除场景 | 场景页 | 是 |
| 22 | POST | `/api/scenes/{id}/run` | 执行场景 | 场景页 | 是 |
| 23 | WS | `/ws/device?token=&device_id=` | 实时状态 / 应答 / 链路 / 音乐 / 天气 | 全局（进监控台就连） | 是（query token） |

**仍然不需要实现的**：用户删除/角色权限管理、校时接口（0x08 由后端定时自己下发，不经过 HTTP）、日志导出、WebSocket 客户端消息（前端只收不发）。

### 2.1 页面已实现、落地必须靠后端/固件的能力

这张表是给后端同学和答辩用的：**页面上看起来都能点，是因为现在跑在 Mock 上**；`VITE_USE_MOCK=false` 之后，下面这些能力才真正依赖后端和硬件。

| 功能 | 页面入口 | 前端已经做完 | 后端必须做 | 固件/硬件必须做 | 契约位置 |
|---|---|---|---|---|---|
| 登录 / 鉴权 | 登录页 | 表单、token 存 localStorage、Bearer 头、401 跳登录 | 校验密码、签 JWT、保护所有 `/api` 与 WS | — | §3.2 / §3.4 |
| **注册账号** | 登录页「注册」 | 表单校验（3–20 位、≥6 位、两次一致）、调接口、成功回登录 | `users` 表、唯一索引、密码哈希、重名返回 40900 | — | §3.3 |
| 设备列表 | 设备页 | 卡片、在线点、当前设备记忆 | `devices` 表、心跳 < 30 秒判在线、保证 id=1 存在 | 每 5 秒上报 0x03 | §3.5 |
| **设备改名** | 设备页铅笔 | 弹窗、PATCH、列表即时刷新 | 更新 `device.name`、返回完整 Device | 可选：屏幕同步显示名字 | §3.7 |
| 动作下发 / 三态 | 控制台 | 19 个按钮、seq 配对、3 秒超时 | `/commands/send` 立即返回 seq；串口帧；更新日志；推 `ack` | 0x01 执行、0x81 受理、0x02 完成 | §3.10 |
| 实时状态 | 控制台状态条 | 电量/电压/动作/表情、WS 退避重连 | 解析 0x03、缓存快照、广播 `state` / `link` | 0x03 状态帧、心跳 | §4 |
| **天气** | 控制台时钟卡 | 图标映射、温度/地点展示、10 分钟缓存 | 定时抓 Open-Meteo（湘潭雨湖区），缓存，返回 `/weather` 并推 `weather` | 0x09 下发屏显 | §3.17 |
| **音乐播放** | 控制台音乐面板 | 播放/暂停/上下首/停止/音量 0–30、曲目显示 | `/music` → 0x0A 帧；推 `music` 事件（state/track/volume） | DFPlayer + TF 卡 + 0x0A / 0x0B | §3.9 |
| 表情切换 / 上传 | 表情库、控制台 | 7 张内置 SVG、512 字节校验、上传/删除 | 0x07 下发、文件落盘、`preview` 必须匿名可 GET | OLED 0x07 换脸 | §3.11–§3.14 |
| 日志 / 遥测 | 日志页、看板 | 分页表格、筛选、三张 ECharts | 指令落库、分页过滤、24h 电量聚合 | 0x03 提供电量/电压 | §3.15 / §3.16 |
| 场景编排 / 执行 | 场景页 | 新建、增删步骤、排序、保存、执行 | 场景落库；`/run` 立即返回并串行下发动作 | 按收到的动作逐条执行 | §3.18–§3.22 |
| 音乐导入 | 音乐面板 | 不做上传，只发控制命令 | 无（可选：曲库列表接口） | 把 `mp3/0001.mp3` 等放进 DFPlayer 的 TF 卡 | §5.4 说明 |

> **答辩口径**：注册、改名、音乐、天气这些页面功能已经写完，但目前由 Mock 托底；真机演示前必须由后端把对应接口实现，天气和音乐还分别依赖外网和 TF 卡。

---

## 3. 逐条接口

请求/响应示例都已按前端 mock 的真实形状写，可以直接当测试用例用。

### 3.1 GET `/api/health`

联调用，前端**不调用**（只在 mock 里有一条）。返回任意内容即可，建议：

```json
{ "code": 0, "message": "ok", "data": { "status": "ok", "mode": "serial" }, "timestamp": 1762587000000 }
```

---

### 3.2 POST `/api/auth/login`

前端调用点：`api/auth.ts → login()`，登录页 `views/Login.vue`

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `username` | string | 是 | 前端不做 trim，后端自己处理 |
| `password` | string | 是 | 明文，dev 环境无所谓；上线前再谈 |

```json
{ "username": "admin", "password": "123456" }
```

**响应 data**

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": { "username": "admin", "name": "管理员", "role": "admin" }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `token` | string | JWT，前端原样存 localStorage 并加 `Bearer ` 前缀 |
| `user.username` | string | 账号 |
| `user.name` | string | 显示名，中文 |
| `user.role` | string | `admin` / `viewer`，前端目前只展示不校验 |

**失败**：`code: 40001`，`message: "用户名或密码错误"`（HTTP 200）。前端把这个 message 直接弹出来，所以别写成 `invalid credentials`。

**建议**：token 有效期 ≥ 12 小时，`sub` 放 username，过期后所有接口返回 HTTP 401 + `code: 40101`。

---

### 3.3 POST `/api/auth/register`（V1.1 新增）

前端调用点：`api/auth.ts → register()`，登录页「注册」切换。

**这条只建账号，不签发 token**。前端注册成功后切回登录页，让用户用新账号登录。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `username` | string | 是 | 3–20 位字母、数字、下划线或中文；前端会先 trim |
| `password` | string | 是 | 至少 6 位；后端存哈希，不要明文落库 |

```json
{ "username": "tester01", "password": "secret123" }
```

**响应 data**

```json
{ "username": "tester01", "name": "tester01" }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `username` | string | 账号，必须和请求一致 |
| `name` | string | 显示名，默认等于 username；以后做用户资料时再允许修改 |

**失败**

- 用户名不合规 → `code: 40002`，`message: "用户名需 3–20 位字母、数字、下划线或中文"`
- 密码太短 → `code: 40002`，`message: "密码至少 6 位"`
- 用户名已存在 → `code: 40900`，`message: "用户名已存在"`

> 40900 是第 7 章预留的冲突码，注册重名就用它，不要新造数字。

**后端必须做的事**：建 `users` 表（或等价存储）、用户名唯一索引、密码哈希（bcrypt/passlib 均可）、注册后该账号能走 `/api/auth/login`。

---

### 3.4 GET `/api/auth/me`

前端调用点：`api/auth.ts → fetchMe()`，布局加载时校验登录态。

**响应 data**：同上的 `user` 对象

```json
{ "username": "admin", "name": "管理员", "role": "admin" }
```

**失败**：token 无效 → HTTP 401 + `code: 40101`，`message: "登录已过期，请重新登录"`。

---

### 3.5 GET `/api/devices`

前端调用点：`api/device.ts → listDevices()`，设备页 / 日志页过滤器 / 看板在线数。

**响应 data**：`Device[]`（**直接是数组**，不要再包一层 `{items:[]}`；`PageResult` 只用于日志）

```json
[
  {
    "id": 1,
    "name": "桌宠一号 · 小灰",
    "online": true,
    "firmware": "v2.0.0",
    "last_heartbeat": "2026-11-08T15:29:52+08:00",
    "battery": 78,
    "location": "书桌"
  },
  {
    "id": 2,
    "name": "桌宠二号 · 小白",
    "online": false,
    "firmware": "v1.9.3",
    "last_heartbeat": "2026-11-08T13:30:00+08:00",
    "battery": 41,
    "location": "客厅"
  }
]
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | int | 是 | 主键，**必须有 id=1**，前端默认选它 |
| `name` | string | 是 | 中文名 |
| `online` | bool | 是 | 后端按「心跳 < 30 秒」判定（看板文案写的就是 30s） |
| `firmware` | string | 是 | 固件版本号，字符串 |
| `last_heartbeat` | string | 是 | ISO 时间，离线设备给最后一次心跳时间 |
| `battery` | int | 是 | 0-100 |
| `location` | string | 否 | 前端只展示，可空 |

**注意**：前端 `stores/device.ts` 会把这个数组的第一个 id 存进 localStorage（键 `petdog_device`）作为当前设备。**列表为空时，监控台无法确定 device_id**，所以 seed 数据必须至少有一台设备。

---

### 3.6 GET `/api/devices/{id}`

前端调用点：`api/device.ts → getDevice()`。

**这条前端暂时没有页面调用**（`getDevice()` 写了但没用上），保留在契约里是为了以后做设备详情。后端实现成本很低，建议顺手实现，不实现也不会影响任何页面。

**响应 data**：单个 `Device` 对象，字段同上。

**失败**：`code: 40400`，`message: "设备不存在"`。

---

### 3.7 PATCH `/api/devices/{id}`（V1.1 新增，改名）

前端调用点：`api/device.ts → renameDevice()`，设备页名字后的铅笔按钮。

**只改显示名**，不动串口/蓝牙连接参数，也不要求设备在线。返回修改后的完整 `Device`，前端直接用它替换列表里那一台。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 1–20 个字符；前后端都会 trim |

```json
{ "name": "小灰灰" }
```

**响应 data**：完整 `Device`，字段和 `GET /api/devices` 里的一致。

```json
{
  "id": 1,
  "name": "小灰灰",
  "online": true,
  "firmware": "v2.0.0",
  "last_heartbeat": "2026-11-08T15:29:52+08:00",
  "battery": 78,
  "location": "书桌"
}
```

**失败**

- 名字为空或超过 20 字 → `code: 40002`，`message: "名字需要 1–20 个字符"`
- 设备不存在 → `code: 40400`，`message: "设备不存在"`

> 不要用 `PUT /api/devices/{id}` 要求前端传整个 Device；前端只发 `{name}`，其余字段保持不动。

---

### 3.8 GET `/api/devices/{id}/status`

前端调用点：`api/device.ts → getDeviceStatus()`，进监控台时调一次（`stores/pet.ts` 的 `connect`），之后靠 WebSocket 增量更新。

**响应 data**：`DeviceStatus`，11 个字段，**一个都不能少**（前端 `applyState` 直接把字段赋给 store）

```json
{
  "device_id": 1,
  "battery": 78,
  "voltage": 3.92,
  "action": 49,
  "face": 0,
  "music_state": 0,
  "track": 3,
  "volume": 15,
  "weather_code": 0,
  "temp": 23,
  "updated_at": "2026-11-08T15:30:00+08:00"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `device_id` | int | 设备 id |
| `battery` | int | 0-100，% |
| `voltage` | float | 电池电压，V，两位小数 |
| `action` | int | 当前动作码，见第 5.1 节。`49` 就是 `0x31` 站立 |
| `face` | int | 当前表情编号 0-6 |
| `music_state` | int | 0 停止 / 1 播放 / 2 暂停 |
| `track` | int | 当前曲目号，1 起 |
| `volume` | int | 0-30（DFPlayer 量程，别写 0-100） |
| `weather_code` | int | 0-9，见 5.3 |
| `temp` | int | 摄氏度，可负 |
| `updated_at` | string | 这份快照的时间 |

**实现要求**：返回后端**缓存的实时值**，不要在请求里同步去串口查一遍（串口等待会让接口偶尔超过 1 秒，页面上状态区会闪）。数据来源是设备每 5 秒上报的 `0x03`。

---

### 3.9 POST `/api/devices/{id}/music`

前端调用点：`api/music.ts → sendMusic()`，监控台音乐面板（播放/暂停/上下曲/音量）。

路径里的 `{id}` 是**当前选中设备**（`MusicPanel.vue` 取 `deviceStore.currentId`，没选过时兜底 1）。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `command` | int | 是 | 0 停止 / 1 播放 / 2 暂停 / 3 下一首 / 4 上一首 / 5 设音量 |
| `value` | int | 否 | 只在 `command=5` 时有效，0-30；其它情况前端传 0 |

```json
{ "command": 5, "value": 20 }
```

**响应 data**（前端**不读**，但要返回成功）

```json
{ "ok": true, "state": 1, "track": 3, "volume": 20 }
```

**注意**：

- 前端**不看这个响应**，界面状态完全靠 WS `music` 事件更新。所以后端执行完必须推一条 `music` 事件，否则音量条不动。
- `command=2` 是「暂停/继续」切换语义还是纯暂停，由后端定；前端只发指令、看 `music_state`。建议做成纯暂停，前端按钮文案按 `music_state` 显示。
- 曲目号越界要自己回绕，别把 `track` 推成 0 或 10+ 导致前端显示空格。

---

### 3.10 POST `/api/commands/send`

前端调用点：`api/command.ts → sendCommand()`，监控台 19 个动作按钮、场景执行。

**请求体**

```json
{ "action": 51 }
```

`action` 是十进制整数（`0x33` = 51），取值见 5.1 节 19 个动作码。

**响应 data**

```json
{ "seq": 17, "action": 51, "accepted": true }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `seq` | int | **1-250 循环**的序号，必须回填到串口帧里，设备应答时原样带回 |
| `action` | int | 回显请求的动作码 |
| `accepted` | bool | 是否已受理。`false` 前端也会进 pending 等 ack，所以建议只返回 `true`，失败直接用错误码 |

**关键约束（前端写死的行为）**

1. 这个接口**必须立刻返回**（< 300ms），不能等设备 ack。前端拿到 `seq` 后自己起 3 秒计时器，等 WS 里的 `ack`。如果这里阻塞到 ack 才返回，等于把 3 秒预算吃掉了，按钮几乎必然标红。
2. `seq` 要在 1-250 之间循环，**同一时刻不能有两个在用同一个 seq**。前端用 `pending[seq]` 配对 ack，撞号会把 A 的应答算到 B 头上。250 是前端 mock 的模数（`runtime.nextSeq()`），照做即可。
3. 没有 `device_id` 字段，这是**故意的**：前端只接一条串口链路。后端按「当前唯一设备（id=1）」处理。将来要做多设备，需要改成 `/api/devices/{id}/commands`，两边同时改。
4. 不管设备回没回，后端都要往 `command_log` 写一行：受理时 `PENDING`，之后更新成 `OK` / `TIMEOUT`（3 秒）/ `ERROR`。

**失败**：`code: 40002`，`message: "动作码不合法"`（比如传了 5.1 表里没有的码）。

---

### 3.11 GET `/api/faces`

前端调用点：`api/face.ts → listFaces()`，表情页、监控台表情条。

**响应 data**：`FaceItem[]`

```json
[
  { "id": 0, "name": "普通", "builtin": true },
  { "id": 1, "name": "开心", "builtin": true },
  { "id": 6, "name": "卖萌", "builtin": true },
  { "id": 100, "name": "我的狗", "builtin": false, "preview": "/api/faces/100/preview" }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 0-6 是内置表情（和固件里的编号一致），自定义从 100 起 |
| `name` | string | 中文名 |
| `builtin` | bool | `true` 的不能删 |
| `preview` | string | 可选，图片 URL 或 data URI。内置表情前端自己用 SVG 画，不需要给。如果是 URL，必须是 `<img>` 能**匿名 GET** 的地址（不能要求 `Authorization` 头），否则自定义表情会裂图 |

**前端行为**：`builtin: true` 且 `id <= 6` 的，前端直接用 `constants/faces.ts` 里的 SVG 画，`preview` 会被忽略。

---

### 3.12 POST `/api/faces`（上传自定义表情）

前端调用点：`api/face.ts → uploadFace(file)`，表情页上传按钮。

**请求**：`multipart/form-data`，字段名 **`file`**（前端 `form.append('file', file)` 写死，改名就收不到）。

**硬约束**：文件必须**正好 512 字节**，128×32 单色位图。前端已经拦了一道（`Faces.vue` 的 `onFile`），但后端必须**再校验一次**并返回中文 message：

- 大小不对 → `code: 40002`，`message: "图片必须正好 512 字节（128×32 单色位图）"`
- 格式不对 → `code: 40002`，`message: "只支持 128×32 单色 BMP"`

**响应 data**：新建的 `FaceItem`，`builtin: false`，`preview` 建议给可访问的 URL：

```json
{ "id": 101, "name": "我的狗", "builtin": false, "preview": "/api/faces/101/preview" }
```

**注意**：`name` 前端会从文件名去掉扩展名推导，后端不用管中文编码。`preview` 如果给相对路径，前端会直接塞进 `<img src>`：同源部署或 Vite 代理下能显示，但**浏览器加载图片不会带 Authorization 头**。所以预览路由必须满足下面任一条：

- 公开可 GET（推荐），例如 `/api/faces/101/preview`，不做登录校验；
- 返回 `data:image/...;base64,...` 形式的 data URI；
- 或者在 URL 里自带短期签名参数。

如果预览路由也要求 Bearer token，`<img>` 会 401，自定义表情显示为空白。别返回 base64 大字符串塞进列表接口。

---

### 3.13 POST `/api/faces/current`

前端调用点：`api/face.ts → setCurrentFace()`，表情页点一下、监控台点表情。

**请求体**

```json
{ "face": 3 }
```

**响应 data**

```json
{ "face": 3 }
```

**说明**：这是切表情的**唯一入口**，不要设计成「走 `/commands/send` 带 action 字段」——前端已经写死了调这个接口。后端收到后发串口 `0x07`（DATA=表情编号），并推一条 WS `state` 事件（`face` 字段变化）。

`face` 必须是已存在的表情 id；不存在返回 `code: 40400`，`message: "表情不存在"`。

---

### 3.14 DELETE `/api/faces/{id}`

前端调用点：`api/face.ts → deleteFace()`。

**响应 data**：前端忽略，给 `{ "ok": true }` 即可。

**失败**：

- 内置表情 → `code: 40002`，`message: "内置表情不能删除"`
- 不存在 → `code: 40400`，`message: "表情不存在"`

---

### 3.15 GET `/api/logs`

前端调用点：`api/log.ts → listLogs()`，日志页（分页 + 双过滤）、看板（`size=200` 拉一次算成功率）。

**Query 参数**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `page` | int | 是 | 从 1 开始 |
| `size` | int | 是 | 日志页可选 10 / 20 / 50，看板固定 **200**，要支持 |
| `status` | string | 否 | `OK` / `TIMEOUT` / `ERROR` / `PENDING`；**前端选「全部」时这个参数直接不发**，所以后端要把它当可选 |
| `device_id` | int | 否 | 不传表示全部设备 |

**响应 data**：`PageResult<CommandLog>`

```json
{
  "items": [
    {
      "id": 1024,
      "device_id": 1,
      "time": "2026-11-08T15:29:41+08:00",
      "action": 51,
      "action_name": "前进",
      "status": "OK",
      "cost_ms": 312,
      "seq": 17,
      "response": "0x81 受理 / 0x02 完成"
    }
  ],
  "total": 57,
  "page": 1,
  "size": 10
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 主键 |
| `device_id` | int | 哪台设备 |
| `time` | string | 下发时间，ISO 带时区 |
| `action` | int | 动作码（十进制） |
| `action_name` | string | **后端存中文名**，前端只是展示；没这个字段日志页第一列会是 `未知动作 0x33` |
| `status` | string | `OK` / `TIMEOUT` / `ERROR` / `PENDING` |
| `cost_ms` | int | 从下发到应答的毫秒数；超时给 3000 左右；`PENDING` 给 0 |
| `seq` | int | 对应串口序号 |
| `response` | string | 原始应答摘要，给人看的，例如 `0x81 受理 / 0x02 完成`、`3 s 内无应答`、`0x05 执行失败` |

**排序**：按 `time` **倒序**（最新在最前）。日志页第一页就是最近的，看板也默认拿最近的 200 条。

**实现要求**：`total` 是过滤后的条数；`size=200` 时也走同一段逻辑，别写死上限 100。

---

### 3.16 GET `/api/telemetry`

前端调用点：`api/telemetry.ts → listTelemetry()`，看板电量曲线。

**响应 data**：`TelemetryPoint[]`，**按时间升序**（最旧 → 最新），建议最近 24 小时每小时 1 条，共 24 条。

```json
[
  { "time": "2026-11-07T16:00:00+08:00", "battery": 84, "voltage": 4.06 },
  { "time": "2026-11-07T17:00:00+08:00", "battery": 82, "voltage": 4.05 }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `time` | string | ISO 带时区，等间隔最好 |
| `battery` | int | 0-100 |
| `voltage` | float | V |

**前端行为**：直接 `points.value = telemetry` 后画折线。**顺序反了曲线就是倒着走的**；点数不足 2 个时前端画出来是空白，谈不上报错，所以库里没数据时最好也返回一条当前值。

---

### 3.17 GET `/api/weather`

前端调用点：`api/weather.ts → getWeather()`，进监控台拉一次；之后 WS `weather` 事件更新。

**响应 data**

```json
{
  "code": 0,
  "text": "晴",
  "temp": 23,
  "updated_at": "2026-11-08T15:30:00+08:00",
  "location": "湘潭 · 雨湖区",
  "source": "Open-Meteo"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `code` | int | 是 | 0-9，见 5.3；不在表内前端按「未知」显示 |
| `text` | string | 是 | 中文描述，前端**也**会根据 code 自己映射文案，这个字段只做兜底 |
| `temp` | int | 是 | 摄氏度，可负（`-3`） |
| `updated_at` | string | 是 | 抓取时间，ISO 带时区 |
| `location` | string | 否 | 展示地点；不返回时前端兜底「湘潭 · 雨湖区」 |
| `source` | string | 否 | 数据源名称，只用于页面 tooltip，不影响渲染 |

**天气源约定（V1.1 明确）**

- 项目展示地点固定为**湖南省湘潭市雨湖区**，坐标 `27.856, 112.903`。
- 推荐 Open-Meteo（免 key、支持 CORS），用 `current=temperature_2m,weather_code`，时区 `Asia/Shanghai`。
- 后端每 **10 分钟**抓一次，成功写缓存；失败或断网返回**上一次缓存**，并保持 `code` 有效，不要返回 500。
- WMO 码 → 项目 0–9 的映射见 5.3，和前端 `constants/weather.ts` 必须一致。
- 后端拿到天气后还要下发串口 `0x09`（天气码 + 有符号温度），屏幕下半部分才会更新。

> 现在 `VITE_USE_MOCK=true` 时，前端 Mock 会直接请求 Open-Meteo 并缓存 10 分钟；这是**开发期兜底**，不是最终架构。`VITE_USE_MOCK=false` 后前端只认 `/api/weather`，所以后端必须实现抓取和缓存，否则时钟卡会退回静态数据。

---

### 3.18 GET `/api/scenes`

前端调用点：`api/scene.ts → listScenes()`。

**响应 data**：`Scene[]`（数组，不翻页）

```json
[
  {
    "id": 1,
    "name": "早上好",
    "description": "起床三连，适合演示开场",
    "steps": [{ "action": 49 }, { "action": 67 }, { "action": 64 }],
    "updated_at": "2026-11-08T15:00:00+08:00"
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 主键 |
| `name` | string | 场景名，1-20 字 |
| `description` | string | 可为空字符串，不要 null（前端直接 `{{ }}` 渲染） |
| `steps` | array | 有序动作列表，每项只有 `action` 一个字段 |
| `updated_at` | string | 最后修改时间 |

**steps 里只有 `action`**，没有延时字段、没有循环次数。**节奏由后端定**（mock 是每步间隔 0.9 秒），前端不关心。别自作主张加 `delay_ms` 让前端去传——前端表单没有这个输入框。

---

### 3.19 POST `/api/scenes`

前端调用点：`api/scene.ts → createScene()`。

**请求体**

```json
{ "name": "巡游", "description": "走两步转个身", "steps": [{ "action": 51 }, { "action": 53 }] }
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 是 | 前端已 trim + 非空校验，后端再校验长度 1-20 |
| `description` | string | 否 | 省略时按 `""` 存 |
| `steps` | array | 是 | 至少 1 步（前端已拦），每项 `{action:int}` |

**响应 data**：完整 `Scene`，**必须带真实 id**（前端拿返回对象去替换草稿，没有 id 后续改不了）。

**失败**：名字空 → `code: 40002`，`message: "场景名不能为空"`。

---

### 3.20 PUT `/api/scenes/{id}`

前端调用点：`api/scene.ts → updateScene()`，场景页保存按钮。

**请求体**：字段全部可选，前端**每次都会把 name/description/steps 全传**（全量覆盖，不是 patch）。

```json
{ "name": "巡游", "description": "", "steps": [{ "action": 51 }] }
```

**响应 data**：更新后的完整 `Scene`（含新 `updated_at`）。

**失败**：`code: 40400`，`message: "场景不存在"`。

**注意**：`steps` 是全量替换——后端要「先删旧步骤再插新的」，别做增量追加，否则改一次场景步骤翻倍。

---

### 3.21 DELETE `/api/scenes/{id}`

前端调用点：`api/scene.ts → deleteScene()`（页面先弹确认框，确认后才调）。

**响应 data**：`{ "ok": true }`。

**失败**：`code: 40400`，`message: "场景不存在"`。

---

### 3.22 POST `/api/scenes/{id}/run`

前端调用点：`api/scene.ts → runScene()`。

**请求体**：无（`POST` 空 body 或 `{}` 都行，前端没传 data）。

**响应 data**

```json
{ "steps": 3 }
```

前端弹一句「开始执行「巡游」，共 3 步」。**这个接口要立刻返回**，不要等整个场景跑完——三步 × 0.9 秒就是 2.7 秒，五步就超时了。后台用 `asyncio.create_task` 逐步下发，每步推 `state` 事件。

**失败**：`code: 40400`，`message: "场景不存在"`。

---

## 4. WebSocket `/ws/device`

前端调用点：`utils/ws.ts → DeviceSocket`，进监控台时连接（`stores/pet.ts → connect()`）。

### 4.1 连接

```
ws://127.0.0.1:8000/ws/device?token=<urlencode(token)>&device_id=1
```

- token 从 query 拿（浏览器的 WebSocket API 不能自定义 header，这不是偷懒，是唯一办法）。
- 鉴权失败：**直接 `close(code=4001)`**。前端会自动重连（1 → 2 → 4 → 8 → 10 秒封顶），用户重新登录后 token 变了自然能连上。
- 前端**不会**给服务端发任何消息。所以后端不能设计成「等客户端 ping」——断线检测靠 TCP 关闭事件。
- 建议服务端每 30 秒至少推一条 `state` 或 `link`，避免中间代理掐掉空闲连接；设备本来就 5 秒一条 `0x03`，正常情况不用额外造。

### 4.2 消息格式

**一条消息一个 JSON 对象，纯文本帧**：

```json
{ "event": "state", "data": { } }
```

前端 `handleMessage` 只处理 `typeof raw === 'string'` 的帧，收到二进制帧、空帧、非 JSON 一律**静默丢弃**。所以别用 MessagePack、别把多条事件拼成一个数组。

### 4.3 五种事件

#### `state` — 设备状态

设备每上报一次 `0x03`，或任何动作/表情/音乐改变后推一次。

```json
{
  "event": "state",
  "data": {
    "battery": 78,
    "voltage": 3.92,
    "action": 51,
    "face": 0,
    "music_state": 0,
    "track": 3,
    "weather_code": 0,
    "temp": 23
  }
}
```

8 个字段，和 3.8 的 `DeviceStatus` 一致，只少了 `device_id`、`volume`、`updated_at`（前端 `applyState` 只读这 8 个）。多给字段不报错，少给会变成 `undefined` → 页面上显示 `NaN`。

#### `ack` — 指令应答

设备回 `0x81`（受理）或错误码时推。**这是三态按钮唯一的成功信号**。

```json
{ "event": "ack", "data": { "seq": 17, "status": "OK", "cost_ms": 312 } }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `seq` | int | 必须和 `POST /api/commands/send` 返回的 `seq` 一致 |
| `status` | string | `OK` 或 `ERROR`（大写）。注意这里**没有** `TIMEOUT`——超时是前端自己判的 |
| `cost_ms` | int | 实际耗时 |

前端按 `seq` 认领（`stores/pet.ts → onAck`），**找不到对应 seq 的 ack 直接丢弃**。设备回 `0x81` 时如果连 `seq` 都没带回来，按钮永远停在黄色。

#### `link` — 链路通断

串口连上/断开时推。

```json
{ "event": "link", "data": { "online": true } }
```

前端用它控制顶部状态条（`online`）+ 是否显示「设备离线」。

#### `music` — 音乐状态

```json
{ "event": "music", "data": { "state": 1, "track": 3, "volume": 15 } }
```

`volume` 可选（前端判了 `typeof === 'number'`）；`state`、`track` 必给。

#### `weather` — 天气变化

```json
{ "event": "weather", "data": { "code": 0, "text": "晴", "temp": 23 } }
```

后端抓到新天气、下发 `0x09` 后推一条。`updated_at` 前端自己补当前时间，不用给。

### 4.4 广播范围

有多台设备时，`device_id` 只影响订阅哪台设备的事件。前端同一时刻只连一个 `device_id`。

---

## 5. 枚举表

### 5.1 动作码（19 个，前端按钮就是这些）

| 码 | 十进制 | 名称 | 分组 |
|---|---|---|---|
| 0x29 | 41 | 放松趴下 | 姿态 |
| 0x30 | 48 | 蹲下 | 姿态 |
| 0x31 | 49 | 站立 | 姿态 |
| 0x32 | 50 | 趴下 | 姿态 |
| 0x33 | 51 | 前进 | 移动 |
| 0x34 | 52 | 后退 | 移动 |
| 0x38 | 56 | 提速 | 移动 |
| 0x41 | 65 | 前跳 | 移动 |
| 0x42 | 66 | 后跳 | 移动 |
| 0x48 | 72 | 伸懒腰 | 移动 |
| 0x49 | 73 | 后腿拉伸 | 移动 |
| 0x35 | 53 | 左转 | 转向 |
| 0x36 | 54 | 右转 | 转向 |
| 0x37 | 55 | 摇摆 | 转向 |
| 0x39 | 57 | 摇摆加速 | 转向 |
| 0x40 | 64 | 摇尾巴 | 转向 |
| 0x43 | 67 | 打招呼 | 互动 |
| 0x44 | 68 | 开灯 | 灯光 |
| 0x45 | 69 | 关灯 | 灯光 |

`0x46` / `0x47`（呼吸灯）**不在**这 19 个里，前端没有按钮，后端别加。

### 5.2 表情编号（内置 7 个）

| id | 名称 |
|---|---|
| 0 | 普通 |
| 1 | 开心 |
| 2 | 困倦 |
| 3 | 生气 |
| 4 | 惊讶 |
| 5 | 伤心 |
| 6 | 卖萌 |

自定义表情 id 从 **100** 起（避开固件编号），`builtin: false`。

### 5.3 天气码（10 个）

| code | 文案 | code | 文案 |
|---|---|---|---|
| 0 | 晴 | 5 | 大雨 |
| 1 | 多云 | 6 | 雷阵雨 |
| 2 | 阴 | 7 | 雪 |
| 3 | 小雨 | 8 | 雾 |
| 4 | 中雨 | 9 | 未知 |

前端按 code 选 SVG 图标（`constants/weather.ts`），所以**只认 code**，文本可以不看。

### 5.4 音乐子命令

| 值 | 含义 | 说明 |
|---|---|---|
| 0 | 停止 | |
| 1 | 播放 | |
| 2 | 暂停 | |
| 3 | 下一首 | |
| 4 | 上一首 | |
| 5 | 设音量 | `value` 生效，0-30 |

**曲目从哪来**：音频不经过网页和后端，存在 DFPlayer 的 TF 卡里，按 `mp3/0001.mp3`、`0002.mp3` 顺序编号；网页的「上一首 / 下一首」只是让固件切相邻曲目。

**当前没有「播放指定曲目」命令**。如果以后要做网页选曲，需要三边一起加，例如 `command: 6, value: 曲目号`，并同步更新本文件、`openapi.yaml`、前端 `MusicRequest` 枚举和固件 0x0A 分支；不要只改前端。

### 5.5 日志状态

`OK` / `TIMEOUT` / `ERROR` / `PENDING`，四个值固定大写。前端用它们上色（绿 / 黄 / 红 / 灰），多一个值就没颜色。

---

## 6. REST ↔ 串口 对照

给后端实现时对一下账号，**串口帧细节以后端计划第 6 章为准**，这里只说明「哪个接口对应哪一帧」：

| REST / WS | 串口帧 | 方向 |
|---|---|---|
| `POST /api/commands/send` | `0x01`（DATA 含动作码 + seq） | 下发 |
| WS `ack` ← | `0x81` 受理 / `0x05` 等错误码 | 上报 |
| `POST /api/faces/current` | `0x07`（DATA 表情编号） | 下发 |
| `POST /api/devices/{id}/music` | `0x0A`（子命令 + 参数） | 下发 |
| `GET /api/devices/{id}/status` | 读缓存，来源是 `0x03` | — |
| WS `state` ← | `0x03`（六字节状态） | 上报 |
| WS `music` ← | `0x0B` | 上报 |
| WS `link` ← | `0x04` 心跳超时 / 串口断开 | 上报 |
| WS `weather` ← | 后端抓天气后下发 `0x09` | 下发 |
| 校时（无 HTTP） | `0x08`，后端每分钟一次 | 下发 |
| `GET /api/telemetry` | 从 `0x03` 落库聚合 | — |

---

## 7. 错误码

| code | HTTP | 含义 | 前端表现 |
|---|---|---|---|
| 0 | 200 | 成功 | 正常渲染 |
| 40000 | 200 | 参数缺失/类型错 | 弹 message |
| 40001 | 200 | 用户名或密码错误 | 登录页弹 message |
| 40002 | 200 | 业务校验失败（注册字段不合规、图片大小、场景名空、内置表情不可删…） | 弹 message |
| 40100 | 401 | 没带 token | 跳登录页 |
| 40101 | 401 | token 过期/无效 | 跳登录页 + 弹「登录已过期」 |
| 40300 | 403 | 无权限（预留，前端暂未用） | 弹「请求失败（HTTP 403）」 |
| 40400 | 200 | 资源不存在（设备/表情/场景） | 弹 message |
| 40900 | 200 | 冲突（注册用户名已存在等） | 弹 message |
| 50000 | 200 | 服务内部错误 | 弹 message |

`message` 是给用户看的中文，一句话，别带 `Exception`、别带堆栈、别带英文。

**40900 的用法**：注册时用户名已存在统一用它，`message: "用户名已存在"`；不要新造 `40009` 之类的数字，前端只认 `message`，但错误码表要保持可查。

---

## 8. 两条最容易翻车的时序要求

这两条不是风格问题，不照做联调会出「按钮永远变红」「日志永远为空」这种查半天的问题。

### 8.1 ack 必须晚于 HTTP 响应

前端 `stores/pet.ts` 的顺序是：

```ts
const { seq } = await sendCommand(code)   // ① 先拿到 seq
pending[seq] = { action, timer }           // ② 才登记
```

`onAck` 里第一句是 `const item = pending[seq]; if (!item) return`。

也就是说：**如果后端在 HTTP 响应之前（或同一瞬间）就把 ack 推到 WebSocket，前端还没登记这个 seq，ack 会被当成「迟到的」丢掉**，按钮 3 秒后标红，但设备其实动了——这是最难查的一类 bug。

做法：`commands/send` 先把 `seq` 返回，**再**下发串口帧；或者至少在 `await asyncio.sleep(0.05)` 之后才允许推 ack。0.05 秒足够。

### 8.2 `commands/send` 不能等设备应答

`send` 里 `await` 到设备 ack 才返回，等于把前端的 3 秒计时器吃掉大半。串口还可能因为设备没上电一直不返回，直接把 axios 的 10 秒超时踩爆，前端弹「网络异常」。

正确顺序：

1. 生成 `seq`，写一条 `PENDING` 日志
2. **立即返回** `{seq, action, accepted: true}`
3. 后台任务下发串口帧、等应答、更新日志为 `OK`/`TIMEOUT`/`ERROR`、推 WS `ack` + `state`

---

## 9. 前端联调步骤与自查表

### 9.1 三步切到真后端

1. 后端起在 8000：`cd backend && python run.py`
2. 改 `frontend/.env.development`：

```diff
- VITE_USE_MOCK=true
+ VITE_USE_MOCK=false
```

3. `cd frontend && pnpm dev`，打开 `http://localhost:5173`

> 这台机器上 Vite 默认绑 **localhost（IPv6 ::1）**，用 `127.0.0.1:5173` 可能直接连不上。要固定用 127，需要在 `vite.config.ts` 的 `server` 里显式设置 `host: '127.0.0.1'`；联调文档和 README 统一写 `localhost`。

> `VITE_USE_MOCK=true` 时前端**根本不会发请求**（mock 在 axios 之前就拦掉了），页面上一切正常会让人误以为联调通了。联调开始第一件事就是关掉它。

### 9.2 逐页自查（照着打勾）

| # | 操作 | 期望 | 不通时先查 |
|---|---|---|---|
| 1 | 打开 `/` | 跳 `/login` | 路由守卫 |
| 2 | `admin/123456` 登录 | 进设备页，列出设备 | `/api/auth/login`、CORS（走了代理就不会有） |
| 3 | 注册 `tester01 / secret123` | 提示成功、回登录页；用新账号能登录 | `/api/auth/register`、40900 重名、密码哈希 |
| 4 | 设备页 | 卡片显示在线/固件/电量，名字后有 Q 版挂件 | `/api/devices` 里的 `online`、`battery` |
| 5 | 点名字后的铅笔改名 | 名字立即更新，刷新后仍是新名字 | `PATCH /api/devices/1`、返回完整 Device |
| 6 | 进监控台 | 状态区有电量/动作/表情 | `/api/devices/1/status`、WS 是否连上（查 Network → WS） |
| 7 | 看时钟卡天气 | 地点「湘潭 · 雨湖区」，温度/文字和 Open-Meteo 当前值一致 | `/api/weather`、后端是否抓取并缓存、WS `weather` |
| 8 | 点「前进」 | 按钮黄 → 绿（≤3 秒） | 见 8.1 / 8.2 |
| 9 | 连点 5 个不同动作 | 5 个都变绿，不串号 | `seq` 是否 1-250 循环且不撞 |
| 10 | 音乐面板点播放 | 状态变「播放中」，音量条能动 | WS `music` 事件是否推、DFPlayer 是否有 TF 卡 |
| 11 | 表情页点「生气」 | 设备屏幕换脸，页面高亮 | `/api/faces/current` + WS `state.face` |
| 12 | 表情页上传 512 字节图 | 列表多一张，可删 | multipart 字段名必须是 `file`、`preview` 是否匿名可 GET |
| 13 | 日志页 | 刚才点的动作都在，状态/耗时对得上 | `/api/logs` 排序倒序、`action_name` 中文 |
| 14 | 日志页切过滤 | 列表变化，`total` 跟着变 | `status` 不传时按全部处理 |
| 15 | 看板 | 电量曲线 24 点、成功率不空 | `/api/telemetry` 升序、`/api/logs?size=200` |
| 16 | 场景页执行「巡游」 | 设备逐步动，页面提示步数 | `/api/scenes/1/run` 必须立刻返回 |
| 17 | 停后端 | 顶部黄条，弹「网络异常」 | WS 关闭事件 |
| 18 | 起回后端 | 5 秒内恢复，无需刷新 | 退避重连（1/2/4/8/10s） |
| 19 | 手改 `localStorage.petdog_token` 后刷新 | 跳登录页 | 后端 401 语义（见 1.3） |

### 9.3 前端这边要记得改的两处

联调时如果后端 seed 的账号不是 `admin/123456`，改测试输入即可，不用改代码；但 `.env.development` 的 `VITE_USE_MOCK` **一定要改成 false**，别提交上去。

---

## 10. 后端可自定、不影响前端的部分

以下这些前端完全不感知，后端按自己方便来，不用来回确认：

| 项 | 说明 |
|---|---|
| token 具体实现 | JWT 的算法、密钥、有效期（建议 ≥12h）、`sub` 放什么 |
| 数据落库 | SQLite 表结构、是否加索引、日志保留多久 |
| 用户密码存储 | bcrypt / passlib 都行，只要注册能登录；`username` 必须唯一 |
| 设备名字存储 | 存在 `devices.name`，`PATCH` 改完返回完整 Device；是否同步到屏幕由固件决定 |
| 表情文件存哪 | 磁盘路径、文件名规则；`preview` 必须能被 `<img>` 匿名 GET，或直接返回 data URI |
| 场景执行节奏 | 每步间隔多少毫秒（mock 是 900ms），是否需要步间延时字段 |
| 天气数据源 | 默认 Open-Meteo（湘潭雨湖区 27.856/112.903），缓存 10 分钟；换源可以，但字段必须保持 §3.17，且要下发 0x09 到屏幕 |
| seed 数据 | 初始设备名、场景示例，只要**保证 id=1 的设备存在** |
| 在线判定阈值 | 建议 30 秒（看板文案写的就是 30s） |

---

## 11. 附录：对象字段定义

供快速对照，字段顺序和 `frontend/src/types/index.ts` 一致。

### Device

```
id: int                主键
name: string           中文名（可用 PATCH /api/devices/{id} 修改）
online: bool           心跳 < 30s
firmware: string       固件版本
last_heartbeat: string ISO 时间
battery: int           0-100
location?: string      可选
```

### DeviceStatus

```
device_id: int         battery: int        voltage: float
action: int            face: int           music_state: int
track: int             volume: int         weather_code: int
temp: int              updated_at: string
```

### CommandLog

```
id: int                device_id: int      time: string
action: int            action_name: string status: OK|TIMEOUT|ERROR|PENDING
cost_ms: int           seq: int            response: string
```

### PageResult<T>

```
items: T[]             total: int          page: int          size: int
```

### Scene / SceneStep

```
Scene:      id: int    name: string       description: string
            steps: SceneStep[]            updated_at: string
SceneStep:  action: int
```

### FaceItem

```
id: int                name: string       builtin: bool      preview?: string
```

`preview` 若是 URL，必须能被 `<img>` 匿名 GET（不带 Authorization），否则自定义表情裂图。

### WeatherInfo

```
code: int              text: string       temp: int          updated_at: string
location?: string      source?: string
```

`location` / `source` 是 V1.1 新增的可选展示字段，不返回时前端兜底「湘潭 · 雨湖区」。

### LoginResult / User / RegisterResult

```
LoginResult:    token: string   user: User
User:           username: string  name: string  role: string
RegisterResult: username: string  name: string
```

### DeviceRename

```
name: string           1-20 个字符，PATCH /api/devices/{id} 的请求体
```

### WsEvent

```
{ event: 'state',   data: StateData }    // battery, voltage, action, face,
                                         // music_state, track, weather_code, temp
{ event: 'ack',     data: { seq, status: 'OK'|'ERROR', cost_ms } }
{ event: 'link',    data: { online: bool } }
{ event: 'music',   data: { state: int, track: int, volume?: int } }
{ event: 'weather', data: { code: int, text: string, temp: int } }
```

---

## 变更记录

| 版本 | 日期 | 改动 |
|---|---|---|
| V1.0 | 2026-11-08 | 首次冻结。前端代码已按此实现，共 20 个 HTTP + 1 条 WS；补上文档里此前没定死的 8 条（场景增删改、表情删除与切换、天气），并明确 `/commands/send` 的时序、`/faces/current` 是切表情唯一入口 |
| V1.1 | 2026-11-08 | 前端新增登录页注册、设备页改名 + Q 版挂件后同步契约：新增 `POST /api/auth/register`、`PATCH /api/devices/{id}`，共 22 个 HTTP + 1 条 WS；`WeatherInfo` 增加可选 `location` / `source` 并明确湘潭雨湖区 Open-Meteo 缓存策略；明确 `preview` 必须匿名可 GET；新增 §2.1「页面已实现、后端待落地」清单；修正联调地址为 `localhost` |

改动流程：先改本文件 + `openapi.yaml`，群里说一声，再各自改代码。
