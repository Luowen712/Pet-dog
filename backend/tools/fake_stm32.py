# 假 STM32：在 27810 端口冒充硬件，把短帧协议跑完整。
#   用法：python tools/fake_stm32.py
#   后端把 .env 里的 SERIAL_PORT 改成 socket://127.0.0.1:27810 就能连上。
import socket, threading, time

HEAD0, HEAD1, MAX_LEN = 0xAA, 0x55, 32
PORT = 27810

def checksum(body: bytes) -> int:
    return (~sum(body)) & 0xFF

def build(cmd: int, data: bytes = b"") -> bytes:
    body = bytes([len(data), cmd]) + data
    return bytes([HEAD0, HEAD1]) + body + bytes([checksum(body)])

class Parser:
    def __init__(self):
        self.buf = bytearray()

    def feed(self, byte: int):
        self.buf.append(byte)
        out = []
        while True:
            i = self.buf.find(b"\xAA\x55")
            if i < 0:
                self.buf = bytearray(b"\xAA") if self.buf[-1:] == b"\xAA" else bytearray()
                break
            if i:
                del self.buf[:i]
            if len(self.buf) < 3:
                break
            ln = self.buf[2]
            if ln > MAX_LEN:
                del self.buf[:1]
                continue
            total = 5 + ln
            if len(self.buf) < total:
                break
            body = bytes(self.buf[2:total - 1])
            if checksum(body) == self.buf[total - 1]:
                out.append((body[1], body[2:]))
                del self.buf[:total]
            else:
                del self.buf[:1]
        return out

class FakePet:
    def __init__(self):
        self.conn = None
        self.battery = 87
        self.action = 0
        self.face = 0
        self.music = 0

    def state_frame(self):
        v = 3900
        return build(0x03, bytes([
            self.battery, (v >> 8) & 0xFF, v & 0xFF,
            self.action, self.face, 0x00, 0x20, 0x0F, self.music]))

    def handle(self, cmd, data):
        out = []
        if cmd == 0x01:
            act = data[0] if len(data) > 0 else 0
            seq = data[3] if len(data) > 3 else 0
            self.action = act
            out.append(build(0x81, bytes([seq, 0x00])))
            threading.Timer(1.0, self._done, args=(act, seq)).start()
        elif cmd == 0x04:
            out.append(build(0x84))
        elif cmd == 0x06:
            out.append(self.state_frame())
        elif cmd == 0x07:
            self.face = data[0] if data else 0
            out.append(build(0x87, bytes([self.face, 0x00])))
        elif cmd == 0x08:
            out.append(build(0x88, bytes([0x00])))
        elif cmd == 0x09:
            out.append(build(0x89, bytes([0x00])))
        elif cmd == 0x0A:
            self.music = data[0] if data else 0
            out.append(build(0x8A, bytes([self.music, 0x00])))
        return out

    def _done(self, act, seq):
        self.push(build(0x02, bytes([act, 0x00, seq])))

    def push(self, raw):
        c = self.conn
        if c is not None:
            try:
                c.sendall(raw)
            except OSError:
                pass

    def serve(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", PORT))
        srv.listen(1)
        print("假 STM32 已就绪，监听 127.0.0.1:%d" % PORT, flush=True)
        while True:
            print("等后端连上来 ...", flush=True)
            conn, _ = srv.accept()
            self.conn = conn
            conn.settimeout(1.0)
            print("后端已连上", flush=True)
            threading.Thread(target=self._tick, args=(conn,), daemon=True).start()
            parser = Parser()
            while True:
                try:
                    chunk = conn.recv(256)
                except socket.timeout:
                    continue                      # 空闲超时不算断开，继续等
                except OSError:
                    break
                if not chunk:
                    break
                for b in chunk:
                    for cmd, data in parser.feed(b):
                        print("  收到 %02X 数据 %s" % (cmd, data.hex(" ").upper() or "(空)"), flush=True)
                        for raw in self.handle(cmd, data):
                            conn.sendall(raw)
                            print("    回 %s" % raw.hex(" ").upper(), flush=True)
            self.conn = None
            conn.close()
            print("后端断开，等下一次连接", flush=True)

    def _tick(self, conn):
        while self.conn is conn:
            time.sleep(5)
            if self.conn is conn:
                self.push(self.state_frame())

if __name__ == "__main__":
    FakePet().serve()
