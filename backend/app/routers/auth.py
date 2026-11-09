from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import User
from app.resp import fail, ok
from app.security import hash_pwd, make_token

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginIn(BaseModel):
    username: str
    password: str


def user_out(u: User) -> dict:
    return {
        "username": u.username,
        "name": u.username,
        "role": u.role or "user",
    }


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == body.username).first()
    if not u or u.password_hash != hash_pwd(body.password):
        return fail(40001, "用户名或密码错误")

    return ok({"token": make_token(u.id, u.username), "user": user_out(u)})


@router.get("/me")
def me(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user.get("uid")).first()
    if not u:
        raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})
    return ok(user_out(u))
