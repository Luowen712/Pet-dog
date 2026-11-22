"""Committed command receipts and the authorization shared by HTTP, writer and WS."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging

from fastapi import HTTPException
from app.db import SessionLocal
from app.link.send_gate import AuthContext
from app.models import AuditLog, CommandLog, Device, User

logger = logging.getLogger(__name__)
STATES = {10: 'pending', 20: 'accepted', 30: 'done', 40: 'rejected', 50: 'unknown', 60: 'superseded'}
TRANSPORT = {None: None, 0: 'ok', 1: 'write_failed', 2: 'partial_write'}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso(dt):
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


def receipt(row):
    return dict(cmd_id=row.msg_id, device_id=row.device_pk, seq=row.seq, action=row.action,
                status=STATES[row.status], transport=TRANSPORT[row.transport], reason=row.reason,
                revision=row.revision, error_code=row.error_code, created_at=iso(row.created_at),
                updated_at=iso(row.updated_at or row.finished_at or row.created_at), finished_at=iso(row.finished_at))


def auth_context(db, uid, tv, pk):
    user = db.get(User, uid)
    if not user or user.status != 'active' or user.token_version != tv:
        raise HTTPException(401, detail={'code': 40101, 'message': '登录已过期'})
    d = db.query(Device).filter_by(id=pk, owner_id=uid, status='bound').first()
    return AuthContext(uid, tv, pk, d.be) if d else None


def invalid_code(ctx):
    with SessionLocal() as db:
        try:
            return None if auth_context(db, ctx.uid, ctx.tv, ctx.device_pk) == ctx else 1008
        except HTTPException:
            return 4401


class ReceiptWriter:
    """Serialize callbacks off the event loop; DB commit precedes publication."""

    def __init__(self, events):
        self.events = events
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='command-db')

    def on_event(self, session, event):
        data = event.payload.copy()
        if event.kind in ('accepted', 'done', 'rejected', 'unknown'):
            self.pool.submit(self._update, session, event.session_id, data, event.kind, None)
        elif event.kind in ('state', 'link', 'fault'):
            snap = session.snapshot()
            if event.session_id != snap.session_id:
                return
            if event.kind == 'fault':
                self.publish_link(session, snap.session_id, snap.be, data['reason'])
                return
            data.pop('affected_cmd_ids', None)
            if event.kind == 'state':
                data['updated_at'] = iso(utcnow())
            self.events.publish(snap.device_pk, snap.be, event.kind, data)

    def publish_link(self, session, sid, be, reason=None):
        snap = session.snapshot()
        if (snap.session_id, snap.be) == (sid, be):
            self.events.publish(snap.device_pk, be, 'link', dict(device_id=snap.device_pk,
                                session_id=sid, state_revision=snap.state_revision, online=snap.online,
                                control_state=snap.control_state, reason=reason))

    def on_write(self, session, sid, cmd_id, uid, outcome):
        self.pool.submit(self._update, session, sid, dict(cmd_id=cmd_id, actor_user_id=uid), 'write', outcome)

    def _update(self, session, sid, data, kind, outcome):
        try:
            with SessionLocal.begin() as db:
                match = {'actor_user_id': data['actor_user_id']} if kind == 'write' else {'seq': data['seq']}
                row = db.query(CommandLog).filter_by(device_pk=session.device_pk, session_id=sid,
                        msg_id=data['cmd_id'], **match).with_for_update().one_or_none()
                if not row or row.status in (30, 40, 60):
                    return
                if kind == 'write':
                    if row.transport == 0 or row.transport == outcome.transport:
                        return
                    row.transport = outcome.transport
                    if outcome.transport:
                        row.status, row.reason = 50, outcome.reason
                elif kind == 'unknown':
                    if row.status == 50:
                        return
                    row.status, row.reason = 50, data['reason']
                else:
                    if row.transport == 1 or kind == 'accepted' and row.status != 10:
                        return
                    if row.transport == 2:
                        db.add(AuditLog(device_pk=row.device_pk, actor_user_id=row.actor_user_id,
                                action='late_device_evidence', detail=f'{row.msg_id} {row.reason} -> {kind}'))
                    row.status = {'accepted': 20, 'done': 30, 'rejected': 40}[kind]
                    row.transport, row.reason = 0, None
                    row.error_code = data.get('error_code')
                row.updated_at = utcnow()
                if row.status in (30, 40):
                    row.finished_at = row.updated_at
                row.revision += 1
                pk, be, result = row.device_pk, row.be, receipt(row)
            self.events.publish(pk, be, 'command', result)
            self.publish_link(session, sid, be, result['reason'])
        except Exception:
            session.fail_closed('receipt_commit_failed')
            logger.exception('Receipt not persisted; no retry: cmd_id=%s session=%s seq=%s kind=%s', data['cmd_id'], sid, data.get('seq'), kind)
