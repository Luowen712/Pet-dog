import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Device, DeviceClaim

CODE_LEN = 6
CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
LOCK_TTL = timedelta(minutes=10)


class ClaimError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _hash_code(code: str) -> str:
    return hmac.new(
        settings.CLAIM_SECRET.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _new_code() -> str:
    return "%0*d" % (CODE_LEN, secrets.randbelow(10**CODE_LEN))


def issue_claim(db: Session, device_pk: int) -> str:
    d = db.query(Device).filter(Device.id == device_pk).first()
    if d is None:
        raise ClaimError(40400, "设备不存在")

    if d.handover_state != "ready":
        raise ClaimError(40900, "设备交接未完成，不能发配对码")

    code = _new_code()
    now = datetime.now()
    expires = now + CODE_TTL

    row = db.query(DeviceClaim).filter(DeviceClaim.device_pk == device_pk).first()
    if row is None:
        row = DeviceClaim(
            device_pk=device_pk,
            code_hash=_hash_code(code),
            expires_at=expires,
        )
        db.add(row)
    else:
        row.code_hash = _hash_code(code)
        row.expires_at = expires
        row.attempts = 0
        row.locked_until = None
        row.consumed_at = None
        row.consumed_by_user_id = None

    db.commit()
    return code


def claim_device(db: Session, uid: int, device_pk: int, code: str) -> Device:
    if len(code) != CODE_LEN or not code.isdigit():
        raise ClaimError(40002, "配对码应为 6 位数字")

    if db.query(Device).filter(Device.owner_id == uid).first() is not None:
        raise ClaimError(40900, "当前账号已绑定设备，请先解绑")

    d = db.query(Device).filter(Device.id == device_pk).first()
    if d is None:
        raise ClaimError(40400, "设备不存在")

    row = (
        db.query(DeviceClaim)
        .filter(DeviceClaim.device_pk == device_pk)
        .with_for_update()
        .first()
    )
    if row is None:
        raise ClaimError(40900, "配对码无效")

    now = datetime.now()

    if row.consumed_at is not None:
        raise ClaimError(40900, "配对码已使用")

    if row.expires_at <= now:
        raise ClaimError(40900, "配对码已过期")

    if row.locked_until is not None and row.locked_until > now:
        raise ClaimError(40900, "配对码已锁定，请 10 分钟后再试")

    if not hmac.compare_digest(_hash_code(code), row.code_hash):
        row.attempts = (row.attempts or 0) + 1
        if row.attempts >= MAX_ATTEMPTS:
            row.locked_until = now + LOCK_TTL
        db.commit()
        raise ClaimError(40900, "配对码无效")

    if d.owner_id is not None or d.status != "claimable" or d.handover_state != "ready":
        raise ClaimError(40900, "设备当前不可认领")

    d.owner_id = uid
    d.status = "bound"
    d.bound_at = now
    row.consumed_at = now
    row.consumed_by_user_id = uid

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ClaimError(40900, "当前账号已绑定设备，请先解绑")

    db.refresh(d)
    return d
