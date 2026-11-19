from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "桌面宠物后端"
    PORT: int = 8000
    DB_URL: str = Field(min_length=1)
    SERIAL_PORT: str = "COM5"
    SERIAL_BAUD: int = 9600
    JWT_SECRET: str = Field(min_length=32)
    # 配对码 HMAC 密钥，刻意与 JWT_SECRET 分开（见 02 的 BB03 第 3 条）：
    # 轮换登录密钥不该连带作废未使用的配对码，单点泄露也不该同时打开配对码的离线穷举。
    # 与 JWT_SECRET 同一套 fail-closed 口径：不给默认值，缺了就起不来。
    CLAIM_SECRET: str = Field(min_length=32)
    JWT_EXPIRE_HOURS: int = 24
    ONLINE_TTL_SEC: int = 30
    DEV_HEARTBEAT: bool = False


settings = Settings()
