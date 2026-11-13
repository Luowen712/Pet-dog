"""注销账号的收尾清理：revoking → revoked。
幂等：只查 revoking，跑完就变 revoked，重复调用返回 0。
可重启续跑：不依赖内存状态，每次都扫库。
"""

from sqlalchemy.orm import Session

from app.models import Scene, User


def purge_revoking(db: Session) -> dict:
    rows = db.query(User).filter(User.status == "revoking").all()

    purged = []
    failed = []
    for u in rows:
        try:
            n_scene = (
                db.query(Scene)
                .filter(Scene.owner_id == u.id)
                .delete(synchronize_session=False)
            )
            # TODO: face_asset 表没有 owner_id，自定义表情暂时无法按用户清理
            u.status = "revoked"
            db.commit()
            purged.append({"id": u.id, "scenes": n_scene})
        except Exception as e:
            db.rollback()
            failed.append({"id": u.id, "error": str(e)})

    return {
        "purged": len(purged),
        "failed": len(failed),
        "detail": purged,
        "errors": failed,
    }
