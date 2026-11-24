"""注销账号的收尾清理：revoking → revoked。
幂等：只查 revoking，跑完就变 revoked，重复调用返回 0。
可重启续跑：不依赖内存状态，每次都扫库。
"""

from sqlalchemy.orm import Session

from app.models import FaceAsset, Scene, User



def purge_revoking(db: Session) -> dict:
    """把 revoking 账号清成 revoked：先删场景与人脸，再改状态；幂等可重跑。"""
    rows = db.query(User).filter(User.status == "revoking").all()

    purged = []
    failed = []
    for u in rows:
        try:
            # 先删子行、再改父行状态：外键是 RESTRICT，顺序不能反
            # （反了会报 1451，整个事务回滚，账号永远注销不掉）。
            n_scene = (
                db.query(Scene)
                .filter(Scene.owner_id == u.id)
                .delete(synchronize_session=False)
            )
            n_face = (
                db.query(FaceAsset)
                .filter(FaceAsset.owner_id == u.id)
                .delete(synchronize_session=False)
            )
            u.status = "revoked"
            db.commit()
            purged.append({"id": u.id, "scenes": n_scene, "faces": n_face})
        except Exception as e:
            db.rollback()
            failed.append({"id": u.id, "error": str(e)})

    return {
        "purged": len(purged),
        "failed": len(failed),
        "detail": purged,
        "errors": failed,
    }
