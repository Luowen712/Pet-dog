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
import time
from dataclasses import dataclass
from typing import Any, Callable

from serial import SerialException, SerialTimeoutException

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
DEFAULT_NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
DEFAULT_WRITE_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
# 无线 BLE GATT 写入受连接间隔与空口重传影响，不能沿用有线串口的 200ms 写超时
DEFAULT_BLE_WRITE_TIMEOUT = 3.0

SIM_BLE_ADDRESS = "SIM-ECB02H2-01"
SIM_BLE_NAME = "PetDog-ECB02H2 (SIM)"

_SCAN_CACHE_TTL_SEC = 60.0
_scan_cache_lock = threading.Lock()
# 缓存近期扫描到的 BLEDevice，直连时避免 Windows WinRT 立刻二次启停扫描器导致建连抖动
_scan_cache: dict[str, tuple[float, Any]] = {}


def _cache_ble_device(address: str, dev: Any) -> None:
    if not address or dev is None:
        return
    with _scan_cache_lock:
        _scan_cache[address.strip().upper()] = (time.monotonic(), dev)


def _get_cached_ble_device(address: str) -> Any | None:
    key = address.strip().upper()
    with _scan_cache_lock:
        entry = _scan_cache.get(key)
        if entry is None:
            return None
        ts, dev = entry
        if (time.monotonic() - ts) > _SCAN_CACHE_TTL_SEC:
            _scan_cache.pop(key, None)
            return None
        return dev


def _drop_cached_ble_device(address: str) -> None:
    with _scan_cache_lock:
        _scan_cache.pop(address.strip().upper(), None)


class BleUnavailableError(SerialException):
    """本机未安装 bleak 或蓝牙适配器不可用。"""


@dataclass(frozen=True)
class BleCandidate:
    address: str
    name: str
    rssi: int | None = None
    transport: str = "ble"



def norm_uuid(raw: str) -> str:
    """把 4 位短 UUID 补全成 128 位标准形式，其余只做去空格与小写。"""
    s = raw.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    if len(s) == 4 and all(c in "0123456789abcdef" for c in s):
        return f"0000{s}-0000-1000-8000-00805f9b34fb"
    return s



def _import_bleak():
    """延迟导入 bleak；未安装则抛 BleUnavailableError 并提示替代方案。"""
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
        """把特征属性集合统一转成小写字符串集合。"""
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
    use_real_scanner = discover_fn is None
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
        if use_real_scanner:
            _cache_ble_device(addr, dev)
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
        write_timeout: float = DEFAULT_BLE_WRITE_TIMEOUT,
        connect_timeout: float = 15.0,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        """起独立事件循环线程并在其中完成 BLE 连接，失败立即关闭。"""
        self.address = address.strip()
        if not self.address:
            raise SerialException("BLE 地址不能为空")
        self._service_uuid = service_uuid
        self._notify_uuid = notify_uuid
        self._write_uuid = write_uuid
        self._mtu_chunk = max(20, int(mtu_chunk))
        self._write_timeout = max(0.05, float(write_timeout))
        self._connect_timeout = max(0.1, float(connect_timeout))
        self._client_factory = client_factory

        self._rx = bytearray()
        self._rx_callback: Callable[[], None] | None = None
        self._mu = threading.Lock()
        self._open = False
        self._disconnected = False
        self._notify_started = False
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
            # 阶段超时由 _async_connect 内部 asyncio.wait_for 精确裁决，外层留足余量，
            # 防止外层提前停循环导致 WinRT GattSession 清理代码来不及执行而泄漏。
            self._submit(self._async_connect(), timeout=self._connect_timeout * 2.0 + 10.0)
        except Exception as exc:
            self.close()
            if isinstance(exc, SerialException):
                raise
            raise SerialException(f"BLE 连接失败（{self.address}）：{exc}") from exc



    def _run_loop(self) -> None:
        """事件循环线程主体：绑定循环、通知就绪后常驻运行。"""
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        self._loop.run_forever()
        self._loop.close()



    def _submit(self, coro, *, timeout: float):
        """把协程投到 BLE 事件循环并同步等结果，超时抛 SerialTimeoutException。"""
        if not self._loop.is_running():
            coro.close()
            raise SerialException("BLE 事件循环已关闭")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout)
        except TimeoutError as exc:
            if not fut.done():
                fut.cancel()
                try:
                    fut.result(timeout=2.0)
                except BaseException:
                    pass
            raise SerialTimeoutException("BLE 操作超时") from exc



    def _on_disconnect(self, _client: Any) -> None:
        """断线回调：标记端口已关闭并记录断线。"""
        with self._mu:
            self._open = False
            self._disconnected = True
        logger.warning("BLE 设备已断开：%s", self.address)

    def set_rx_callback(self, callback: Callable[[], None] | None) -> None:
        """注册收帧回调：Notify 到达时立即唤醒读线程，避免等满帧间隔。"""
        with self._mu:
            self._rx_callback = callback

    def _on_notify(self, _sender: Any, data: bytearray | bytes) -> None:
        """通知回调：把收到的字节追加进接收缓冲区。"""
        if not data:
            return
        with self._mu:
            self._rx.extend(data)
            cb = self._rx_callback
        if cb is not None:
            cb()

    async def _safe_disconnect(self, client: Any) -> None:
        """安全断连：停通知、断连并释放残留的 WinRT 会话对象，异常一律忽略。"""
        if client is None:
            return
        try:
            if self._notify_started and getattr(client, "is_connected", False):
                try:
                    await asyncio.wait_for(client.stop_notify(self._notify_uuid), timeout=1.0)
                except Exception:
                    pass
            self._notify_started = False
            # 不以 is_connected 门控 disconnect()：瞬断或半连态下底层仍可能持有 GattSession
            try:
                await asyncio.wait_for(client.disconnect(), timeout=3.0)
            except Exception:
                pass
            # 防御 bleak WinRT 在 services=None 时 disconnect() 早退，确保释放残留 _session/_requester
            backend = getattr(client, "_backend", None)
            if backend is not None:
                for attr in ("_session", "_requester"):
                    obj = getattr(backend, attr, None)
                    if obj is not None:
                        try:
                            obj.close()
                        except Exception:
                            pass
                        try:
                            setattr(backend, attr, None)
                        except Exception:
                            pass
        except Exception:
            pass



    async def _connect_once(self, factory: Callable[..., Any], target: Any, budget: float) -> Any:
        """异步建连：解析透传特征、订阅通知，成功后标记端口已打开。"""
        client = factory(
            target,
            disconnected_callback=self._on_disconnect,
            timeout=self._connect_timeout,
        )
        self._client = client
        try:
            await asyncio.wait_for(client.connect(), timeout=budget)
        except TimeoutError as exc:
            await self._safe_disconnect(client)
            self._client = None
            raise SerialTimeoutException(
                "BLE 建连超时（请确认设备已通电、靠近主机且未被其他程序占用；若刚断开过可重启蓝牙模块后重试）"
            ) from exc
        except BaseException:
            await self._safe_disconnect(client)
            self._client = None
            raise
        return client

    async def _async_connect(self) -> None:
        factory = self._client_factory
        cached_dev = None
        if factory is None:
            BleakClient, _ = _import_bleak()
            factory = BleakClient
            cached_dev = _get_cached_ble_device(self.address)

        if cached_dev is not None:
            try:
                client = await self._connect_once(factory, cached_dev, self._connect_timeout + 2.0)
            except Exception as exc:
                _drop_cached_ble_device(self.address)
                if isinstance(exc, SerialTimeoutException):
                    raise
                client = await self._connect_once(
                    factory, self.address, self._connect_timeout * 2.0 + 2.0
                )
        else:
            budget = (
                self._connect_timeout
                if self._client_factory is not None
                else self._connect_timeout * 2.0 + 2.0
            )
            try:
                client = await self._connect_once(factory, self.address, budget)
            except Exception as exc:
                # 真机 WinRT 在模块刚复位或广播切换瞬间偶发快速建连失败，短暂回落后自动重试一次；
                # 已经完整扫描仍未发现设备（BleakDeviceNotFoundError）或超时则直接返回，不再白等一轮
                if (
                    self._client_factory is not None
                    or isinstance(exc, SerialTimeoutException)
                    or type(exc).__name__ == "BleakDeviceNotFoundError"
                ):
                    raise
                await asyncio.sleep(0.6)
                client = await self._connect_once(factory, self.address, budget)

        try:
            notify_uuid, write_uuid, use_response = resolve_gatt_chars(
                getattr(client, "services", ()),
                self._service_uuid,
                self._notify_uuid,
                self._write_uuid,
            )
            self._notify_uuid = notify_uuid
            self._write_uuid = write_uuid
            self._write_with_response = use_response
            try:
                await asyncio.wait_for(
                    client.start_notify(self._notify_uuid, self._on_notify),
                    timeout=min(self._connect_timeout, 8.0),
                )
            except TimeoutError as exc:
                raise SerialTimeoutException("BLE 订阅通知超时") from exc
            self._notify_started = True
            with self._mu:
                if self._disconnected:
                    raise SerialException("BLE 连接建立后立即断开")
                self._open = True
        except BaseException:
            await self._safe_disconnect(client)
            self._client = None
            raise



    async def _async_write_chunk(self, chunk: bytes) -> None:
        """把一片数据写到 Write 特征，是否带响应由连接时探测结果决定。"""
        client = self._client
        if client is None:
            raise SerialException("BLE 端口已关闭")
        try:
            await asyncio.wait_for(
                client.write_gatt_char(
                    self._write_uuid, chunk, response=self._write_with_response
                ),
                timeout=self._write_timeout,
            )
        except TimeoutError as exc:
            raise SerialTimeoutException(
                f"BLE 写入超时（>{self._write_timeout:.1f}s）"
            ) from exc



    async def _async_close(self) -> None:
        """异步断开：先停通知再断连，过程中的异常一律忽略。"""
        client = self._client
        self._client = None
        await self._safe_disconnect(client)
        # 取消并等待残留协程跑完 finally，避免停循环时遗留未关闭的 WinRT 对象
        me = asyncio.current_task()
        others = [t for t in asyncio.all_tasks() if t is not me and not t.done()]
        for task in others:
            task.cancel()
        if others:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*others, return_exceptions=True), timeout=2.0
                )
            except Exception:
                pass



    @property
    def is_open(self) -> bool:
        """端口是否已经连上并打开。"""
        with self._mu:
            return self._open



    def read(self, size: int = 1) -> bytes:
        """从接收缓冲区取数据；端口关闭或已断开时抛 SerialException。"""
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
        """按 MTU 切片写入，分片中途中失败按部分写上报。"""
        if not self.is_open:
            raise SerialException("BLE 端口未打开或已断开")
        if not data:
            return 0
        written = 0
        for offset in range(0, len(data), self._mtu_chunk):
            chunk = data[offset : offset + self._mtu_chunk]
            try:
                self._submit(
                    self._async_write_chunk(chunk),
                    timeout=self._write_timeout + 1.0,
                )
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
        """空实现，仅校验端口仍打开。"""
        if not self.is_open:
            raise SerialException("BLE 端口已关闭")



    def close(self) -> None:
        """先关连接再停事件循环，最后回收线程。"""
        with self._mu:
            self._open = False
            self._rx_callback = None
        if self._loop.is_running():
            try:
                self._submit(self._async_close(), timeout=5.0)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=3.0)
