from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.resp import ok

router = APIRouter(prefix="/api/setup", tags=["运维"])


@router.get("/status")
def get_setup_status(db: Session = Depends(get_db)):
    # 只查主键，不把整行读进来；只认 active admin，disabled/revoked 不算有效管理员
    has_admin = (
        db.query(User.id)
        .filter(User.role == "admin", User.status == "active")
        .first()
        is not None
    )
    return ok({"setup_required": not has_admin})
