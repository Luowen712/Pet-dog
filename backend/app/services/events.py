"""All ticket, socket and queue mutations run on the lifespan event loop."""
import asyncio
from collections import deque
from dataclasses import dataclass, field
import secrets
import time

from fastapi import WebSocketDisconnect
from app.link.send_gate import AuthContext
from app.services.control import invalid_code, iso, utcnow


@dataclass(eq=False)
class Connection:
    ctx: AuthContext
    queue: deque = field(default_factory=deque)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    close_code: int | None = None

    def close(self, code):
        self.close_code = code
        self.queue.clear()
        self.wake.set()


class Events:
    def __init__(self, loop):
        self.loop = loop
        self.tickets = {}
        self.sockets = set()

    def issue(self, ctx):
        now = time.monotonic()
        self.tickets = {k: v for k, v in self.tickets.items() if v[1] > now}
        ticket = secrets.token_urlsafe(32)
        self.tickets[ticket] = (ctx, now + 30)
        return {'ticket': ticket, 'expires_in_sec': 30}

    def publish(self, pk, be, event, data):
        self.loop.call_soon_threadsafe(self._offer, pk, be, event, data)

    def _offer(self, pk, be, event, data):
        for c in self.sockets:
            if c.close_code or (c.ctx.device_pk, c.ctx.be) != (pk, be):
                continue
            if event == 'state' or len(c.queue) >= 128:
                old_state = next((m for m in c.queue if m['event'] == 'state'), None)
                if old_state:
                    c.queue.remove(old_state)
            if len(c.queue) >= 128:
                if event != 'state':
                    c.close(1011)
                continue
            c.queue.append({'event': event, 'data': data})
            c.wake.set()

    def revoke(self, event):
        def code(ctx):
            if event.uid == ctx.uid and event.new_tv is not None and ctx.tv < event.new_tv:
                return 4401
            if event.device_pk == ctx.device_pk and event.new_be is not None and ctx.be < event.new_be:
                return 1008
            return None
        def invalidate():
            self.tickets = {k: v for k, v in self.tickets.items() if not code(v[0])}
            for c in self.sockets:
                if reason := code(c.ctx):
                    c.close(reason)
        self.loop.call_soon_threadsafe(invalidate)

    async def connect(self, ws, pk, ticket):
        async def deny(code):
            await ws.accept()  # a completed upgrade is needed for an application close code
            await ws.close(code)
        item = self.tickets.pop(ticket, None)
        if not item or item[1] <= time.monotonic() or item[0].device_pk != pk:
            await deny(4003)
            return
        ctx = item[0]
        reason = await asyncio.to_thread(invalid_code, ctx)
        if reason:
            await deny(reason)
            return
        if sum(c.ctx.uid == ctx.uid and c.ctx.device_pk == pk for c in self.sockets) >= 3:
            await deny(4009)
            return
        c = Connection(ctx)
        self.sockets.add(c)

        async def receive_disconnect():
            try:
                while (await ws.receive())['type'] != 'websocket.disconnect':
                    pass
            finally:
                c.close(1000)

        reader = None
        try:
            await ws.accept()  # slot already registered; no event gap after the client sees open
            reader = asyncio.create_task(receive_disconnect())
            while not c.close_code:
                if not c.queue:
                    c.wake.clear()
                    try:
                        await asyncio.wait_for(c.wake.wait(), 30)
                        continue
                    except asyncio.TimeoutError:
                        msg = {'event': 'ping', 'data': {'server_time': iso(utcnow())}}
                else:
                    msg = c.queue.popleft()
                reason = await asyncio.to_thread(invalid_code, ctx)
                if reason or c.close_code:
                    c.close(reason or c.close_code)
                    break
                await asyncio.wait_for(ws.send_json(msg), 5)
            if not reader.done():
                await ws.close(c.close_code or 1001)
        except (WebSocketDisconnect, OSError):
            pass
        except asyncio.TimeoutError:
            await ws.close(1011)
        finally:
            self.sockets.discard(c)
            if reader is not None:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
