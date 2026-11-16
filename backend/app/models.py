from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from app.db import Base


class Device(Base):
    __tablename__ = "device"
    id = Column(Integer, primary_key=True)
    device_id = Column(String(32), unique=True, nullable=False)
    name = Column(String(64), default="桌宠一号")
    firmware = Column(String(16), default="2.0.0")
    capability = Column(Integer, default=31)
    online = Column(Boolean, default=False)
    last_seen = Column(DateTime, nullable=True)
    owner_id = Column(Integer)
    be = Column(Integer, nullable=False, default=0, server_default=text("0"))  # ②
    status = Column(
        String(16),
        nullable=False,
        default="claimable",
        server_default=text("'claimable'"),
    )  # ③
    handover_state = Column(
        String(16),
        nullable=False,
        default="required",
        server_default=text("'required'"),
    )  # ④
    bound_at = Column(DateTime, nullable=True)


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


class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(16), default="user")
    token_version = Column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at = Column(DateTime, default=datetime.now)
    status = Column(
        String(16), nullable=False, default="active", server_default=text("'active'")
    )


# 设备是否有主人,是否被认领
class DeviceClaim(Base):
    __tablename__ = "device_claim"
    id = Column(Integer, primary_key=True)
    device_pk = Column(
        Integer, ForeignKey("device.id", ondelete="RESTRICT"), nullable=False
    )
    code_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    locked_until = Column(DateTime, nullable=True)
    consumed_at = Column(DateTime, nullable=True)
    consumed_by_user_id = Column(
        Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.now)


class AuditLog(Base):
    """审计：账号动作 device_pk 可空，设备动作 actor_user_id 可空。

    只存数字身份，不存用户名 —— 注销时 username 会被改写成 ~del~1~xxxx，
    存字符串就永远对不上当时那个人了。
    """

    __tablename__ = "audit"
    id = Column(Integer, primary_key=True)
    actor_user_id = Column(
        Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True
    )
    device_pk = Column(
        Integer, ForeignKey("device.id", ondelete="RESTRICT"), nullable=True
    )
    action = Column(String(32), nullable=False)
    detail = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)


class LegacyRowArchive(Base):
    """无法证明归属的历史行先归档再删除活跃源行。

    UNIQUE(source_table, source_pk) 是幂等的关键：迁移重跑时同一行只归档一次，
    不会生成两条只有 id 不同的重复记录。
    """

    __tablename__ = "legacy_row_archive"
    __table_args__ = (
        UniqueConstraint("source_table", "source_pk", name="uq_legacy_row"),
    )
    id = Column(Integer, primary_key=True)
    source_table = Column(String(32), nullable=False)
    source_pk = Column(Integer, nullable=False)
    row_hash = Column(String(64), nullable=False)
    payload = Column(Text, nullable=True)
    reason = Column(String(64), nullable=True)
    archived_at = Column(DateTime, default=datetime.now)


class DeviceSessionRecord(Base):
    """串口会话记录：每次复位/链路重建都开新 session，旧未终结的改 unknown。

    1..255 的序号在同一会话内不复用，last_seq 必须落库 ——
    只放内存的话后端一重启就忘了发到第几号，设备会把迟到响应当成新指令。
    """

    __tablename__ = "device_session_record"
    id = Column(Integer, primary_key=True)
    device_pk = Column(
        Integer, ForeignKey("device.id", ondelete="RESTRICT"), nullable=False
    )
    be = Column(Integer, nullable=False, default=0, server_default=text("0"))
    session_id = Column(String(36), nullable=False)
    state = Column(
        String(16), nullable=False, default="open", server_default=text("'open'")
    )
    last_seq = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.now)
    ended_at = Column(DateTime, nullable=True)
