import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket
from pydantic import BaseModel, ConfigDict

from app import ratelimit
from app.db import SessionLocal
from app.deps import current_user
from app.link.device_session import SeqExhaustedError, SessionFaultedError, SessionNotReadyError
from app.link.send_gate import send_gate
from app.link.serial_link import LinkError
from app.models import CommandLog, Device
from app.resp import fail, ok
from app.services.control import auth_context, invalid_code, receipt, utcnow

router = APIRouter(tags=['设备控制'])


class Target(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    device_id: int


class Motion(Target):
    action: int


class Face(Target):
    face: int


def unavailable(reason):
    return {**fail(40900, '当前不能控制设备'), 'reason': reason}


def not_visible():
    return fail(40400, '记录不存在或不可见')


def check_limit(key, limit):
    wait = ratelimit.check(key, limit, 60)
    if wait:
        raise ratelimit.too_many(wait)


def current_session(app, ctx):
    session = app.state.device_session
    return session if session and (session.device_pk, session.be) == (ctx.device_pk, ctx.be) else None


@router.post('/api/commands/send')
def send(body: Motion, request: Request, user=Depends(current_user), idempotency_key: UUID = Header()):
    key = str(idempotency_key)
    committed = False
    expected_hold = -1
    with send_gate.hold():
        with SessionLocal() as db:
            ctx = auth_context(db, user['uid'], user['tv'], body.device_id)
            if not ctx:
                return not_visible()
            original = db.query(CommandLog).filter_by(actor_user_id=ctx.uid, msg_id=key).first()
            if original:
                if (original.device_pk, original.be, original.action) != (ctx.device_pk, ctx.be, body.action):
                    return unavailable('idempotency_conflict')
                return ok(receipt(original))
            session = current_session(request.app, ctx)
            if not session:
                return unavailable('offline')
            snap = session.snapshot()
            if body.action not in snap.supported_actions:
                return {**fail(40002, '不支持该动作'), 'reason': 'unsupported_action'}
            bucket = f'command:{ctx.uid}:{ctx.device_pk}'
            check_limit(bucket, 20)
            sid = snap.session_id
            row = CommandLog(actor_user_id=ctx.uid, device_pk=ctx.device_pk, device_id=db.get(Device, ctx.device_pk).device_id,
                             be=ctx.be, tv=ctx.tv, msg_id=key, session_id=sid, cmd=1, action=body.action,
                             status=10, revision=1, created_at=utcnow())
            # Insert before enqueue. Early transport failures lock this row and see the committed seq
            # (or no row after rollback); they cannot race an as-yet nonexistent receipt.
            db.add(row)
            db.flush()
            writer = request.app.state.receipts

            def may_write():
                if not committed or session.session_id != sid or session.control_state != 'busy':
                    return False
                # No other holder entered send_gate between POST commit and SerialLink write.
                if send_gate.hold_seq == expected_hold:
                    return True
                with SessionLocal() as fresh:
                    try:
                        if auth_context(fresh, ctx.uid, ctx.tv, ctx.device_pk) != ctx:
                            return False
                    except HTTPException:
                        return False
                    return fresh.query(CommandLog.id).filter_by(actor_user_id=ctx.uid, msg_id=key, session_id=sid,
                                                               seq=seq, be=ctx.be, status=10).first() is not None
            try:
                seq = session.send_motion(key, body.action, before_write=may_write, expected_session_id=sid,
                        on_write=lambda outcome: writer.on_write(session, sid, key, ctx.uid, outcome))
            except SessionNotReadyError as exc:
                return unavailable(exc.control_state)
            except SeqExhaustedError:
                return unavailable('seq_exhausted')
            except (SessionFaultedError, LinkError):
                return unavailable('link_unavailable')
            row.seq = seq
            result = receipt(row)
            db.commit()  # writer takes the same gate and verifies this row before touching the port
            committed = True
            expected_hold = send_gate.hold_seq + 1
    ratelimit.record(bucket, 60)
    request.app.state.events.publish(ctx.device_pk, ctx.be, 'command', result)
    writer.publish_link(session, sid, ctx.be)
    return ok(result)


@router.get('/api/commands/{cmd_id}')
def get_command(cmd_id: UUID, user=Depends(current_user)):
    with SessionLocal() as db:
        row = db.query(CommandLog).join(Device, Device.id == CommandLog.device_pk).filter(
            CommandLog.actor_user_id == user['uid'], CommandLog.msg_id == str(cmd_id),
            Device.owner_id == user['uid'], Device.be == CommandLog.be).first()
        return ok(receipt(row)) if row else not_visible()


@router.post('/api/faces/current')
def face(body: Face, request: Request, user=Depends(current_user)):
    with send_gate.hold():
        with SessionLocal() as db:
            ctx = auth_context(db, user['uid'], user['tv'], body.device_id)
            if not ctx:
                return not_visible()
            if not 0 <= body.face <= 6:
                return fail(40002, '表情编号超出 0..6')
            session = current_session(request.app, ctx)
            if not session:
                return unavailable('offline')
            sid = session.session_id
            expected_hold = send_gate.hold_seq + 1
            try:
                session.send_face(body.face, before_write=lambda: session.session_id == sid
                                  and session.control_state in ('ready', 'busy')
                                  and (send_gate.hold_seq == expected_hold or not invalid_code(ctx)))
            except SessionNotReadyError as exc:
                return unavailable(exc.control_state)
            except (SessionFaultedError, LinkError):
                return unavailable('link_unavailable')
    return ok({'face': body.face, 'dispatched': True})


@router.post('/api/events/ticket')
async def ticket(body: Target, request: Request, user=Depends(current_user)):
    def authorize():
        with SessionLocal() as db:
            return auth_context(db, user['uid'], user['tv'], body.device_id)
    ctx = await asyncio.to_thread(authorize)
    if not ctx:
        return not_visible()
    buckets = [(f'ticket:user:{ctx.uid}', 30), (f'ticket:device:{ctx.device_pk}', 60)]
    for key, limit in buckets:
        check_limit(key, limit)
    for key, _ in buckets:
        ratelimit.record(key, 60)
    return ok(request.app.state.events.issue(ctx))


@router.websocket('/ws/device')
async def stream(ws: WebSocket, device_id: int, ticket: str):
    await ws.app.state.events.connect(ws, device_id, ticket)
