from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401  必须留着，否则一张表都不建
from app.db import engine, Base

Base.metadata.create_all(bind=engine)

app = FastAPI(title="桌面宠物后端", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"code": 0, "message": "ok", "data": {"version": "2.0.0"}, "timestamp": 0}
