from fastapi import APIRouter, Depends

from app.deps import current_user
from app.resp import ok

router = APIRouter(prefix="/api/faces", tags=["表情"])

_BUILTIN_FACES = (
    (0, "睡觉"),
    (1, "委屈"),
    (2, "开心"),
    (3, "狂热"),
    (4, "超开心"),
    (5, "眼睛"),
    (6, "震惊"),
)


@router.get("")
def list_faces(user: dict = Depends(current_user)):
    return ok(
        [
            {"id": fid, "name": name, "builtin": True, "preview": None}
            for fid, name in _BUILTIN_FACES
        ]
    )
