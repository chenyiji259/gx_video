"""ProjectSpec 版本 API（doc 05 §17.6）。

接口：
  POST /projects/{project_id}/spec/versions  - 创建新 ProjectSpec 版本
  POST /projects/{project_id}/spec/activate  - 激活指定版本（触发 input_ready 推进）
  GET  /projects/{project_id}/spec/active    - 获取当前激活版本详情
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

from app.api.v1.deps import get_current_user, get_request_id, ok
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.duration_recommendation_service import (
    DurationRecommendationError,
    DurationRecommendationService,
)
from app.services.project_spec_service import (
    ProjectSpecError,
    ProjectSpecService,
    normalize_product_reference_asset_ids,
)
from app.services.output_spec_service import normalize_output_config

router = APIRouter(
    prefix="/projects/{project_id}/spec",
    tags=["project-spec"],
)


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class CreateSpecVersionRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    input_mode: str = Field(
        default="audio_text",
        description="输入模式：audio_text / audio_image_text",
    )
    audio_asset_id: Optional[str] = Field(
        None, description="音频资产 ID（已上传的 audio_original 资产）"
    )
    audio_start_sec: float = Field(
        default=0.0, ge=0.0, description="音频起始时间（秒）"
    )
    audio_end_sec: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "音频结束时间（秒）。"
            "传 0 或不传时，系统自动从已上传的 audio_asset_id 读取实际音频时长回填。"
            "如果尚未上传音频或音频无 duration_ms，则保持 0，后续流程会在达到需要时抛出错误提示用户重新设置。"
        ),
    )
    user_prompt: str = Field(
        default="", max_length=2000, description="用户创意描述"
    )
    output_config: Optional[dict] = Field(
        None, description="输出配置（aspect_ratio / resolution / target_duration_sec 等）"
    )
    reference_image_asset_ids: Optional[list] = Field(
        None,
        description=(
            "用户上传的角色参考图 asset_id 列表，顺序即上传顺序（最多 5 张）。"
            "有内容时 input_mode 自动切换为 audio_image_text。"
        ),
    )
    product_reference_asset_ids: Optional[list] = Field(
        None,
        description="用户上传的产品图 asset_id 列表，顺序即上传顺序，最多 3 张。",
    )
    constraints: Optional[dict] = Field(
        None, description="附加约束（可选）"
    )

    # ---- 新流程字段（AI视频内容生成模式）----
    platform: Optional[str] = Field(
        None,
        description="发布平台：tiktok / bilibili / youtube / youtube_shorts / instagram / xiaohongshu",
    )
    target_audience: Optional[str] = Field(
        None,
        description="目标受众描述，例如：'面向小白用户' / '专业技术人员'",
    )
    style_preference: Optional[str] = Field(
        None,
        description="视觉风格偏好：animated_tech / live_action / minimal / cinematic 等",
    )
    human_on_camera: Optional[bool] = Field(
        None,
        description="是否需要真人入镜。true=关键画面应有真人主体，false=后续画面应避免真人主体。",
    )
    target_duration_sec: Optional[float] = Field(
        None,
        ge=5.0,
        le=600.0,
        description="目标视频时长（秒），新流程必填。例如 60.0 表示 1 分钟。",
    )
    aspect_ratio: Optional[str] = Field(
        None,
        description="画面比例：9:16（竖屏/TikTok）/ 16:9（横屏/YouTube）/ 1:1（方形）",
    )
    video_resolution: Optional[str] = Field(
        None,
        description="视频生成清晰度：480p / 720p / 1080p。必须从需求入口确定并传递到 Seedance。",
    )
    image_resolution: Optional[str] = Field(
        None,
        description="三宫格生图清晰度，当前主流程固定规范化为 2K。",
    )
    generation_profile: Optional[str] = Field(
        None,
        description="生成链路 profile，例如 talking_head_production_board。",
    )
    storyboard_layout: Optional[str] = Field(
        None,
        description="Storyboard 布局，例如 talking_head_story_overview_board。",
    )
    segment_duration_sec: Optional[int] = Field(
        None,
        description="口播类项目固定为 15 秒。",
    )
    story_board_aspect_ratio: Optional[str] = Field(
        None,
        description="故事大图画幅，口播类固定为 21:9。",
    )
    subtitles_enabled: Optional[bool] = Field(
        None,
        description="当前口播主链路固定 false。",
    )


class ActivateSpecVersionRequest(BaseModel):
    version_id: str = Field(..., description="要激活的 ProjectSpec 版本 ID")


class RecommendDurationRequest(BaseModel):
    user_prompt: str = Field(default="", max_length=2000, description="用户创意描述")
    platform: Optional[str] = Field(None, description="发布平台")
    target_audience: Optional[str] = Field(None, description="目标受众")
    style_preference: Optional[str] = Field(None, description="视觉风格偏好")
    human_on_camera: Optional[bool] = Field(None, description="是否需要真人入镜")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/versions", status_code=status.HTTP_201_CREATED)
async def create_spec_version(
    project_id: str,
    body: CreateSpecVersionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """创建新 ProjectSpec 版本（不自动激活）。

    版本创建后处于非激活状态，需要调用 /activate 接口激活。
    此设计支持先创建多个草稿版本，再选择激活某一个。
    """
    req_id = get_request_id(request)
    try:
        # 新流程：将新字段合并到 output_config
        _output_config = dict(body.output_config or {})
        if body.platform is not None:
            _output_config["platform"] = body.platform
        if body.target_audience is not None:
            _output_config["target_audience"] = body.target_audience
        if body.style_preference is not None:
            _output_config["style_preference"] = body.style_preference
        if body.human_on_camera is not None:
            _output_config["human_on_camera"] = body.human_on_camera
        if body.target_duration_sec is not None:
            _output_config["target_duration_sec"] = body.target_duration_sec
        # 画面比例：优先从 aspect_ratio 字段取，其次从 output_config 取，默认 9:16
        _output_config["aspect_ratio"] = body.aspect_ratio or _output_config.get("aspect_ratio", "9:16")
        if body.video_resolution is not None:
            _output_config["video_resolution"] = body.video_resolution
        if body.image_resolution is not None:
            _output_config["image_resolution"] = body.image_resolution
        if body.generation_profile is not None:
            _output_config["generation_profile"] = body.generation_profile
        if body.storyboard_layout is not None:
            _output_config["storyboard_layout"] = body.storyboard_layout
        if body.segment_duration_sec is not None:
            _output_config["segment_duration_sec"] = body.segment_duration_sec
        if body.story_board_aspect_ratio is not None:
            _output_config["story_board_aspect_ratio"] = body.story_board_aspect_ratio
        if body.subtitles_enabled is not None:
            _output_config["subtitles_enabled"] = body.subtitles_enabled
        if body.product_reference_asset_ids is not None:
            _output_config["product_reference_asset_ids"] = normalize_product_reference_asset_ids(
                body.product_reference_asset_ids
            )
        elif "product_reference_asset_ids" in _output_config:
            _output_config["product_reference_asset_ids"] = normalize_product_reference_asset_ids(
                _output_config.get("product_reference_asset_ids")
            )
        _output_config = normalize_output_config(_output_config)
        # 新流程 input_mode：有文本需求但无音频时自动切换为 text_only
        _input_mode = body.input_mode
        if not body.audio_asset_id and _input_mode == "audio_text":
            _input_mode = "text_only"

        spec = await ProjectSpecService().create_version(
            project_id=project_id,
            user_id=current_user.id,
            input_mode=_input_mode,
            audio_asset_id=body.audio_asset_id,
            audio_start_sec=body.audio_start_sec,
            audio_end_sec=body.audio_end_sec,
            user_prompt=body.user_prompt,
            reference_image_asset_ids=body.reference_image_asset_ids,
            output_config=_output_config,
            constraints=body.constraints,
        )
    except ProjectSpecError as e:
        http_status = (
            status.HTTP_404_NOT_FOUND
            if e.code == "not_found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return JSONResponse(
            status_code=http_status,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"success": False, "error": {"code": "invalid_output_config", "message": str(e)}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=ok(data=spec, request_id=req_id),
    )


@router.post("/recommend-duration", status_code=status.HTTP_200_OK)
async def recommend_duration(
    project_id: str,
    body: RecommendDurationRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """根据用户需求给出推荐总时长。"""
    req_id = get_request_id(request)
    try:
        async with UnitOfWork() as uow:
            project = await ProjectRepository(uow.session).get_by_id_for_user(project_id, current_user.id)
            if project is None:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"success": False, "error": {"code": "not_found", "message": "项目不存在"}, "request_id": req_id},
                )
        result = await DurationRecommendationService().recommend(
            user_prompt=body.user_prompt,
            platform=body.platform or "",
            target_audience=body.target_audience or "",
            style_preference=body.style_preference or "",
            human_on_camera=body.human_on_camera,
        )
    except DurationRecommendationError as e:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data=result, request_id=req_id),
    )


@router.post("/activate", status_code=status.HTTP_200_OK)
async def activate_spec_version(
    project_id: str,
    body: ActivateSpecVersionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """激活指定 ProjectSpec 版本。

    激活操作会：
      1. 失活该项目下所有其他版本
      2. 将目标版本设为 is_active=True
      3. 更新 projects.active_project_spec_version_id
      4. 若满足以下三个条件，自动推进项目到 input_ready：
         - audio_asset_id 不为空
         - audio_end_sec > audio_start_sec
         - user_prompt 不为空
    """
    req_id = get_request_id(request)
    try:
        spec = await ProjectSpecService().activate_version(
            project_id=project_id,
            user_id=current_user.id,
            version_id=body.version_id,
        )
    except ProjectSpecError as e:
        http_status = (
            status.HTTP_404_NOT_FOUND
            if e.code == "not_found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return JSONResponse(
            status_code=http_status,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data=spec, request_id=req_id),
    )


@router.get("/active", status_code=status.HTTP_200_OK)
async def get_active_spec_version(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """获取项目当前激活的 ProjectSpec 版本详情。"""
    req_id = get_request_id(request)
    try:
        spec = await ProjectSpecService().get_active_version(
            project_id=project_id,
            user_id=current_user.id,
        )
    except ProjectSpecError as e:
        http_status = (
            status.HTTP_404_NOT_FOUND
            if e.code == "not_found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return JSONResponse(
            status_code=http_status,
            content={"success": False, "error": {"code": e.code, "message": e.message}, "request_id": req_id},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok(data=spec, request_id=req_id),
    )
