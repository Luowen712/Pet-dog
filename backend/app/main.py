from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import SessionLocal
from app.errors import register_handlers
from app.link.lock import LOCK_NAME, HostProcessLock, ProcessLock
from app.link.send_gate import send_gate
from app.ratelimit import assert_single_process
from app.resp import ok
from app.routers import auth, devices, faces, setup
from app.services.purge import purge_revoking


BASE_DIR = Path(__file__).resolve().parent
PROTOCOL_VERSION = "3.1"

# 06:46 禁止 allow_origins=["*"] 与 allow_credentials=True 同时开启。
# 首版生产走同源部署；开发期跨端口仅放行本机 Vite 前端源。
DEV_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _health_mode() -> str:
    spec = settings.SERIAL_PORT.strip().lower()
    if spec == "sim" or spec.startswith("loop://"):
        return "sim"
    return "serial"


# 启动钩子（BA02 第 1、5 条）：
# 1. 先取本机排他进程锁，再取 MySQL 实例锁；任一失败拒绝启动，绝不降级无锁运行；
# 2. 清理上次未完成的 revoking 账号；
# 3. 关闭时按反序：先停设备会话，再放 DB 实例锁，最后放主机锁。
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

    try:
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
        yield
    finally:
        session = getattr(app.state, "device_session", None)
        if session is not None:
            try:
                session.close()
            finally:
                app.state.device_session = None
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
    allow_origins=DEV_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_handlers(app)

# 把 app/static 挂成 /static，里面的文件就能用网址直接访问
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(devices.router)

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
