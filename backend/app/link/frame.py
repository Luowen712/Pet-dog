"""串口帧编解码"""

from dataclasses import dataclass

SOF = b"\xAA\x55"  # 帧头
OVERHEAD = 5
MAX_DATA = 31
MAX_FRAME = MAX_DATA + OVERHEAD

def checksum(cmd: int, data: bytes) -> int:
    """计算校验和"""
    return ~(len(data) + cmd + sum(data)) & 0xFF

@dataclass(frozen=True)
class Frame:
    cmd: int
    data: bytes

def build(cmd: int, data: bytes = b"") -> bytes:

        if not 0<= cmd <= 0xFF:
            raise ValueError(f"CMD 超出 0..255: {cmd}")

        if len(data) > MAX_DATA:
            raise ValueError(f"DATA 长度{len(data)}超过上限{MAX_DATA}")
        body = bytes([len(data), cmd]) + bytes(data)
        return SOF + body + bytes([checksum(cmd, data)])


class Parser:
    def __init__(self)-> None:
        self._buf = bytearray()
        self.noise = 0
        self.bad_len = 0
        self.bad_sum = 0

    def reset(self) -> None:
            self._buf.clear()
            self.noise = self.bad_len = self.bad_sum = 0

    def feed(self, chunk: bytes) -> list[Frame]:
            self._buf += chunk
            frames: list[Frame] = []
            while True:
                    if len(self._buf) < 3:
                        break
                    if self._buf[0] != 0xAA or self._buf[1] != 0x55:
                        del self._buf[0]
                        self.noise += 1
                        continue
                    length = self._buf[2]
                    if length > MAX_DATA:
                        del self._buf[0]
                        self.bad_len +=1
                        continue
                    total = length + OVERHEAD
                    if len(self._buf) < total:
                        break
                    cmd = self._buf[3]
                    data = bytes(self._buf[4:total-1])
                    if checksum(cmd,data) != self._buf[total-1]:
                        del self._buf[0]
                        self.bad_sum += 1
                        continue
                    frames.append(Frame(cmd, data))
                    del self._buf[:total]
            return frames