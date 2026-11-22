from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    # 归属：可空（未绑定设备），删除用户时 RESTRICT —— 设备是硬件资产，
    # 删账号不等于设备消失，必须先显式解绑
    owner_id = Column(
        Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True
    )
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

    __table_args__ = (
        # 一个账号至多一台设备。MySQL 的 UNIQUE 允许多个 NULL，
        # 所以未绑定设备（owner_id=NULL）不受这条限制。
        UniqueConstraint("owner_id", name="uq_device_owner"),
        # I1：有主必 bound，无主必非 bound。
        # 和 0007 验数、0008 的 DDL 必须是同一句话，三处改一处就等于没改。
        CheckConstraint(
            "(owner_id IS NULL AND status <> 'bound') "
            "OR (owner_id IS NOT NULL AND status = 'bound')",
            name="ck_device_owner_status",
        ),
    )


class CommandLog(Base):
    __tablename__ = "command_log"
    id = Column(Integer, primary_key=True)
    device_id = Column(String(32), index=True)
    # device_pk 指向 device.id。0004 加列时先留可空，0007 验数确认零 NULL 后
    # 0008 才收紧成 NOT NULL + 外键（expand → backfill → verify → contract）
    device_pk = Column(
        Integer, ForeignKey("device.id", ondelete="RESTRICT"), nullable=False
    )
    __table_args__ = (UniqueConstraint('actor_user_id', 'msg_id', name='uq_command_actor_msg'),)
    msg_id = Column(String(36), index=True)
    error_code = Column(Integer, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    cmd = Column(Integer)
    action = Column(Integer, nullable=True)
    param = Column(String(128), nullable=True)
    status = Column(Integer, default=1)
    seq = Column(Integer, nullable=True)
    source = Column(String(16), default="api")
    # 设备自发的命令没有操作人，所以可空
    actor_user_id = Column(
        Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True
    )
    # 发起时的绑定纪元 / 用户 token 版本 / 状态版本，用于事后判定这条命令是否还有效
    be = Column(Integer, nullable=False, default=0, server_default=text("0"))
    tv = Column(Integer, nullable=False, default=0, server_default=text("0"))
    revision = Column(Integer, nullable=False, default=0, server_default=text("0"))
    # null=尚未尝试，0=全写，1=确定未写，2=可能部分写
    transport = Column(Integer, nullable=True)
    reason = Column(String(128), nullable=True)
    session_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)


class Telemetry(Base):
    __tablename__ = "telemetry"
    id = Column(Integer, primary_key=True)
    device_id = Column(String(32), index=True)
    # 同 CommandLog：0004 加列时留可空，0007 验数后 0008 收紧
    device_pk = Column(
        Integer, ForeignKey("device.id", ondelete="RESTRICT"), nullable=False
    )
    battery = Column(Integer, nullable=True)
    music_state = Column(Integer, nullable=True)
    action = Column(Integer, nullable=True)
    raw = Column(String(256), nullable=True)
    # 这条遥测属于哪一代绑定 / 哪一次连接，防止旧快照污染新主人
    be = Column(Integer, nullable=False, default=0, server_default=text("0"))
    session_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)


class Scene(Base):
    __tablename__ = "scene"
    id = Column(Integer, primary_key=True)
    name = Column(String(64))
    steps = Column(Text)
    # 归属：可空外键（0009）。NULL = 无主（系统预置场景），不是错误归属。
    # 原来这里是裸 Integer + default=1：新建场景不传主人就自动归给 id=1 的账号，
    # 而迁移后 id=1 是被禁用的旧账号。默认值也是一种隐式授权，不能留。
    owner_id = Column(
        Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.now)


class FaceAsset(Base):
    __tablename__ = "face_asset"
    id = Column(Integer, primary_key=True)
    name = Column(String(64))
    width = Column(Integer, default=128)
    height = Column(Integer, default=32)
    data = Column(Text)
    # 0009 新增：没有这一列时，注销账号无法按用户清理自定义表情
    # （purge.py 里那条 TODO 说的就是这件事）。
    owner_id = Column(
        Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True
    )
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
    # 软删除时间。账号状态仍以 status(active/revoking/revoked) 为准，这里只记时间做审计
    deleted_at = Column(DateTime, nullable=True)


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
