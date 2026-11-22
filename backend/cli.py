"""本机管理员 CLI（BB02 第 3、4 条）。

用法：
    python cli.py create-admin <username>
    python cli.py list-admin
    python cli.py reset <username>

三条硬约束：
    - 密码只从终端交互读取，绝不出现在 argv / 环境变量 / 日志里
    - 会改授权或管理员状态的操作（create-admin / reset）必须先拿
      petdog:admin:v1 命名锁；拿不到就退出码 3，一个字节都不写
    - 哈希计算放在拿锁之前（06§7：哈希计算先完成再拿锁），
      Argon2id 单次约 40ms，占着锁算等于是把并发窗口白白拉长

list-admin 是只读，按规则 6 不需要命名锁——命名锁只保护跨进程的
管理员计数与状态迁移，不保护读取。
"""

import getpass
import re
import sys
import warnings

from app.db import SessionLocal
from app.hostlock import HostLockError, admin_lock
from app.link.lock import HostProcessLock, LockUnavailable
from app.models import User
from app.security import hash_pwd

PASSWORD_MIN = 10
PASSWORD_MAX = 128


# 与 app/routers/auth.py 的 USERNAME_RE 同一口径。
# 不直接 import 是为了让 CLI 不依赖 FastAPI 路由层。
USERNAME_RE = re.compile(r"[a-zA-Z0-9_\u4e00-\u9fa5]{3,20}")


class CliError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


def _validate_password(pw: str) -> None:
    if not (PASSWORD_MIN <= len(pw) <= PASSWORD_MAX):
        raise CliError("密码需要 %d–%d 位" % (PASSWORD_MIN, PASSWORD_MAX))


def _assert_interactive_terminal() -> None:
    """计划第 4 条的前三步：必须确认「这是一个人在真终端里敲」。

    只在管道下才会出问题的写法（比如只看 GetPassWarning）挡不住
    `echo pw | python cli.py create-admin x` 这种把密码写进管道的方式。
    """
    # ① 三个流任一为 None：被完全重定向或服务化运行
    if sys.stdin is None or sys.__stdin__ is None or sys.stderr is None:
        raise CliError("标准输入/错误流不可用，拒绝在非交互环境读取密码")

    # ② stdin 被替换过：说明输入来自包装器/重定向，不是用户键盘
    if sys.stdin is not sys.__stdin__:
        raise CliError(
            "标准输入已被替换（sys.stdin 不是 sys.__stdin__），拒绝读取密码"
        )

    # ③ isatty 是主判据：管道、重定向文件、here-doc 全都返回 False
    if not sys.stdin.isatty():
        raise CliError("当前不是交互式终端（TTY），拒绝通过管道读取密码")


def _read_password(prompt: str = "密码: ") -> str:
    """五步保护下的密码读取：① ② ③ 在 _assert_interactive_terminal，
    ④ ⑤ 在这里——因为后两步必须紧贴 getpass 调用。"""
    _assert_interactive_terminal()

    with warnings.catch_warnings():
        # ④ GetPassWarning 只在 getpass 判定「可能回显」时触发。
        #    Windows 上走管道并不必然触发它，所以它只是兜底，不是主判据；
        #    但一旦触发就必须当错误停下，不能拿着可能回显的输入继续。
        warnings.simplefilter("error", getpass.GetPassWarning)

        # ⑤ 两次读取施加同一保护并比对，防单次输错锁死自己
        first = getpass.getpass(prompt)
        second = getpass.getpass("再次输入确认: ")

    if first != second:
        raise CliError("两次输入不一致")
    _validate_password(first)
    return first


def cmd_create_admin(username: str) -> int:
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise CliError("用户名需 3–20 位字母、数字、下划线或中文")

    password = _read_password()
    # 先算哈希再拿锁：40ms 的 CPU 时间不该占着跨进程锁。
    pw_hash = hash_pwd(password)

    with HostProcessLock(), admin_lock():
        db = SessionLocal()
        try:
            if db.query(User).filter(User.username == username).first():
                raise CliError("用户已存在：%s" % username)

            u = User(
                username=username,
                password_hash=pw_hash,
                role="admin",
                status="active",
                token_version=0,
            )
            db.add(u)
            db.commit()
            print("已创建管理员：%s (id=%d)" % (username, u.id))
        finally:
            db.close()

    return 0


def cmd_list_admin() -> int:
    db = SessionLocal()
    try:
        rows = db.query(User).filter(User.role == "admin").order_by(User.id).all()
    finally:
        db.close()

    if not rows:
        print("没有任何管理员账号，请先执行 create-admin")
        return 0

    print("%-6s %-18s %-10s %s" % ("id", "username", "status", "created_at"))
    for u in rows:
        print(
            "%-6d %-18s %-10s %s"
            % (u.id, u.username, u.status, u.created_at or "-")
        )
    return 0


def cmd_reset(username: str) -> int:
    username = username.strip()

    password = _read_password()
    pw_hash = hash_pwd(password)

    with HostProcessLock(), admin_lock():
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == username).first()
            if not u:
                raise CliError("用户不存在：%s" % username)

            u.password_hash = pw_hash
            # token_version +1 让所有已签发的旧 token 立刻失效（判据：reset 踢旧 token）
            u.token_version = (u.token_version or 0) + 1
            db.commit()
            print(
                "已重置 %s 的密码，token_version=%d，旧 token 全部失效"
                % (username, u.token_version)
            )
        finally:
            db.close()

    return 0


USAGE = """用法：
  python cli.py create-admin <username>   交互式设置密码并创建管理员
  python cli.py list-admin                列出所有管理员（只读）
  python cli.py reset <username>          交互式重置密码并踢掉旧 token"""


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv

    if not args:
        print(USAGE)
        return 2

    cmd, rest = args[0], args[1:]

    try:
        if cmd == "create-admin":
            if len(rest) != 1:
                raise CliError("用法：python cli.py create-admin <username>")
            return cmd_create_admin(rest[0])

        if cmd == "list-admin":
            if rest:
                raise CliError("list-admin 不接受参数")
            return cmd_list_admin()

        if cmd == "reset":
            if len(rest) != 1:
                raise CliError("用法：python cli.py reset <username>")
            return cmd_reset(rest[0])

        print(USAGE)
        return 2

    except LockUnavailable as e:
        # 06:204 / N24：后端正在运行时拒绝绕过主机锁写库
        print("[拒绝] %s" % e, file=sys.stderr)
        return 3

    except HostLockError as e:
        # 契约要求：拿不到锁 → 退出码 3，不继续任何写操作
        print("[拒绝] %s" % e, file=sys.stderr)
        return e.exit_code

    except CliError as e:
        print("[错误] %s" % e, file=sys.stderr)
        return e.exit_code

    except Exception as e:
        print("[失败] %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
