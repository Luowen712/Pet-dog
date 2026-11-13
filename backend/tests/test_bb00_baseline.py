from sqlalchemy import text

from app.config import settings
from app.db import engine


def test_settings_point_to_test_db():
    assert "pet_dog_test_bb00" in settings.DB_URL
    assert "/pet_dog?" not in settings.DB_URL


def test_engine_can_connect():
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
