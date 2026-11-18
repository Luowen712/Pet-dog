"""校验 0007 的验数与 0008 的 CHECK 说的是同一条规则。

0007 在迁移前判断"数据满不满足 I1"，0008 把 I1 装成 CHECK 永久生效。
两处若是两份不一致的表达式，验数就白验：验的是宽松版、装上去的是严格版，
0008 当场报 3819，而且只说"CHECK 违反"，不会告诉你是哪边写错了。

为什么不能直接 import：迁移文件名以数字开头，`import 0007_xxx` 是语法错误，
只能走 importlib 按文件路径加载。加载时只执行模块级代码（定义常量、构建 CHECKS），
不会调用 upgrade()，所以这个测试不碰数据库。
"""

import importlib.util
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load(filename: str):
    """按路径加载迁移模块，仅取其中的常量，不执行迁移。"""
    path = VERSIONS / filename
    spec = importlib.util.spec_from_file_location(f"mig_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _squash(sql: str) -> str:
    """去掉全部空白并转小写。

    不能直接比字符串：0008 的表达式是单行，0007 的 SQL 里被 NOT(...) 包了一层、
    还带大量对齐用的空格。空白在 SQL 中从不构成语义，抹掉它是最安全的归一化。
    小写同理 —— SQL 关键字大小写不敏感，写 IS NULL 还是 is null 是同一件事。
    """
    return re.sub(r"\s+", "", sql).lower()


def test_0007_verify_sql_contains_0008_check_expression() -> None:
    m7 = _load("0007_verify_binding_invariants.py")
    m8 = _load("0008_add_binding_constraints.py")

    # 按标签定位而不是硬编码下标：CHECKS 中间插一项，下标就全错位了
    matches = [(sql, label) for sql, label, _ in m7.CHECKS if "status 自洽" in label]
    assert len(matches) == 1, (
        f"0007 里应恰好有一项 I1 检查，实际找到 {len(matches)} 项："
        f"{[label for _, label in matches]}。CHECKS 可能被改过标签或删错了项。"
    )
    sql, _ = matches[0]

    expr = m8.I1_EXPR
    assert _squash(expr) in _squash(sql), (
        "0008 的 I1_EXPR 没有出现在 0007 第 9 项的 SQL 里。\n"
        "两处必须描述同一条规则，否则验数验的是宽松版、装上去的是严格版，\n"
        "0008 的 ALTER 会报 3819，而且看不出是哪边写的。\n"
        f"0008 I1_EXPR    = {expr!r}\n"
        f"0007 第 9 项 SQL = {sql.strip()!r}"
    )
