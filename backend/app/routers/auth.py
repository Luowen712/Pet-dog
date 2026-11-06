from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import User
from app.security import hash_pwd, make_token

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == body.username).first()
    if not u or u.password_hash != hash_pwd(body.password):
        raise HTTPException(401, detail={"code": 40001, "message": "账号或密码不对"})

    return {
        "code": 0,
        "message": "ok",
        "data": {"token": make_token(u.id, u.username), "username": u.username},
        "timestamp": 0,
    }


@router.get("/me")
def me(user=Depends(current_user)):
    return {"code": 0, "message": "ok", "data": user, "timestamp": 0}
