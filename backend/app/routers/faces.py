from fastapi import APIRouter, Depends

from app.deps import current_user
from app.resp import ok

router = APIRouter(prefix="/api/faces", tags=["表情"])

_BUILTIN_FACES = (
    (0, "普通"),
    (1, "开心"),
    (2, "困倦"),
    (3, "生气"),
    (4, "惊讶"),
    (5, "伤心"),
    (6, "卖萌"),
)


@router.get("")
def list_faces(user: dict = Depends(current_user)):
    return ok(
        [
            {"id": fid, "name": name, "builtin": True, "preview": None}
            for fid, name in _BUILTIN_FACES
        ]
    )
