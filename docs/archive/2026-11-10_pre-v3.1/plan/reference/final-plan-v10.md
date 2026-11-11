> **审阅资料归档，非当前执行计划。** 归档日期2026-11-10。源文件final-plan-v10.md；原内容保留，包括历史讨论和旧示例，均不构成操作指令。采纳、调整和延期见[统一计划V3第12节](../项目统一实施与交付计划_V3.0.md)。其中默认凭据与迁移例子仅用于问题分析，禁止直接用于部署。

# 桌宠项目 · 架构补全方案 v10（终稿）

> 十二轮与 Codex 对抗审阅后的冻结稿。第十一轮结论是「v9 不闭合」，本版关闭它指出的 8 处自相矛盾与 4 条真实可达的恢复缺口（半迁移、归档删除顺序、NOT NULL 发布窗口、retired 重回认领池）；第十二轮复审又把 3 处新开的口子关掉（retire/reinstate 无可执行 DML、`device_audit` 的 CHECK 漏 `enable_admin`、测试 25/27 与正文冲突），并让 5 条不可复现的测试变成可确定性重跑。**第十三轮 Codex 复核结论：可以冻结**——三条阻断项全部关闭、未发现新的开工阻断项、无开工前必改项。仓库文件未做任何修改。

## 0. 结论

缺的不是一个解绑接口，而是**归属维度**：数据库无真实所有者外键、接口层无 owner 过滤、契约明文要求 id=1、前端把设备 id 写死。补全 = **两条版本标量（user.token_version、device.binding_epoch）+ 不可变归属上下文（行上固定 device_pk / binding_epoch / actor_user_id）+ 一个撤销线性化点（P0 是数据库提交点，P1 是发送锁）**，并用测试而不是 review 守不变量。

## 1. 根因（四层互相加固）

| 层 | 证据 | 后果 |
|---|---|---|
| 数据 | backend/app/models.py:26 owner_id = Column(Integer, default=1) 裸整数无外键 | 任何账号可被写成 owner |
| 逻辑 | backend/app/routers/devices.py:27 db.query(Device).all() | 任何账号看到全部设备 |
| 制度 | docs/contracts/http-api.md:186 仍不需要实现的：用户删除/角色权限管理 | 注销解绑被写进不做清单 |
| 前提 | http-api.md:347 必须有 id=1；openapi.yaml:221 至少含一台 id=1；frontend/src/utils/session.ts:34 默认 1 | 架构假设只有一个用户一台设备 |

物理侧：docs/contracts/frame.md 第2节帧格式 AA 55 LEN CMD DATA SUM **全帧无 device_id/SN/地址位**。故解绑在后端即可生效（固件零改动），但证明硬件归谁必须走带外信道（配对码 → P1 OLED 0x0C → P2 出厂 UID）。

## 2. 数据模型

### 2.1 表变更

| 表 | 变更 |
|---|---|
| user | **不再预置任何账号**；+ status ENUM(active/disabled/revoking/revoked) 默认 active；+ token_version INT 默认 0；+ deleted_at。~~must_change_password~~ **P0 不加**：系统里没有任何「别人替你设密码」的路径，强制改密是死列；它随 P1 的「管理员重置他人密码」与 dg 同批进迁移 |
| device | owner_id → FK user.id **NULL**；+ bound_at；+ device_uid VARCHAR(32) UNIQUE NULL；+ binding_epoch INT NOT NULL 默认 0；+ is_demo BOOL 默认 0；+ demo_grantee_user_id INT NULL FK user.id；+ retired_at DATETIME NULL；+ **status ENUM(claimable/bound/retired) NOT NULL 默认 claimable**——认领池的唯一判据是 `status='claimable' AND owner_id IS NULL`，不是「owner_id 为空」；retired 是终态，见 §4.2 与 §3 |
| ~~system_guard~~ | **v9 起删除这张表**。它原本兼两职：互斥 + 缓存 admin 数。缓存制造第二真相源（一旦漂移，最需要救援时所有命令都拒绝）；互斥有更好的载体——MySQL 命名锁，**锁名是固定常量 `petdog:admin:v1`**（16 字符，不含 `DATABASE()`/`CONCAT`：锁名按字面解释不展开函数，且 `DATABASE()` 可能为 NULL、拼接后可能超 64 字符上限），服务器级、不依赖任何行存在、进程崩溃随连接自动释放。admin 数量每次事务内 `COUNT(*)` 现算，绝不缓存。**该锁只在一个 mysqld 内有效，故 P0 只支持单写 MySQL（多主/跨实例不提供全局互斥）** |
| device_claim | 新表。device_pk **UNIQUE**（1:1），code_hash, nonce, expires_at, attempts INT 默认 0, status ENUM(active/used), created_at, used_at。因为 `device_pk` 唯一，**一台设备在这张表里至多一行**（从未发过码的设备是零行，首次 `issue` 才 INSERT；从第二次起一律原地 UPDATE）：`reissue` 原地覆盖 nonce/hash/expires_at 并把 attempts 归零；`reinstate` 原地把 `used` 改回 `active` 并换新 nonce/hash（不插新行，否则撞唯一键）。两种情况都靠 `ROW_COUNT()=1` 断言并写 `device_audit`——历史留在审计表里，不留在码表里 |
| device_audit | 新表（枚举里的 `register` **专指设备登记**，账号建号一律写 `register_admin`，两者不可混用）。id, device_pk INT **NULL**, action ENUM(register/claim/reissue_claim/unbind/auto_unbind/admin_unbind/retire/reinstate/**register_admin**/**reset_admin_password**/**enable_admin**/**disable_admin**/**promote_admin**/**demote_admin**/**delete_admin**), actor_user_id, prev_owner_id, new_owner_id, prev_epoch, new_epoch, reason VARCHAR(128), created_at。**CHECK 按动作分组**：账号级动作（上列后七个）要求 `device_pk IS NULL`；其余要求 `device_pk IS NOT NULL`。**名单必须一次写全**——`enable_admin` 这类账号级动作漏在名单外，`--enable` 的事务会被数据库直接拒绝（第十二轮点名的第二条阻断项） |
| legacy_row_archive | 新表。id, source_table, source_pk, schema_version, payload_json, reason, archived_at；**UNIQUE(source_table, source_pk)** |
| scene | owner_id → NOT NULL FK user.id |
| face_asset | + owner_id INT NULL FK user.id；+ builtin BOOL 默认 0；CHECK: builtin=1 等价于 owner_id IS NULL |
| command_log | + device_pk INT（P0 可空、代码层强制非空；列级 NOT NULL 见 §10 第 5b 条）+ FK；+ cmd_id CHAR(36) UNIQUE；+ actor_user_id INT **NOT NULL**；+ binding_epoch INT（同上）；+ transport TINYINT 默认 0；保留自增 id 作展示主键 |
| telemetry | + device_pk INT（同上）；+ binding_epoch INT（同上） |

约束：`UNIQUE KEY uq_device_owner(owner_id)` —— MySQL 唯一索引允许多个 NULL，天然实现「一账号一设备 + 空池多台」。
状态与归属必须同步，**两条** CHECK 一起加：`CHECK ((owner_id IS NULL) = (bound_at IS NULL))`、`CHECK ((status = 'bound') = (owner_id IS NOT NULL))`。第二条同时把 `retired` 锁在「必然无 owner」这一侧——「retired ⇒ owner 为空」是它的推论，**不需要第三条 CHECK**（§2.3 的措辞据此统一）

### 2.2 两条版本标量（v4 的三条减为两条）

| 列 | 何时 +1 | 谁读 |
|---|---|---|
| user.token_version (tv) | 改密、注销、封禁、登出全部会话 | JWT 载荷携带，deps 每次请求查库比对 |
| device.binding_epoch (be) | **只在三处 +1：claim 成功、unbind（含 auto_unbind / admin_unbind）、retire**。`reissue_claim` 不加（只换码），`reinstate` 也不加（它不改变任何绑定关系，加了会造出一个没有对应绑定代次的空 epoch；随后真正 claim 时再 +1） | 历史可见性过滤 + command_log / telemetry 的归属戳 |

**dispatch_generation 整体删除**。Codex 第五轮判定它在 P0 是死列、提前递增对 P1 无价值。P1 引入命令通道时用**迁移 0006**（0002–0005 已分配给 P0 迁移）加 `dispatch_generation`，与队列/WS 消费者同批落地。

**改密只翻 tv，不翻 be**：否则用户改密后自己的历史全部消失（A 持 D.be=7 有历史 → 改密后 D.be=8 → 历史仍标 7 → 全不可见）。改密的撤销需求由 tv 承担。

### 2.3 三条不变量（测试守，不靠 review）

- **I1** 三条等价关系锁死归属态：`owner_id IS NULL ⇔ bound_at IS NULL`；`status='bound' ⇔ owner_id IS NOT NULL`；`status='retired' ⇒ owner_id IS NULL`。**前两条落成 CHECK（一共两个约束），第三条由第二条推出、不另建约束**——同一条关系写两遍，将来只会两处各改一半；它写在这里是因为它是 `check-consistency` 的输出项与验收口径。**「可认领」不是 I1 的推论，是独立条件 `status='claimable' AND owner_id IS NULL`**——只看 owner 为空会把 retired 设备放回池里。
- **I2** 所有设备查询 WHERE 必须含 `owner_id = :current_uid`。守法是两账号交叉打全部设备接口的测试。
- **I3** 历史可见性 = `device_pk = :pk AND binding_epoch = :device.binding_epoch` 且 owner 匹配。封装 `visible_telemetry_query()` / `visible_command_query()`，路由禁止自拼。

### 2.4 时间

统一 UTC：连接级 `SET time_zone='+00:00'`；列 DATETIME(6)；写入端一律 `datetime.now(timezone.utc)`（禁止 `datetime.now()`）；输出 `isoformat()` 带偏移。旧行不猜时区，标 `data_origin` 进迁移记录。

## 3. 状态机

**设备**（`status` 列是唯一真相源，不靠 `retired_at` 是否为空推断）：`claimable` --claim--> `bound` --unbind/auto_unbind/admin_unbind--> `claimable`；`claimable`/`bound` --retire--> `retired`（物理报废/遗失）。**retired 是终态，不进入认领池**；恢复必须由管理员显式 `reinstate`（清 retired_at、status 回 claimable、撤销并重签 claim code），不是「把 owner_id 清空自动回到池里」。跨边界必 +1 be。
**配对码**（单行，`device_claim.device_pk` UNIQUE，一台设备永远只有一行，所以所有转移都是原地 UPDATE，绝不 INSERT 第二行）：none --issue--> active --正确码--> used；used --reinstate--> active（**原地**换全新 nonce/hash/expires_at、attempts 归零，见 §4.2；这条转移只为让 retired 设备恢复后可被认领而存在）；active --TTL 到期--> 判过期为失效；active --重签--> 原地覆盖 nonce/hash/expires_at，attempts 归零，写 audit(reissue_claim)；active --retire--> used（retire 同事务消费掉未用的码）；active --第 5 次错码--> status 保持 active 但 attempts=5，此后一律拒绝直到重签。判定优先级固定 **used → attempts>=5 → 过期 → 有效**。
**账号**：active --disable--> disabled --enable--> active；active/disabled --delete--> **revoking**（事务内立即 tombstone 用户名 + tv+1 + 设备解绑）--清理完成--> **revoked**（终态）。revoking 与 revoked 状态下登录、鉴权、认领一律拒绝。**最后一个 active admin 禁止注销与封禁**：所有进入/离开 active admin 的路径（创建、注销、封禁、降权、启用、恢复）**统一先拿同一把命名锁 `GET_LOCK('petdog:admin:v1', 10)`**，见 §4.6 的连接契约；再在同一事务里 `COUNT(*) WHERE role='admin' AND status='active'`。不锁 user 行、不锁任何表行、不缓存计数——只有一把锁、一个真相源。
**命令**（沿用 frame.md:229-265 不改协议）：解绑/注销不改已下发命令状态（superseded 只允许新命令收到 0x81 后触发）；未写出队列项靠 be/tv 失效丢弃并持久化 transport=1；transport=1 的命令**永不被迟到帧提升为 done**。

## 4. 事务与并发

### 4.1 锁序

`user → device（主键升序） → device_claim → device_audit（仅插入）`；涉及 active admin 增减的事务在进这套锁序之前先拿命名锁 `petdog:admin:v1`（见 §4.6）。生命周期事务显式 READ COMMITTED。

三条来自可复现失败模式的实现约束：

- **bcrypt/argon2 必须在开事务之前算完**：一次哈希数百毫秒，放进持锁事务会让所有并发 claim / 建号排在同一把锁后面。
- **拿锁之前禁止查询目标用户或管理员数量**：MySQL REPEATABLE READ 下事务内首次读即建立快照，先读后锁会拿着旧值做判断。顺序只能是「拿锁 → 读 → 写」。
- **死锁 1213 与锁等待超时 1205 都必须显式 `rollback()`**：1205 默认可能只回滚当前语句而不回滚整个事务，随后 COMMIT 会把半成品写进去。捕获后 rollback + 退出码 3，不半途重试。

### 4.2 claim

步骤：锁 user 行 → 锁 device 行 → 锁 device_claim 行 → **锁后复核**（user.status=active；`device.status='claimable'` 且 `owner_id IS NULL`；该用户无其它绑定设备；免码路径要求 `is_demo=1` 且 `demo_grantee_user_id=当前 uid`）→ 恒定时间比较 code_hash。

- **认领池的判据是两个条件**：`status='claimable' AND owner_id IS NULL`。只判 `owner_id IS NULL` 会让 retired 设备（注销/迁移时 owner 被清空）重新进池被陌生人认领——这是第十一轮点名的一条真实缺口。
- **用户名释放**：注销事务内把 username 原子改为 `~del~<id>~<hex8>`（≤32 字符；`~` 不在 backend/app/routers/auth.py:47 的 `USERNAME_RE = re.compile(r"[a-zA-Z0-9_\u4e00-\u9fa5]{3,20}")` 字符集内，因此不是可注册名，也不会和新用户抢名字），UNIQUE 索引因此立即释放；不做「先删行再插同名」的两步。
- **错码分支**：`UPDATE device_claim SET attempts=attempts+1 WHERE device_pk=:pk AND status='active' AND expires_at>UTC_TIMESTAMP(6)`，随即 **COMMIT 计数后返回**（计数不提交，5 次限制形同虚设）。
- **正确码分支**（同一事务，两条 UPDATE 都必须断言 `ROW_COUNT()=1`，任一为 0 立即 rollback 并返回 40900）：
  `UPDATE device SET owner_id=:uid, status='bound', bound_at=UTC_TIMESTAMP(6), binding_epoch=binding_epoch+1, name=:default WHERE id=:pk AND status='claimable' AND owner_id IS NULL`；
  `UPDATE device_claim SET status='used', used_at=UTC_TIMESTAMP(6) WHERE device_pk=:pk AND status='active'`；
  INSERT `device_audit(action='claim')`；COMMIT。
- **retire 与 reinstate 的 DML 写死在这里**（第十二轮指出原来只有一句「撤销并重签」，没有可执行路径——`device_claim.device_pk` 是 UNIQUE，那行还在，reinstate 插新行必然撞键，所以必须原地改）：
  - `retire`（管理员 CLI，设备级）：锁 device 行 → `UPDATE device SET status='retired', owner_id=NULL, bound_at=NULL, binding_epoch=binding_epoch+1, retired_at=UTC_TIMESTAMP(6) WHERE id=:pk AND status IN ('claimable','bound')`，断言 `ROW_COUNT()=1`（已是 retired 直接报 40900，不做幂等覆盖）→ **同一事务**消费该设备的码 `UPDATE device_claim SET status='used', used_at=UTC_TIMESTAMP(6) WHERE device_pk=:pk AND status='active'`（影响 0 行也可接受：本来没签过码）→ `INSERT device_audit(action='retire')` → COMMIT。分成两个事务就会出现「retire 之前签发的码在 retire 之后仍然可用」。
  - `reinstate`（管理员 CLI，设备级）：锁 device 行 → `UPDATE device SET status='claimable', retired_at=NULL WHERE id=:pk AND status='retired'`，断言 `ROW_COUNT()=1` → **同一事务**把码从 used 改回 active 并换全新 nonce/hash/expires_at、attempts 归零：`UPDATE device_claim SET status='active', nonce=:n, code_hash=:h, expires_at=:e, attempts=0, used_at=NULL WHERE device_pk=:pk AND status='used'`（影响 0 行说明该设备从没签过码，此时 INSERT 一行 active；两条分支都由唯一键兜底，撞键即整事务回滚）→ `INSERT device_audit(action='reinstate')` → COMMIT。**reinstate 不动 be**（没有绑定关系改变），随后真正被 claim 时才 +1。
- 免码被拒、已绑、已 used、用户失效等分支**结束事务后返回**，禁止在需要提交的事务内 raise。
- 同一用户多标签页同码：已持有即返回当前状态（幂等成功），不报冲突。

正确码路径的注销窗口已关闭：claim 持 user 行锁至 COMMIT，delete 只能先完成或随后 auto_unbind。

### 4.3 unbind / delete（两阶段）

P0 的撤销线性化点 = 数据库提交点（P0 无发送方）。P1 起改为：撤销动作**先拿 ownership_send_lock，锁内完成权威失效并提交**，锁外做重活。

锁内只做：`UPDATE user SET status=..., token_version=token_version+1`；`UPDATE device SET owner_id=NULL, bound_at=NULL, status='claimable', binding_epoch=binding_epoch+1 WHERE owner_id=:uid AND status='bound'`（逐台，主键升序；**`status` 必须一起回 claimable，否则违反 I1 的第二条**）；批量 INSERT device_audit；COMMIT。设较短 DB 锁等待上限。
锁外做：删 scene / 非 builtin face（大账号走异步任务，账号状态 revoking → 完成后 revoked）；关 WS；撤票据；publish_revocation_locally。**用户名 tombstone 必须在锁内事务完成**（`UPDATE user SET username='~del~<id>~<hex8>'`），否则 UNIQUE(username) 会让同名重注册失败。

**中间不产生发送窗口**：发送方在锁内检查 status 与 be，两阶段期间状态已是拒绝态。

**设备侧不留「账号已 revoking、设备还 bound」的中间窗口**：`status='revoking'` 与设备解绑（`owner_id=NULL, bound_at=NULL, status='claimable'`）在**同一个锁内事务**里提交，不存在「先改账号、后改设备」的两次写入。所以 revoking 账号的设备在同一刻就可被别人认领，而该账号在任何请求上都会被 status 检查拒掉——既不会出现「账号已废但设备还被它占着」，也不会出现「设备已释放但账号还能操作」。设备若已 `retired` 则与本条无关（retired 本来就不进池）。

### 4.4 P1 发送锁（P0 不建）

P0 不引入 ownership_send_lock，也不建空 SendGate（Codex 第六轮判定：以数据库行锁与提交点为撤销线性化点已足够）。P1 引入时用同一撤销核心 + 发送路径共同持锁，P0 黑盒测试保留，新增 send/revoke 竞态测试。

P1 骨架约束：锁是**同步**锁；取消 Future 不停止已执行的 executor 工作；`write` 抛异常不等于零字节（pyserial 有先写部分再超时抛异常的路径），**一律归 partial_write + status=unknown，禁止标 write_failed**；物理写成功但 DB 提交失败不得重发；写成功仅代表软件传输边界。

### 4.5 单实例

lifespan 用**专用长连接**（不归还连接池）执行 `SELECT GET_LOCK('petdog:instance', 0)`，失败即启动失败并打印占用者；退出时显式 `RELEASE_LOCK`。配套 run.py：reload=False、workers=1、host=127.0.0.1。

### 4.6 命名锁的连接契约（第十一轮补充，v9 的表述不够）

`GET_LOCK` 是**会话级、合作式**的：COMMIT / ROLLBACK **不会**释放它；同一会话重复获取会**累计计数**（拿两次要放两次）；超时返回 0、错误返回 NULL（两者都不是「拿到」）；锁名按字面解释、≤64 字符；作用域只覆盖**单个 mysqld**。因此「专用连接 + finally 释放」这句话不足以复现，必须落到下面这条契约：

1. 参数校验与 bcrypt 计算全部做完，**之后**才在一条**新的物理连接**上执行 `SELECT GET_LOCK('petdog:admin:v1', 10)`，只有结果 `= 1` 才继续；返回 0 或 NULL 一律失败关闭（不得退化成无锁执行）。
2. **同一物理连接既持锁又执行管理员事务**，且该事务的第一次业务表读取必须发生在拿锁之后（REPEATABLE READ 下先读会固定旧快照）。绝不把锁连接与业务 Session 分开——锁连接断了，业务事务还能继续写。
3. 所有出口（成功、异常、1205、1213、`ER_USER_LOCK_DEADLOCK`）顺序固定：先 `commit()`/`rollback()`，再 `RELEASE_LOCK`，最后才归还/关闭连接。
4. **释放失败就销毁这条物理连接**，禁止带锁回连接池；连接被销毁时 MySQL 自会释放其命名锁。
5. 使用同一把锁的路径是全集：`create-admin` / `reset-admin` / `list-admins` 之外的**封禁、启用、降权、注销、恢复、seed、迁移中的管理员变更**全部包含。只用在一处等于没锁。
6. 迁移脚本内的管理员变更同样走这把锁，并在迁移前置检查里断言「锁可用」（拿一次放一次），避免迁移在不持锁状态下改 admin。

## 5. 授权规则

### 5.1 统一裁决

| 情形 | HTTP | code | reason |
|---|---|---|---|
| 未登录/令牌无效 | 401 | 40100 / 40101 | — |
| 资源存在但不属于我 | **200** | **40400** | — |
| 能力禁止（非 admin、限流） | **403** | **40300** | forbidden / rate_limited（`password_change_required` 随 P1 强制改密一起加，P0 不出现） |
| 参数缺失或类型错 | 200 | 40000 | — |
| 参数值不合法 | 200 | 40002 | — |
| 业务冲突（用户名占用、已被绑定） | 200 | 40900 | — |
| 内部异常 | **500** | 50000 | — |

`reason` 是新增机器可读字段，前端只 switch code + reason，禁止解析中文 message。契约写明：401/403/500 用真实 HTTP 状态，其余业务错误维持 200。

**实现约束（必须写进契约）**：详情一律 `WHERE id=:id AND owner_id=:me` 的 helper；更新/删除一律带 owner + be 的单条 DML 并检查 rowcount；**禁止先 fetch 再判 owner**。

**两条路径边界（v9 那句「任何 devices 子路径都 40400」过宽，会把认领本身封死）**：
- **按现有 device id 定位的资源路径**（`/api/devices/{id}`、`/status`、`/commands`、`/binding`、`/ticket` 等）：未归属当前用户一律 **40400**，不区分「不存在」与「不是你的」。
- **集合级动作**（`POST /api/devices/claim`、`GET /api/devices/claimable`、`GET /api/setup/status`）走各自独立授权规则：claim 只看「目标设备是否 claimable 且未被占」，claimable 只返回 `status='claimable' AND owner_id IS NULL` 且**不含任何归属者信息**；它们**不属于**上面那条 40400 规则。

### 5.2 逐接口归属

| 接口 | 要求 |
|---|---|
| POST /api/devices/claim（新） | 集合级动作，按 §4.2；不要求调用者已拥有设备；成功即返回该设备 |
| GET /api/devices/claimable（新） | 只返回 `status='claimable' AND owner_id IS NULL` 的 `{device_id, name}`；不泄漏任何归属者、不泄漏 retired |
| GET /api/devices | WHERE owner_id=:me；battery 只取 be 匹配且 9s 内的快照，否则 null |
| GET/PATCH /api/devices/{id} | id 与 owner 同 WHERE；PATCH 带 AND binding_epoch=:authorized_be 并查 rowcount |
| DELETE /api/devices/{id}/binding（新） | owner + 确认字段 |
| GET /api/devices/{id}/status | owner |
| POST /api/commands/send | 当前设备 owner；P1 请求体加显式 device_id |
| GET /api/commands/{id} | cmd_id=:id AND actor_user_id=:me AND device.owner_id=:me AND cmd.binding_epoch=device.binding_epoch 四条件 |
| GET /api/logs | device_pk + be + actor/owner；device_id 省略时只汇总我的设备，items 与 total 同一过滤 |
| GET /api/telemetry | 新增可选 device_id；必须走 visible_telemetry_query |
| POST /api/events/ticket | owner，票据写入 uid/tv/be |
| POST /api/scenes/{id}/run | scene.owner 与设备 owner 双校验；任务固定 (actor_user_id, device_pk, be)，每步复核 |
| GET /api/faces/{id}/preview | 内置匿名可 GET；自定义短期签名 URL |
| DELETE /api/faces/{id} | owner_id=:me AND builtin=0 |
| 管理接口（P1） | require_admin + 审计 |

### 5.3 表情预览签名 URL（冻结，二选一已定）

`HMAC-SHA256(secret, face_id | owner_id | updated_at_epoch | exp)` 取前 32 位十六进制；TTL 上限 24h；恒定时间比较；签名错/过期/不存在**同一响应 40400**；`Cache-Control: no-store`；frontend/src/views/Faces.vue:127 直接塞 src 不改造。**删除 public_token 列**。产品承诺限定为「撤销后服务端不再读取」，已缓存内容不可追回。

## 6. 六类数据可见性

| 表 | 归属戳 | 谁能读 |
|---|---|---|
| command_log | device_pk + binding_epoch + actor_user_id（不可变） | 四条件同时满足；解绑后普通用户不可查 |
| telemetry | device_pk + binding_epoch NOT NULL | 当前 owner 且 be 匹配 |
| device_claim | device_pk | 明文任何人不可见，仅 CLI 签发 |
| device_audit | device_pk | 仅 admin |
| scene | owner_id | 仅 owner |
| face_asset | owner_id / builtin | 内置公开只读；自定义仅 owner |

`legacy_row_archive` 是**迁移隔离区，不是审计表**：禁止业务 ORM 与普通管理员接口访问；只允许离线 CLI 导出；纳入一致备份。

## 7. 契约改造清单

**http-api.md**：:186 改为「本期做：账号注销/改密/登出/设备归属与绑定解绑；仍不做：成员邀请、角色权限、日志导出、WS 客户端消息」；**全文 8 处写死 `admin/123456` 的示例与验收步骤必须同步改**（:237 请求体示例、:245/:309 响应示例、:1188 第9.2节自查第 2 条「`admin/123456` 登录 → 进设备页」、:1209「联调时如果后端 seed 的账号不是 admin/123456」），改为「由 create-admin 创建的本机管理员」，并补一句「系统不提供任何预置账号」；:196/:347/:355 删「保证 id=1」与「至少一台设备」；:349/:1227/:1240 心跳 30s → **9s**；:520 补「P0 每账号 1 台，放开上限必须给所有入口加显式 device_id」；新增第3.0节 归属与权限总则（5.1 表 + reason + 实现约束）；第2节总表增 6 行；:262-298 密码哈希改「必须 bcrypt/argon2id，禁止无盐 sha256，旧哈希首次登录静默升级」；:619/:642-648 改签名 URL + no-store；:725/:730 明确 id 与 cmd_id 并存；:103 内部错误 200 → 500；:915 补「解绑/注销时票据与连接立即作废」；:1105 天气默认坐标统一湘潭雨湖区 27.856/112.903；:203/:204 修正错误的章节编号引用。

**openapi.yaml**：:221 改「可以是空数组」；:424 标注 P0 限制；:1158 改 9s；Device 加 bound_at/is_bound（be 不暴露）；新增 ClaimRequest/ClaimResponse/PasswordChange/AccountDelete/LogoutResponse；User schema **加 id**；example 里的 `admin` + `123456`/`admin123`（:130/:148/:210/:1110/:1114/:1116）全部换成中性占位（如 `alice` / `<password>`），避免示例被当成可用凭据。

**error-codes.md**：:45 40300 从预留改已实现并列出三种 reason；:48/:1111 50000 明确 HTTP 500；:60 保留「设备离线不是错误」并补「write 异常归 partial_write」。

**events.md**：不新增关闭码（1000/4001/4003/4009/1011 够用）；补「解绑/注销以 1000 关闭，前端重拉列表判断归属消失」；补「取票 40300/40400 必须停止重连」。

**frame.md**：不动。

### 7.1 凭据载体全清单（第十轮 Codex 点名，逐条实读核验过）

纯粹在源码里 grep `admin123` 清不干净，因为凭据还躺在这些地方：

| 载体 | 位置（已核验） | 处置 |
|---|---|---|
| 配置默认值 | backend/app/config.py:9 `DB_URL = 'mysql+pymysql://petdog:petdog@127.0.0.1:3306/pet_dog?charset=utf8mb4'`、:12 `JWT_SECRET = 'change-me-in-dotenv'` | 两行都删默认值，缺失即启动失败；.env.example 只放占位符与生成命令 |
| DOCX 内部 | docs/plan/STM32智能桌面宠物_后端线开发计划_V2.0.docx 解包 XML 命中 admin123 / change-me / petdog:petdog | 改写文档并重新导出；**普通 grep 看不到，验收脚本必须解包 docx/xlsx/pptx** |
| OpenAPI 示例 | docs/contracts/openapi.yaml:1143 `example: secret123` | 换 `<password>` 占位 |
| 契约示例 | docs/contracts/http-api.md:276 `{ 'username': 'tester01', 'password': 'secret123' }`、:1189 注册验收第 3 条 | 同上，且验收步骤改为「自选用户名 + 自设密码」 |
| 前端 Mock | frontend/src/mock/index.ts:239 `MOCK_USERS_KEY = 'petdog_mock_users'`、:242-246 `interface MockUser { username, password, name }` | Mock 不存明文密码（只存用户名与假 token）；**并在启动时清一次旧键**，因为旧浏览器里的明文不会因为删代码而消失 |
| .env 变体 | frontend/.env.test 里 `VITE_USE_MOCK=true`（tracked，不被 .gitignore 忽略） | 保留文件但值改 false；验收断言**最终 dist 编译产物**里 mock 为关闭 |
| 字节码 | backend/__pycache__/seed.cpython-314.pyc 内仍含 admin123 | 迁移时清 `__pycache__`；验收脚本扫 .pyc |
| Git 历史 | 已提交的历史仍含旧字符串 | 不承诺清除。安全保证来自「旧账号全部失效 + 真实秘密已轮换」，文档必须这么写，不能写「已清除」 |
| 运行期产物 | 启动后生成的 /openapi.json 会带 example | 验收脚本请求一次并扫 |
| **tracked 字节码** | `backend/__pycache__/*.pyc` 曾进过工作区（.gitignore 第 2-3 行已忽略，但要确认没被 `git add -f` 过） | `git ls-files | findstr /i ".pyc"` 必须为空；非空则 `git rm --cached` 并清目录 |
| **浏览器残留** | 旧版本的 `petdog_mock_users`（明文密码）、`petdog_token`、`petdog_user`、`petdog_device` | 前端启动时执行一次性迁移：读旧键 → 清掉 → 写一个 `petdog_schema_version` 标记，之后不再执行。不清理等于「代码删了、明文还在用户机器上」 |

**处置动作矩阵（第十一轮：清单不是闭环，得分清「删掉」和「换掉」）**：

| 秘密 | 处置 | 理由 |
|---|---|---|
| DB 口令 `petdog/petdog` | **轮换**（改 MySQL 用户口令）+ 从 config.py 删默认值 | 它已经进过源码与 DOCX，可能已进过任何一次复制/备份；只删默认值不轮换等于没换锁 |
| `JWT_SECRET = change-me-in-dotenv` | **轮换**（生成 ≥32 字节随机值写 `.env`）+ 启动断言拒绝默认值/短值 | 同上；旧令牌必须随轮换一次性失效，所以轮换与 `token_version` 递增在同一次发布完成 |
| `admin/admin123` 历史账号 | **失效**（迁移置 disabled + 改 `~legacy~<id>` + 随机不可校验 bcrypt） | 无法「删除历史」，只能让它永远登不进去 |
| 文档/示例里的 `123456`/`secret123` | **删除并换中性占位** | 不是真秘密，但会被人当真 |
| 旧 localStorage 明文 | **一次性清除** | 存在用户浏览器里，删代码清不掉 |

**验收口径**：不能裸 grep `123456`——vendored 的 Swagger UI 与 Axios 里有数字字符表，必然误报。改为「密码字段 + 禁值」的上下文扫描 + 解包 Office 文档 + 扫 .pyc + 扫运行期 /openapi.json + 扫生产 dist/。

**docs/plan/STM32智能桌面宠物_前端开工方案_V1.0.md**：:192「用 admin 登录后列表出现真设备」改为「用 create-admin 建的账号登录，列表为空（设备尚未认领）→ 走认领流程」。**frontend/README.md:21「演示账号：`admin` / `123456`（Mock 模式下有效，登录页有一键填入）」与 :46「内置账号 `admin / 123456` 不受影响」同样删改**（改为「Mock 模式下任意非空账号密码均可登录」）。**发布物凭据门禁见 §7.1**：不能裸 grep，必须扫上下文 + 解包 Office 文档 + 扫 .pyc + 扫运行期 /openapi.json + 扫生产 dist/，落地为 §12 第 24 条测试。

## 8. 后端改动

1. requirements：+ alembic、bcrypt、pytest、pytest-asyncio。
2. models.py 按 2.1 全量改（FK / CHECK / uq_device_owner）。
3. alembic：新建 backend/alembic；0001_legacy_baseline（冻结当前 schema）+ 0002_ownership。
4. 拆掉两处 create_all：backend/app/main.py:14、backend/seed.py:8；seed 改幂等 upsert。
5. security.py：bcrypt/argon2id + 旧 sha256 首次登录静默升级；JWT 加 tv。
6. deps.py：current_user 从只验签改为验签**加查库**（uid/status/tv，每请求一次主键查询，先不缓存）；新增 require_admin、get_owned_device(id)。
7. 新建 app/services/ownership.py：claim/unbind/auto_unbind/delete_account/revoke 唯一入口，路由不得直写 owner_id。
8. 新建 app/services/claim.py：签发 6 位码、HMAC 校验、attempts 推进、限流（仅账号桶与 IP 桶）。
9. devices.py：list 加 owner 过滤 + 去 N+1（一次 group by 取最新快照）+ battery 可空 + bound_at/is_bound；新增 claim/claimable/unbind。
10. auth.py：+ logout / password / account；login 加 status 校验与失败计数。**先查 status=disabled/revoking/revoked 直接拒绝，再比对密码哈希**（顺序反了，非法的 legacy 哈希会让验证器抛 `Invalid salt` 变成 500）。
    **注册（backend/app/routers/auth.py:55）在 P0 保留但对归属零影响**：本项目是「多用户内核 + 单设备演示」，演示要两个账号才能演越权，所以不能关掉注册；但新注册账号必须 `GET /api/devices` 返回空数组、任何 devices 子路径返回 40400——注册只给「一个身份」，不给任何设备。注册同样进 IP 桶限流，且 `USERNAME_RE` 已排除 `~`（迁移用的 `~legacy~<id>` 不可注册）。
11. faces/scenes/logs/telemetry 路由：P1 落地，P0 先写归属断言与可见性封装。
12. main.py：CORS 显式白名单 + credentials；统一错误处理器；lifespan GET_LOCK；启动断言 JWT_SECRET/DB_URL。
13. errors.py：Exception 处理器改 HTTP 500；RequestValidationError 维持 200+40000；新增 404/405 处理器映射统一信封。
14. config.py：删 ACK_TIMEOUT=3.0（引用 frame.md 常量 0.6）、天气默认改湘潭、去掉可用的 DB_URL/JWT_SECRET 默认值。
15. run.py：reload=False、host=127.0.0.1、workers=1。
16. seed.py / seed_devices.py：**删除创建 admin/admin123 的代码**（backend/seed.py:11-13）；设备 owner_id=NULL、name 默认、bound_at=NULL、be=0、不写本地时间。**backend/seed_devices.py:18 现在把设备写成 owner_id=1，必须一起改**——否则旧用户被 disabled、新管理员拿到新 id 之后，新管理员看不到那台设备，会以为「迁移把设备弄丢了」。设备归属只能来自认领或 CLI register-device 的显式指定，不能来自 seed 的魔法常量。
17. 新建 app/cli.py：**create-admin**、**reset-admin**（含 `--enable`）、**list-admins**、**check-consistency**、**retire**、**reinstate**、register-device、issue-claim-code、promote-demo --grantee、export-legacy。密码一律 `getpass` 交互读，禁止 `--password` / 环境变量 / 管道输入；**注意 `GetPassWarning` 默认是 warning 不是异常，单纯 `except GetPassWarning` 无效**，必须按 §11.1 的五步顺序判定并在 `warnings.simplefilter("error", getpass.GetPassWarning)` 之下读取。
17b. 新建 app/routers/setup.py：**只有** `GET /api/setup/status` 返回 `{setup_required}`（`no-store`），**不含任何 POST**——初始化只能走 CLI（见 11.1）。该路由必须进鉴权白名单（未登录可访问），且**不查任何用户数据、不写库、不打日志里的用户名**。
18. User 载荷加 id（auth.py:22-27 与 http-api.md:302-309 现在都只有 username/name/role）。

## 9. 前端改动（P0 最小集）

- utils/session.ts：clearSession 必须清 DEVICE_KEY；getStoredDeviceId 返回 number|null（删掉 ?? '1' 与 || 1）；键名按 **user.id** 分区，不按 username。
- stores/device.ts：空列表 currentId=null；新增 reset()；合并并发 load；回填前校验 sessionEpoch。
- stores/auth.ts + utils/request.ts：共用退出清理；**先换代次再发请求**；成功与失败都先查代次才产生副作用（含 401 跳转、toast、mock 返回）；解析非 2xx 错误信封（现在 :81 丢弃非 401 正文）。
- **跨标签页**：window 监听 storage 事件（或 BroadcastChannel），claim 成功、注销、改密广播换代次，其他标签页立即清理。
- AppLayout.vue：登录后等设备列表确定再处理目标；无设备不建连；currentId 变化由 watch 驱动；P0 不启动未实现的实时链路。
- router/index.ts：P0 只开放 /login、/devices、/account，其余守卫挡回 /devices；新增无设备守卫。
- DeviceList.vue：空态文案改「还没有设备，请用登记命令添加一台，或输入配对码认领」；隐藏未上线入口；电量 null 显示 —。
- types/index.ts：Device 加 bound_at/is_bound；battery 改 number|null（+ battery_at）。
- utils/ws.ts：空 target 守卫；取票 40300/40400 停止重连；reset() 清理完整状态。
- api/device.ts、api/account.ts：claim/claimable/unbind/logout/password/deleteAccount。
- mock/index.ts：补 6 条新路由；设备按账号隔离（现在 :349 是全局 devices）；runtime.ts:52 单例按用户隔离；**删掉演示凭据**——:309 `username === 'admin' && password === '123456'`、:312-318 硬编码的 admin 用户对象、:335 与 :345 对 `'admin'` 的特判，改为「任意非空账号即通过」的 mock 语义。
- views/Login.vue：**删掉 fillDemo()（:66-67 写死 admin/123456）、placeholder 里的 'admin'（:177）、`DEMO · admin / 123456` 一键填入块（:232-237）**；mock 模式下若仍要提示，只写「任意账号密码即可登录（mock 模式）」，不出现具体字符串。
- views/Account.vue（新）：改密、注销（密码 + 输入用户名双确认）。
- errors.ts：40300 + reason 文案表。

## 10. 迁移

**总原则（第十一轮）：一个 Alembic revision 在 MySQL 上不是原子事务**——`ALTER TABLE` 隐式提交，Alembic 自己的 MySQL 方言把 `transactional_ddl` 标为 False。所以「一条大迁移跑完就好」是假的：中断后更常见的是「部分 DDL 已生效、版本号未推进」。因此 P0 的迁移必须拆成 **expand → backfill → verify → contract 四个 revision**，每个都**幂等可重跑**（先查 `information_schema` 再建、用 `INSERT ... ON DUPLICATE KEY UPDATE` 或先判存在），并且**禁止** `stamp head` 代替数据搬迁、**禁止**用 try/except 吞掉 DML 异常后继续推进版本号。

0. **迁移期间后端必须停机，且不得启动 Web 服务**：当前 backend/app/main.py:14 在 import 时执行 `Base.metadata.create_all()`，它只建缺失的表、不改已存在的表，与 Alembic 并存会造出「表已存在但没有版本号」的半迁移库。**两处 create_all 必须先拆掉**（main.py:14、seed.py:8），此后建库唯一入口是 `alembic upgrade head`——全新机器也一样，不存在「先 create_all 再 stamp」这种路径。
1. **停写 + 备份**：停后端；mysqldump 到 pet-dog-temp；**先恢复到 `pet_dog_verify` 并在那里把整套迁移跑一遍**，确认可重跑、可中断、可续跑，再对生产库动手。
2. **0001 baseline**：校验现有 schema（列/索引）与冻结内容一致后 `alembic stamp 0001`。不一致（有人手改过库）先停下来人工对齐，不允许硬 stamp。
3. **0002 expand（只加不改不删）**：建新表（device_claim / device_audit / legacy_row_archive）→ 给 device 加可空列（owner_id 暂不动，见第 4 条）→ 加 `status` / `binding_epoch` 默认值 → 加索引。全是加法，跑到一半中断可以直接重跑。
4. **0003 backfill（只写数据，无 DDL）**：
   - **预检冲突**：先 `SELECT username FROM user WHERE username LIKE '~legacy~%' OR username LIKE '~del~%'`，非空即中止并打印——`~` 只是「不可注册」，挡不住历史脏数据。
   - `device`：`owner_id=NULL, bound_at=NULL, binding_epoch=0, status='claimable'`（现有 `owner_id=1` 不构成归属证据，人工登记的设备由 CLI 显式给 owner）。
   - `telemetry` / `command_log`：无法证明归属的行**复制**进 `legacy_row_archive`（`UNIQUE(source_table, source_pk)` + 完整 payload + 校验和），**P0 不删源行**——归档、校验、删除三步之间只要夹任何 DDL 或跨进程，崩溃就会丢数据或无法安全重跑。源行删除与旧列 drop 一起移到 P1。
   - 现有 2 行 user 的处置见第 6 条。
   - 这一步是纯 DML，可以整体重跑；重复执行结果必须完全相同（幂等断言：跑两遍后 `SELECT COUNT(*)` 与校验和不变）。
5. **0004 verify（只读断言，不改数据）**：迁移自己用 SQL 判断，失败即 `raise` 阻止后续：
   - `COUNT(*) FROM device WHERE status='bound' AND owner_id IS NULL` = 0，且反向 `status='claimable' AND owner_id IS NOT NULL` = 0（I1 的推广）；
   - `COUNT(*) FROM (SELECT owner_id FROM device WHERE owner_id IS NOT NULL GROUP BY owner_id HAVING COUNT(*)>1)` = 0（uq_device_owner 生效）；
   - `telemetry` / `command_log` 里 `device_pk IS NULL` 的行必须全部能在 archive 中找到同 `(source_table, source_pk)`；
   - `COUNT(*) FROM user WHERE role='admin' AND status='active'` = 0（迁移后必然无管理员，见第 6 条）——这条同时用来验证「没有偷偷留下可用管理员」。
6. **0005 contract（收紧约束，单独一次 DDL）**：`ALTER TABLE ... MODIFY owner_id INT NULL`（**device.owner_id 永远保持可空**，可认领池的定义就依赖 NULL）、给 `telemetry`/`command_log` 加 FK、给 `device` 加 `UNIQUE uq_device_owner(owner_id)`、加 CHECK（I1）。
   `telemetry.device_pk` / `command_log.device_pk` / `binding_epoch` 的 `NOT NULL` **必须在 P0 之后单独一批**（见下条），因为它有一个发布窗口问题。

**关于 NOT NULL 的发布窗口（第十一轮点名，v9 漏了）**：只做 backfill 就 `ALTER ... NOT NULL` 会让「旧实例仍在跑、有写路径还没加这一列」的部署在上线瞬间写入全部失败。正确顺序是四段：**先部署所有 writer 的兼容代码（写入端已填 device_pk/be）→ backfill → 持续观测「零 NULL 写入」一段时间 → 停/排空旧 writer → 再 contract**。P0 只做到「非空由代码保证 + 一条测试断言新写入不为空」，列级 NOT NULL 放 P1 与 §13 的收口批一起。

6. **处置现有 2 行 user**，五个副作用都要一次处理干净：
   - `username` 改为 **`~legacy~<id>`**（**不是** `legacy_<id>`：后者完全匹配 backend/app/routers/auth.py:47 的 `USERNAME_RE = re.compile(r"[a-zA-Z0-9_\u4e00-\u9fa5]{3,20}")`，等于一个没人占用的合法新用户名，可能被真人注册走）。`~` 不在字符集内，天然不是可注册名。
   - `password_hash` 改为**格式合法、对应随机未知密码**的 bcrypt 串。不能填 `'x'` 之类的假值：验证器遇到非法格式会抛 `Invalid salt` → 500，而不是「密码错误」。
   - `status` 置 `disabled`，且登录路径**先查 status、后比密码**（见 §8 第 10 项），双保险。
   - 不删除行，保留历史外键（历史数据引用的是数字 id，改 username 不会断链）。
   - 原用户名释放后可被新账号注册——**所有审计、所有本地缓存分区因此必须以 user_id 为身份依据，不能以 username 为身份依据**。
   之后系统处于「无 active admin」状态，必须执行 11.1 的 `python -m app.cli create-admin <用户名>` 建新管理员（网页端无任何初始化入口）。
7. 跑 cli register-device + 幂等 seed 重建初始数据。
8. 校验：两账号交叉查询、归档行不可见、备份可恢复。**生产回退靠恢复备份，不把 downgrade 描述成可靠回退。**
9. 备份文件 7 天内清理，访问限本机。

## 11. 配置与运维

| 项 | 处置 |
|---|---|
| JWT_SECRET 默认值 | 启动断言：等于默认值或长度<32 拒绝启动（ALLOW_INSECURE_SECRET=1 仅本机） |
| DB_URL 明文默认口令 | 去掉默认值，缺失即失败；.env.example 用占位符 |
| CORS * + credentials | 显式 allow_origins |
| host 0.0.0.0 / reload=True | 127.0.0.1 / reload=False |
| 多实例 | GET_LOCK 专用长连接，拿不到即退出 |
| 初始管理员 | **系统内不存在任何预置口令**，改为纯 CLI 建号（`create-admin`），见 11.1。后端目录与 `backend/.env`、DB 口令的 ACL 必须一并收紧 |
| 登录限流 | 账号桶 + IP 桶（删除无标识可用的设备桶），超限 403+40300+reason=rate_limited+retry_after。**桶必须落在可信入口**：进程内桶在多 worker 下不共享，P0 以 `workers=1` 成立；将来多进程要换 Redis 或网关限流，不能假装进程内桶是全局限流。**客户端 IP 只认 socket 地址**，`X-Forwarded-For` 仅当请求来自配置里的可信代理名单时才参与解析——否则任何人伪造一个头就换一个桶。 |
| 配对码 DoS | 承认「任意人连错 5 次可锁死设备」是允许路径，管理员 cli issue-claim-code 恢复 |

## 11.1 初始管理员：纯 CLI 建号（推翻 admin/admin123）

### 为什么原方案不成立

`must_change_password` 只是把「任何人可登录」换成「任何人可抢先登录并改密后接管」。攻击者不需要知道你的密码，只需要比你先按一次登录——这是**先到先得型**漏洞，靠 WARN 和文档关不掉。所以整条预置口令的路都必须拆掉。

### 为什么最终选「纯 CLI」而不是「一次性引导令牌 + /setup 网页」

两版都成立，取舍在于**初始化入口要不要出现在网络上**。令牌版（v7）为了「网页也能初始化」付出了：一个未认证但能创建管理员的 HTTP 端点、一份 43 字符文件凭据的生命周期（生成 / icacls / 消费 / 删除 / reset）、一个前端 /setup 页面及其守卫。

而本项目的部署前提本身就写着：**后端必须在那台笔记本上手动启动**（`cd backend && python run.py`，串口 COM5 也挂在那台机器上）。也就是说「能跑后端的人」恒等于「能开这台机器终端的人」。既然 shell 访问是既有前提，初始化走 CLI 就不增加任何新的信任假设，反而让攻击面从「网络端点」退回到「本地进程」。

令牌版**不是**致命缺陷（回环 + 高熵 + 事务复核，远程接管不现实），砍掉它是因为复杂度换不来收益：这个项目没有任何「无 shell 也要初始化」的场景。

### 目标状态

**代码、seed、迁移、文档、前端里都不再出现任何形如 `admin/admin123` 的可用凭据。** 系统冷启动处于「未初始化」状态，唯一初始化路径是后端目录里的 shell 命令。

### 三条 CLI 命令（`python -m app.cli ...`，全部在 backend 目录执行）

**① `create-admin USERNAME`** —— 冷启动建第一个管理员

```
cd backend
python -m app.cli create-admin luowen
```

- 密码用 `getpass.getpass()` 交互读两遍，**不接受 `--password` 参数、不读环境变量、不读 stdin 管道**（否则密码进 argv / shell 历史 / 父进程环境）。
- **先判定终端，再读密码**（顺序照抄，缺一步就漏）。单纯 `except GetPassWarning` 是无效的——它默认是 warning 不是异常，且在 Windows 上 `Get-Content x | python -m app.cli ...` 这种管道**根本不会触发它**（CPython 的 `sys.stdin` 仍等于 `sys.__stdin__`，`msvcrt.getwch()` 继续从控制台读键盘），所以必须自己判：
  1. `sys.stdin` / `sys.__stdin__` / `sys.stderr` 任一为 `None` → 失败（`pythonw.exe` 场景）；
  2. `sys.stdin is not sys.__stdin__` → 拒绝（标准输入被替换）；
  3. `not sys.stdin.isatty()`（捕 `AttributeError`/`OSError`/`ValueError`）→ 拒绝（管道 / 重定向 / VS Code 输出面板）；
  4. `with warnings.catch_warnings(): warnings.simplefilter("error", getpass.GetPassWarning)` 再 `getpass.getpass()`，捕 `(GetPassWarning, EOFError, OSError, KeyboardInterrupt)`；
  5. 两次读取（密码 + 确认）都套同一层保护，不能只护第一次。
- 用户名走 `argparse` 位置参数（进 shell 历史无害），校验沿用 `auth.py:47` 的 `USERNAME_RE`。
- 密码长度 ≥10，两次输入必须一致，不一致退出码 2。
- 执行顺序（**锁永远在第一次读之前**，连接契约见 §4.6）：在一条新的物理连接上 `SELECT GET_LOCK('petdog:admin:v1', 10)`，结果 = 1 才继续（0/NULL 即退出码 3）→ **同一连接**开事务 → `COUNT(*) WHERE role='admin' AND status='active'`（必须是本事务第一次业务表读取），非 0 即 rollback + 退出码 1 → 插入 `User(bcrypt, role=admin, status=active)` → 写 `device_audit(action=register_admin, device_pk=NULL)` → COMMIT → `RELEASE_LOCK`（放 finally；释放失败即销毁该连接，不带锁回池）。
- 密码哈希**在拿锁之前**算完（bcrypt 是数百毫秒级别，别占着全局管理员锁做 CPU 活）。
- 死锁 1213 / 锁等待超时 1205 / 拿不到 `GET_LOCK`：显式 `rollback()` 后用退出码 3 提示「请重试」，不做半途重试。

**② `reset-admin USERNAME`** —— 唯一 active 管理员忘记密码 / 令牌全失效时的恢复路径

```
cd backend
python -m app.cli reset-admin luowen
```

- **不是 create-admin 的别名**（v7 的 `reset-bootstrap` 在这里是错的：它只在 `admin_count==0` 时可用，而真正需要恢复的场景恰恰是「管理员仍 active 但登不进去」，计数是 1）。
- 语义：把**指定现存账号**的密码重置为新密码，并 `token_version += 1`（踢掉所有旧会话），写 `device_audit(action=reset_admin_password)`。
- **`tv += 1` 必须与 enable 同事务**：disabled 期间旧 JWT 只是「查库拒绝了」，它的签名和过期时间都还活着；若启用时不递增版本，那个旧 token 会在账号变回 active 的瞬间重新有效。reset / enable / 改密三条路径都要 +1，且 JWT 里带 `tv`、每次鉴权与库值比对（§2.2）。
- 前置（v9 这里自相矛盾过：写「必须 active」会让 `--enable` 永远无法处理 disabled 账号，已改）：目标行必须 `role='admin'`；
  - `status='active'` → 直接重置；
  - `status='disabled'` → **默认拒绝**，只有显式 `--enable` 才在同一事务里「改回 active + 重置密码 + 写 `device_audit(action=enable_admin)`」；静默接受 disabled 是操作陷阱（命令成功、密码换了、人还是登不进去）；
  - `revoking` / `revoked` → 一律拒绝（终态，不该被 CLI 复活）。
- 锁：与其它 admin 路径同一把 `GET_LOCK('petdog:admin:v1', 10)`，同一物理连接、锁内读、锁内写（§4.6）。
- 不要求 `COUNT(*)=0`：恰恰相反，它服务的就是「计数为 1 但人登不进去」这个场景。
- 本命令**不创建新账号**，因此不存在「攻击者用它凭空获得管理员」。攻击者要能用它，先得能改数据库或能在这台机器上跑命令——那时游戏已经结束。

**③ `list-admins`** —— 只读，打印 `id / username / status / created_at`，用于确认「到底还有没有管理员」。不打印任何哈希。

### 并发

两个 `create-admin` 同时跑：都先拿同一把命名锁，第二个拿到锁后才读到真实 `COUNT(*)=1`，直接退出码 1。**不靠 `UNIQUE(username)`**（用户名不同就挡不住）。

命名锁的生命周期由 MySQL 保证：连接断开即自动释放，进程崩溃不会留下死锁（这正是不用「单行表 + FOR UPDATE」的原因——那种写法的锁点是数据行，行没了就永久自锁）。同一把锁必须被 `create-admin` / `reset-admin` / 封禁 / 解封 / 注销 / 降权**全部**使用，只用在一处等于没锁。

### 一致性：只有一份真相源

- **不存在缓存计数**。`active admin` 永远是锁内 `COUNT(*) FROM user WHERE role='admin' AND status='active'` 现算的结果。
- 删除缓存正是为了删掉一条自锁路径：v8 的规则是「缓存与真实值不一致就拒绝」，而校验命令只查不修——于是最需要救援的时刻（有人手动改过库、某条路径漏了锁），建号与重置会**同时**拒绝，只能人工写库。现在这条路径不存在了，因为没有可漂移的第二份数据。
- 只读诊断命令 `python -m app.cli check-consistency` 保留，但只报告**模型级不变量**：`I1` 三条等价关系、`status='bound'` 但 owner 为空的设备、`status='claimable'` 但 owner 非空的设备、`uq_device_owner` 是否出现重复 owner、`telemetry`/`command_log` 是否有 NULL 的 `device_pk`/`binding_epoch`。它**不阻塞任何管理命令**——诊断工具不该成为救援的守门人。

### 前端要改的（比令牌版少一整页）

- `GET /api/setup/status` → `{ setup_required: bool }`，只读、无副作用、`Cache-Control: no-store`。**不暴露管理员数量、不暴露恢复原因、不暴露 CLI 存在**。
- 登录页在 `setup_required === true` 时显示固定文案：「系统尚未初始化，请在后端目录运行 `python -m app.cli create-admin <用户名>`」，并**禁用登录按钮**（此时库里没有任何可登录账号，让用户点了再报 40001 是浪费）。
- 该布尔值**只能决定 UI 提示，不能当授权依据**；后端所有鉴权仍按 `user.status` + `token_version` 查库判定。
- **门禁判定只认这一种成功形态**：HTTP 200 **且** 响应体 `code === 0` **且** `data` 是对象 **且** `data.setup_required === true`（与 backend/app/resp.py:12 的统一信封一致）。其余全部保持普通登录形态：网络错误、超时、401、404、**500**、非 JSON、缺字段、字段不是布尔——一律 fail-open。理由：把「探测失败」当成「未初始化」会让一次后端抖动把所有人的登录页锁死。
- 这个探测必须用**独立的、没有拦截器的客户端**发，不带 `Authorization`——否则浏览器里残留的旧 token 会触发全局 401 清理/跳转，登录页会自己把自己踢成循环。
- 该探测**只控制 UI**，不承担任何服务端授权。

### 与既有账号生命周期的衔接（补的两条硬约束）

1. **进入 `revoking` 的那一刻就要做「最后一个 active admin」检查**，不能等清理完成——否则中间态里可能存在 0 个 active admin。
2. 每次鉴权都必须复核 `user.status` 与 `token_version`（`deps.py` 查库，见 §8 第 6 项）。状态是 `revoking`/`revoked` 一律 401，不因为 JWT 未过期而放行。

### 配套改动（6 处，全部必须）

1. `backend/seed.py:11-13` 删除 admin 创建（只保留建表/幂等基础数据）。
2. `.gitignore` **不需要**再加凭据文件条目（方案 B 不落任何令牌文件）；但要确认 `backend/.env` 已被忽略。
3. 迁移处置现有 2 行 user（见 §10 第 6 步），完成后系统处于「无 active admin」状态。
4. **不新增 `system_guard` 表**（v9 起删除）。互斥用 MySQL 命名锁，无需任何迁移插入的行，也就没有「行被删了怎么办」这个问题。
5. `backend/app/cli.py` 提供 `create-admin` / `reset-admin`（`--enable`）/ `list-admins` / `check-consistency` / `retire` / `reinstate`，与既有的 `register-device` / `issue-claim-code` / `promote-demo` / `export-legacy` 同一个入口。`retire` / `reinstate` 的 DML 见 §4.2，两者都必须写 `device_audit`。
6. `backend/app/routers/setup.py` 只保留 `GET /api/setup/status`；**不提供任何 POST**。

### 为什么这条路仍然闭合

| 威胁 | 方案 B 的答案 |
|---|---|
| 陌生人打开网页先登录抢账号 | 库里没有账号，登录必然失败；也没有任何 HTTP 端点能建号 |
| 局域网里有人想初始化 | 初始化不是网络操作，必须有本机 shell |
| 备份/同步/误提交泄漏凭据 | 不存在凭据文件，无可泄漏物 |
| 两个初始化并发 | 同名 `GET_LOCK` 互斥 + 锁内现算 count，恰好一个成功 |
| 管理员忘记密码 | `reset-admin` 重置现存账号密码并 `tv+1` |
| 管理员被误删/库被清空 | `create-admin` 在 active admin 数为 0 时可用；能跑它说明已有 shell/DB 权限 |
| 密码泄露到 argv/历史/环境 | 只走 `getpass`，无参数、无环境变量、无管道输入 |

### 演示场景的代价

从「打开就登录」变成「在后端目录跑一次 `create-admin`，输两遍密码」。约 20 秒，一次性，且答辩时可以直接现场演示「系统里没有任何默认口令，第一个管理员是我用命令行建的」。比令牌版少一步（不用去文件里复制 43 字符）。

### 残余风险（替换 v6 第 1 条）

- **能在这台机器上开 shell 的人就能建/重置管理员**：这是刻意的等价于「物理接触」，不是漏洞。
- 本机被完全控制（恶意进程、键盘记录、`getpass` 被 hook）→ 任何方案都挡不住，明确承认。
- 后端目录与 `.env`、数据库口令的 Windows ACL 仍需收紧（与 §11 表里的 DB_URL 项合并处理）：本方案只是把「建管理员」的门槛统一到「能读后端目录」这一层，不再额外要求更高的门槛。
- `reset-admin` 无法防「已经能改数据库的人」——那种情况下对方可以直接写 `password_hash`。

## 12. 测试（P0 必须实跑真实 MySQL，非 mock）

1. A 看不到 B 的设备（列表/详情/状态三条）。
2. A 用 B 的 device_id 写操作 → 40400；PATCH 改名不生效。
3. 同码两人并发 claim → 恰好一人成功，另一人 40900；be 只 +1。
4. 错码 4 次后：错码 A 提交 5 → 锁定；正确码 B → 拒绝且不绑定。
5. 正确码先消费 → 之后错码不再增 attempts（不出现第 6 次）。
6. 解绑后可被他人认领；换绑后新主人看不到旧主历史。
7. 改密后本人历史仍可见（be 未变），旧 token 401。
8. 注销并发 claim → 绝不出现设备归已注销账号。
9. 注销后设备回 `claimable`（owner_id NULL + status='claimable'）、用户名可同名重注册、旧 token 全 401、scene/face 已删、telemetry 保留但对新主人不可见。
10. 封禁登录 → 403+40300；旧 token → 401。
11. 同一用户并发认领两台 → 只有一台成功（uq_device_owner）。
12. 同一用户多标签页同码 → 幂等成功，不报冲突。
13. 重签后旧码立即失败。
14. 最后一个 active admin 注销/封禁/降权/禁用 → 拒绝（四条路径都测，验证共用同一把命名锁；再加一条并发测试：两个请求同时想清掉最后两个 admin 中的不同人，结果必须至少剩一个）。
15. **代码层非空**：在写入端（不是读端）断言 `device_pk` / `binding_epoch` 非空，断言失败即抛错并回滚；再跑一次 `SELECT COUNT(*) FROM telemetry WHERE device_pk IS NULL` 与 command_log 同形查询 = 0。**这条测的是 P0 的代码保证，不是列约束**（列级 NOT NULL 随 §10 第 5b 条的收口批一起上，那时这条测试再补一条「直连 INSERT NULL 被数据库拒绝」）。
16. 归档行普通查询与普通管理员接口均不可见，仅 CLI 导出。
17. 冷启动无 admin 时 `GET /api/setup/status` 返回 `setup_required=true`。**没有初始化端点**这一点用路由表断言而不是猜路径：读出 app 的 routes，断言 `/api/setup/*` 前缀下只有 GET 一条、无任何 POST/PUT/DELETE 注册；再补两条黑盒探针——`POST /api/setup/status` → 405，`POST /api/setup/anything-else` → 404（**不存在的路径是 404，不是 405**）。
18. `create-admin` 成功后 `setup_required=false`；再次运行 `create-admin` → 退出码 1 且库内 admin 数不变。
19. 两个 `create-admin` 并发 → 恰好一个成功，另一个退出码 1，active admin 恒为 1、审计恰好一条。**防回归断言改为静态检查**：`information_schema.tables` 里不存在 `system_guard`，代码与迁移里也没有对它的读写（第十二轮指出 v9 的「手动 DELETE 守卫行」在没有守卫表时没有真实目标，跑不了）。
20. `reset-admin` 在「唯一 admin 仍 active 但密码未知」时可用：重置后可登录、旧 token 全部 401、`tv` +1、active admin 数不变。`reset-admin` 对 `disabled` 账号默认拒绝；加 `--enable` 后成功且该账号变回 active 并写一条 `enable_admin` 审计。
21. `reset-admin` 对 `revoking`/`revoked` 账号 → 拒绝。`check-consistency` 对 `I1` 违反 → FAIL 且**它 FAIL 不影响 create-admin 与 reset-admin 继续可用**（诊断不是守门人）。**注入方式必须换**：0005 的 CHECK 生效后，正常途径插不进违反 I1 的行（能插进去才说明约束没建上）。改为两层——(a) 在 0004 之前的 fixture 库（还没加 CHECK）注入违规行，跑 `check-consistency` 断言 FAIL；(b) 最终库上用直连 SQL 尝试写 `owner_id=NULL, bound_at=NOW(), status='bound'`，断言被数据库**拒绝**（这同时是 CHECK 真的生效的证明）。
22. `seed.py` 与迁移跑完后，库里不存在任何可用的预置凭据（用 admin/admin123 登录必须失败）。
23. `getpass` 回退（无 tty）时必须中止，不得明文回显并要求重输；`create-admin --password` 这类参数不存在（argparse 未定义即报错）。
24. **发布物凭据门禁**（不是裸 grep）：扫 (a) `git ls-files` 列出的 tracked 文件里「密码字段 + 禁用值」的上下文，(b) 解包后的 .docx/.xlsx/.pptx 内部 XML，(c) **tracked 的 `.pyc` 与正式发布包里不含字节码**，(d) 运行期请求一次 `/openapi.json`，(e) 生产 `npm run build` 产物 `dist/`。全部零命中才通过。**「工作区所有 `.pyc` 为零」不是合法断言**——只要跑过 Python 就会重新生成，临时缓存目录不进安全门禁。裸 grep `123456` 会被 vendored 的 Swagger UI 与 Axios 数字字符表误报，同样不能当断言。
25. **匿名注册不构成越权**（拆成两条，因为 claim 不能算在「按 device_id 定位的资源路径」里）：(a) 未初始化状态注册普通账号 → 设备列表为空，且**按 device_id 定位的资源路径**（详情/状态/PATCH/binding/ticket）对他人的设备一律 40400（backend/app/routers/devices.py:25 现在只验 token 不查 owner，这条就是钉死它的）；(b) 同一账号持**有效码**对一台 claimable 设备 claim → **必须成功**（集合级动作走独立授权规则，不能被 (a) 顺手封死）。
26. **前端门禁 fail-open**：`GET /api/setup/status` 返回 500 / 超时 / 非 JSON / 缺字段 / 字段非布尔时，登录页保持可登录形态（只有 HTTP 200 且 `setup_required === true` 才禁用登录按钮）；该请求不得带 Authorization、不得触发全局 401 跳转。
27. **retired 不可被认领**（必须用**两台**设备，否则「retired 之后又变回 claimable」的写法会被读成同一条设备）：设备 A 被认领 → 管理员 retire（同事务撤销 claim code）→ A 既不出现在 `/claimable`，持旧码 claim A 也一律失败，直到管理员 `reinstate`；设备 B 属于另一个账号 → 该账号注销（auto_unbind）→ B 回到 `claimable` 可被他人认领。A 与 B 的行为必须不同。
28. **迁移中断可重跑**：随机 `kill` 没有确定性断点，人工和 CI 都复现不了。改为在 0003 里放一个**仅测试环境生效的 failpoint**（读到环境变量 `PETDOG_MIGRATION_FAILPOINT=after_archive_write` 时在该点 `raise SystemExit(9)`，生产环境变量不存在则该分支不被编译执行）→ 跑 `upgrade head` 必然停在该点 → 再次 `upgrade head` → 最终 schema、数据、归档行、admin 计数与「一次跑完」的**规范化摘要**（各表 `COUNT(*)` + 关键列 `CHECKSUM TABLE` 或排序后 hash）逐项相等。这是四个 revision 真幂等的唯一证明。
29. **备份恢复演练**：mysqldump 一份 → 恢复到空库 → 跑 `alembic upgrade head` → 两个账号交叉查询结果与原库一致。**生产回退走这条，不走 downgrade。**
30. **旧浏览器存储清理**：手工写入旧键 `petdog_mock_users`（含明文密码）→ 打开前端 → 启动迁移后该键被删除且写了 `petdog_schema_version`；再次刷新不重复执行。
31. **开工第一天就要写的这条**（第十三轮指定，因为它一次覆盖本轮风险最高的 INSERT 分支、设备行锁、唯一键、事务回滚、`be` 规则与审计原子性）：造一台**从未生成 claim 行**的设备（表里零行）→ 执行 `retire` → 并发执行两次 `reinstate` → 断言恰好一次成功、另一次 40900，最终表里恰好一条 `active` claim 行、设备为 `claimable`、`be` 只因 retire 增加过一次、`reinstate` 审计恰好一条。

## 13. 分期

**P0（15–22 工作日，单人全职；第十一轮明确否掉了「压到 10 日」）**：第2 数据模型（不含 dg）、第3 状态机、第4 事务（claim 完整实现）、第5 授权、第7 契约改造、第8 全部、第9 前端全部、第10 迁移、第12 的 P0 自动化子集。

| 阶段 | 工作日 | 内容 |
|---|---|---|
| 迁移与恢复演练 | 2 | 拆 create_all、0001–0005 四段、verify 断言、`pet_dog_verify` 里跑一遍中断重跑、一次 dump→restore |
| ownership / claim | 2.5 | owner 过滤与 40400、claim CAS、retired 语义、`uq_device_owner`、真实 MySQL 并发 |
| 管理员生命周期 | 1.5 | create-admin / reset-admin / list-admins、§4.6 连接契约、四条路径共用同一把锁 |
| 凭据与注册 | 1 | 删默认秘密 + 轮换、bcrypt、注册边界、限流 |
| 前端收口 | 1 | 去 id=1、user.id 分区、跨标签页、空态、/account、旧键清理 |
| 真实 MySQL 测试与验收 | 2 | 下述自动化子集 + 手工清单 |

**P0 必须自动化的是 13 条**（其余 18 条写成手工核对清单，答辩前逐条走一遍即可）：3（同码并发）、4（错码锁定）、8（注销并发 claim）、9（注销全链路）、10（封禁）、11（`uq_device_owner`）、14（最后管理员四路径 + 并发）、19（并发 create-admin）、20（reset-admin 与 --enable 的 tv）、27（retired 不可认领）、28（迁移中断重跑）、29（备份恢复）、31（reinstate 的 INSERT 分支与并发）。剩下 18 条里，1/2/6/7/13/25 是**手工两账号交叉验收**（必须真点一遍，不能只靠自动化测试假装覆盖 UI），24/26 是发布前门禁脚本。

**P1（15–25 工作日）**：命令通道（串口/CmdQueue/SendGate/seq 退休/心跳 9s/online）、WS（票据+hub+撤销协议）、`dispatch_generation` 迁移 0006、faces/scenes/logs/telemetry 路由与页面、OLED 0x0C、admin 页面、六个竞态测试（出队后解绑、旧场景继续下发、迟到帧跨换绑、WS 建连撞撤销、同浏览器切账号、双进程互斥），以及**被 P0 有意推迟的收口批**：legacy 源行删除与旧列 drop、archive 压缩、`telemetry`/`command_log` 的列级 NOT NULL（§10 那条发布窗口）、完整 Git 历史重写（前提：全部真实秘密已轮换）、全并发矩阵与故障注入、跨标签页即时 UI 同步、浏览器兼容矩阵、多版本多拓扑恢复演练。
**P2**：多设备（device_uid 自动注册 + 全入口显式 device_id）、家庭成员与角色、自助找回、数据导出与隐私说明、历史档案。

## 14. 残余风险（承认，不假装解决）

1. 初始化与管理员恢复完全依赖本机 shell 访问——这是刻意的「等价于物理接触」。同机能开终端的人即可建/重置管理员；本机被完全控制（键盘记录、`getpass` 被 hook）时任何方案都无法防御，明确承认。
2. 硬件归属无法强证明：帧无 UID，配对码是人肉带外信道；真设备认证等 P2 出厂 UID。
3. 交接清理只能尽力：协议无复位命令，只能用 0x31 站立 / 0x45,0x47 关灯 / 0x07 重置表情，不承诺设备已清空。
4. 签名 URL 是 bearer 分享：持有者可读，撤销只保证服务端不再读取。
5. 单实例约束：GET_LOCK 意味着不能水平扩展。
6. 用户名可复用 → 本地缓存必须按 user.id 分区，否则同名新账号读到旧缓存。
7. 唯一管理员消失：靠 CLI `reset-admin` 恢复，不做自助。
8. 设备遗失/丢弃：retired 状态 + 管理员强制释放，无自动化。
9. 归档数据仅 CLI 导出，无自助。
10. 旧行时区不可知，只标 data_origin，不猜。
11. P0 每账号 1 台是产品限制，不是模型限制（uq_device_owner 去掉即可放开）。

## 15. Codex 前置条件的落点（九项 + 第十一轮六项 + 第十二轮三条）

| 前置条件 | 落点 |
|---|---|
| 初始管理员无预置口令 | 11.1 纯 CLI `create-admin` + `GET_LOCK` 命名锁 + `reset-admin`（含 `--enable`） |
| 演示授权口径不混称 | demo_grantee_user_id 单账号免码，锁后复跑策略 |
| 撤销线性化 | P0=数据库提交点；P1=发送锁，锁内提交 |
| epoch 语义二选一 | 只留 binding_epoch（可见性），改密靠 tv；dg 移 P1 |
| 配对码事务 | 错码先提交计数；正确码同事务消费+绑定+审计 |
| 旧数据不可回填成可见 | 归档表 + 代码层强制非空（列级 NOT NULL 走 §10 发布窗口，不拿 NULL 造特例） |
| 会话隔离 | 先换代次；User.id 分区；storage 事件跨标签页 |
| P0 可用范围收窄 | 导航隐藏 + 路由守卫 + 禁止自动取票 |
| P1 上线门槛 | SendGate、异常写入归类、WS 撤销协议与通道同时验收 |
| 命名锁是同连接契约（第十一轮） | §4.6：同一物理连接持锁 + 执行事务，释放失败即销毁连接 |
| reset 分支与 tv 一起改（第十一轮） | §11.1 命令②：active 直通 / disabled 需 --enable / revoking·revoked 拒绝；三条路径 tv+1 |
| 迁移四段可重入（第十一轮） | §10：0002 expand / 0003 backfill（P0 只复制不删源行）/ 0004 verify / 0005 contract |
| retired 状态化 CAS（第十一轮） | §3 设备状态机 + §4.2：认领判据 `status='claimable' AND owner_id IS NULL`，retire 同事务撤码 |
| 注册与 claim 路径边界（第十一轮） | §5.1 路径边界 + §8 第 10 项注册立场 + §11 限流可信入口 |
| 凭据轮换闭环（第十一轮） | §7.1 处置动作矩阵 + 测试 24/30 |
| retire/reinstate 可执行（第十二轮） | §4.2 两项 DML + §3 配对码状态机补 `used --reinstate--> active` 原地转移 + §2.1 `device_claim` 单行约束说明 |
| 审计 CHECK 名单写全（第十二轮） | §2.1 `device_audit`：账号级七个动作 device_pk NULL、其余 NOT NULL，枚举一次写全 |
| 测试可确定性复现（第十二轮） | §12 第 15/17/19/21/24/25/27/28 条重写：路由表断言、fixture 库注入、两设备对照、迁移 failpoint |