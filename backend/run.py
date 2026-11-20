"""后端启动入口（BA02 / 06 §5 / 01 §8）。

为什么默认关闭 reload 并显式 workers=1：
    - 串口句柄、SendGate、限流桶与主机/DB 实例锁都要求单进程唯一；
    - reload 会起监控父进程 + 子进程，改代码热重载期间容易撞上旧子进程还没放锁或串口未关闭；
    - 开发期如果确需热重载，可显式设环境变量 PETDOG_RELOAD=1。

ws_ping_interval=20 / ws_ping_timeout=10 对应 06 §5 连接槽半开检测要求：
    最后一个成功 Pong 后 30 秒内释放槽位。
"""

import os

import uvicorn

from app.config import settings

if __name__ == "__main__":
    dev_reload = os.environ.get("PETDOG_RELOAD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        workers=1,
        reload=dev_reload,
        ws_ping_interval=20.0,
        ws_ping_timeout=10.0,
    )
