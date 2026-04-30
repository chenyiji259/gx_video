from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.services.project_service import ProjectService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
async def get_overview(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """获取用户 Dashboard 概览（最近项目 + 统计）。"""
    req_id = get_request_id(request)
    data = await ProjectService().get_dashboard_summary(user_id=current_user.id)
    
    # 修改统计数据以包含真实用户余额
    data["stats"]["credits_balance"] = getattr(current_user, "credits", 200)
    
    return JSONResponse(content=ok(data=data, request_id=req_id))
