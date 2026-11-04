from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean

from app.db import Base


class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(16), default="user")
    created_at = Column(DateTime, default=datetime.now)


class Device(Base):
    __tablename__ = "device"
    id = Column(Integer, primary_key=True)
    device_id = Column(String(32), unique=True, nullable=False)
    name = Column(String(64), default="桌宠一号")
    firmware = Column(String(16), default="2.0.0")
    capability = Column(Integer, default=31)
    online = Column(Boolean, default=False)
    last_seen = Column(DateTime, nullable=True)
    owner_id = Column(Integer, default=1)


class CommandLog(Base):
    __tablename__ = "command_log"
    id = Column(Integer, primary_key=True)
    device_id = Column(String(32), index=True)
    msg_id = Column(String(36), index=True)
    cmd = Column(Integer)
    action = Column(Integer, nullable=True)
    param = Column(String(128), nullable=True)
    status = Column(Integer, default=1)
    seq = Column(Integer, nullable=True)
    source = Column(String(16), default="api")
    created_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)


class Telemetry(Base):
    __tablename__ = "telemetry"
    id = Column(Integer, primary_key=True)
    device_id = Column(String(32), index=True)
    battery = Column(Integer, nullable=True)
    music_state = Column(Integer, nullable=True)
    action = Column(Integer, nullable=True)
    raw = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)


class Scene(Base):
    __tablename__ = "scene"
    id = Column(Integer, primary_key=True)
    name = Column(String(64))
    steps = Column(Text)
    owner_id = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)


class FaceAsset(Base):
    __tablename__ = "face_asset"
    id = Column(Integer, primary_key=True)
    name = Column(String(64))
    width = Column(Integer, default=128)
    height = Column(Integer, default=32)
    data = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
