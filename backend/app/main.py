from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401  必须留着，否则一张表都不建
from app.db import Base, engine
from app.errors import register_handlers
from app.resp import ok
from app.routers import auth, devices, faces, setup

Base.metadata.create_all(bind=engine)

BASE_DIR = Path(__file__).resolve().parent

# docs_url=None：关掉 FastAPI 内置的 /docs（它从国外 CDN 取资源，国内打不开）
app = FastAPI(title="桌面宠物后端", version="2.0.0", docs_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    return ok({"status": "ok", "mode": "serial"})
