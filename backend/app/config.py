from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "桌面宠物后端"
    PORT: int = 8000
    DB_URL: str = Field(min_length=1)
    # 链路入口：ble（扫描后前端点选直连）/ ble://<地址> / sim / COMx / loop://
    SERIAL_PORT: str = "ble"
    SERIAL_BAUD: int = 9600
    SERIAL_DEVICE_PK: int | None = Field(default=None, gt=0)
    # 低功耗蓝牙透传模块 ECB02H2 默认 GATT UUID（不同固件批次可在 .env 覆写，例如 FFE0/FFE1）
    BLE_SERVICE_UUID: str = "0000fff0-0000-1000-8000-00805f9b34fb"
    BLE_NOTIFY_UUID: str = "0000fff1-0000-1000-8000-00805f9b34fb"
    BLE_WRITE_UUID: str = "0000fff2-0000-1000-8000-00805f9b34fb"
    BLE_MTU_CHUNK: int = Field(default=20, ge=20, le=244)
    BLE_SCAN_TIMEOUT_SEC: float = Field(default=4.0, gt=0, le=15.0)
    JWT_SECRET: str = Field(min_length=32)
    JWT_EXPIRE_HOURS: int = 24
    ONLINE_TTL_SEC: int = 30
    DEV_HEARTBEAT: bool = False


settings = Settings()
