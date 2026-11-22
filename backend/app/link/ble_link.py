"""低功耗蓝牙（ECB02H2 BLE 透传）适配器：复用 BytePort 接入唯一 SerialLink/DeviceSession。

- 默认 GATT 透传 UUID 为 ECB02H2 常见的 FFF0 / FFF1(Notify) / FFF2(Write)，
  也可在 .env 覆写（如 FFE0/FFE1）；服务内特征若因固件批次互换或合并，按属性自动回落。
- 写帧按 BLE_MTU_CHUNK（默认 20B，保守兼容 ATT_MTU=23）切片；第 1 片失败抛 SerialException，
  后续分片失败抛 SerialTimeoutException；进入协议栈后的异常由 SerialLink 保守记 partial_write 并转 faulted。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from serial import SerialException, SerialTimeoutException

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
DEFAULT_NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
DEFAULT_WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

SIM_BLE_ADDRESS = "SIM-ECB02H2-01"
SIM_BLE_NAME = "PetDog-ECB02H2 (SIM)"


class BleUnavailableError(SerialException):
    """本机未安装 bleak 或蓝牙适配器不可用。"""


@dataclass(frozen=True)
class BleCandidate:
    address: str
    name: str
    rssi: int | None = None
    transport: str = "ble"


def norm_uuid(raw: str) -> str:
    s = raw.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    if len(s) == 4 and all(c in "0123456789abcdef" for c in s):
        return f"0000{s}-0000-1000-8000-00805f9b34fb"
    return s


def _import_bleak():
    try:
        from bleak import BleakClient, BleakScanner

        return BleakClient, BleakScanner
    except ImportError as exc:
        raise BleUnavailableError(
            "未安装 bleak，无法使用低功耗蓝牙；请安装 bleak 或改用 SERIAL_PORT=sim"
        ) from exc


def resolve_gatt_chars(
    services: Any,
    service_uuid: str,
    notify_uuid: str,
    write_uuid: str,
) -> tuple[str, str, bool]:
    """解析 Notify 与 Write 特征 UUID 及是否支持无响应写（write-without-response）。"""
    want_svc = norm_uuid(service_uuid)
    want_notify = norm_uuid(notify_uuid)
    want_write = norm_uuid(write_uuid)

    all_chars = []
    target_chars = []
    for svc in services or ():
        chars = list(getattr(svc, "characteristics", ()) or ())
        all_chars.extend(chars)
        if norm_uuid(str(getattr(svc, "uuid", ""))) == want_svc:
            target_chars.extend(chars)

    pool = target_chars or all_chars
    if not pool:
        return want_notify, want_write, True

    def props_of(ch) -> set[str]:
        return {str(p).lower() for p in (getattr(ch, "properties", ()) or ())}

    notify_char = next(
        (c for c in pool if norm_uuid(str(c.uuid)) == want_notify and "notify" in props_of(c)),
        None,
    ) or next((c for c in pool if "notify" in props_of(c)), None)

    write_char = next(
        (
            c
            for c in pool
            if norm_uuid(str(c.uuid)) == want_write
            and bool(props_of(c) & {"write-without-response", "write"})
        ),
        None,
    ) or next(
        (c for c in pool if bool(props_of(c) & {"write-without-response", "write"})),
        None,
    )

    if notify_char is None or write_char is None:
        raise SerialException(
            f"BLE 设备缺少可用的透传特征（期望服务 {service_uuid} 的 Notify/Write）"
        )

    use_response = "write-without-response" not in props_of(write_char)
    return str(notify_char.uuid), str(write_char.uuid), use_response


async def scan_ble_devices(
    *,
    timeout: float = 4.0,
    service_uuid: str = DEFAULT_SERVICE_UUID,
    discover_fn: Callable[..., Any] | None = None,
) -> list[BleCandidate]:
    """扫描附近 BLE 外设，优先排列匹配 ECB02/PetDog 名称或透传服务的设备。"""
    if discover_fn is None:
        _, BleakScanner = _import_bleak()
        discover_fn = BleakScanner.discover

    try:
        found = await discover_fn(timeout=timeout, return_adv=True)
    except Exception as exc:
        raise BleUnavailableError(f"BLE 扫描失败：{exc}") from exc

    want_svc = norm_uuid(service_uuid)
    items: list[tuple[int, int, BleCandidate]] = []
    seen: set[str] = set()

    entries = found.values() if isinstance(found, dict) else [(d, None) for d in found]
    for dev, adv in entries:
        addr = str(getattr(dev, "address", "") or "").strip()
        if not addr or addr in seen or len(addr) > 32:
            continue
        seen.add(addr)
        name = (
            getattr(dev, "name", None)
            or (getattr(adv, "local_name", None) if adv is not None else None)
            or addr
        )
        rssi = getattr(adv, "rssi", None) if adv is not None else getattr(dev, "rssi", None)
        uuids = [norm_uuid(u) for u in (getattr(adv, "service_uuids", None) or ())]
        name_upper = str(name).upper()
        preferred = (
            1
            if (want_svc in uuids or "ECB02" in name_upper or "PETDOG" in name_upper)
            else 0
        )
        items.append(
            (
                preferred,
                int(rssi) if isinstance(rssi, int) else -999,
                BleCandidate(
                    address=addr,
                    name=str(name)[:64],
                    rssi=int(rssi) if isinstance(rssi, int) else None,
                    transport="ble",
                ),
            )
        )

    items.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [row[2] for row in items]


class BleBytePort:
    """将 bleak 异步 GATT 透传包装为同步 BytePort，供 SerialLink 单线程 I/O 使用。"""

    def __init__(
        self,
        address: str,
        *,
        service_uuid: str = DEFAULT_SERVICE_UUID,
        notify_uuid: str = DEFAULT_NOTIFY_UUID,
        write_uuid: str = DEFAULT_WRITE_UUID,
        mtu_chunk: int = 20,
        write_timeout: float = 0.2,
        connect_timeout: float = 8.0,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.address = address.strip()
        if not self.address:
            raise SerialException("BLE 地址不能为空")
        self._service_uuid = service_uuid
        self._notify_uuid = notify_uuid
        self._write_uuid = write_uuid
        self._mtu_chunk = max(20, int(mtu_chunk))
        self._write_timeout = max(0.05, float(write_timeout))
        self._connect_timeout = max(1.0, float(connect_timeout))
        self._client_factory = client_factory

        self._rx = bytearray()
        self._mu = threading.Lock()
        self._open = False
        self._disconnected = False
        self._write_with_response = False

        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop, name=f"petdog-ble-{self.address}", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)

        self._client: Any = None
        try:
            self._submit(self._async_connect(), timeout=self._connect_timeout + 2.0)
        except Exception as exc:
            self.close()
            if isinstance(exc, SerialException):
                raise
            raise SerialException(f"BLE 连接失败（{self.address}）：{exc}") from exc

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        self._loop.close()

    def _submit(self, coro, *, timeout: float):
        if not self._loop.is_running():
            coro.close()
            raise SerialException("BLE 事件循环已关闭")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout)
        except TimeoutError as exc:
            fut.cancel()
            raise SerialTimeoutException("BLE 操作超时") from exc

    def _on_disconnect(self, _client: Any) -> None:
        with self._mu:
            self._open = False
            self._disconnected = True
        logger.warning("BLE 设备已断开：%s", self.address)

    def _on_notify(self, _sender: Any, data: bytearray | bytes) -> None:
        if not data:
            return
        with self._mu:
            self._rx.extend(data)

    async def _async_connect(self) -> None:
        factory = self._client_factory
        if factory is None:
            BleakClient, _ = _import_bleak()
            factory = BleakClient
        client = factory(
            self.address,
            disconnected_callback=self._on_disconnect,
            timeout=self._connect_timeout,
        )
        self._client = client
        await client.connect()
        notify_uuid, write_uuid, use_response = resolve_gatt_chars(
            getattr(client, "services", ()),
            self._service_uuid,
            self._notify_uuid,
            self._write_uuid,
        )
        self._notify_uuid = notify_uuid
        self._write_uuid = write_uuid
        self._write_with_response = use_response
        await client.start_notify(self._notify_uuid, self._on_notify)
        with self._mu:
            self._open = True

    async def _async_write_chunk(self, chunk: bytes) -> None:
        assert self._client is not None
        await self._client.write_gatt_char(
            self._write_uuid, chunk, response=self._write_with_response
        )

    async def _async_close(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            if getattr(client, "is_connected", False):
                try:
                    await client.stop_notify(self._notify_uuid)
                except Exception:
                    pass
                await client.disconnect()
        except Exception:
            pass

    @property
    def is_open(self) -> bool:
        with self._mu:
            return self._open

    def read(self, size: int = 1) -> bytes:
        with self._mu:
            if not self._open:
                raise SerialException(
                    "BLE 连接已断开" if self._disconnected else "BLE 端口已关闭"
                )
            if not self._rx:
                return b""
            n = max(1, size)
            out = bytes(self._rx[:n])
            del self._rx[:n]
            return out

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise SerialException("BLE 端口未打开或已断开")
        if not data:
            return 0
        written = 0
        for offset in range(0, len(data), self._mtu_chunk):
            chunk = data[offset : offset + self._mtu_chunk]
            try:
                self._submit(self._async_write_chunk(chunk), timeout=self._write_timeout)
            except SerialTimeoutException:
                raise
            except Exception as exc:
                if written > 0:
                    raise SerialTimeoutException(
                        f"BLE 分片写入中断（已写 {written}/{len(data)} 字节）：{exc}"
                    ) from exc
                raise SerialException(f"BLE 写入失败：{exc}") from exc
            written += len(chunk)
        return written

    def flush(self) -> None:
        if not self.is_open:
            raise SerialException("BLE 端口已关闭")

    def close(self) -> None:
        with self._mu:
            self._open = False
        if self._loop.is_running():
            try:
                self._submit(self._async_close(), timeout=2.0)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)
