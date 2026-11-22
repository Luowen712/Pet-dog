import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles
from serial import SerialException

from app.config import settings
from app.db import SessionLocal, engine
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.errors import register_handlers
from app.link.device_session import (
    HEARTBEAT_INTERVAL_SEC,
    DeviceSession,
)
from app.link.lock import LOCK_NAME, HostProcessLock, ProcessLock
from app.link.send_gate import send_gate
from app.link.serial_link import LinkClosedError, SerialLink, open_port
from app.models import Device
from app.ratelimit import assert_single_process
from app.resp import ok
from app.routers import auth, control, devices, faces, setup
from app.services.events import Events
from app.services.control import ReceiptWriter
from app.link.device_session import SUPPORTED_CORE_ACTIONS
from app.services.purge import purge_revoking

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
PROTOCOL_VERSION = "3.1"

# 06:46 禁止 allow_origins=["*"] 与 allow_credentials=True 同时开启。
# 02:16 约定 config.py 归 BB02 唯一合入，因此此处用环境变量 PETDOG_CORS_ORIGINS
# 允许开发期扩展白名单（逗号分隔，显式过滤 "*"），默认放行本机 Vite 常用端口 5173/5174。
_DEFAULT_DEV_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]


def _resolve_cors_origins() -> list[str]:
    raw = os.environ.get("PETDOG_CORS_ORIGINS", "").strip()
    if not raw:
        return list(_DEFAULT_DEV_CORS_ORIGINS)
    origins = [item.strip() for item in raw.split(",") if item.strip() and item.strip() != "*"]
    return origins or list(_DEFAULT_DEV_CORS_ORIGINS)


def _health_mode() -> str:
    spec = settings.SERIAL_PORT.strip().lower()
    if spec == "sim" or spec.startswith("loop://"):
        return "sim"
    if spec == "ble" or spec.startswith("ble://"):
        return "ble"
    return "serial"


def _require_schema():
    expected = set(ScriptDirectory(str(BASE_DIR.parent / 'alembic')).get_heads())
    with engine.connect() as conn:
        current = set(MigrationContext.configure(conn).get_current_heads())
    if current != expected:
        raise RuntimeError(
            f"数据库版本不匹配：当前 {','.join(sorted(current)) or '未迁移'}，需要 {','.join(sorted(expected))}。"
            "请备份并在副本完成 Alembic 迁移演练；不会自动迁移或更改设备归属。"
        )


def _resolve_device_pk(app: FastAPI) -> int | None:
    pk = getattr(app.state, 'device_pk', settings.SERIAL_DEVICE_PK)
    with SessionLocal() as db:
        if pk is not None:
            if db.get(Device, pk) is None:
                raise RuntimeError('SERIAL_DEVICE_PK 未指向已登记设备')
            return int(pk)
        rows = db.query(Device.id).limit(2).all()
    if len(rows) > 1:
        app.state.device_session_error = 'ambiguous_serial_device'
        logger.error('有多台设备，设置 SERIAL_DEVICE_PK 后重启以启用串口控制')
        return None
    return int(rows[0][0]) if rows else None


async def _session_maintenance_loop(
    session: DeviceSession,
    *,
    heartbeat_interval: float = HEARTBEAT_INTERVAL_SEC,
    check_interval: float = 1.0,
) -> None:
    """后台调度任务（06:219 每 3 秒发 04 心跳；06 第 12.1 节 9 秒无上行判 offline）。

    异常保护：
        - check_uplink_timeout 可能触发写库（关闭会话/标 unknown），放进 asyncio.to_thread，
          避免 DB 抖动阻塞事件循环里的心跳和 HTTP；
        - 除 CancelledError 和链路已关闭/故障外，任何未预期异常只记日志并继续下一轮，
          不让心跳与看门狗静默停摆。
    """
    loop = asyncio.get_running_loop()
    last_hb = loop.time() - heartbeat_interval  # 启动后尽快发首帧心跳
    step = max(0.01, min(check_interval, heartbeat_interval))
    try:
        while True:
            try:
                now = loop.time()
                if session.control_state == "faulted":
                    return
                if (now - last_hb) >= heartbeat_interval:
                    try:
                        session.send_heartbeat()
                    except LinkClosedError:
                        return
                    except Exception:
                        logger.exception("后台心跳入队异常")
                    last_hb = now
                # 已上线且通过准备门禁、仅差首帧 0x03 快照时主动催一次状态（内部限频 ≥1s），
                # 既让真机上线后不必苦等 5 秒周期，也让无线程 SIM 自动进入 ready。
                if session.online and session.control_state == "unconfigured":
                    try:
                        session.poll_status()
                    except LinkClosedError:
                        return
                    except Exception:
                        logger.exception("后台首帧催状态异常")
                try:
                    session.check_command_timeout()
                    await asyncio.to_thread(session.check_uplink_timeout)
                except Exception:
                    logger.exception("后台上行超时检查异常")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("后台会话维护循环捕获未预期异常，继续下一轮")
            await asyncio.sleep(step)
    except asyncio.CancelledError:
        return


async def stop_device_session(app: FastAPI) -> None:
    ticker_task = getattr(app.state, "ticker_task", None)
    app.state.ticker_task = None
    if ticker_task is not None:
        ticker_task.cancel()
        try:
            await ticker_task
        except asyncio.CancelledError:
            pass

    session = getattr(app.state, "device_session", None)
    if session is not None:
        try:
            await asyncio.to_thread(session.close)
        finally:
            app.state.device_session = None


async def stop_ble_session_if_matching(app: FastAPI, device_pks: set[int]) -> None:
    """解绑或注销后若当前占用动态 BLE 链路，主动断开以便 ECB02H2 重新广播。"""
    if not device_pks:
        return
    from app.link.ble_link import BleBytePort

    async def _maybe_stop() -> None:
        sess = getattr(app.state, "device_session", None)
        if (
            sess is not None
            and sess.device_pk in device_pks
            and isinstance(getattr(sess._link, "_port", None), BleBytePort)
        ):
            await stop_device_session(app)

    session_lock = getattr(app.state, "session_lock", None)
    if session_lock is not None:
        async with session_lock:
            await _maybe_stop()
    else:
        await _maybe_stop()


async def start_device_session(
    app: FastAPI,
    device_pk: int,
    *,
    port=None,
    port_spec: str | None = None,
    is_sim: bool | None = None,
) -> DeviceSession | None:
    await stop_device_session(app)

    loop = asyncio.get_running_loop()
    process_lock = getattr(app.state, "process_lock", None)
    receipts = getattr(app.state, "receipts", None)
    spec = (port_spec if port_spec is not None else settings.SERIAL_PORT).strip()
    port_override = getattr(app.state, "serial_port_override", None) if (port is None and port_spec is None) else None
    sim_mode = (spec.lower() == "sim") if is_sim is None else is_sim

    if port is None:
        try:
            port = (
                port_override
                if port_override is not None
                else await asyncio.to_thread(open_port, spec, baudrate=settings.SERIAL_BAUD)
            )
        except (SerialException, OSError) as exc:
            # 链路打开失败保持锁不降级，记录故障原因供诊断
            app.state.device_session_error = f"serial_open_failed:{exc}"
            logger.error("打开设备链路失败（保持双锁不降级）：%s", exc)
            return None

    link = SerialLink(
        port,
        baudrate=settings.SERIAL_BAUD,
        loop=loop,
        lock_check=process_lock.still_held if process_lock is not None else None,
        send_gate=send_gate,
        min_frame_gap=getattr(app.state, "min_frame_gap_sec", 0.02),
    )
    # 真实硬件（含 BLE 实板）在完成动作时序验收前不开放运动。
    session = DeviceSession(
        device_pk,
        SessionLocal,
        link,
        process_lock=process_lock,
        send_gate=send_gate,
        loop=loop,
        prepared_marker=getattr(app.state, "prepared_marker", None),
        on_event=(lambda event: receipts.on_event(session, event)) if receipts is not None else None,
        supported_actions=SUPPORTED_CORE_ACTIONS if sim_mode else (),
        auto_prepare_sim=sim_mode or port_override is not None,
    )
    try:
        await asyncio.to_thread(session.start)
    except BaseException:
        link.close(timeout=0.5)
        raise
    app.state.device_session = session
    app.state.device_session_error = None

    hb_interval = float(getattr(app.state, "heartbeat_interval_sec", HEARTBEAT_INTERVAL_SEC))
    chk_interval = float(getattr(app.state, "timeout_check_interval_sec", 1.0))
    app.state.ticker_task = asyncio.create_task(
        _session_maintenance_loop(
            session,
            heartbeat_interval=hb_interval,
            check_interval=chk_interval,
        ),
        name="petdog-session-ticker",
    )
    return session


# 启动钩子（BA02 第 1、5 条）：
# 1. 先取本机排他进程锁，再取 MySQL 实例锁；任一失败拒绝启动，绝不降级无锁运行；
# 2. 清理上次未完成的 revoking 账号；
# 3. 装配唯一 DeviceSession + SerialLink（绑定事件循环、DB 锁写前验活与 SendGate），
#    并启动 3 秒心跳 / 9 秒看门狗后台调度任务；BLE 动态扫描模式等待前端点选连接；
# 4. 关闭时按反序：先停后台任务 → 关设备会话 → 放 DB 实例锁 → 放主机锁。
@asynccontextmanager
async def lifespan(app: FastAPI):
    host_lock_path = getattr(app.state, "host_lock_path", None)
    db_lock_name = getattr(app.state, "db_lock_name", LOCK_NAME)

    host_lock = HostProcessLock(path=host_lock_path)
    process_lock = ProcessLock(name=db_lock_name)

    host_lock.acquire()
    try:
        process_lock.acquire()
    except BaseException:
        host_lock.release()
        raise

    app.state.host_lock = host_lock
    app.state.process_lock = process_lock
    app.state.send_gate = send_gate
    app.state.device_session = None
    app.state.device_session_error = None
    app.state.ticker_task = None
    app.state.session_lock = asyncio.Lock()

    events = app.state.events = Events(asyncio.get_running_loop())
    receipts = app.state.receipts = ReceiptWriter(events)
    unsubscribe = send_gate.register_revoke_listener(events.revoke)

    try:
        _require_schema()
        try:
            db = SessionLocal()
            try:
                r = purge_revoking(db)
                if r["purged"] or r["failed"]:
                    print(
                        "[启动清理] revoking → revoked: %d 个，失败 %d 个"
                        % (r["purged"], r["failed"])
                    )
            finally:
                db.close()
        except Exception as e:
            print("[启动清理] 已跳过（数据库不可用？）：%s" % e)

        # 装配唯一设备会话：纯 ble 模式等待前端扫描后点选直连，其余模式按配置自动建链
        spec = settings.SERIAL_PORT.strip().lower()
        has_override = getattr(app.state, "serial_port_override", None) is not None
        if spec != "ble" or has_override:
            device_pk = _resolve_device_pk(app)
            if device_pk is not None:
                await start_device_session(app, device_pk)

        yield
    finally:
        await stop_device_session(app)
        unsubscribe()
        await asyncio.to_thread(receipts.pool.shutdown, wait=True)
        process_lock.release()
        host_lock.release()


# 限流是单进程内存计数器（06§2）：多 worker 时每个进程各算一份，实际阈值
# 被放大成 N 倍，等于限流失效。契约要求此时拒绝启动，而不是悄悄降级。
assert_single_process()

# docs_url=None：关掉 FastAPI 内置的 /docs（它从国外 CDN 取资源，国内打不开）
app = FastAPI(
    title="桌面宠物后端", version="2.0.0", docs_url=None, lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_handlers(app)

# 把 app/static 挂成 /static，里面的文件就能用网址直接访问
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(devices.router)
app.include_router(control.router)

# 把 auth 路由挂到应用上：/api/auth/login、/api/auth/me
app.include_router(auth.router)
# 初始化提示（匿名）与七个内置表情（只读）
app.include_router(setup.router)
app.include_router(faces.router)


@app.get("/docs", include_in_schema=False)
def custom_docs():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url="/static/vendor/swagger-ui-bundle.js",
        swagger_css_url="/static/vendor/swagger-ui.css",
        swagger_favicon_url="",
    )


@app.get("/api/health")
def health():
    return ok(
        {
            "status": "ok",
            "mode": _health_mode(),
            "protocol_version": PROTOCOL_VERSION,
        }
    )
