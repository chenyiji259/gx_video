"""
VidMuse 全链路 E2E 测试脚本
============================

测试链路：
  创建项目 → 上传音频 → 激活规格 → 音频分析 → 风格选择(自动) →
  创意方案 → 确认(自动) → 镜头计划 → 确认(自动) →
  分镜图生成 → 确认(自动) → 视频 clip 生成 → clips_ready

运行前提（缺任何一项测试无法正常执行）：
  1. config/base/workflow.yaml: auto_confirm_decisions: true   ← 已设置
  2. 后端服务器:  cd backend && uvicorn main:app --host 0.0.0.0 --port 8000
  3. Worker 进程: cd backend && python -m app.tasks.worker
  4. PostgreSQL / Redis / MinIO 全部连通（可先用 test_connections.py 验证）
  5. 准备测试音频: scripts/test_audio.mp3（30 秒左右的 MP3 文件）

配置参数（修改下方 CONFIG 字典）：
  BASE_URL          后端地址（默认 http://localhost:8000）
  USERNAME/PASSWORD 已存在的测试账户（需提前在数据库中创建）
  AUDIO_FILE        测试音频文件路径
  USER_PROMPT       创意描述文本

运行方式：
  cd C:/Users/Administrator/Desktop/1/vidMuse
  python scripts/test_e2e_flow.py

注意事项：
  - 脚本只调用 HTTP API，不直接操作数据库
  - 视频生成耗时很长（每个 clip 约 10-15 分钟），请保持网络通畅
  - 如果某步骤超时，查看后端日志排查原因
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

# 确保 backend 目录在 Python 路径中（与现有 scripts 保持一致）
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

# ─────────────────────────────────────────────────────────────────────────────
# 配置区（按实际情况修改）
# ─────────────────────────────────────────────────────────────────────────────
CONFIG = {
    # 后端地址
    "BASE_URL": "http://localhost:8000",

    # 已存在的测试账户（用户名 + 密码）
    "USERNAME": "admin",
    "PASSWORD": "changeme",

    # 测试音频文件（MP3 / WAV，建议 20-60 秒）
    "AUDIO_FILE": str(Path(__file__).parent / "test_audio.mp3"),

    # 音频分析区间（0 = 从头开始，0 = 结束时自动取全长）
    "AUDIO_START_SEC": 0.0,
    "AUDIO_END_SEC": 30.0,  # 修改为音频实际时长（秒）

    # 创意描述
    "USER_PROMPT": "清新日系风格，温馨青春，讲述夏日相遇的短暂与美好",

    # 目标 MV 时长（秒）
    "TARGET_DURATION_SEC": 30.0,

    # 输出比例
    "ASPECT_RATIO": "16:9",

    # 轮询间隔（秒）
    "POLL_INTERVAL": 10,

    # 每个等待阶段最大轮询次数
    # 音频分析：约 30-120s；分镜：约 2-8 分钟；视频：约 10-30 分钟
    "MAX_POLLS_SHORT": 30,   # 30×10s = 5分钟（音频分析、创意方案）
    "MAX_POLLS_MEDIUM": 60,  # 60×10s = 10分钟（分镜生成）
    "MAX_POLLS_LONG": 180,   # 180×10s = 30分钟（视频 clip 生成）

    # 触发 Director 自动确认的 chat 消息后等待时长（秒）
    "AUTO_CONFIRM_WAIT": 15,
}


# ─────────────────────────────────────────────────────────────────────────────
# 彩色输出
# ─────────────────────────────────────────────────────────────────────────────
def c_ok(msg: str)   -> None: print(f"\033[32m[✓] {msg}\033[0m")
def c_fail(msg: str) -> None: print(f"\033[31m[✗] {msg}\033[0m"); sys.exit(1)
def c_info(msg: str) -> None: print(f"\033[36m[·] {msg}\033[0m")
def c_step(title: str) -> None:
    sep = "─" * 55
    print(f"\n\033[1m{sep}\n  {title}\n{sep}\033[0m")
def c_warn(msg: str) -> None: print(f"\033[33m[!] {msg}\033[0m")


# ─────────────────────────────────────────────────────────────────────────────
# E2E 测试主类
# ─────────────────────────────────────────────────────────────────────────────
class E2ETest:

    def __init__(self) -> None:
        self.api_base    = CONFIG["BASE_URL"] + "/api/v1"
        self.chat_base   = CONFIG["BASE_URL"] + "/v1"
        self.token: str  = ""
        self.project_id: str = ""
        self.session_id: str | None = None
        self._headers: dict = {}

    @property
    def auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    # ─────────────────────────────────────────
    # 辅助：API 调用封装
    # ─────────────────────────────────────────

    async def _get(self, client: httpx.AsyncClient, path: str) -> dict:
        resp = await client.get(f"{self.api_base}{path}", headers=self.auth_headers)
        return resp.json()

    async def _post(self, client: httpx.AsyncClient, path: str, body: dict) -> dict:
        resp = await client.post(
            f"{self.api_base}{path}",
            json=body,
            headers=self.auth_headers,
        )
        return resp.json()

    # ─────────────────────────────────────────
    # 辅助：轮询项目阶段
    # ─────────────────────────────────────────

    async def poll_stage(
        self,
        client: httpx.AsyncClient,
        target_stage: str,
        desc: str,
        max_polls: int | None = None,
    ) -> None:
        max_p = max_polls or CONFIG["MAX_POLLS_SHORT"]
        c_info(f"等待阶段 [{target_stage}] — {desc}")
        for i in range(max_p):
            data = await self._get(client, f"/projects/{self.project_id}")
            stage = data.get("data", {}).get("current_stage", "unknown")
            c_info(f"  [{i+1}/{max_p}] current_stage = {stage}")
            if stage == target_stage:
                c_ok(f"已到达 {target_stage}")
                return
            # 如果已超过目标阶段（阶段顺序是递进的），也视为成功
            _stage_order = [
                "created", "input_ready", "audio_analyzed", "brief_ready",
                "narrative_ready", "visual_bible_ready", "shot_plan_ready",
                "storyboard_ready", "clips_ready", "timeline_ready",
                "export_ready", "completed",
            ]
            if (
                stage in _stage_order
                and target_stage in _stage_order
                and _stage_order.index(stage) > _stage_order.index(target_stage)
            ):
                c_warn(f"阶段已超过目标（{stage} > {target_stage}），继续执行")
                return
            await asyncio.sleep(CONFIG["POLL_INTERVAL"])
        c_fail(f"超时：等待 {target_stage} 超过 {max_p * CONFIG['POLL_INTERVAL']}s")

    # ─────────────────────────────────────────
    # 辅助：发送 chat 消息触发 Director 图
    # 目的：让 human_confirmation_gate 自动创建并确认决策
    # ─────────────────────────────────────────

    async def trigger_director(
        self,
        client: httpx.AsyncClient,
        message: str = "请继续下一步",
    ) -> None:
        c_info(f"触发 Director（auto_confirm=true）: \"{message}\"")
        body: dict = {
            "model": "vidmuse-director",
            "messages": [{"role": "user", "content": message}],
            "stream": False,
            "project_id": self.project_id,
        }
        if self.session_id:
            body["session_id"] = self.session_id

        resp = await client.post(
            f"{self.chat_base}/chat/completions",
            json=body,
            headers=self.auth_headers,
            timeout=120.0,
        )
        result = resp.json()

        # 保存 session_id 供后续复用
        choices = result.get("choices", [{}])
        if choices:
            assistant_msg = choices[0].get("message", {}).get("content", "")
            if assistant_msg:
                c_info(f"  Director 回复（前100字）: {assistant_msg[:100]}...")

        # 等待 auto_confirm 后台处理
        await asyncio.sleep(CONFIG["AUTO_CONFIRM_WAIT"])

    # ─────────────────────────────────────────
    # 辅助：轮询并等待指定决策被选中
    # ─────────────────────────────────────────

    async def wait_decision_selected(
        self,
        client: httpx.AsyncClient,
        decision_type: str,
        desc: str,
    ) -> None:
        """等待指定类型的决策出现且状态为 selected（由 auto_confirm 完成）。"""
        c_info(f"等待决策自动确认: {decision_type} — {desc}")
        for i in range(CONFIG["MAX_POLLS_SHORT"]):
            data = await self._get(client, f"/projects/{self.project_id}/decisions")
            items = data.get("data", {}).get("items", [])
            # 同时检查 selected 状态（auto_confirm 后才是 selected）
            # decisions API 只返回 open 状态，需要另外检查
            # 方案：只要 open 决策消失（或从未出现），说明已 selected 或不存在
            open_dec = next(
                (d for d in items if d.get("decision_type") == decision_type),
                None,
            )
            if open_dec is None:
                # open 决策不存在：可能已 selected，或尚未创建（继续等）
                c_info(f"  [{i+1}] {decision_type} 无 open 决策，已自动确认或尚未创建")
                # 等待后再检查一次，避免尚未创建的误判
                if i >= 2:
                    c_ok(f"决策 {decision_type} 已处理")
                    return
            else:
                c_info(f"  [{i+1}] {decision_type} 仍为 open，等待 auto_confirm...")
            await asyncio.sleep(CONFIG["POLL_INTERVAL"])
        c_warn(f"等待决策 {decision_type} 超时，继续执行（可能 auto_confirm 尚未完成）")

    # ─────────────────────────────────────────
    # Step 1: 登录
    # ─────────────────────────────────────────

    async def step_login(self, client: httpx.AsyncClient) -> None:
        c_step("Step 1 ▶ 登录")
        resp = await client.post(
            f"{self.api_base}/auth/login",
            json={
                "username": CONFIG["USERNAME"],
                "password": CONFIG["PASSWORD"],
            },
        )
        data = resp.json()
        if resp.status_code != 200 or not data.get("success"):
            c_fail(f"登录失败 HTTP {resp.status_code}: {data}")
        self.token = data["data"]["access_token"]
        c_ok(f"登录成功，token 前20位: {self.token[:20]}...")

    # ─────────────────────────────────────────
    # Step 2: 创建项目
    # ─────────────────────────────────────────

    async def step_create_project(self, client: httpx.AsyncClient) -> None:
        c_step("Step 2 ▶ 创建项目")
        project_name = f"E2E-Test-{int(time.time())}"
        data = await self._post(client, "/projects", {"name": project_name})
        if not data.get("success"):
            c_fail(f"创建项目失败: {data}")
        self.project_id = data["data"]["id"]
        c_ok(f"项目已创建: {project_name}  project_id={self.project_id}")

    # ─────────────────────────────────────────
    # Step 3: 上传音频（三步式）
    # ─────────────────────────────────────────

    async def step_upload_audio(self, client: httpx.AsyncClient) -> str:
        c_step("Step 3 ▶ 上传音频")

        audio_path = Path(CONFIG["AUDIO_FILE"])
        if not audio_path.exists():
            c_fail(
                f"音频文件不存在: {audio_path}\n"
                "请在 scripts/ 目录放置 test_audio.mp3（约 30 秒的 MP3 文件）"
            )

        filename = audio_path.name
        content_type = "audio/mpeg" if filename.lower().endswith(".mp3") else "audio/wav"
        pid = self.project_id

        # ─── 3a: upload-init ───
        c_info(f"申请上传槽位: {filename} ({content_type})")
        data = await self._post(
            client,
            f"/projects/{pid}/assets/upload-init",
            {
                "filename": filename,
                "content_type": content_type,
                "asset_type": "audio_original",
            },
        )
        if not data.get("success"):
            c_fail(f"upload-init 失败: {data}")

        upload_url  = data["data"]["upload_url"]
        asset_id    = data["data"]["asset_id"]
        object_key  = data["data"]["object_key"]
        bucket_name = data["data"]["bucket_name"]
        c_info(f"asset_id={asset_id}")

        # ─── 3b: PUT 文件到 MinIO ───
        c_info("直传文件到 MinIO（可能稍慢）...")
        audio_bytes = audio_path.read_bytes()
        put_resp = await client.put(
            upload_url,
            content=audio_bytes,
            headers={"Content-Type": content_type},
            timeout=180.0,
        )
        if put_resp.status_code not in (200, 204):
            c_fail(f"PUT 文件到 MinIO 失败: HTTP {put_resp.status_code}\n{put_resp.text[:200]}")
        c_info(f"文件已上传，大小 {len(audio_bytes) // 1024} KB")

        # ─── 3c: complete ───
        c_info("通知后端确认上传完成...")
        data = await self._post(
            client,
            f"/projects/{pid}/assets/complete",
            {
                "asset_id":     asset_id,
                "object_key":   object_key,
                "bucket_name":  bucket_name,
                "filename":     filename,
                "content_type": content_type,
                "asset_type":   "audio_original",
            },
        )
        if not data.get("success"):
            c_fail(f"complete 失败: {data}")

        c_ok(f"音频上传完成: asset_id={asset_id}")
        return asset_id

    # ─────────────────────────────────────────
    # Step 4: 创建并激活 ProjectSpec
    # ─────────────────────────────────────────

    async def step_activate_spec(
        self,
        client: httpx.AsyncClient,
        audio_asset_id: str,
    ) -> None:
        c_step("Step 4 ▶ 激活 ProjectSpec → input_ready")
        pid = self.project_id

        # 4a: 创建版本
        data = await self._post(
            client,
            f"/projects/{pid}/spec/versions",
            {
                "input_mode":      "audio_text",
                "audio_asset_id":  audio_asset_id,
                "audio_start_sec": CONFIG["AUDIO_START_SEC"],
                "audio_end_sec":   CONFIG["AUDIO_END_SEC"],
                "user_prompt":     CONFIG["USER_PROMPT"],
                "output_config": {
                    "aspect_ratio":        CONFIG["ASPECT_RATIO"],
                    "target_duration_sec": CONFIG["TARGET_DURATION_SEC"],
                },
            },
        )
        if not data.get("success"):
            c_fail(f"创建 spec 版本失败: {data}")
        version_id = data["data"]["id"]
        c_info(f"spec version_id={version_id}")

        # 4b: 激活
        data = await self._post(
            client,
            f"/projects/{pid}/spec/activate",
            {"version_id": version_id},
        )
        if not data.get("success"):
            c_fail(f"激活 spec 失败: {data}")
        c_ok("ProjectSpec 已激活 → 项目进入 input_ready")

    # ─────────────────────────────────────────
    # Step 5: 触发音频分析
    # ─────────────────────────────────────────

    async def step_analyze_audio(self, client: httpx.AsyncClient) -> None:
        c_step("Step 5 ▶ 触发音频分析（异步 Worker）")
        pid = self.project_id

        data = await self._post(
            client,
            f"/projects/{pid}/workflow/analyze-audio",
            {},
        )
        if not data.get("success"):
            c_fail(f"触发音频分析失败: {data}")
        job_id = data["data"]["job_id"]
        c_ok(f"音频分析任务已提交: job_id={job_id}")

        # 等待 audio_analyzed（Worker 完成后 → Mode B Director 自动运行
        # → human_confirmation_gate 创建 select_style_direction 决策
        # → auto_confirm=true 自动选 style_cinematic）
        await self.poll_stage(
            client,
            "audio_analyzed",
            "音频分析 + 风格决策自动确认",
            max_polls=CONFIG["MAX_POLLS_SHORT"],
        )

    # ─────────────────────────────────────────
    # Step 6: 生成创意方案（brief）
    # ─────────────────────────────────────────

    async def step_generate_brief(self, client: httpx.AsyncClient) -> None:
        c_step("Step 6 ▶ 生成创意方案（brief + style）")
        pid = self.project_id

        # Mode B Director 在音频分析后已 auto-select select_style_direction
        # 但如果 Mode B 还没跑完，这里先等一下再触发
        c_info("等待风格决策自动确认完成...")
        await asyncio.sleep(5)

        # 如果 select_style_direction 还未 selected，发一条 chat 消息触发 Director
        decisions = await self._get(client, f"/projects/{pid}/decisions")
        open_style = next(
            (
                d for d in decisions.get("data", {}).get("items", [])
                if d.get("decision_type") == "select_style_direction"
            ),
            None,
        )
        if open_style:
            c_warn("风格决策仍 open，发送 chat 消息触发自动确认...")
            await self.trigger_director(client, "音频分析完成，请继续选择风格")

        data = await self._post(
            client,
            f"/projects/{pid}/workflow/generate-brief",
            {},
        )
        if not data.get("success"):
            c_fail(
                f"生成创意方案失败: {data}\n"
                "可能原因：select_style_direction 决策尚未 selected，"
                "请检查 auto_confirm_decisions=true 且 Worker 正常运行"
            )
        c_ok(
            f"创意方案已生成: brief_version_id={data['data']['brief_version_id']} "
            f"| {data['data'].get('summary', '')}"
        )

        # generate-brief 是同步调用，brief_ready 已在返回时完成
        # 但 confirm_brief 决策需要 Director 图触发才会创建
        # → 发一条 chat 消息驱动 Director → gate 创建 confirm_brief → auto_confirm
        c_info("触发 Director 创建 confirm_brief 决策并自动确认...")
        await self.trigger_director(client, "创意方案已生成，请继续")

    # ─────────────────────────────────────────
    # Step 7: 生成镜头计划（shot plan）
    # ─────────────────────────────────────────

    async def step_generate_shot_plan(self, client: httpx.AsyncClient) -> None:
        c_step("Step 7 ▶ 生成镜头计划（shot plan）")
        pid = self.project_id

        data = await self._post(
            client,
            f"/projects/{pid}/workflow/generate-shot-plan",
            {},
        )
        if not data.get("success"):
            err = data.get("error", {})
            if err.get("code") == "decision_required":
                # confirm_brief 还未 selected，再等并重试
                c_warn("confirm_brief 未就绪，再等 20s 后重试...")
                await asyncio.sleep(20)
                await self.trigger_director(client, "请确认创意方案并继续")
                data = await self._post(
                    client,
                    f"/projects/{pid}/workflow/generate-shot-plan",
                    {},
                )
                if not data.get("success"):
                    c_fail(f"生成镜头计划失败（重试）: {data}")
            else:
                c_fail(f"生成镜头计划失败: {data}")

        shot_count = data["data"]["shot_count"]
        c_ok(f"镜头计划已生成: {shot_count} 个镜头")

        # 同理：触发 Director 创建 confirm_shot_plan 决策并 auto_confirm
        c_info("触发 Director 创建 confirm_shot_plan 决策并自动确认...")
        await self.trigger_director(client, "镜头计划已生成，请继续生成分镜图")

    # ─────────────────────────────────────────
    # Step 8: 生成分镜图（storyboard）
    # ─────────────────────────────────────────

    async def step_generate_storyboard(self, client: httpx.AsyncClient) -> None:
        c_step("Step 8 ▶ 生成分镜图（异步 Worker，耗时 2-8 分钟）")
        pid = self.project_id

        data = await self._post(
            client,
            f"/projects/{pid}/workflow/generate-storyboard",
            {},
        )
        if not data.get("success"):
            err = data.get("error", {})
            if err.get("code") == "decision_required":
                c_warn("confirm_shot_plan 未就绪，再等 20s 后重试...")
                await asyncio.sleep(20)
                await self.trigger_director(client, "请确认镜头计划并开始分镜生成")
                data = await self._post(
                    client,
                    f"/projects/{pid}/workflow/generate-storyboard",
                    {},
                )
                if not data.get("success"):
                    c_fail(f"触发分镜生成失败（重试）: {data}")
            else:
                c_fail(f"触发分镜生成失败: {data}")

        job_id = data["data"]["job_id"]
        c_ok(f"分镜生成任务已提交: job_id={job_id}")

        # Worker 完成后 Mode B Director 自动创建 confirm_storyboard 并 auto_confirm
        await self.poll_stage(
            client,
            "storyboard_ready",
            "分镜图生成完成（约 2-8 分钟）",
            max_polls=CONFIG["MAX_POLLS_MEDIUM"],
        )

    # ─────────────────────────────────────────
    # Step 9: 生成视频 clip
    # ─────────────────────────────────────────

    async def step_generate_clips(self, client: httpx.AsyncClient) -> None:
        c_step("Step 9 ▶ 生成视频 clip（异步 Worker，每个 clip 约 10-15 分钟）")
        pid = self.project_id

        # Mode B Director 在 storyboard_ready 后 auto_confirm confirm_storyboard
        # 等一小会再触发
        await asyncio.sleep(5)

        data = await self._post(
            client,
            f"/projects/{pid}/workflow/generate-clips",
            {},
        )
        if not data.get("success"):
            err = data.get("error", {})
            if err.get("code") == "decision_required":
                c_warn("confirm_storyboard 未就绪，发 chat 触发自动确认后重试...")
                await self.trigger_director(client, "分镜图已确认，请开始生成视频片段")
                data = await self._post(
                    client,
                    f"/projects/{pid}/workflow/generate-clips",
                    {},
                )
                if not data.get("success"):
                    c_fail(f"触发视频生成失败（重试）: {data}")
            else:
                c_fail(f"触发视频生成失败: {data}")

        job_id = data["data"]["job_id"]
        c_ok(f"视频生成任务已提交: job_id={job_id}")
        c_info("提示：每个镜头约 10-15 分钟，请耐心等待 SSE 推送 clip.shot.completed 事件")

        await self.poll_stage(
            client,
            "clips_ready",
            "所有视频 clip 生成完成",
            max_polls=CONFIG["MAX_POLLS_LONG"],
        )

    # ─────────────────────────────────────────
    # 主流程
    # ─────────────────────────────────────────

    async def run(self) -> None:
        print("\n" + "═" * 60)
        print("  VidMuse 全链路 E2E 测试")
        print(f"  BASE_URL  : {CONFIG['BASE_URL']}")
        print(f"  AUDIO_FILE: {CONFIG['AUDIO_FILE']}")
        print(f"  USER_PROMPT: {CONFIG['USER_PROMPT']}")
        print("═" * 60)

        start_ts = time.monotonic()

        async with httpx.AsyncClient(timeout=180.0) as client:
            await self.step_login(client)
            await self.step_create_project(client)
            audio_asset_id = await self.step_upload_audio(client)
            await self.step_activate_spec(client, audio_asset_id)
            await self.step_analyze_audio(client)
            await self.step_generate_brief(client)
            await self.step_generate_shot_plan(client)
            await self.step_generate_storyboard(client)
            await self.step_generate_clips(client)

        elapsed = round(time.monotonic() - start_ts, 1)
        elapsed_min = round(elapsed / 60, 1)

        print("\n" + "═" * 60)
        print("\033[32m  ✓ 全链路测试完成！\033[0m")
        print(f"  project_id : {self.project_id}")
        print(f"  总耗时     : {elapsed}s（约 {elapsed_min} 分钟）")
        print("═" * 60 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        import httpx  # 确认依赖已安装
    except ImportError:
        print("[✗] 缺少依赖: pip install httpx")
        sys.exit(1)

    asyncio.run(E2ETest().run())
