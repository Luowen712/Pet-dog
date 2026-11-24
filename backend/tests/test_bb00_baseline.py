from sqlalchemy import text

from app.config import settings
from app.db import engine



def test_settings_point_to_test_db():
    """确认配置指向隔离测试库，不会误连正式库。"""
    assert "pet_dog_test_bb00" in settings.DB_URL
    assert "/pet_dog?" not in settings.DB_URL



def test_engine_can_connect():
    """确认数据库引擎能连上并执行查询。"""
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
