# Pet-dog 前端 · 桌宠网页控制台

STM32 智能桌面宠物项目的 Vue 3 控制台。七个页面：登录、设备列表、控制台、指令日志、数据看板、表情库、场景编排。

## 技术栈

Vue 3.5 · Vite 8 · TypeScript 6 · Element Plus 2 · Pinia 3 · Vue Router 4 · Axios · ECharts 5 · Sass

依赖版本刻意锁在计划文档用的那几个大版本（router 4 / pinia 3 / echarts 5），没有跟最新的 router 5、pinia 4。`pnpm add` 默认会装新的，别顺手升级。

## 快速开始

```powershell
cd frontend
pnpm install
pnpm dev
```

打开 Vite 启动日志给出的本机地址。

演示账号：`admin` / `admin123`（仅 Mock 模式下有效，登录页有一键填入）。

## 视觉

整套界面是一版「暖白纸 + 细网格」的编辑感设计，不再是 Element Plus 默认蓝：

- 底色 `#efece6`，卡片 `#f7f4ee`，全部用 1px 发丝线分隔，不用阴影堆层次
- 背景三条竖向参考线固定在 17% / 50% / 83%，窄屏自动隐藏
- 小标签全部 IBM Plex Mono、大写、加字距；数字（时钟、电量、seq、曲目号）也用等宽字体
- 渐变只出现在三处：logo 的 C 形环、导航当前项的 1px 下划线、按钮/卡片的悬停边线
- 登录页的机器狗和所有表情都是内联 SVG，没有图片资源；3D 机器人没有搬过来，太重了
- 字体落在 `src/assets/fonts/`，离线演示不会掉字

色板、间距、Element Plus 的覆写都在 [src/styles/index.scss](src/styles/index.scss)，改主题只动这一个文件；七个页面的布局变量集中在各页 `<style scoped>` 里。

## 数据源

开发默认 VITE_USE_MOCK=false，由 Vite 转发到真实后端。无板联调用仓库根 README 中的 run_sim.py，使用它生成的本机账号。只验证页面时可在本机 .env.local 中设 VITE_USE_MOCK=true 并重启 Vite；Mock 不验证 HTTP、串口或设备确认。日志、看板、场景和音乐本期不开放。


| 前端请求 | 转发到 |
|---|---|
| `/api/**` | `http://127.0.0.1:8000/api/**` |
| `/ws/device` | `ws://127.0.0.1:8000/ws/device` |

生产环境关闭 Mock。由同源反向代理提供 dist、SPA history fallback，并把 /api 与 /ws 转发到后端；FastAPI 本身不托管前端 dist。

## 脚本

| 命令 | 干什么 |
|---|---|
| `pnpm dev` | 本地开发，5173 |
| `pnpm build` | `vue-tsc` 类型检查 + 打包到 `dist/` |
| `pnpm preview` | 预览打包结果 |
| `pnpm test` | Vitest + jsdom 页面与状态同步测试（13 条） |

`pnpm build` 会先跑类型检查，类型不过不会出包。大 chunk 警告来自 Element Plus 全量引入和 ECharts，课程项目先接受，等功能全通再按需引入。

## 目录

```
frontend/
├── .env.development        # VITE_USE_MOCK=false
├── vite.config.ts          # @ 别名、/api 与 /ws 代理
├── vitest.config.ts        # jsdom 环境
└── src/
    ├── api/                # 一个接口一个文件
    ├── components/         # ActionButton / BrandMark / RobotDog / PetCharm / EmptyState / FaceTile / WeatherIcon / StateBar / ClockCard / MusicPanel
    ├── constants/          # 19 个动作码、10 个天气码、7 张表情定义
    ├── layouts/AppLayout.vue
    ├── mock/               # 假后端 + 共享运行时状态
    ├── router/index.ts     # 6 条子路由 + 登录守卫
    ├── stores/             # auth / device / pet
    ├── types/index.ts
    ├── utils/              # request / ws / format / session / errors
    └── views/              # 七个页面
```

## 已经做完的

- 登录：表单校验、token 落 localStorage、退出登录；401 统一清登录态跳登录页
- 注册：登录框内切换「登录 / 注册」，校验用户名 3–20 位、密码至少 6 位、两次一致；注册成功回登录页
- 机器狗：默认歪头、眨眼、慢摇尾巴；鼠标悬停摇尾，点一下会左右晃，登录成功会左右摇摆 + 快速摇尾再跳转
- 路由：未登录访问内页弹回 `/login`，登录后回跳原地址；页面标题跟着路由走
- 设备列表：在线状态、固件版本、电量、最近心跳，点进去切当前设备；无绑定设备时支持低功耗蓝牙（ECB02H2）扫描与一键直连绑定（取消 6 位配对码），支持改名与解绑
- 控制台：19 个动作码按 5 组铺开，按设备能力 `supported_actions`、`online`、`control_state=ready` 启用本期 7 个核心动作；只有收到后端 `done` 才亮绿灯 1.5 秒，未完成/结果不明不自动重发；7 张内置表情切换
- 实时状态条：电量、电压、当前动作、表情、WS 连接状态；断线顶部黄条；每次重连重新拉取 `/status` 快照并按 `session_id`/`state_revision` 重放与按 `cmd_id` 对账
- WebSocket：1 → 2 → 4 → 8 → 10 秒退避重连，同一时间只留一个重连定时器；按关闭码分支（4401 统一登出、1008 清设备保留登录、4003 换票、4009 停自动重试）
- 历史扩展页（日志、看板、场景、天气、音乐、表情上传）：保留源码但本期已关闭路由与导航入口
- 空状态、loading、错误提示统一：空状态是自绘的「小屏幕 + 两点眼睛」，接口失败统一 `el-message`

## 接口约定（前端实际用的）

后端路径以 `docs/contracts/openapi.yaml` 与 `docs/contracts/http-api.md` 为准，后端的 `/docs` 是运行时权威。这里记的是前端已经写死、改起来要一起改的地方：

```
POST   /api/auth/login            { username, password } → { token, user }
POST   /api/auth/register         { username, password } → User
GET    /api/auth/me
POST   /api/auth/logout
PUT    /api/auth/password         { old_password, new_password }
DELETE /api/auth/account          { password, confirm_username }
GET    /api/setup/status
GET    /api/devices
GET    /api/devices/ble/scan      → BleDevice[]（扫描附近低功耗蓝牙 ECB02H2）
POST   /api/devices/ble/connect   { address, name? } → Device（直连并绑定，无配对码）
GET    /api/devices/{id}
PATCH  /api/devices/{id}          { name }
GET    /api/devices/{id}/status
DELETE /api/devices/{id}/binding  { confirm_device_id }
POST   /api/commands/send         Header Idempotency-Key; { device_id, action } → CommandReceipt
GET    /api/commands/{id}         # 断线对账用，记录不存在返回 code 40400
POST   /api/events/ticket         { device_id } → { ticket, expires_in_sec }
GET    /api/faces
POST   /api/faces/current         { device_id, face }
WS     /ws/device?device_id=1&ticket=<一次性票据>
```

返回体统一 `{ code, message, data, timestamp }`，`code === 0` 才取 `data`，其余抛错并弹提示。前端只在 `request.ts` 里拆一次壳，页面里不出现 `.data.data`。

WebSocket 事件五种：

```json
{ "event": "state",   "data": { "battery": 78, "voltage": 3.92, "action": 51, "face": 0, "music_state": 0, "track": 3, "weather_code": 0, "temp": 23 } }
{ "event": "ack",     "data": { "cmd_id": "6f1f…", "seq": 12, "status": "OK", "cost_ms": 860 } }
{ "event": "link",    "data": { "online": true } }
{ "event": "music",   "data": { "state": 1, "track": 3, "volume": 15 } }
{ "event": "weather", "data": { "code": 0, "text": "晴", "temp": 23 } }
```

## 和计划文档不完全一样的地方

- Node 24 / pnpm 11 建出来的工程，TS 是 6.0、Vite 是 8。`baseUrl` 在 TS 6 里废弃了，路径别名只用 `paths`。
- Element Plus 全量引入，没配 `unplugin-auto-import`，按计划文档第 2.2 节的建议来。
- 按钮未完成超时（`DISPLAY_TIMEOUT_MS`）只显示“结果不明”，不直接判失败、不删除可能已写出的待对账命令；真正的终态只由后端 `command_log` 判定。
- 图标用 Element Plus 图标 + 内联 SVG（脸、天气、机器狗、logo），没有额外图片资源。
- 视觉是后改的一版：暖白纸底、细网格、等宽小标签、发丝线卡片。没引 three.js，机器狗是手画的 SVG 线稿。
- 加了一套 jsdom 冒烟测试，`pnpm test` 能跑；计划文档里没有这一项，但它能挡住「改一处白屏」这类低级事故。

## 打包交付

```powershell
pnpm build
```

产物位于 frontend/dist/；部署时使用上述同源代理配置。
