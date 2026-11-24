"""0009：Scene / FaceAsset 的归属约束

文档映射：
- 06 §10「Scene/FaceAsset不能因为暂不开页面就遗留错误owner；按同一策略回填/隔离」
- 06 §10 归属约束表：「可空，引用 user.id，删除父行时 RESTRICT」
- 05 N25「遗留scene/face引用失效owner；迁移不得只修command/telemetry，所有活跃外键成立」

0008 只给 device / command_log / telemetry / device_claim 落了约束，这两张表被漏掉：

- scene.owner_id 是裸 Integer（无外键），模型层还带着 default=1。
  新建场景只要没显式传主人，SQLAlchemy 就自动填 1 —— 迁移后 id=1 是那个被禁用的
  旧账号。这是「用约定值当默认归属」，06 §10 明确禁止。
- face_asset 连 owner_id 列都没有。purge.py 里那行 TODO
  「自定义表情暂时无法按用户清理」，根因就是它。

本版只做结构，一行数据都不碰：
1. scene.owner_id 加外键 → user.id，ON DELETE RESTRICT
2. face_asset 新增可空 owner_id，同样加外键
3. 加外键前验数：指向不存在 user 的行必须为 0，非 0 即 raise 中止

为什么不走 expand→backfill→verify→contract 四段式：
两张表在正式库（见 backups/pet_dog_before_cleanup_*.sql）和测试库当前都是 0 行，
没有存量行需要回填，也没有「先放开再收紧」的时间差。若某个环境真有存量行，
第 3 步会拦住并打印定位 SQL，人工按 06 §10「隔离」处置后重跑即可——
为此拆成四个版本反而是过度设计。

为什么两列都允许 NULL：
NULL 表示「无主」：系统预置场景、或历史表情确实无法证明归属。
06 §10 要的是「不能遗留错误 owner」，NULL 不是错误 owner，猜一个 id 才是。
这和 0005 的 device_pk「配不上就留 NULL」是同一条判断——无证据不补值。

为什么 ON DELETE RESTRICT 而不是 CASCADE：
CASCADE 删父行时静默删子行，删完不告诉你删了什么，与本项目「禁止 CASCADE 默默删」
冲突。注销清理由应用层显式做（app/services/purge.py），先删子行再改 status，
这个顺序本身就是证据链。
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def _orphan_count(bind, table: str) -> int:
    """owner_id 非 NULL、但指向不存在 user 的行数。

    LEFT JOIN + IS NULL（反连接）是 0005/0006/0007 一直在用的同一个套路：
    左表每行都出现，右表匹配不上就整行填 NULL，所以 u.id IS NULL 精确命中悬空引用。
    """
    sql = (
        f"SELECT COUNT(*) FROM {table} t "
        "LEFT JOIN user u ON u.id = t.owner_id "
        "WHERE t.owner_id IS NOT NULL AND u.id IS NULL"
    )
    return int(bind.execute(sa.text(sql)).scalar_one())



def upgrade() -> None:
    """给 scene 与 face_asset 的 owner_id 加外键，先验悬空数据再加约束。"""
    bind = op.get_bind()

    # ---- scene：已有 owner_id 列，先验数再加外键 ----
    n = _orphan_count(bind, "scene")
    if n:
        raise RuntimeError(
            f"[验数失败] scene.owner_id 有 {n} 行指向不存在的 user。\n"
            "        0009 已中止，未写入版本号，修好后重跑即可。\n"
            "        不要自动置 NULL——那等于替人决定归属。按 06 §10「隔离」处理：\n"
            "        先清点这些行属于谁，能确认就改对 owner_id，不能确认就移出活跃表。\n"
            "        定位用的 SQL：\n"
            "        SELECT t.id, t.name, t.owner_id FROM scene t\n"
            "          LEFT JOIN user u ON u.id = t.owner_id\n"
            "         WHERE t.owner_id IS NOT NULL AND u.id IS NULL"
        )

    op.create_foreign_key(
        "fk_scene_owner",
        "scene",
        "user",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # ---- face_asset：先补列，再加外键 ----
    # 新列对存量行一律是 NULL，NULL 不违反外键，所以这一步不需要验数。
    op.add_column("face_asset", sa.Column("owner_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_face_asset_owner",
        "face_asset",
        "user",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )



def downgrade() -> None:
    # 顺序：先删引用方（face_asset 的外键/列），再删被引用方的约束。
    #
    # drop_index 这两行不能省。MySQL 删外键时不会连带删掉当初为它自动建的索引，
    # 少删一次，回退后的表结构就比 0008 多一个空索引，test_migration 的
    # compare_metadata 会立刻报差异。0008 的 downgrade 踩过同一个坑。
    """回滚 0009：按依赖顺序删除外键、索引与 owner_id 列。"""
    op.drop_constraint("fk_face_asset_owner", "face_asset", type_="foreignkey")
    op.drop_index("fk_face_asset_owner", table_name="face_asset")
    op.drop_column("face_asset", "owner_id")

    op.drop_constraint("fk_scene_owner", "scene", type_="foreignkey")
    op.drop_index("fk_scene_owner", table_name="scene")

    # 注意：downgrade 不恢复 models.py 里的 default=1。
    # 那个默认值是本次要消除的问题本身，不是可回退的结构。
