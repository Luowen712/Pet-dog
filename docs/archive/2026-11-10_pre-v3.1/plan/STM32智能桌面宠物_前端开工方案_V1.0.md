# STM32 智能桌面宠物 · 前端开工方案

> **历史开工记录，2026-11-10标注。** 范围、任务和验收已由[统一计划V3](项目统一实施与交付计划_V3.0.md)及其追踪表接替。原正文保留作追溯；其中空目录、工具版本和模拟器描述是当时记录，不代表当前状态。禁止在已有工程上重复执行初始化或未经核对照抄示例。

功能汇总表和前端线计划已经把「做什么」写完了。这份文档只解决一件事：**空目录怎么变成能跑的工程，以及第一周每一天新建哪个文件**。

| 项目 | 内容 |
|---|---|
| 文档编号 | PET-FE-START-V1.0 |
| 适用对象 | 前端线 1 人 |
| 配套文档 | 《前端线开发计划 V2.0》（下称"计划文档"） |
| 版本 / 日期 | V1.0 ｜ 2026-11-03 |
| 和计划文档的关系 | 计划文档定"做什么、什么时候做"；本文档定"第一个文件建在哪、按什么顺序建" |

---

## 第 1 章  开工具备的条件

开工前先确认下面六项，缺哪项先补哪项。

| 项 | 状态 | 说明 |
|---|---|---|
| 仓库 | ✅ | `D:\TY\Pet-dog`，远端 `Luowen712/Pet-dog` |
| 分支 | ✅ | `feature/frontend-ui`，与 main / dev 同一个 commit，工作区干净 |
| `frontend/` 目录 | ⚠️ 空 | 只有一个 `.gitkeep`，没有任何代码 |
| 计划文档 | ✅ | 7 个页面、19 个动作码、5 类 WS 事件都定死了 |
| 本机环境 | ✅ | node 24.16、pnpm 11.24、git 2.54 |
| 假硬件 | ✅ | `backend/tools/fake_stm32.py`，27810 端口冒充 STM32 |

结论：不缺口径，不缺环境，缺一个能跑的工程骨架。

---

## 第 2 章  第一步：把空目录变成工程

整个动作四十分钟，一个晚上做完，做完就能看到页面。

### 2.1  四条命令

```powershell
cd D:\TY\Pet-dog\frontend
pnpm create vite . --template vue-ts
pnpm install
pnpm add vue-router pinia element-plus @element-plus/icons-vue axios echarts
pnpm add -D sass @types/node
pnpm dev
```

浏览器打开 `http://localhost:5173` 看到 Vite 默认页，这一步就算过。

### 2.2  三个坑，先说清楚

**坑一：`Current directory is not empty`**

`frontend/` 里有 `.gitkeep`，Vite 建工程时会拦住你。选 `Ignore files and continue`，不要选 `Remove existing files`。

**坑二：装到的版本比计划文档新一个大版本**

现在 `pnpm add` 拿到的是 vue-router 5、pinia 4、echarts 6、vite 8、TypeScript 7。计划文档写作时这些还是上一代。

处理办法：先跑通 `pnpm dev` 再写业务代码。如果 vue-router 5 的路由守卫行为跟教程对不上，退回一版：

```powershell
pnpm add vue-router@4
```

**坑三：不要一上来就配 Element Plus 的按需引入**

`unplugin-auto-import` 加 `unplugin-vue-components` 这套配置，第一次配的人平均要花一晚上排「组件不生效、样式不出现」。你一个人 8 周做 7 个页面，全量引入一行就够：

```ts
// src/main.ts
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
app.use(ElementPlus)
```

体积大一点无所谓，这是课程项目不是产品。等功能全跑通、W8 有余力再回头优化。

### 2.3  跑起来之后顺手做的三件事

1. 删掉 `frontend/.gitkeep`（目录里已经有真文件了）
2. 清掉 `src/components/HelloWorld.vue` 和 `src/style.css` 里的默认样式
3. 建 `.env.development`，内容 `VITE_API_BASE=/api`

---

## 第 3 章  依赖清单

只装这些，不要再加。

| 包 | 干什么 | 什么时候装 |
|---|---|---|
| `vue` / `vite` / `typescript` | 底子，scaffold 自带 | W1 |
| `element-plus` + `@element-plus/icons-vue` | 表单、表格、按钮、消息提示 | W1 |
| `vue-router` | 7 个页面的路由和守卫 | W1 |
| `pinia` | 三个 store：auth、device、pet | W1 |
| `axios` | 请求封装 | W2 |
| `echarts` | 看板三张图 | W1 一起装，W6 才用 |
| `sass` | 计划文档 3.4 的样式写法要用 | W1 |
| `@types/node` | `vite.config.ts` 里配路径别名要它 | W1 |

不需要装：日期库（Element Plus 够用）、状态管理之外的轮子（三态按钮用不着）、图表之外的 UI 库。

---

## 第 4 章  目录结构

`[W1]` 表示那一周建。这个结构是从计划文档 7.2 展开的，只多了文件级的说明。

```
frontend/
├── .env.development            [W1]  VITE_API_BASE=/api
├── vite.config.ts              [W1]  proxy + @ 别名
├── src/
│   ├── main.ts                 [W1]
│   ├── App.vue                 [W1]
│   ├── router/index.ts         [W2]  路由表 + beforeEach 守卫
│   ├── utils/
│   │   ├── request.ts          [W2]  axios 实例 + 拆壳 + 401 拦截
│   │   ├── ws.ts               [W3]  WebSocket 封装 + 退避重连
│   │   └── format.ts           [W2]  时间、耗时格式化
│   ├── api/
│   │   ├── auth.ts             [W2]
│   │   ├── device.ts           [W2]
│   │   ├── command.ts          [W3]
│   │   ├── music.ts            [W5]
│   │   ├── weather.ts          [W5]
│   │   ├── log.ts              [W6]
│   │   ├── telemetry.ts        [W6]
│   │   ├── face.ts             [W7]
│   │   └── scene.ts            [W7]
│   ├── stores/
│   │   ├── auth.ts             [W2]  token、user、login / logout
│   │   ├── device.ts           [W2]  设备列表、当前设备
│   │   └── pet.ts              [W3]  battery / action / face / music + pending 表
│   ├── constants/
│   │   ├── actions.ts          [W3]  19 个动作码，照计划文档 7.5 抄
│   │   └── weather.ts          [W5]  10 个天气码映射到图标
│   ├── types/index.ts          [W2]  统一返回体、Device、Ack 等
│   ├── components/
│   │   ├── ActionButton.vue    [W3]  三态按钮，核心组件
│   │   ├── StateBar.vue        [W3]  实时状态条
│   │   ├── ClockCard.vue       [W5]
│   │   └── MusicPanel.vue      [W5]
│   └── views/
│       ├── Login.vue           [W1]
│       ├── DeviceList.vue      [W2]
│       ├── Console.vue         [W3]
│       ├── Logs.vue            [W6]
│       ├── Dashboard.vue       [W6]
│       ├── Faces.vue           [W7]
│       └── Scenes.vue          [W7]
```

---

## 第 5 章  开工顺序，以及为什么不能先写页面

计划文档排的顺序是：请求封装 → store → 路由 → 页面。这个顺序是对的，理由补在下面，这样你自己能判断哪一步可以跳过、哪一步不能。

```
request.ts ──► stores ──► views ──► components
    │             │          │
    │             │          └─ 只管渲染，不碰 axios
    │             └─ 数据从哪来、存在哪
    └─ 拆壳规则、错误提示、401 跳转
```

四条理由：

1. **先写页面会把自己锁死。** 页面里一旦写了 `axios.get('/api/devices').then(r => r.data.data)`，等返回体外壳变一次，7 个文件全要改。写进 `request.ts` 就只有一处。
2. **`request.ts` 是所有代码的总闸。** 它错一次，后面全错。所以它第一个写、第一个验证——计划文档 W2 周一那条「在页面里调 request 打印出 data 字段」，验的就是这个闸门通不通。
3. **store 必须在 views 之前。** Console 页要同时读 `device` 和 `pet` 两个 store，store 定下来，页面就是拼装。
4. **组件最后抽。** `ActionButton` 一开始直接写在 `Console.vue` 里，等第二个页面也要用同样的按钮再抽出来。过早抽组件是最常见的时间浪费。

---

## 第 6 章  前两周文件级对照表

计划文档写的是「今晚做什么」，这里是「今晚新建哪个文件」。

| 天 | 计划文档原话 | 新建 / 修改的文件 | 看到什么算过 |
|---|---|---|---|
| W1 周三 | clone 仓库、切分支 | 已完成 | `git branch` 显示 feature/frontend-ui |
| W1 周四 | create vite，选 Vue 和 TypeScript | `frontend/` 全套 | `pnpm dev` 出 5173 默认页 |
| W1 周五 | 只写标题的登录页 | `views/Login.vue`、`router/index.ts`（此时只一条路由） | 打开首页就是登录页 |
| W1 周六 | 装 Element Plus 和 Pinia，换 el-form | `main.ts`、`stores/auth.ts`（先只放空字段） | 用户名、密码输入框和按钮出现 |
| W2 周一 | 写 request.ts | `utils/request.ts`、`types/index.ts` | 控制台打印出后端返回的 data |
| W2 周二 | 401 拦截 | 改 `request.ts`、`auth.ts` | 删掉 localStorage 的 token 刷新回登录页 |
| W2 周三 | 三个 store | `stores/auth.ts`、`device.ts`、`pet.ts` | Vue Devtools 里能看到三个 store |
| W2 周四 | 配路由 + 守卫 | `router/index.ts` 补齐 7 条 | 未登录访问 `/devices` 被弹回 `/login` |
| W2 周五 | 假数据 el-table | `views/DeviceList.vue`（写死一行） | 页面出现一行设备 |
| W2 周六 | 换真请求 | `api/device.ts` + 改 `DeviceList.vue` | 用 admin 登录后列表出现真设备 |

---

## 第 7 章  开工前必须先对齐的接口

把三份文档里的接口路径逐个比过，**同一件事有两种写法**。这不是吹毛求疵，这决定你 `baseURL` 怎么写。

| 功能 | 前端计划里 | 实施方案里 | 风险 |
|---|---|---|---|
| 发动作 | `/commands`（W3 周五） | `/api/commands/send`（第 4 章示例） | 若 `baseURL='/api'`，写 `/commands` 实际请求 `/api/commands`，跟后端注册的 `/api/commands/send` 对不上，直接 404 |
| 切表情 | `/face`（W4 周四） | 未出现 | 是 `/api/faces/current`，还是 `/api/commands` 带 action 字段？不清楚 |
| 设备列表 | `/api/devices`（W2） | `/api/devices` | 一致，没问题 |

从文档里能确认的 13 条：

```
GET  /api/health
POST /api/auth/login            GET  /api/auth/me
GET  /api/devices                GET  /api/devices/{id}
GET  /api/devices/{id}/status    POST /api/devices/{id}/music  {command, value}
POST /api/commands/send          {action: 0x33}   ← 路径待确认
POST /api/faces（上传）           GET  /api/faces
GET  /api/logs                   GET  /api/telemetry
GET  /api/scenes                 POST /api/scenes/{id}/run
WS   /ws/device?token=xxx
```

剩下 8 条（场景增删改、表情删除、天气、设备重命名等）文档里没定死。**不要猜。** 后端 W1 把 `/api/health` 跑起来之后，打开 `http://127.0.0.1:8000/docs` 看 FastAPI 自动生成的接口表，那才是唯一权威。

这一条比什么都重要：文档会过期，`/docs` 不会。

---

## 第 8 章  三个难点，判断标准比代码重要

### 8.1  三态按钮（W4 全压在这一条上）

计划文档 7.8 给的 `btnType` 和 `onAck` 是对的，但别只用 `store.status[code]` 一个字段——连点三个按钮时立刻踩坑。做到下面三句就是对的：

1. 一个按钮一个状态，不是全局一个 `loading`
2. ack 只认 `seq`，不认 `action`。同一个动作连点两次，第二次的 ack 不能覆盖第一次
3. 超时后必须清掉 pending 里的条目，否则那个 seq 一直占着，下次同 seq 会串号

自测：把按钮做成「点一次变黄，一秒后自动变绿」，连点 5 个不同按钮，5 个都变绿且不串。过这一关，W4 就稳了。

### 8.2  WebSocket（W3）

难点不在连上，在断线重连不写成死循环。计划文档第 5 章 R03 已经给了退避公式（1、2、4 秒，上限 10 秒），照抄。判断标准两条：

- 拔网线，顶部出黄条；插回去，5 秒内黄条消失、数据恢复
- 反复开关后端 10 次，浏览器内存不涨（说明没漏定时器）

### 8.3  ECharts（W6）

计划文档第 5 章 R08 那条（容器要有确定高度）能省两小时。另外三张图分三次做，别一次写完：电量折线先跑通，再加环形图，最后加柱状图。ECharts 是「配置错了不报错、只是空白」的东西，一次只调一个图，出问题才知道是哪个。

---

## 第 9 章  每周末的验收

照计划文档第 6 章打勾。任何一周有一个没打上，周报里就别写「本周完成」。

| 周 | 这一周的最低线 |
|---|---|
| W1 | 三条命令出版本号 ｜ 登录页能打开 ｜ 代码推到分支 |
| W2 | 真登录 ｜ 设备列表显示真实数据 ｜ 删 token 跳登录页 ｜ 三个 store 都建了 |
| W3 | 19 个按钮全部铺出 ｜ WebSocket 能连能重连 ｜ state 事件能更新右侧状态 |
| W4 | 三态正确 ｜ ack 按 seq 对上 ｜ 3 秒超时有提示 ｜ 表情面板接真接口 |

---

## 第 10 章  两个文档里没写的小地雷

**一、`.vscode/` 被 gitignore 忽略了。** 计划文档 3.4 让你在项目根建 `.vscode/settings.json`，但 `.gitignore` 的「IDE」段里有 `.vscode/`——这份配置不会进仓库，队友拿不到。要么删掉 `.gitignore` 里那一行，要么接受它只在本机生效。

**二、`frontend/.gitkeep` 要在放进第一个文件之后删掉。** 否则将来有人重建目录时会困惑为什么有个空文件。

---

最后更新：2026-11-03 ｜ 本文档只讲开工顺序，功能与验收口径以《前端线开发计划 V2.0》为准。
