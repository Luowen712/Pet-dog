"""手工跑一次注销清理。可重复执行，不影响正在使用的账号。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.services.purge import purge_revoking


def main():
    db = SessionLocal()
    try:
        r = purge_revoking(db)
    finally:
        db.close()

    print("本次转 revoked: %d 个，失败 %d 个" % (r["purged"], r["failed"]))
    for item in r["detail"]:
        print("  id=%s  删除 scene %s 条" % (item["id"], item["scenes"]))
    for item in r["errors"]:
        print("  [失败] id=%s  %s" % (item["id"], item["error"]))
    return 0 if r["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
