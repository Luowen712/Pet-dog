import asyncio
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import ratelimit as rl
from app.db import SessionLocal, get_db
from app.deps import current_user
from app.link.send_gate import RevokeEvent, send_gate
from app.models import Device, User
from app.resp import fail, ok
from app.security import hash_pwd, make_token, needs_rehash, verify_pwd

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginIn(BaseModel):
    username: str
    password: str



def user_out(u: User) -> dict:
    """把用户对象转成返回给前端的精简字段。"""
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
    """按账号与 IP 双维度限流后校验密码，通过则顺手升级旧哈希并签发令牌。"""
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
    """返回当前登录用户的精简信息。"""
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
    """按 IP 限流并校验用户名与密码格式，通过后创建账号。"""
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

    db.refresh(u)
    return ok(user_out(u))



@router.post("/logout")
def logout(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    """递增令牌版本让旧令牌立即失效，释锁后广播撤销事件。"""
    uid = user.get("uid")
    new_tv: int | None = None
    with send_gate.hold():
        u = db.query(User).filter(User.id == uid).with_for_update().first()
        if not u or u.status != "active":
            raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})
        u.token_version += 1
        new_tv = u.token_version
        db.commit()
    send_gate.notify_revoke(
        RevokeEvent(uid=uid, device_pk=None, kind="logout", new_tv=new_tv)
    )
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
    """校验原密码与新密码规则，更新哈希并递增令牌版本强制重新登录。"""
    uid = user.get("uid")
    u = db.query(User).filter(User.id == uid).first()
    if not u or u.status != "active":
        raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})

    if not verify_pwd(u.password_hash, body.old_password):
        return fail(40001, "原密码错误")

    if not (10 <= len(body.new_password) <= 128):
        return fail(40002, "新密码需要 10–128 位")

    if body.new_password == body.old_password:
        return fail(40002, "新密码不能与原密码相同")

    # 06:191 密码哈希先算完再拿 SendGate
    new_hash = hash_pwd(body.new_password)
    new_tv: int | None = None
    with send_gate.hold():
        u = db.query(User).filter(User.id == uid).with_for_update().first()
        if not u or u.status != "active":
            raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})
        u.password_hash = new_hash
        u.token_version += 1
        new_tv = u.token_version
        db.commit()

    send_gate.notify_revoke(
        RevokeEvent(uid=uid, device_pk=None, kind="password_change", new_tv=new_tv)
    )
    return ok({"reauth_required": True})


class AccountDeleteIn(BaseModel):
    password: str
    confirm_username: str



@router.delete("/account")
async def delete_account(
    body: AccountDeleteIn,
    request: Request,
    user: dict = Depends(current_user),
):
    """校验密码与确认用户名后注销账号：解绑设备、改名、状态置 revoking。"""
    uid = user.get("uid")

    def _verify_and_revoke():
        """在门禁与事务内完成密码校验、管理员守卫、解绑与注销，返回解绑设备或错误。"""
        with SessionLocal() as db:
            u = db.query(User).filter(User.id == uid).first()
            if not u or u.status != "active":
                raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})

            # Argon2 校验放在 SendGate 锁外（06:191）
            if not verify_pwd(u.password_hash, body.password):
                return None, None, fail(40001, "密码错误")

        unbound_devices: list[tuple[int, int]] = []
        with send_gate.hold(), SessionLocal() as db:
            u = db.query(User).filter(User.id == uid).with_for_update().first()
            if not u or u.status != "active":
                raise HTTPException(401, detail={"code": 40101, "message": "登录已过期"})

            # 契约 02:230：最后一个 active admin 禁止注销；加行锁防止两管理员并发注销删光管理员。
            if u.role == "admin":
                active_admins = (
                    db.query(User)
                    .filter(User.role == "admin", User.status == "active")
                    .with_for_update()
                    .all()
                )
                if len([a for a in active_admins if a.id != u.id]) == 0:
                    return None, None, fail(40900, "系统必须保留至少一个管理员")

            if body.confirm_username.strip() != u.username:
                return None, None, fail(40002, "用户名不匹配")

            # 解绑与 DELETE /devices/{id}/binding 保持同一口径（06:296 / S01）：
            # 五列同事务修改 + be + 1，防止换主后读到旧主人数据。
            owned = (
                db.query(Device)
                .filter(Device.owner_id == u.id)
                .order_by(Device.id)
                .with_for_update()
                .all()
            )
            for d in owned:
                old_be = d.be
                d.owner_id = None
                d.status = "claimable"
                d.handover_state = "required"
                d.bound_at = None
                d.be = old_be + 1
                unbound_devices.append((d.id, d.be))

            u.username = "~del~%d~%s" % (u.id, secrets.token_hex(4))
            u.status = "revoking"
            u.deleted_at = datetime.now()
            u.token_version += 1
            new_tv = u.token_version
            db.commit()
        return unbound_devices, new_tv, None

    unbound_devices, new_tv, err = await asyncio.to_thread(_verify_and_revoke)
    if err is not None:
        return err

    if unbound_devices:
        for dpk, new_be in unbound_devices:
            send_gate.notify_revoke(
                RevokeEvent(
                    uid=uid,
                    device_pk=dpk,
                    kind="account_delete",
                    new_tv=new_tv,
                    new_be=new_be,
                )
            )
        from app.main import stop_ble_session_if_matching

        await stop_ble_session_if_matching(request.app, {dpk for dpk, _ in unbound_devices})
    else:
        send_gate.notify_revoke(
            RevokeEvent(uid=uid, device_pk=None, kind="account_delete", new_tv=new_tv)
        )

    return ok({"status": "revoking"})
