from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "桌面宠物后端"
    PORT: int = 8000
    DB_URL: str = "mysql+pymysql://petdog:petdog@127.0.0.1:3306/pet_dog?charset=utf8mb4"
    SERIAL_PORT: str = "COM5"
    SERIAL_BAUD: int = 9600
    JWT_SECRET: str = "change-me-in-dotenv"
    JWT_EXPIRE_HOURS: int = 24
    ACK_TIMEOUT: float = 3.0
    WEATHER_LAT: float = 39.90
    WEATHER_LON: float = 116.40
    WEATHER_CITY: str = "北京"
    ONLINE_TTL_SEC: int = 30
    DEV_HEARTBEAT: bool = False


settings = Settings()
