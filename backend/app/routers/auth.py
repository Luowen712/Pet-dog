import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import ratelimit as rl
from app.db import get_db
from app.deps import current_user
from app.models import Device, User
from app.resp import fail, ok
from app.security import hash_pwd, make_token, needs_rehash, verify_pwd

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginIn(BaseModel):
    username: str
    password: str


def user_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "name": u.username,
        "role": u.role or "user",
    }


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    # 两套键同时判：账号 5 次/15 分钟防定向爆破，IP 30 次/15 分钟防撞库。
    # 账号键统一小写，避免用 Admin/ADMIN 分流绕过（库里 username 比较本身不区分大小写）。
    acct_key = "login:acct:" + body.username.strip().lower()
    ip_key = "login:ip:" + rl.client_ip(request)

    wait = rl.check(acct_key, rl.LOGIN_ACCT_LIMIT, rl.LOGIN_ACCT_WINDOW)
    if not wait:
        wait = rl.check(ip_key, rl.LOGIN_IP_LIMIT, rl.LOGIN_IP_WINDOW)
    if wait:
        raise rl.too_many(wait)

    u = db.query(User).filter(User.username == body.username).first()
    if not u or not verify_pwd(u.password_hash, body.password):
        rl.record(acct_key, rl.LOGIN_ACCT_WINDOW)
        rl.record(ip_key, rl.LOGIN_IP_WINDOW)
        return fail(40001, "用户名或密码错误")
    if u.status != "active":
        # 账号不可用同样算失败：不记账的话可以无限探测某个账号是否被封。
        rl.record(acct_key, rl.LOGIN_ACCT_WINDOW)
        rl.record(ip_key, rl.LOGIN_IP_WINDOW)
        return fail(40001, "用户名或密码错误")

    # 旧摘要升级：验证通过且账号可用时，才把存量 SHA-256 换成 Argon2id。
    # 顺序不能提前——验证没过就写哈希，等于把错误密码当成新密码存进去。
    if needs_rehash(u.password_hash):
        u.password_hash = hash_pwd(body.password)
        db.commit()

    return ok(
        {"token": make_token(u.id, u.username, u.token_version), "user": user_out(u)}
    )


@router.get("/me")
def me(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user.get("uid")).first()
    if not u:
        raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})
    return ok(user_out(u))


class RegisterIn(BaseModel):
    username: str
    password: str


USERNAME_RE = re.compile(r"[a-zA-Z0-9_\u4e00-\u9fa5]{3,20}")


@router.post("/register")
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    ip_key = "register:ip:" + rl.client_ip(request)
    wait = rl.check(ip_key, rl.REGISTER_IP_LIMIT, rl.REGISTER_IP_WINDOW)
    if wait:
        raise rl.too_many(wait)

    username = body.username.strip()
    if not USERNAME_RE.fullmatch(username):
        return fail(40002, "用户名需 3–20 位字母、数字、下划线或中文")
    # 与改密码保持同一口径（10–128），此前注册只要求 6 位，两套标准。
    if not (10 <= len(body.password) <= 128):
        return fail(40002, "密码需要 10–128 位")

    # 注册按「请求次数」计，成功也占额度。
    # 契约第 34 行写「计数只累计失败与拒绝」，但注册若只计失败，
    # 攻击者换个用户名就能无限建号——限流本意是防批量注册，这里按请求数记。
    # 放在参数校验之后：格式不对的请求不该消耗正常用户的额度。
    rl.record(ip_key, rl.REGISTER_IP_WINDOW)

    u = User(username=username, password_hash=hash_pwd(body.password))
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return fail(40900, "用户名已存在")

    return ok({"username": username, "name": username})


@router.post("/logout")
def logout(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user.get("uid")).first()
    if not u:
        raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})
    u.token_version += 1
    db.commit()
    return ok({"logged_out": True})


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


@router.put("/password")
def change_password(
    body: ChangePasswordIn,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.id == user.get("uid")).first()
    if not u:
        raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})

    if not verify_pwd(u.password_hash, body.old_password):
        return fail(40001, "原密码错误")

    if not (10 <= len(body.new_password) <= 128):
        return fail(40002, "新密码需要 10–128 位")

    if body.new_password == body.old_password:
        return fail(40002, "新密码不能与原密码相同")

    u.password_hash = hash_pwd(body.new_password)
    u.token_version += 1
    db.commit()
    return ok({"reauth_required": True})


class AccountDeleteIn(BaseModel):
    password: str
    confirm_username: str


@router.delete("/account")
def delete_account(
    body: AccountDeleteIn,
    user: dict = Depends(current_user),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.id == user.get("uid")).first()
    if not u:
        raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})

    if not verify_pwd(u.password_hash, body.password):
        return fail(40001, "密码错误")

    # 契约 02:230：最后一个 active admin 禁止注销，否则系统再没有管理员。
    # 放在密码校验之后，避免未验证身份就能探出「谁是最后一个管理员」。
    if u.role == "admin":
        others = (
            db.query(User)
            .filter(User.role == "admin", User.status == "active", User.id != u.id)
            .count()
        )
        if others == 0:
            return fail(40900, "系统必须保留至少一个管理员")

    if body.confirm_username.strip() != u.username:
        return fail(40002, "用户名不匹配")

    # 解绑必须四列一起改。ck_device_owner_status 要求「无主必非 bound」，
    # 只清 owner_id 会立刻违反 CHECK 报 3819，整个注销事务回滚、账号删不掉。
    # 重置成 claimable/required 与 0003 回填的口径一致：无主设备回到可被认领状态。
    # be（绑定纪元）不在这里 +1 —— 它属于「下一次绑定」的语义，
    # 下次被认领时 +1 才能让旧主人的旧命令失效。
    db.query(Device).filter(Device.owner_id == u.id).update(
        {
            "owner_id": None,
            "status": "claimable",
            "handover_state": "required",
            "bound_at": None,
        },
        synchronize_session=False,
    )

    u.username = "~del~%d~%s" % (u.id, secrets.token_hex(4))

    u.status = "revoking"
    u.token_version += 1
    db.commit()

    return ok({"status": "revoking"})
