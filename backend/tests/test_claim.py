"""BB03 第 3 条：配对码生成、消费与失败计数。

这里有一条用例是别的用例替代不了的：
    test_wrong_code_attempt_is_committed_before_error

它用**一个全新的 session** 去读 attempts，只有真正 COMMIT 过的改动才看得见。
如果哪天有人把 claim_device 里那句 db.commit() 挪到 raise 之后（或者删掉），
其余用例可能照样全绿，只有这条会挂——因为内存里的改动不会跨 session。
"""

import re
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Device, DeviceClaim, User
from app.security import make_token
from app.services.claim import ClaimError, _hash_code, issue_claim

client = TestClient(app)


# ---------- 造数据 ----------


def _mk_user(db, username: str) -> User:
    u = User(
        username=username,
        password_hash="x" * 64,
        role="user",
        status="active",
        token_version=0,
    )
    db.add(u)
    db.commit()
    return u


def _mk_device(
    db, device_id: str, owner_id=None, be: int = 0, handover: str = "ready"
) -> Device:
    # ck_device_owner_status：有主必 bound，无主必非 bound
    d = Device(
        device_id=device_id,
        owner_id=owner_id,
        be=be,
        status="bound" if owner_id else "claimable",
        handover_state=handover,
    )
    db.add(d)
    db.commit()
    return d


def _headers(u: User) -> dict:
    return {"Authorization": "Bearer " + make_token(u.id, u.username, u.token_version)}


def _row(device_pk: int) -> DeviceClaim | None:
    """另开 session 读：只有已提交的数据才读得到。"""
    db = SessionLocal()
    try:
        return db.query(DeviceClaim).filter(DeviceClaim.device_pk == device_pk).first()
    finally:
        db.close()


def _other(code: str) -> str:
    """另一串一定能对不上的 6 位码，避开随机码恰好等于它的极小概率。"""
    return "000000" if code != "000000" else "111111"


def _dev(device_pk: int) -> Device | None:
    """另开 session 读设备。

    不能用测试自己的 db 会话复查：claim_device 结尾的 db.refresh(d) 在 commit
    之后又发了一条 SELECT，把这个会话重新拉进一个新事务；MySQL 默认
    REPEATABLE READ 会把快照钉在那一刻，之后无论 expire_all 还是重新 query
    都看不到 HTTP 请求后来提交的数据。
    """
    db = SessionLocal()
    try:
        return db.query(Device).filter(Device.id == device_pk).first()
    finally:
        db.close()


# ---------- 发码 ----------


def test_issue_claim_rejects_handover_required():
    db = SessionLocal()
    try:
        d = _mk_device(db, "CLM-REQ", handover="required")
        try:
            issue_claim(db, d.id)
            raise AssertionError("交接未完成却发出了配对码")
        except ClaimError as e:
            assert e.code == 40900
    finally:
        db.close()


def test_issue_claim_stores_hash_not_plaintext():
    db = SessionLocal()
    try:
        d = _mk_device(db, "CLM-HASH")
        code = issue_claim(db, d.id)

        assert re.fullmatch(r"\d{6}", code), "配对码必须是 6 位数字"
        row = _row(d.id)
        assert row is not None
        # 库里只能是 HMAC，不能是明文
        assert row.code_hash == _hash_code(code)
        assert code not in row.code_hash
        assert row.attempts == 0
        assert row.expires_at > datetime.now()
    finally:
        db.close()


def test_reissue_resets_attempts_lock_and_consumption():
    """重新发码是 UPDATE 一行，且必须把上一轮的脏状态全部清掉。"""
    db = SessionLocal()
    try:
        d = _mk_device(db, "CLM-RE")
        issue_claim(db, d.id)

        row = db.query(DeviceClaim).filter(DeviceClaim.device_pk == d.id).first()
        row.attempts = 4
        row.locked_until = datetime.now() + timedelta(minutes=5)
        row.consumed_at = datetime.now()
        db.commit()

        issue_claim(db, d.id)

        row = _row(d.id)
        assert row.attempts == 0, "上一轮的失败次数没清零，新码一出生就是快被锁的"
        assert row.locked_until is None, "锁没解开，新码用不了"
        assert row.consumed_at is None, "没清消费标记，新码一用就被判已使用"
    finally:
        db.close()


# ---------- 认领 ----------


def test_claim_binds_device():
    db = SessionLocal()
    try:
        u = _mk_user(db, "clm_ok")
        d = _mk_device(db, "CLM-OK")
        code = issue_claim(db, d.id)

        r = client.post(
            "/api/devices/claim",
            json={"device_id": d.id, "code": code},
            headers=_headers(u),
        )
        assert r.status_code == 200
        assert r.json()["code"] == 0
        assert r.json()["data"]["id"] == d.id

        row = _row(d.id)
        assert row.consumed_at is not None
        assert row.consumed_by_user_id == u.id

        db.expire_all()
        dd = _dev(d.id)
        assert dd.owner_id == u.id
        assert dd.status == "bound"
        assert dd.bound_at is not None
        assert dd.be == 0, "be+1 属于解绑，认领不该动它"
    finally:
        db.close()


def test_wrong_code_attempt_is_committed_before_error():
    """错码计数必须落库。见文件头说明。"""
    db = SessionLocal()
    try:
        u = _mk_user(db, "clm_cnt")
        d = _mk_device(db, "CLM-CNT")
        code = issue_claim(db, d.id)

        r = client.post(
            "/api/devices/claim",
            json={"device_id": d.id, "code": _other(code)},
            headers=_headers(u),
        )
        assert r.json()["code"] == 40900

        assert _row(d.id).attempts == 1, "attempts 没落库：先抛异常后 commit 会回滚掉"
    finally:
        db.close()


def test_five_failures_lock_then_correct_code_rejected():
    """06:29 —— 锁定期内正确码也拒。"""
    db = SessionLocal()
    try:
        u = _mk_user(db, "clm_lock")
        d = _mk_device(db, "CLM-LOCK")
        code = issue_claim(db, d.id)
        wrong = _other(code)

        for _ in range(5):
            r = client.post(
                "/api/devices/claim",
                json={"device_id": d.id, "code": wrong},
                headers=_headers(u),
            )
            assert r.json()["code"] == 40900

        row = _row(d.id)
        assert row.attempts == 5
        assert row.locked_until is not None

        r = client.post(
            "/api/devices/claim",
            json={"device_id": d.id, "code": code},
            headers=_headers(u),
        )
        assert r.json()["code"] == 40900
        assert "锁" in r.json()["message"]
        assert _row(d.id).consumed_at is None, "锁定期内不许被消费"
    finally:
        db.close()


def test_consumed_code_cannot_be_replayed():
    db = SessionLocal()
    try:
        u1 = _mk_user(db, "clm_re1")
        u2 = _mk_user(db, "clm_re2")
        d = _mk_device(db, "CLM-REPLAY")
        code = issue_claim(db, d.id)

        r1 = client.post(
            "/api/devices/claim",
            json={"device_id": d.id, "code": code},
            headers=_headers(u1),
        )
        assert r1.json()["code"] == 0

        # 换个人再拿同一个码：必须被「已使用」挡住
        r2 = client.post(
            "/api/devices/claim",
            json={"device_id": d.id, "code": code},
            headers=_headers(u2),
        )
        assert r2.json()["code"] == 40900

        db.expire_all()
        dd = _dev(d.id)
        assert dd.owner_id == u1.id, "第二个人的重放把设备抢走了"
    finally:
        db.close()


def test_expired_code_rejected():
    db = SessionLocal()
    try:
        u = _mk_user(db, "clm_exp")
        d = _mk_device(db, "CLM-EXP")
        code = issue_claim(db, d.id)

        row = db.query(DeviceClaim).filter(DeviceClaim.device_pk == d.id).first()
        row.expires_at = datetime.now() - timedelta(minutes=1)
        db.commit()

        r = client.post(
            "/api/devices/claim",
            json={"device_id": d.id, "code": code},
            headers=_headers(u),
        )
        assert r.json()["code"] == 40900
        assert "过期" in r.json()["message"]
    finally:
        db.close()


def test_account_with_device_cannot_claim_another():
    """每账号至多一台（uq_device_owner）。"""
    db = SessionLocal()
    try:
        u = _mk_user(db, "clm_two")
        _mk_device(db, "CLM-OWN1", owner_id=u.id)
        d2 = _mk_device(db, "CLM-OWN2")
        code = issue_claim(db, d2.id)

        r = client.post(
            "/api/devices/claim",
            json={"device_id": d2.id, "code": code},
            headers=_headers(u),
        )
        assert r.json()["code"] == 40900
        assert _row(d2.id).consumed_at is None
    finally:
        db.close()


def test_bad_format_returns_40002():
    """格式错误是 40002，不是 40000，也不是 40900。"""
    db = SessionLocal()
    try:
        u = _mk_user(db, "clm_fmt")
        d = _mk_device(db, "CLM-FMT")

        for bad in ("12345", "1234567", "abcdef", ""):
            r = client.post(
                "/api/devices/claim",
                json={"device_id": d.id, "code": bad},
                headers=_headers(u),
            )
            assert r.json()["code"] == 40002, "码 %r 应返回 40002" % bad
    finally:
        db.close()


def test_wrong_code_is_not_echoed_in_response():
    """错误响应里不能回显用户输入的码——否则它就可能被写进日志。"""
    db = SessionLocal()
    try:
        u = _mk_user(db, "clm_echo")
        d = _mk_device(db, "CLM-ECHO")
        code = issue_claim(db, d.id)
        wrong = _other(code)

        r = client.post(
            "/api/devices/claim",
            json={"device_id": d.id, "code": wrong},
            headers=_headers(u),
        )
        assert wrong not in r.text
    finally:
        db.close()


def test_claim_unknown_device_returns_40400():
    db = SessionLocal()
    try:
        u = _mk_user(db, "clm_404")
        r = client.post(
            "/api/devices/claim",
            json={"device_id": 99999999, "code": "123456"},
            headers=_headers(u),
        )
        assert r.json()["code"] == 40400
    finally:
        db.close()


def test_claim_without_code_row_returns_40900():
    """没发过码的设备，对外和「码错了」是同一句话。"""
    db = SessionLocal()
    try:
        u = _mk_user(db, "clm_nocode")
        d = _mk_device(db, "CLM-NOCODE")

        r = client.post(
            "/api/devices/claim",
            json={"device_id": d.id, "code": "123456"},
            headers=_headers(u),
        )
        assert r.json()["code"] == 40900
    finally:
        db.close()
