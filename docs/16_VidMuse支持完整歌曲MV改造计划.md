# VidMuse 支持完整歌曲 MV 改造计划

**版本**: v1.3（定稿）
**日期**: 2026-04-04
**状态**: 完成 ✅
**执行人**: Warp AI (Oz)

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-04
- 产出：
  - `backend/app/services/project_spec_service.py` — audio_end_sec 自动检测
  - `backend/app/api/v1/project_spec.py` — 字段说明更新
  - `backend/app/services/brief_persistence_service.py` — 清除 30s 居性默认
  - `backend/app/services/shot_plan_persistence_service.py` — 清除 30s 兜底 + max_shots 公式更换
  - `backend/app/agents/creative_planning_agent.py` — 移除默认値 + 动态 max_tokens + recursion_limit
  - `backend/app/services/storyboard_service.py` — 并发锁 150→1800s
  - `backend/app/services/clip_service.py` — 并发锁动态计算
  - `backend/app/agents/audio_analysis_agent.py` — URL 传输 + max_tokens + 降级兜底
  - `backend/app/services/audio_analysis_service.py` — Omni URL + 并发锁 150→2700s
  - `backend/app/services/timeline_composer_service.py` — 并发锁 150→600s
  - `backend/app/core/config_loader.py` — LLMConfig 新增 max_tokens_shot_plan 字段
  - `config/base/llm.yaml` — max_tokens_shot_plan: 8192
  - `config/providers/omni.yaml` — timeout: 900, max_tokens: 32768
  - `config/base/workflow.yaml` — job_timeout_seconds: 3000
  - `prompts/system/audio_analysis.md` — 全量分析要求

---

## 一、需求目标

用户上传歌曲音频，系统生成与音频**完整时长匹配**的 MV，不再固定 30~90 秒。
生成的 MV 时长 = 用户上传音频的实际时长。

---

## 二、全链路调查结论

### 2.1 正向数据流（当前状态）

```
用户上传音频（Asset.duration_ms 已存储）
    ↓
ProjectSpec.create_version()
    audio_end_sec 默认 0 → _can_advance_to_input_ready() 阻断  [L1]
    ↓
AudioAnalysisService
    下载音频到临时文件 → base64 编码 → Omni API              [L7]
    并发锁 timeout_sec=150，Omni timeout=120s                 [L8/L9]
    ↓
BriefPersistenceService
    target_duration_sec = (audio_end_sec or 30) - start       [L3]
    if dur <= 0: target_duration_sec = 30.0                   [L3]
    ↓
ShotPlanPersistenceService
    target_duration_sec = (audio_end_sec or 30) - start       [L2 side]
    max_shots = max(4, min(24, int(dur / 2.5)))  ← 上限 24   [L2]
    ↓
CreativePlanningAgent.run_phase1()
    target_duration_sec 默认 30.0                             [L4]
CreativePlanningAgent.run_phase2()
    target_duration_sec 默认 30.0，max_tokens=4096            [L4/L5]
    ↓
StoryboardService   并发锁 timeout_sec=150                    [L8]
    ↓
ClipService         并发锁 timeout_sec=660（30+ shots 必超）  [L8]
    ↓
TimelineComposerService  并发锁 timeout_sec=150              [L8]
    ↓
ExportService  ffmpeg 转码，无时长限制 ✅
```

### 2.2 限制点总表

| # | 文件 | 位置 | 问题 | 性质 | 修复批次 |
|---|------|------|------|------|---------|
| L1 | `project_spec_service.py` | :279-298 | `audio_end_sec > 0` 才能推进 input_ready；用户不传默认 0 → 全链路阻断 | **阻断** | 16-01 |
| L2 | `shot_plan_persistence_service.py` | :317 / :360 | :317 `(audio_end_sec or 30)` 隐性兜底；:360 `min(24,...)` 硬上限 24 镜头 | **阻断**（≥5min）| :317 → 16-01；:360 → 16-02 |
| L3 | `brief_persistence_service.py` | :179-182 | `(audio_end_sec or 30)` + `= 30.0` 双重兜底，brief 按 30s 生成 | **阻断**（输出质量）| 16-01 |
| L4 | `creative_planning_agent.py` | :153 / :241 | phase1/phase2 均有 `target_duration_sec = 30.0` 隐性兜底 | 隐性风险 | 16-02 |
| L5 | `creative_planning_agent.py` | :271 | `max_tokens` 取全局 `llm.yaml`（4096），40+ 镜头 JSON 可能截断 | 容量风险 | 16-02 |
| L6 | `workflow.yaml` | :20 | `job_timeout_seconds: 660`；Omni 改为 900s × 3 次重试 = 2700s，Worker 重启误判僵尸 | 边界风险 | 16-03 |
| L7 | `audio_analysis_agent.py` | :150-177 | 音频下载为临时文件 → base64 编码，8min 音频约 100MB+，效率低且不必要 | 效率风险 | 16-03 |
| L8 | `storyboard_service.py` :96<br>`clip_service.py` :105<br>`timeline_composer_service.py` :92 | — | 并发锁过短：storyboard=150s、clip=660s（必然过期）、timeline=150s | **storyboard/clip 高风险** | 16-02（storyboard/clip）<br>16-03（timeline）|
| L9 | `config/providers/omni.yaml` | :22-23 | `timeout=120s`（8min 音频远不够）；`max_tokens=4096`（长音频 JSON 可能截断）| **阻断**（长音频）| 16-03 |

### 2.3 确认无需改动的部分

| 文件 | 原因 |
|------|------|
| `audio_trim_tool.py` | 已支持任意时长裁切，无限制 |
| `timeline_composer_service.py`（拼接逻辑） | 按 clip 数量拼接，无时长上限 |
| `export_service.py` | ffmpeg 转码，无时长限制 |
| `cost_estimation_service.py` | 已按秒计费，天然支持任意时长 |
| `cost_gate_service.py` | 按 shot 数量/费用门控，无时长阻断 |
| `project_spec_version.py`（ORM 模型） | `audio_end_sec` 字段类型无限制 |
| `generate_shot_plan.md`（prompt） | `target_duration_sec` 已参数化 |
| 数据库 migration | 不需要新增字段或表 |

### 2.4 视频模型约束

当前实际使用：**ToAPIs → Grok Video 3**（`grok_video_3`）。

> `kling_adapter.py` 存在但未被启用，`video_providers.yaml` 仅注册 `grok_imagine_10_video` 和 `grok_video_3`，均为 ToAPIs 接口。

Grok Video 3 单 shot 时长约束：**10 秒或 15 秒**（硬约束，不改动）。

| 歌曲时长 | @10s/shot（最多镜头） | @15s/shot（最少镜头） | 当前 max_shots=24 够用？ |
|---------|--------------------|--------------------|-----------------------|
| 3 分钟  | 18 | 12 | ✅ |
| 4 分钟  | 24 | 16 | ⚠️ 刚好到极限 |
| 5 分钟  | 30 | 20 | ❌ |
| 6 分钟  | 36 | 24 | ❌ |

---

## 三、执行批次

总改动量预估：**380~560 行**，分 3 个批次串行执行。

---

### 批次 16-01：打通完整歌曲入口（修复 L1/L3，清理 L2/L4 兜底）

**目标**：audio_end_sec 自动检测，全链路拿到正确音频时长。

**根因**：`Asset.duration_ms` 已存，只需在 `create_version()` 时自动回填；
`brief_persistence_service` 和 `shot_plan_persistence_service` 的 30 秒兜底在 L1 修好后虽不会触发，但属于静默失效隐患，一并清理。

**涉及文件（4 个）**：

**① `backend/app/services/project_spec_service.py`**
- 新增 import：`from app.repositories.asset_repository import AssetRepository`
- `create_version()` 中，若 `audio_end_sec=0` 且有 `audio_asset_id`，查询 Asset 取 `duration_ms`，自动设置 `audio_end_sec = duration_ms / 1000`
- 改动量：约 +35 行

**② `backend/app/api/v1/project_spec.py`**
- `audio_end_sec` 字段 `description` 补充说明：传 0 或不传时，系统自动从已上传音频读取时长
- 改动量：约 +3 行

**③ `backend/app/services/shot_plan_persistence_service.py`**（仅 :317 行，:360 行在批次 16-02 修改）
- `:317` `(spec.audio_end_sec or 30)` → `(spec.audio_end_sec or 0)`
- `dur <= 0` 时抛出 `ShotPlanGenerationError`，不再静默回落
- 改动量：约 +5 行

**④ `backend/app/services/brief_persistence_service.py`**
- `:179` `(spec.audio_end_sec or 30)` → `(spec.audio_end_sec or 0)`
- `:181-182` 删除 `if target_duration_sec <= 0: target_duration_sec = 30.0`，改为抛 `BriefGenerationError`
- 改动量：约 +8 行

**预计总改动量**：50~55 行

**验收标准**：
- 仅传 `audio_asset_id + user_prompt`（不传 `audio_end_sec`），项目推进到 `input_ready`
- `spec.audio_end_sec` = 上传音频实际时长（秒）
- brief 生成时 `target_duration_sec` = 实际音频时长，非 30 秒

---

### 批次 16-02：突破镜头上限 + 修复并发锁（修复 L2/L4/L5/L8-storyboard/clip）

**目标**：移除 max_shots=24 硬上限；动态调整 max_tokens；修复 storyboard/clip 并发锁在长歌曲下必然过期的问题。

**根因**：
- `max_shots = min(24,...)` 写死，5 分钟以上歌曲镜头不够
- clip 并发锁 660s，30+ shots 预计耗时 2~5 小时，锁必然过期 → 重复触发生成 + 双倍扣费

**涉及文件（5 个）**：

**① `backend/app/services/shot_plan_persistence_service.py`**（仅 :360 行，:317 行已在批次 16-01 修改）
- `:360` 改为：`max_shots = max(4, min(80, int(target_duration_sec / 10)))`
  - 以 10s/shot（最密排列）为基准，上限由 24 → 80
  - 注释说明：上限 80 对应约 13 分钟全高能歌曲
- 改动量：约 +5 行

**② `backend/app/agents/creative_planning_agent.py`**
- `run_phase1()` `:153`：`target_duration_sec = 30.0` 默认值 → 无默认，调用方必须显式传入
- `run_phase2()` `:241`：同上
- `run_phase2()` `:271`：`max_tokens` 改为动态计算：`max_tokens = max(4096, max_shots * 250)`（从 `llm.yaml` 或 `max_tokens_shot_plan` 配置读取基础值）
- `run_phase2()` `recursion_limit`：15 → 25（长歌曲工具调用轮次更多）
- 改动量：约 +20 行

**③ `backend/app/services/storyboard_service.py`**
- `:96` `timeout_sec=150` → `timeout_sec=1800`
  - 依据：80 shots × 8s/image × 3 = 1920s，取整 1800 作为合理上界
- 改动量：约 +1 行

**④ `backend/app/services/clip_service.py`**
- `:105` 动态并发锁：在 `shots_to_process` 列表确定后，计算 `lock_timeout = max(660, len(shots_to_process) * 600)`（每 shot 最多 10 分钟）
- 将锁获取移到 shots_to_process 读取之后
- 改动量：约 +10 行

**⑤ `config/base/llm.yaml`**
- 新增 `max_tokens_shot_plan: 8192`（作为 shot plan 专用基础值，动态计算时的参考下界）
- 改动量：约 +5 行

**预计总改动量**：60~85 行

**验收标准**：
- 5 分钟歌曲生成 30 个 shot，不因 max_shots=24 截断
- LLM 输出完整 JSON，不因 max_tokens 截断
- 30+ shots storyboard/clip 批量生成不因锁过期而重复执行

---

### 批次 16-03：稳定长音频分析（修复 L6/L7/L8-timeline/L9）

**目标**：音频分析改用 MinIO URL 传输；Omni 超时和 token 上限调大；全局任务超时对齐；timeline 锁补充。

**根因**：
- `audio_analysis_agent.py` 下载文件后 base64 编码，8 分钟音频编码后 ~100MB，效率低且无必要；Qwen3.5 Omni Plus 支持直接 URL 输入，最大 64K 上下文
- `config/providers/omni.yaml` 当前 `timeout=120s`，单次远不够；`max_tokens=4096`，长音频分析 JSON 通常 5000~12000 token
- `audio_analysis_agent.py` 中 `ChatOpenAI` 构造器未传 `max_tokens` 参数，omni.yaml 的 `max_tokens` 配置当前实际**未生效**，必须同步将配置值接入 LLM 构造器
- `workflow.yaml:job_timeout_seconds=660`，Omni 改为 900s 后 3 次重试 = 2700s，Worker 重启会误判僵尸任务

**涉及文件（6 个）**：

**① `config/providers/omni.yaml`**
- `timeout: 120` → `timeout: 900`（单次调用最多 15 分钟）
- `max_tokens: 4096` → `max_tokens: 32768`（长音频完整分析约 5000~12000 token；取 32K 与 Qwen3.5-Omni-Plus 支持上限对齐，从配置文件控制）
- 改动量：约 +4 行

**② `config/base/workflow.yaml`**
- `job_timeout_seconds: 660` → `job_timeout_seconds: 3000`（覆盖 3 次重试 × 900s = 2700s + 余量）
- 改动量：约 +2 行

**③ `backend/app/agents/audio_analysis_agent.py`**
- `run_with_omni(audio_file_path)` → `run_with_omni(audio_url)`，接收 MinIO storage_uri
- 移除 `_encode_audio()` 调用，改为直接构建：
  `{"type": "input_audio", "input_audio": {"url": audio_url}}`
- LLM 构造时补加 `max_tokens=int(omni_cfg.get("max_tokens", 4096))`（当前代码未传该参数，omni.yaml 的 max_tokens 配置实际未生效，**必须同步修改**）
- 降级兜底条件：`audio_url` 为空、以 `file://` 开头、或以 `http://localhost`/`http://127.`/`http://10.`/`http://192.168.` 开头（覆盖 dev 环境 MinIO 不可公网访问的场景），均回退 base64 模式
- `run()` 别名方法参数名同步更新为 `audio_url`
- 改动量：约 +30 行

**④ `backend/app/services/audio_analysis_service.py`**
- `tempfile.TemporaryDirectory` 下载块**保留不动**：librosa `_beat_analyze` 在 `audio_analysis_tool.py:23` 以 `librosa.load(str(audio_path))` 实现，必须传本地文件路径，无法接受 URL；删除该块会导致节拍分析 `RuntimeError`
- 只修改 `asyncio.gather()` 中 Omni 那一行：`agent.run_with_omni(audio_path)` → `agent.run_with_omni(audio_url=trimmed_asset.storage_uri)`
- 并发锁 `:79` `timeout_sec=150` → `timeout_sec=2700`（覆盖 3 次重试上限）
- 改动量：约 +5 行

**⑤ `backend/app/services/timeline_composer_service.py`**
- `:92` `timeout_sec=150` → `timeout_sec=600`（下载 30+ clip + ffmpeg concat 预留 10 分钟）
- 改动量：约 +1 行

**⑥ `prompts/system/audio_analysis.md`**
- 在 `## 关键要求` 章节补充：分析必须覆盖音频**完整时长**，不得只分析前段，`music_structure_summary.sections` 的 `end` 时间必须接近音频总时长
- 改动量：约 +8 行

**预计总改动量**：55~75 行

**验收标准**：
- 8 分钟音频分析完成，Omni 通过 URL 读取音频（本地 dev 环境自动降级 base64），librosa 节拍分析仍基于本地下载文件正常运行，`section_map` 覆盖全部段落
- `config/providers/omni.yaml` timeout=900，max_tokens=32768
- `workflow.yaml` job_timeout_seconds=3000

---

## 四、改动文件速查表

| 文件 | 批次 | 改动性质 | 行数预估 |
|------|------|---------|---------|
| `backend/app/services/project_spec_service.py` | 16-01 | 新增 audio_end_sec 自动检测 | +35 |
| `backend/app/api/v1/project_spec.py` | 16-01 | 注释更新 | +3 |
| `backend/app/services/shot_plan_persistence_service.py` | 16-01 / 16-02 | :317 清理兜底 / :360 改 max_shots 公式 | +5 / +5 |
| `backend/app/services/brief_persistence_service.py` | 16-01 | 清理 30s 双重兜底 | +8 |
| `backend/app/agents/creative_planning_agent.py` | 16-02 | 移除默认值 + 动态 max_tokens + recursion_limit | +20 |
| `backend/app/services/storyboard_service.py` | 16-02 | 并发锁 150→1800 | +1 |
| `backend/app/services/clip_service.py` | 16-02 | 并发锁动态计算 | +10 |
| `config/base/llm.yaml` | 16-02 | 新增 max_tokens_shot_plan | +5 |
| `config/providers/omni.yaml` | 16-03 | timeout/max_tokens 调大 | +4 |
| `config/base/workflow.yaml` | 16-03 | job_timeout_seconds 调大 | +2 |
| `backend/app/agents/audio_analysis_agent.py` | 16-03 | URL 传输 + max_tokens 接入 + 降级兜底补全 | +30 |
| `backend/app/services/audio_analysis_service.py` | 16-03 | Omni 行改 URL（保留 tempfile 下载供 librosa）+ 并发锁 150→2700 | +5 |
| `backend/app/services/timeline_composer_service.py` | 16-03 | 并发锁 150→600 | +1 |
| `prompts/system/audio_analysis.md` | 16-03 | 全量分析要求 | +8 |

---

## 五、执行顺序与依赖

```
16-01（打通入口，L1/L2/L3/L4 兜底清理）
    ↓ 验收通过后
16-02（扩容镜头 + 并发锁，L2/L4/L5/L8）
    ↓ 验收通过后
16-03（稳定长音频，L6/L7/L8/L9）
```

---

## 六、范围之外（本次不做）

1. **前端时长 UI**：frontend 目录为空，后端已自动处理，前端建设时无需适配
2. **Grok Video 3 时长约束**：10/15 秒是提供商硬约束，不改动
3. **数据库迁移**：无需新增字段或表
4. **Kling 适配器**：`kling_adapter.py` 暂不清理
5. **计费模型**：`cost_estimation_service.py` 已按秒计费，天然支持

---

## 七、主要风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| MinIO URL 不可公网访问 | Omni 无法读取音频 | 执行前确认 bucket 公开读；agent 降级条件已覆盖 localhost/内网 IP，dev 环境自动回退 base64 |
| LLM 40+ 镜头 JSON 结构错乱 | 镜头计划不完整 | 已有兜底机制；16-02 动态扩 max_tokens |
| 30+ shots clip 生成耗时 2~5 小时 | 用户等待时间长 | per-clip SSE 实时通知；成本门控已存在 |
| audio_end_sec 精度误差（±1s） | 轻微 MV 时长偏差 | 对 MV 生成无影响 |

---

*定稿：Warp AI (Oz)，2026-04-04，基于全链路代码调查*
