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
    JWT_EXPIRE_HOURS: int = 24
    ONLINE_TTL_SEC: int = 30
    DEV_HEARTBEAT: bool = False


settings = Settings()
