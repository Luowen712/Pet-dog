"""模拟设备心跳，让设备在页面上持续显示在线。

用法（在 backend 目录下）：
    .venv\\Scripts\\python.exe tools\\sim_heartbeat.py
    .venv\\Scripts\\python.exe tools\\sim_heartbeat.py PET-0001-ABCD
    .venv\\Scripts\\python.exe tools\\sim_heartbeat.py PET-0001-ABCD PET-0002-EFGH

不带参数时给两台演示设备都发。Ctrl+C 停止，停止 30 秒后设备自动转为离线。

这是开发期的"假设备"，等串口线程接上以后（收到 0x03 帧就刷新 last_seen），
把本文件删掉即可。
"""

import json
import sys
import time
import urllib.request

URL = "http://127.0.0.1:8000/api/devices/heartbeat"
INTERVAL = 10  # 秒；必须小于 config.ONLINE_TTL_SEC，否则会来回抖动
DEFAULT_DEVICES = ["PET-0001-ABCD", "PET-0002-EFGH"]


def beat(device_id: str) -> str:
    body = json.dumps({"device_id": device_id, "battery": 80}).encode()
    req = urllib.request.Request(
        URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.load(resp)["data"]
        return f"online={data['online']} last={data['last_heartbeat']}"


def main() -> None:
    devices = sys.argv[1:] or DEFAULT_DEVICES
    print(f"heartbeat every {INTERVAL}s -> {URL}")
    print(f"devices: {', '.join(devices)}")
    print("Ctrl+C to stop\n")

    try:
        while True:
            stamp = time.strftime("%H:%M:%S")
            for dev in devices:
                try:
                    print(f"{stamp}  {dev}  {beat(dev)}", flush=True)
                except Exception as exc:
                    print(f"{stamp}  {dev}  FAILED: {exc}", flush=True)
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nstopped. devices turn offline in 30s.")


if __name__ == "__main__":
    main()
