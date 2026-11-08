# Pet-dog 前端 · 桌宠网页控制台

STM32 智能桌面宠物项目的 Vue 3 控制台。七个页面：登录、设备列表、控制台、指令日志、数据看板、表情库、场景编排。

## 技术栈

Vue 3.5 · Vite 8 · TypeScript 6 · Element Plus 2 · Pinia 3 · Vue Router 4 · Axios · ECharts 5 · Sass

依赖版本刻意锁在计划文档用的那几个大版本（router 4 / pinia 3 / echarts 5），没有跟最新的 router 5、pinia 4。`pnpm add` 默认会装新的，别顺手升级。

## 快速开始

```powershell
cd D:\TY\Pet-dog\frontend
pnpm install
pnpm dev
```

浏览器打开 <http://localhost:5173>。Vite 默认只绑 IPv6 的 localhost，用 `127.0.0.1:5173` 可能连不上，别以为是服务没起。

演示账号：`admin` / `123456`（Mock 模式下有效，登录页有一键填入）。

## 视觉

整套界面是一版「暖白纸 + 细网格」的编辑感设计，不再是 Element Plus 默认蓝：

- 底色 `#efece6`，卡片 `#f7f4ee`，全部用 1px 发丝线分隔，不用阴影堆层次
- 背景三条竖向参考线固定在 17% / 50% / 83%，窄屏自动隐藏
- 小标签全部 IBM Plex Mono、大写、加字距；数字（时钟、电量、seq、曲目号）也用等宽字体
- 渐变只出现在三处：logo 的 C 形环、导航当前项的 1px 下划线、按钮/卡片的悬停边线
- 登录页的机器狗和所有表情都是内联 SVG，没有图片资源；3D 机器人没有搬过来，太重了
- 字体落在 `src/assets/fonts/`，离线演示不会掉字

色板、间距、Element Plus 的覆写都在 [src/styles/index.scss](src/styles/index.scss)，改主题只动这一个文件；七个页面的布局变量集中在各页 `<style scoped>` 里。

## Mock 模式

后端还没起来，所以 `.env.development` 里默认：

```
VITE_USE_MOCK=true
```

打开时，`src/utils/request.ts` 先问 `src/mock/index.ts` 要数据，不会发真实请求；WebSocket 也换成一个会推 `state` / `ack` 的假连接。19 个按钮、表情、音乐、日志、看板、场景全部能点、能看。

登录页可以注册新账号，注册信息存在浏览器 localStorage 的 `petdog_mock_users` 里，清缓存会一起清掉；内置账号 `admin / 123456` 不受影响。

Mock 的天气会直接请求 Open-Meteo（坐标固定在湘潭雨湖区 27.856 / 112.903），结果缓存 10 分钟；断网、超时或接口不可用时退回静态数据。改过的桌宠名字存在 `petdog_mock_device_names`，刷新页面不会丢。这两处都只是 Mock 的临时方案，正式环境应由后端抓天气、存设备名。

后端 `/api/health` 跑起来之后，把 `.env.development` 改成 `VITE_USE_MOCK=false`，请求就真的走 Vite 代理到 `127.0.0.1:8000`：

| 前端请求 | 转发到 |
|---|---|
| `/api/**` | `http://127.0.0.1:8000/api/**` |
| `/ws/device` | `ws://127.0.0.1:8000/ws/device` |

生产环境（`.env.production`）固定 `VITE_USE_MOCK=false`，接口前缀就是 `/api`，同源，由后端托管 `dist`。

## 脚本

| 命令 | 干什么 |
|---|---|
| `pnpm dev` | 本地开发，5173 |
| `pnpm build` | `vue-tsc` 类型检查 + 打包到 `dist/` |
| `pnpm preview` | 预览打包结果 |
| `pnpm test` | Vitest + jsdom 页面冒烟测试（9 条） |

`pnpm build` 会先跑类型检查，类型不过不会出包。大 chunk 警告来自 Element Plus 全量引入和 ECharts，课程项目先接受，等功能全通再按需引入。

## 目录

```
frontend/
├── .env.development        # VITE_USE_MOCK=true
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
- 设备列表：在线绿点、固件版本、电量、最近心跳，点进去切当前设备；名字后面挂一只 Q 版电子桌宠挂件，可点铅笔改名
- 控制台：19 个动作码按 5 组铺开，**三态按钮**（黄已发 / 绿成功 / 红超时）；`seq → pending` 对 ack，3 秒超时清 pending 并提示；7 张表情切换
- 实时状态条：电量、电压、当前动作、表情、音乐、WS 连接状态；断线顶部黄条
- WebSocket：1 → 2 → 4 → 8 → 10 秒退避重连，同一时间只留一个重连定时器
- 时钟天气卡：每秒走时，天气码 → SVG 图标；显示湘潭雨湖区实时温度，10 分钟更新一次
- 音乐面板：播放 / 暂停 / 停止 / 上下首 / 音量 0~30，`change` 才发请求
- 日志页：设备、状态筛选 + 分页表格，显示动作码、seq、耗时、应答结果
- 看板：电量折线、成功率环形、动作分布柱状三张 ECharts 图 + 四个统计卡
- 表情库：7 张内置 + 上传（先校验正好 512 字节）+ 删除自定义
- 场景：新建弹窗、步骤增删、上下移动、保存、保存并执行
- 空状态、loading、错误提示统一：空状态是自绘的「小屏幕 + 两点眼睛」，接口失败统一 `el-message`

## 接口约定（前端实际用的）

后端路径以 `docs/contracts/openapi.yaml` 与 `docs/contracts/http-api.md` 为准，后端的 `/docs` 是运行时权威。这里记的是前端已经写死、改起来要一起改的地方：

```
POST /api/auth/login            { username, password } → { token, user }
POST /api/auth/register         { username, password } → { username, name }   # 契约 §3.3
GET  /api/auth/me
GET  /api/devices
GET  /api/devices/{id}
PATCH /api/devices/{id}         { name }    # 契约 §3.7，改名
GET  /api/devices/{id}/status
POST /api/devices/{id}/music    { command, value }
POST /api/commands/send         { action }  → { cmd_id, seq, action, accepted, status, transport }
GET  /api/commands/{id}                     # 断线对账用，记录不存在返回 code 40400
POST /api/events/ticket         { device_id } → { ticket, expires_in_sec }
GET  /api/faces
POST /api/faces                 上传，multipart 字段名 file
POST /api/faces/current         { face }
DELETE /api/faces/{id}
GET  /api/logs?page&size&status&device_id   → { items, total, page, size }
GET  /api/telemetry
GET  /api/weather               → { code, text, temp, updated_at, location?, source? }
GET  /api/scenes
POST /api/scenes
PUT  /api/scenes/{id}
DELETE /api/scenes/{id}
POST /api/scenes/{id}/run
WS   /ws/device?device_id=1&ticket=<一次性票据>
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
- 三态按钮的 `pending` 没有把按钮锁死：点第二次会重发并换一个新 `cmd_id`，旧回执按 `cmd_id` 找不到 pending 就丢掉。这样「同一动作连点两次不串号」能自测。
- 按钮 3 秒变红是纯展示（`DISPLAY_TIMEOUT_MS`），不写任何命令状态；真正的终态只由后端 `command_log` 判定。
- 图标用 Element Plus 图标 + 内联 SVG（脸、天气、机器狗、logo），没有额外图片资源。
- 视觉是后改的一版：暖白纸底、细网格、等宽小标签、发丝线卡片。没引 three.js，机器狗是手画的 SVG 线稿。
- 加了一套 jsdom 冒烟测试，`pnpm test` 能跑；计划文档里没有这一项，但它能挡住「改一处白屏」这类低级事故。

## 打包交付

```powershell
pnpm build
```

产物在 `frontend/dist/`，整个目录丢给后端挂静态目录即可。注意 SPA 要配 history fallback，刷新 `/console` 不能 404。
