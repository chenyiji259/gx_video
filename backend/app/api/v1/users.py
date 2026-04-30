from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(request: Request, current_user: User = Depends(get_current_user)) -> JSONResponse:
    """获取当前用户信息及余额。"""
    data = {
        "id": current_user.id,
        "username": current_user.username,
        "status": current_user.status,
        "credits": getattr(current_user, "credits", 200),
        "plan_type": getattr(current_user, "plan_type", "free"),
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }
    return JSONResponse(content=ok(data=data, request_id=get_request_id(request)))
