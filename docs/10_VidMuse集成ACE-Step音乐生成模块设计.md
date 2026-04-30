# VidMuse 集成 ACE-Step 1.5 音乐生成模块设计

> 文档目标：在完成当前 01-09 号文档定义的核心系统之后，将 ACE-Step 1.5 作为音乐生成与增强分析扩展模块接入 VidMuse，形成"音乐生成 → 音频分析 → MV 生成"的完整闭环。
>
> 本文档定位为**扩展阶段设计文档**，不影响当前开发主线，待第 3 组 API 层开发完成后可并行推进。
>
> 文档时间：2026-03-29

---

## 1. ACE-Step 1.5 背景与来源

### 1.1 是谁做的

**ACE-Step 1.5** 由 **ACE Studio**（中国 AI 音乐公司）和 **StepFun**（阶跃星辰）联合出品，于 **2026 年 1 月 28 日**开源发布。

- GitHub：`https://github.com/ace-step/ACE-Step-1.5`
- 论文：arXiv:2602.00744（2026-01-31）
- 许可证：**MIT**（可商用，可修改，可分发）
- Stars：8,304（截至 2026-03-29，仍在快速增长）

它的目标是做**音乐生成领域的 Stable Diffusion 时刻**：把商业级音乐生成能力带到本地消费级显卡上。

### 1.2 核心架构：Hybrid LM + DiT

这个模型不是单一端到端的黑箱，而是两个模块分工协作：

```text
用户输入（tags + lyrics）
       ↓
  LM Planner（语言模型，0.6B / 1.7B / 4B 三档）
  ├── 基于 Qwen3 微调
  ├── Chain-of-Thought 生成 song blueprint（BPM、Key、结构、副歌位置等）
  ├── 格式化歌词、扩写 query
  └── 输出标准化条件给 DiT
       ↓
  DiT（Diffusion Transformer，~2B 参数）
  ├── 专注声学渲染，不处理语义
  ├── Adversarial 蒸馏：推理步骤从 50 步压缩到 4-8 步
  └── 输出高保真音频
       ↓
  高质量完整歌曲（最长 10 分钟，48kHz 立体声）
```

这个分离设计和 VidMuse 的 Agent Harness 理念完全吻合：

> **LM = Composer Agent（规划）**  
> **DiT = 声学渲染工具（执行）**

职责边界清晰，可独立升级，可独立替换。

### 1.3 训练数据与质量

模型在 2700 万音频样本上训练，采用分阶段课程学习：

- 使用 Gemini 2.5 Pro 标注了 500 万 "黄金样本"，再用 RL 精炼专有标注模型
- 对非罗马字母语言（中文、日文、泰文等）做了专门的音素预处理
- 支持 2000+ 音乐风格 / 50+ 语言歌词

训练数据来源：**授权音乐 + 免版权音乐 + 合成音频**，官方声明可商业使用生成结果。

### 1.4 基准性能

| 模型 | 音乐质量（SongEval 综合） | 推理速度（生成4分钟歌） |
|---|---|---|
| Suno v4.5 | 4.55 | 云端数分钟 |
| Suno v5 | 4.63（最强商业） | 云端数分钟 |
| **ACE-Step 1.5** | **4.67（超过Suno v4.5，接近v5）** | **A100 约 2 秒** |
| Udio v1.5 | 4.01 | 云端数分钟 |

---

## 2. ACE-Step 1.5 完整能力矩阵

### 2.1 无需训练的原生能力（Generation Mode）

| 能力 | 说明 | 需要哪个模型 |
|---|---|---|
| **text2music** | 文字描述 + 可选歌词 → 完整歌曲 | turbo/sft/base |
| **cover** | 上传参考音频 → 同结构不同风格重演 | turbo/sft/base |
| **repaint** | 指定 3-90 秒区间做局部修改 | turbo/sft/base |
| **vocal2bgm** | 上传人声清唱 → 自动生成伴奏 | turbo/sft/base |
| **lego** | 向已有音频叠加新轨道（加吉他/鼓/和声等） | base 专属 |
| **extract** | 分离音频为人声 + 各乐器 stem 轨道 | base 专属 |
| **complete** | 对未完成的音乐段落做续写 | base 专属 |
| **Reference Audio Input** | 上传参考音频引导生成风格（零样本） | turbo/sft/base |

### 2.2 无需训练的分析能力（Understanding Mode）

| 能力 | 说明 | 对应 VidMuse 现有需求 |
|---|---|---|
| **BPM 提取** | 精确曲速检测 | doc01 §10.1 |
| **Key/Scale 提取** | 调式识别 | 新增 |
| **Time Signature 提取** | 拍号识别 | 新增 |
| **Section 识别** | intro/verse/chorus/bridge/outro 分段（含时间戳） | doc01 §10.1 |
| **情绪/风格 Caption** | 自然语言描述歌曲情绪、风格、乐器 | doc01 §10.1 |
| **LRC 生成** | 为生成的音乐自动对齐歌词时间戳 | doc01 §10.1 |

### 2.3 需要训练的定制能力（ACE-Step LoRA Fine-tuning，后续阶段）

| LoRA 类型 | 训练数据 | 学到什么 |
|---|---|---|
| Style LoRA | 完整歌曲 8-20 首 + 歌词 + BPM | 编曲风格 + 乐器组合 + 声场特点 |
| Vocal LoRA | 清晰人声录音 7-20 段 | 声色倾向、音域、演唱方式 |
| Instrumental LoRA | 纯器乐轨道 20-50 首 | 特定乐器演奏风格（如全吉他编曲） |
| LoRA 合并 | 已有 LoRA | 按权重组合多个私有 LoRA |

> 注：LoRA 训练需要 16GB VRAM（最低），训练时间约 1-2 小时（8-20 首歌），为后续扩展阶段内容，不在当前主线开发中。

### 2.4 歌声转换（Singing Voice Conversion）

这是一项独立于音乐生成之外的能力——**把已有的歌声音频转换成用户自己的声音**。

#### 技术选型：Seed-VC（零样本歌声转换）

**GitHub**：`https://github.com/Plachtaa/seed-vc`（南洋理工大学，4K stars，已归档稳定版）  
**论文**：arXiv:2411.09943  
**License**：GPL-3.0（SaaS 部署无分发行为，不影响商业使用）

**核心原则：不需要训练，只需提供 1-30 秒参考音频**

```bash
# 完整歌声转换命令
python inference.py \
  --source  ACE-Step分离的人声干声.wav \
  --target  用户上传的20秒录音.wav \
  --output  ./output/ \
  --f0-condition True \        # 歌声模式：保持音调轮廓
  --diffusion-steps 30          # 质量档：30步（快速用10步）
```

**歌声转换 vs 传统 RVC 的性能对比**（M4Singer 数据集，客观测试）：

| 指标 | 含义 | RVCv2（专门训练） | Seed-VC（零样本） |
|---|---|---|---|
| SECS↑ | 声音与目标的相似度 | 0.7264 | **0.7405** |
| CER↓ | 歌词识别准确率 | 28.46% | **19.70%** |
| F0CORR↑ | 音调保持准确性 | 0.9404 | 0.9375（相当） |
| 音质 DNSMOS | 音频自然度 | 略高 | 略低 |  

**零样本相似度超过了专门训练的 RVCv2**。唯一 RVC 略好的是音质自然度，差距可感知但不大。

#### 注意：讯飞相关 API 不适用于此场景

讯飞开放平台有两个看似相关的 API，但**均不支持歌声转换**：

- **一句话复刻（声音克隆）**：生成的 voice_id 只用于 TTS（文字→语音），无法把已有歌声音频转换成用户声音
- **音色转换**：只支持固定内置音色（虫虫/小丸子等预设），不接受用户自定义音色

正确路径：使用 **Seed-VC** 本地推理，完全离线，无需调用任何云 API。

---

## 3. 与 VidMuse 现有架构的对接分析

### 3.1 对现有项目入口的影响（doc01 §22）

原文档定义了两种主创作入口：
- 入口 A：`音频 + 文字`
- 入口 B：`音频 + 图片 + 文字`

接入 ACE-Step 后，新增两种前置入口：
- 入口 C（新）：`文字 + 歌词 → 生成音乐 → 进入主流程`
- 入口 D（新）：`上传清唱 → 生成伴奏 → 进入主流程`

这两种新入口的**输出都要归一化为现有的 ProjectSpec 结构**（doc01 §29），和上传音频的路径最终合并，不影响下游流程。

### 3.2 对 Audio Analysis Agent 的影响（doc02 §7.2）

原音乐分析 Agent 职责：BPM / beat / section / 歌词对齐 / 情绪曲线 / 高潮点标注

接入 ACE-Step 后，分析层变成**双路并行**，在 Audio Analysis Agent 内部整合：

```text
音频输入
  ├── ACE-Step Audio Understanding
  │     → BPM、Key、section_map、情绪 caption、LRC 歌词时间戳
  │
  └── librosa（保留，不可替代）
        → beat_map（精确逐 beat 毫秒时间戳）
        → energy_curve（连续能量信号）
        → 人声进入点（onset detection）

合并输出 → audio_analysis_versions 表
```

这样分析结果比原方案**更完整、更准确**，且 ACE-Step 段落识别基于语义理解，比纯信号处理更接近人类感知。

### 3.3 对工具层的影响（doc06 §26.1）

原音频工具清单：提取节拍 / 提取段落 / 歌词时间对齐 / 音频切段

新增工具（统一注册为 ACE-Step Provider 的子工具）：
- `tool_music_generate`（text2music）
- `tool_music_vocal2bgm`（上传清唱→伴奏）
- `tool_music_cover`（风格翻唱）
- `tool_music_repaint`（局部修改）
- `tool_music_extract_stems`（分离 stems，替代 Demucs）
- `tool_music_lego`（叠加轨道）
- `tool_music_understand`（BPM + key + section + caption）
- `tool_music_lrc`（生成歌词时间轴）

新增工具（Seed-VC Provider）：
- `tool_voice_convert`（零样本歌声转换，将任意人声替换为用户声音）

### 3.4 对 Provider 配置的影响（doc08 §6.2）

`config/providers/audio_providers.yaml` 原来只有 `librosa_local` 和 `whisperx_local`。

需要新增 `music_providers.yaml`：

```yaml
ace_step:
  name: ace-step-1.5
  type: local_service
  base_url: "http://localhost:8001"
  model_dit: "acestep-v15-turbo"
  model_lm: "acestep-5Hz-lm-1.7B"
  capabilities:
    - text2music
    - cover
    - repaint
    - vocal2bgm
    - extract
    - lego
    - complete
    - audio_understanding
    - lrc_generation
  max_duration_sec: 600
  min_duration_sec: 10
  supported_languages: 50
  vram_required_gb: 12
  generation_speed_rtf: 12  # 3090基准，3070Ti约8
  pricing:
    text2music_per_min: 15       # credits/分钟
    cover_per_min: 12
    vocal2bgm_per_min: 18
    extract_per_track: 8
    audio_understanding: 3

suno_api:
  name: suno-v5
  type: cloud_api
  base_url: "https://api.suno.ai"
  capabilities:
    - text2music
  pricing:
    text2music_per_min: 25
  fallback_for: ace_step
```

新增 `voice_providers.yaml`（歌声转换专用）：

```yaml
seed_vc:
  name: seed-vc
  type: local_process        # 直接调用 Python 进程，非 REST 服务
  repo: "https://github.com/Plachtaa/seed-vc"
  model: "seed-uvit-whisper-base"   # 44100Hz 歌声转换专用模型，200M 参数
  license: "GPL-3.0"               # SaaS 后端部署无需开源
  vram_required_gb: 4               # 推理最低 4GB，16GB 绰绰有余
  capabilities:
    - singing_voice_conversion      # 零样本歌声转换
  reference_audio_min_sec: 1
  reference_audio_max_sec: 30
  diffusion_steps_default: 30      # 质量优先；快速模式用 10
  pricing:
    voice_convert_per_min: 10       # credits/分钟（本地推理，成本低）
```

---

## 4. 数据设计补充

### 4.1 新增 asset_type

在 `doc03 §7.3` 的 `assets` 表 `asset_type` 字段中，新增：

```text
audio_generated        → ACE-Step 生成的完整音频
audio_vocal_upload     → 用户上传的清唱人声
audio_voice_ref        → 用户上传的声音参考（用于 Seed-VC 声音转换）
audio_stem_vocal       → 分离后的人声 stem
audio_stem_instrumental → 分离后的伴奏 stem
audio_stem_drums       → 分离后的鼓轨 stem
audio_stem_bass        → 分离后的贝斯 stem
audio_voice_converted  → Seed-VC 转换后的人声干声
audio_lrc              → 歌词时间轴文件（LRC格式）
```

### 4.2 新增表：`music_generation_versions`

记录 ACE-Step 生成的音乐产物（版本化）：

```sql
CREATE TABLE music_generation_versions (
    id              VARCHAR(26)  PRIMARY KEY,
    project_id      VARCHAR(26)  NOT NULL REFERENCES projects(id),
    version_no      INTEGER      NOT NULL,

    -- 生成模式
    generation_mode VARCHAR(32)  NOT NULL,  -- text2music|cover|vocal2bgm|repaint
    provider        VARCHAR(32)  NOT NULL,  -- ace_step|suno_api

    -- 输入参数快照
    input_tags      TEXT,                   -- 风格描述 tags
    input_lyrics    TEXT,                   -- 结构化歌词
    input_audio_asset_id VARCHAR(26),       -- 参考音频（cover/vocal2bgm用）
    duration_sec    NUMERIC(8,2),
    bpm_target      INTEGER,
    key_target      VARCHAR(16),
    lora_ids        JSONB,                  -- 使用的 LoRA 列表（未来扩展）

    -- 生成结果
    audio_asset_id  VARCHAR(26),            -- 生成的音频 asset
    lrc_asset_id    VARCHAR(26),            -- 对应 LRC 文件
    quality_score   NUMERIC(4,2),           -- 自动质量评分（0-10）
    provider_meta   JSONB,                  -- provider 返回的原始元数据

    -- 状态
    status          VARCHAR(32)  NOT NULL,  -- pending|generating|succeeded|failed
    is_active       BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_music_gen_project ON music_generation_versions(project_id, is_active);
CREATE INDEX idx_music_gen_status  ON music_generation_versions(status);
```

### 4.3 新增表：`stem_tracks`

记录 stem 分离的结果：

```sql
CREATE TABLE stem_tracks (
    id                        VARCHAR(26) PRIMARY KEY,
    project_id                VARCHAR(26) NOT NULL REFERENCES projects(id),
    source_audio_asset_id     VARCHAR(26) NOT NULL,  -- 源音频
    stem_type                 VARCHAR(32) NOT NULL,  -- vocal|instrumental|drums|bass|other
    audio_asset_id            VARCHAR(26) NOT NULL,  -- 分离后的 stem 文件
    provider                  VARCHAR(32) NOT NULL,  -- ace_step|demucs
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4.4 `audio_analysis_versions` 表补充字段

在 `doc03 §7.4` 已有字段基础上，新增：

```sql
ALTER TABLE audio_analysis_versions ADD COLUMN IF NOT EXISTS
    key_scale           VARCHAR(16),    -- 如 "D major"
    time_signature      VARCHAR(8),     -- 如 "4/4"
    style_caption       TEXT,           -- ACE-Step 生成的风格描述
    lrc_asset_id        VARCHAR(26),    -- 对应 LRC 文件的 asset id
    analysis_provider   JSONB;          -- {"beat":{"provider":"librosa"},"section":{"provider":"ace_step"},...}
```

`analysis_provider` 字段记录每个分析子项实际使用的 provider，便于追溯和 debug。

### 4.5 `projects` 表补充字段

```sql
ALTER TABLE projects ADD COLUMN IF NOT EXISTS
    audio_source_mode   VARCHAR(32) DEFAULT 'upload';
    -- 取值：upload（上传）| generated（AI生成）| vocal2bgm（清唱转伴奏）
```

---

## 5. 状态机扩展（doc04 补充）

### 5.1 新增项目阶段（音乐生成路径）

在原 `input_ready → audio_analyzed` 转换之前，新增可选的音乐生成阶段：

```text
created
  → music_generating  ← 新增（仅当 audio_source_mode = generated/vocal2bgm 时）
  → music_ready       ← 新增（生成完成，等待用户确认）
  → input_ready       ← 确认后进入原主流程
```

`music_generating` 状态：

- 允许：取消生成、修改参数后重新生成、在线试听
- 禁止：音频分析、生成 brief、生成 shot plan

`music_ready` 状态：

- 允许：接受（→ input_ready）、重新生成、调整参数后再生成、在线试听、微调重绘（repaint）
- 禁止：音频分析（必须先接受）

### 5.2 音乐生成任务状态机

复用 `doc04 §20.2` 的任务状态机，但新增：

```text
pending → generating → previewing → user_approved → succeeded
                   ↘ user_rejected → pending（重新生成）
                   ↘ failed → retrying → generating
```

`previewing` 状态：任务已完成，音频已生成，用户正在试听，尚未确认。

---

## 6. API 设计补充（doc05 扩展）

### 6.1 音乐生成控制面 API

```text
# 音乐生成（异步，立即返回 job_id）
POST /api/v1/projects/{project_id}/music/generate
Body: {
  "mode": "text2music|cover|vocal2bgm|repaint",
  "tags": "cinematic, rainy night, lo-fi, emotional",
  "lyrics": "[Verse]\n...\n[Chorus]\n...",
  "duration_sec": 120,
  "bpm": 95,
  "key": "D minor",
  "reference_audio_asset_id": null,    # cover/vocal2bgm 时必填
  "repaint_start_sec": null,           # repaint 时必填
  "repaint_end_sec": null,
  "provider": "ace_step",
  "lora_ids": []
}
Response: { "job_id": "...", "estimated_seconds": 20 }

# 获取生成状态（轮询或 SSE）
GET /api/v1/projects/{project_id}/music/jobs/{job_id}

# 接受生成结果（→ input_ready 状态）
POST /api/v1/projects/{project_id}/music/versions/{version_id}/accept

# 拒绝并重新生成
POST /api/v1/projects/{project_id}/music/versions/{version_id}/reject

# 获取预签名播放地址（在线试听）
GET /api/v1/projects/{project_id}/music/versions/{version_id}/play_url

# stem 分离
POST /api/v1/projects/{project_id}/music/extract_stems
Body: { "audio_asset_id": "...", "stems": ["vocal", "instrumental"] }

# 上传清唱
POST /api/v1/projects/{project_id}/music/upload_vocal
Content-Type: multipart/form-data
Body: { "file": <audio_file> }
Response: { "asset_id": "..." }

# 音频分析（增强版，双路）
POST /api/v1/projects/{project_id}/audio/analyze
Body: {
  "audio_asset_id": "...",
  "providers": {
    "structural": "ace_step",
    "beat": "librosa"
  }
}
```

### 6.2 声音转换 API

```text
# 上传声音参考（用于 Seed-VC）
POST /api/v1/projects/{project_id}/voice/upload_reference
Content-Type: multipart/form-data
Body: { "file": <audio_file>  }   # 1-30秒，清晰录音
Response: { "asset_id": "...", "duration_sec": 18.5 }

# 声音转换（异步）
POST /api/v1/projects/{project_id}/voice/convert
Body: {
  "source_vocal_asset_id": "...",    # ACE-Step 分离出的人声干声
  "reference_asset_id": "...",       # 用户的声音参考
  "diffusion_steps": 30,             # 30=质量优先，10=速度优先
  "semitone_shift": 0                # 音调偏移（男→女 +12，女→男 -12）
}
Response: { "job_id": "...", "estimated_seconds": 30 }

# 获取转换结果
GET /api/v1/projects/{project_id}/voice/jobs/{job_id}
```

### 6.3 SSE 事件扩展（doc05 Project SSE）

在原项目事件流中新增事件类型：

```json
{ "event": "music.generating.progress", "data": { "job_id": "...", "progress_pct": 45 } }
{ "event": "music.ready",               "data": { "job_id": "...", "version_id": "...", "duration_sec": 118 } }
{ "event": "music.failed",              "data": { "job_id": "...", "error_code": "provider_timeout", "retryable": true } }
{ "event": "stems.ready",               "data": { "stems": { "vocal": "asset_id_1", "instrumental": "asset_id_2" } } }
{ "event": "audio.analyzed",            "data": { "version_id": "...", "bpm": 95, "key": "D minor" } }
{ "event": "voice.convert.ready",       "data": { "job_id": "...", "asset_id": "..." } }
{ "event": "voice.convert.failed",      "data": { "job_id": "...", "error": "..." } }
```

---

## 7. 工具层实现设计

### 7.1 ACE-Step 作为 Provider 的接入方式

ACE-Step 提供原生 REST API Server（`uv run acestep-api`，默认端口 8001）。

后端通过统一的 `ProviderAdapter` 封装调用（和现有图片/视频 provider 一致），不在业务代码中直接调用 HTTP。

```python
# backend/app/providers/music/ace_step_adapter.py

class ACEStepAdapter:
    """
    ACE-Step 1.5 Provider 适配器
    文档：https://github.com/ace-step/ACE-Step-1.5
    """

    async def generate_music(self, params: MusicGenerationParams) -> MusicGenerationResult:
        """
        调用 /generate 接口，支持 text2music / cover / vocal2bgm / repaint
        异步提交任务，轮询直到完成
        """
        ...

    async def extract_stems(self, audio_path: str, stems: list[str]) -> dict[str, str]:
        """
        调用 /extract 接口，分离 stem 轨道
        替代 Demucs
        """
        ...

    async def audio_understanding(self, audio_path: str) -> AudioAnalysisResult:
        """
        调用 /audio_understanding 接口
        返回 BPM + Key + section_map + caption
        """
        ...

    async def generate_lrc(self, audio_path: str, lyrics: str) -> str:
        """
        调用 /lrc_generation 接口
        返回标准 LRC 格式字符串
        替代 WhisperX（对 ACE-Step 生成的音乐更准）
        """
        ...
```

### 7.2 音频分析双路融合

```python
# backend/app/services/audio_analysis_service.py

async def analyze_audio_enhanced(audio_asset_id: str) -> AudioAnalysisVersion:
    """
    双路融合分析：
    - ACE-Step：BPM, Key, section_map, style_caption, lrc（音乐语义理解）
    - librosa：beat_map, energy_curve, onset_times（信号级精度）
    """
    # 并行执行两路分析
    ace_result, librosa_result = await asyncio.gather(
        ace_step_adapter.audio_understanding(audio_path),
        librosa_tool.analyze(audio_path)
    )

    return AudioAnalysisVersion(
        bpm=ace_result.bpm,                    # ACE-Step 更准
        beat_map=librosa_result.beat_map,       # librosa 精确到毫秒
        section_map=ace_result.section_map,     # ACE-Step 语义更好
        energy_curve=librosa_result.energy_curve,
        key_scale=ace_result.key_scale,
        style_caption=ace_result.caption,
        lyrics_alignment=ace_result.lrc_data,
        analysis_provider={
            "bpm": "ace_step",
            "beat_map": "librosa",
            "section_map": "ace_step",
            "energy_curve": "librosa"
        }
    )
```

### 7.3 重试与容错设计

```python
# 音乐生成任务的重试策略（与 doc03 §16 幂等设计一致）

MUSIC_GENERATION_RETRY_POLICY = {
    "max_retries": 2,
    "backoff_seconds": [10, 30],
    "retryable_errors": [
        "provider_timeout",
        "oom_error",
        "connection_refused"
    ],
    "non_retryable_errors": [
        "invalid_lyrics",
        "unsupported_duration",
        "credit_insufficient"
    ],
    "fallback_provider": "suno_api"  # 本地跑不了时 fallback 到云端
}
```

**幂等性保证**（复用 doc03 §16.1 的幂等键设计）：

```python
idempotency_key = hash(
    "music_generate" +
    tags + lyrics + str(duration) + str(bpm) +
    reference_audio_hash +  # 如果有参考音频
    provider
)
```

重复提交相同参数的生成请求时，直接返回已有 job 结果，不重复消耗 credits。

### 7.4 在线试听设计

生成完成后，音频文件存入 MinIO（对象路径：`music/{project_id}/generated/{version_id}/full.mp3`）。

前端通过**预签名 URL**（有效期 1 小时）直接从 MinIO 拉流播放，不经过后端 API，减少带宽压力：

```text
GET /api/v1/projects/{project_id}/music/versions/{version_id}/play_url
Response: {
  "url": "https://minio.host/vidmuse/music/.../full.mp3?X-Amz-Signature=...",
  "expires_at": "2026-03-29T21:00:00Z"
}
```

前端使用 HTML5 `<audio>` 或 WaveSurfer.js 播放，支持：
- 波形可视化（WaveSurfer.js，和现有音频分析页复用）
- 拖动时间轴任意位置播放
- 显示 section 标记（intro/verse/chorus 等）
- 对比多个版本（左右滑动切换 v1/v2/v3）

---

## 8. Agent 集成设计

### 8.1 导演 Agent 需要理解的新意图

在 `doc06 §15` Director Agent 协议基础上，新增以下 `intent`：

```json
{ "intent": "generate_music",   "mode": "text2music|cover|vocal2bgm" }
{ "intent": "repaint_music",    "target_range": {"start_sec": 30, "end_sec": 60} }
{ "intent": "extract_stems",    "stems": ["vocal", "instrumental"] }
{ "intent": "accept_music",     "version_id": "..." }
{ "intent": "reject_music",     "reason": "节奏太慢" }
{ "intent": "preview_music",    "version_id": "..." }
{ "intent": "add_layer",        "layer_type": "guitar|drums|pad" }
```

### 8.2 Audio Analysis Agent 的变化

原职责（doc02 §7.2）在工具层实现上发生变化，但 Agent 本身的职责定义不变——它依然负责：
- 解释分析结果
- 生成音乐结构摘要
- 为创意规划层提供结构化节奏语义

内部实现从"调用 librosa Tool"变为"调用双路分析 Service"，Agent 层感知不到差异。

### 8.3 新增 Music Generation Agent（轻量级）

不建议做成复杂 Agent，而是做成**轻量规划层 + Tool**的组合：

```text
Music Generation 规划：
  - 解析用户意图（想要什么风格的歌）
  - 从 brief / style bible 提取关键信息
  - 编译成 ACE-Step 的 tags + lyrics 参数
  - 估算生成时长和成本
  - 向导演 Agent 返回结构化生成计划

Music Generation Tool：
  - 接收生成计划
  - 调用 ACE-Step Adapter
  - 管理任务轮询
  - 写入数据库
  - 推送 SSE 事件
```

---

## 9. 前端集成设计（doc07 扩展）

### 9.1 项目创建流程新增入口

在原来"上传音频"的选项之前，新增：

```text
┌─────────────────────────────────────────────────────────┐
│  开始创作                                               │
│                                                         │
│  ◉ 上传已有音乐                     （原有入口）         │
│  ○ AI 生成音乐                      （新增入口 C）       │
│     → 输入风格描述 + 歌词 → 生成    │
│  ○ 上传我的清唱                     （新增入口 D）       │
│     → 上传人声 → 自动生成伴奏       │
└─────────────────────────────────────────────────────────┘
```

### 9.2 Pipeline 左侧新增节点（doc07 §5.1）

原流程节点：`输入 → 音频分析 → 创意方案 → ...`

新流程（音乐生成路径）：

```text
输入
  → 音乐生成（新增，仅 AI 生成路径显示）
    ├── 配置参数（风格、时长、BPM、歌词）
    ├── 生成中（进度条）
    └── 在线试听 / 接受 / 重新生成
  → 音频分析
  → 创意方案
  → ...（后续不变）
```

### 9.3 音乐生成阶段的工作区视图（doc07 §6 扩展）

工作区显示：
- 左上：生成参数面板（风格 tags / 歌词 / BPM / Key / 时长）
- 右上：版本列表（v1 / v2 / v3，可切换对比）
- 中间：WaveSurfer 波形 + Section 标注（实时更新）
- 底部：试听控制栏（播放/暂停/进度/音量）

操作：
- "重新生成"：修改参数后再生成新版本
- "接受此版本"：进入音频分析阶段
- "局部重绘"：选中波形区间 → 仅重新生成该段
- "叠加轨道"：选择要叠加的乐器类型 → Lego 模式

### 9.4 试听功能的状态联动

试听时：
- 右侧 Chat 保持可用，用户可以边听边说"副歌更炸一点"
- 导演 Agent 接收意图后，生成 repaint 计划
- 显示 "预计消耗 8 credits，是否确认" 确认卡
- 确认后只重绘副歌段，而非整首重生成

---

## 10. 用户侧完整玩法说明

### 玩法 A：纯 AI 创作（text2music → MV）

```text
用户描述：
"做一首雨夜、低饱和、情绪压抑但副歌爆发的中文歌，
 90 秒，BPM 约 85，想要吉他 + 钢琴的编曲"

系统生成：
1. 导演 Agent 分析意图 → 生成 ACE-Step 参数
2. ACE-Step 生成音乐（约 20 秒）
3. 用户在线试听
4. 满意 → 接受 → 进入 beat/section 分析 → 生成 shot plan → MV
```

### 玩法 B：清唱转完整歌（vocal2bgm → MV）

```text
用户上传：一段自己哼唱的 90 秒无伴奏旋律

系统处理：
1. 上传清唱 → 存为 audio_vocal_upload 资产
2. ACE-Step Vocal2BGM → 生成匹配伴奏
3. 混合人声 + 伴奏（ffmpeg）
4. 用户试听 → 微调 → 接受 → 进入 MV 流程
```

### 玩法 C：风格翻唱（cover → MV）

```text
用户上传：一首已有歌曲（可以是用户自己的作品）

用户指令：
"用这首歌的旋律结构，换成赛博朋克合成器风格"

系统处理：
1. Cover 模式，保留结构，换编曲风格
2. 生成结果对比原曲（并排波形）
3. 接受 → MV 流程
```

### 玩法 D：精细化编辑（repaint + lego）

```text
场景：用户已有一首生成的歌，想进一步调整

操作：
- 选中副歌 40-60 秒 → 局部重绘 → 把副歌做得更炸
- 向伴奏叠加一条吉他独奏（Lego 模式）
- 分离人声 + 伴奏 → 单独下载 stem

这些操作完成后，更新 audio_asset_id → 触发重新分析 → 更新 shot plan
```

### 玩法 E：增强分析（仅分析，不生成）

```text
用户上传已有音乐
→ 触发双路增强分析
→ section_map + beat_map + style_caption + LRC 全部生成
→ 分析结果比原来（librosa-only）更丰富
→ 进入 MV 流程，shot plan 的镜头情绪/节奏规划更准确
```

### 玩法 F：专属声音 MV（Seed-VC 歌声转换）

这是整个方案最具差异化的玩法，完整链路：

```text
第一步：建立声音档案（一次性，长期复用）
  用户上传 20-30 秒清晰录音（说话或哼唱均可）
  → 存为 audio_voice_ref 资产
  → 与用户账号绑定，后续使用无需再上传

第二步：生成基础音乐（任意方式）
  可以是玩法 A（text2music）、玩法 B（vocal2bgm）
  或玩法 C（cover），或直接上传已有歌曲

第三步：ACE-Step Stem 分离
  → 分离出纯人声干声（audio_stem_vocal）
  → 伴奏单独保存（audio_stem_instrumental）

第四步：Seed-VC 歌声转换（核心步骤）
  输入：
    source = 第三步的人声干声
    target = 第一步的用户声音参考
  输出：换成用户声音的人声（约 30 秒处理时间/每分钟）
  参数：
    --f0-condition True        # 保持旋律音调不变
    --diffusion-steps 30       # 质量模式

第五步：ffmpeg 混音
  → 转换后的人声 + 原伴奏 → 合并为完整歌曲
  → 存入 audio_generated 资产

第六步：进入 VidMuse 主流程
  → 双路音频分析 → shot plan → MV 生成 → 导出
```

**用户感知**：「用我的声音唱了一首完整 MV」  
**技术事实**：零训练，30 秒参考录音，全本地处理，无需云端

---

## 11. 实施优先级与集成顺序

这份设计文档定位为**主线开发完成后的扩展阶段**，建议按以下顺序实施：

### 扩展阶段 1：增强分析（最低风险，最高收益）

**前提**：完成 doc09 第 5 组（分析与规划闭环）之后

实现内容：
- 部署 ACE-Step API Server（本地）
- 实现 `ACEStepAdapter.audio_understanding()`
- 实现双路分析融合（ace_step + librosa 并行）
- 补充 `audio_analysis_versions` 表字段（key_scale / style_caption / lrc_asset_id）
- 前端展示增强分析结果（Section 标注 + 情绪 caption）

**效果**：现有上传音乐 → MV 流程的分析质量显著提升，用户无感知变化。

### 扩展阶段 2：音乐生成入口（新增核心功能）

**前提**：完成扩展阶段 1 + 完成 doc09 第 6 组（前端工作台骨架）之后

实现内容：
- `music_generation_versions` 表
- `tool_music_generate` Tool 实现（text2music）
- `tool_music_vocal2bgm` Tool 实现
- 项目创建流程新增入口 C/D
- Pipeline 新增"音乐生成"节点
- 在线试听功能（预签名 URL + WaveSurfer）
- 音乐生成相关 SSE 事件

### 扩展阶段 3：高级编辑与定制（深度功能）

**前提**：扩展阶段 2 稳定之后

实现内容：
- Repaint（局部重绘）
- Lego（叠加轨道）
- Cover（风格翻唱）
- Stem 分离前端交互
- Suno API fallback（本地不可用时）

### 扩展阶段 4：LoRA 定制模型（用户私有 AI）

**前提**：扩展阶段 3 稳定之后

实现内容（详细设计需另立文档）：
- LoRA 训练任务管理
- 私有 LoRA 存储与版本管理
- 生成时 LoRA 选择界面
- LoRA 合并（多风格融合）

### 扩展阶段 5：Seed-VC 歌声转换（专属声音 MV）

**前提**：扩展阶段 2 稳定之后（并行推进，不依赖扩展阶段 3/4）

实现内容：
- 安装 Seed-VC（`git clone` + `pip install -r requirements.txt`）
- 实现 `SeedVCAdapter`（封装 Python 进程调用）
- `audio_voice_ref` 资产上传与存储
- `tool_voice_convert` Tool 实现
- `/voice/upload_reference` 和 `/voice/convert` API
- 前端：创建页面新增「使用我的声音」入口
- 前端：声音档案管理界面（上传/试听/删除）
- 玩法 F 的完整前端交互流程
- VRAM 调度（Seed-VC 推理与 ACE-Step 串行执行）

---

## 12. Credits 计费扩展

### 12.1 音乐生成计费原则

音乐生成属于**重付费层**，按"生成时长 × 操作类型"计费：

```text
text2music：15 credits / 分钟
vocal2bgm：18 credits / 分钟（处理更复杂）
cover：12 credits / 分钟
repaint：按修改时长区间计，最低 5 credits
extract（stem 分离）：8 credits / 次
lego（叠加轨道）：10 credits / 次
audio_understanding（增强分析）：3 credits / 次（可免费提供）
voice_convert（歌声转换）：10 credits / 分钟（本地推理，成本低）
```

### 12.2 成本估算时机

和原 credits 设计（doc01 §13.3）一致：

- 用户点击"生成音乐"前，先展示预估 credits
- 确认后才执行并扣费
- 扣费逻辑走 `credit_ledger` 表（doc03 §7.8）

### 12.3 新增 CreditLedger 的 tool_name 值

```text
tool_name: "music_generate_text2music"
tool_name: "music_generate_vocal2bgm"
tool_name: "music_generate_cover"
tool_name: "music_repaint"
tool_name: "music_extract_stems"
tool_name: "music_lego"
tool_name: "music_audio_understanding"
tool_name: "voice_convert_singing"    # Seed-VC 歌声转换
```

---

## 13. 本地部署与运维注意事项

### 13.1 ACE-Step API Server 的启动

```bash
# Windows（开发环境）
git clone https://github.com/ACE-Step/ACE-Step-1.5.git
cd ACE-Step-1.5
uv sync

# 启动 REST API 服务
uv run acestep-api --port 8001 --server-name 127.0.0.1 \
  --config_path acestep-v15-turbo \
  --lm_model_path acestep-5Hz-lm-1.7B \
  --init_service true
```

### 13.2 与 VidMuse 主服务的关系

ACE-Step 作为一个独立的本地服务运行，VidMuse 后端通过 HTTP 调用它：

```text
VidMuse Backend (port 8000)
    └── HTTP → ACE-Step API Server (port 8001) [本地，同机器]
```

这和现有的 MinIO（端口 9000）、Redis（端口 6379）、Postgres 一样，都是本地依赖服务，统一在 `config/base/` 中配置地址。

### 13.3 Seed-VC 本地部署

```bash
# Windows 安装
git clone https://github.com/Plachtaa/seed-vc.git
cd seed-vc
pip install -r requirements.txt

# 首次运行时自动下载模型权重（约 1.2GB）
# 模型：seed-uvit-whisper-base（歌声转换专用，200M参数，44.1kHz）
python inference.py --source test.wav --target ref.wav --output ./out --f0-condition True
```

VidMuse 通过 Python 子进程调用 Seed-VC，而非 REST API（无额外端口）：

```python
# backend/app/providers/voice/seed_vc_adapter.py
import subprocess

class SeedVCAdapter:
    async def convert_singing(
        self,
        source_path: str,      # ACE-Step 分离的人声干声
        reference_path: str,   # 用户声音参考
        output_path: str,
        diffusion_steps: int = 30,
        semitone_shift: int = 0
    ) -> str:
        cmd = [
            "python", "inference.py",
            "--source", source_path,
            "--target", reference_path,
            "--output", output_path,
            "--f0-condition", "True",
            "--diffusion-steps", str(diffusion_steps),
            "--semi-tone-shift", str(semitone_shift),
            "--fp16", "True"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=settings.seed_vc_dir,   # config 中配置 seed-vc 目录
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return output_path
```

### 13.4 VRAM 管理

VidMuse 后端在调用 ACE-Step 前，应确保没有其他 GPU 密集任务并行：

- 视频生成、音乐生成、歌声转换三类任务**全部串行**，不并发
- 通过 Redis 队列的优先级和锁机制保证
- VRAM 占用参考：ACE-Step 推理 ~12GB，Seed-VC 推理 ~4GB，视频生成 ~8-12GB
- 音乐生成完成后 ACE-Step 释放 VRAM，再启动 Seed-VC 或视频生成任务

### 13.4 健康检查

在 `bootstrap/services.py` 的 `ServiceManager.check_all()` 中补充：

```python
async def check_ace_step(self) -> bool:
    """检查 ACE-Step API Server 是否可用"""
    try:
        resp = await http_client.get("http://localhost:8001/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False

async def check_seed_vc(self) -> bool:
    """检查 Seed-VC 目录与依赖是否可用"""
    import os
    seed_vc_dir = settings.seed_vc_dir
    inference_script = os.path.join(seed_vc_dir, "inference.py")
    return os.path.exists(inference_script)
```

---

## 14. 本文档与前序文档的关系总结

| 前序文档 | 受影响的内容 | 修改方式 |
|---|---|---|
| doc01 §10.2 | 音频分析技术栈 | 新增 ACE-Step 为第一路，librosa 保留为第二路 |
| doc02 §7.2 | Audio Analysis Agent 工具层 | 调用方式变为双路融合，Agent 接口不变 |
| doc03 §7.3 | asset_type 枚举 | 新增 7 种音频相关 asset type |
| doc03 §7.4 | audio_analysis_versions 表 | 新增 4 个字段 |
| doc04 | 项目状态机 | 新增 music_generating / music_ready 两个状态 |
| doc05 | API 设计 | 新增 6 个音乐相关 API 端点 + 5 个 SSE 事件 |
| doc06 §26.1 | 音频工具清单 | 新增 8 个 ACE-Step 工具 |
| doc07 §5.1 / §6 | 前端 Pipeline + 工作区 | 新增音乐生成阶段节点和视图 |
| doc08 §6.2 | Provider 配置 | 新增 music_providers.yaml |
| doc09 | 开发执行计划 | 扩展阶段 1-5 作为后续任务组追加 |

---

## 15. 参考资料

- ACE-Step 1.5 GitHub：https://github.com/ace-step/ACE-Step-1.5
- ACE-Step 技术论文：https://arxiv.org/abs/2602.00744
- ACE-Step 项目主页：https://ace-step.github.io/ace-step-v1.5.github.io/
- ACE-Step LoRA 训练教程：https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/LoRA_Training_Tutorial.md
- 社区 LoRA 案例（人声 + 乐器）：https://huggingface.co/DisturbingTheField/ACE-Step-v1.5-raspy-vocal-and-instrumental-5-LoRAs
- 官方新年主题 LoRA：https://huggingface.co/ACE-Step/ACE-Step-v1.5-chinese-new-year-LoRA
- ACE-Step REST API 文档：https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md
- Seed-VC GitHub：https://github.com/Plachtaa/seed-vc
- Seed-VC 技术论文：https://arxiv.org/abs/2411.09943
- Seed-VC 歌声转换评测：https://github.com/Plachtaa/seed-vc/blob/main/EVAL.md
- Seed-VC vs RVCv2 歌声转换基准：M4Singer 数据集，SECS 0.7405 vs 0.7264，CER 19.70% vs 28.46%
