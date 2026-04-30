# VidMuse 按真实开发顺序重构执行计划

> 文档目标：这份文档不是把模块名字重新列一遍，而是按“真实开发已经做完一遍”的视角，把整个项目重构成一个依赖链清晰、输入输出明确、可以逐步执行的开发顺序。
>
> 核心原则：
> - 每个任务都必须回答 4 个问题：
>   1. 上一步已经交付了什么
>   2. 这一步要实现什么
>   3. 这一步产出什么供下一个任务使用
>   4. 为什么现在做它，而不是更早或更晚
> - 每个任务尽量控制在单次改动 `2000` 行以内
> - 开发顺序优先遵守真实依赖链，而不是概念上的“看起来相关”

---

## 1. 为什么要重构执行计划

前面的 [09_VidMuse详细开发执行计划](C:\Users\Administrator\Desktop\面试简历\09_VidMuse详细开发执行计划.md) 已经够细，但它仍然偏“模块清单”视角。

真实开发里，工程师脑子里的顺序不是：

- 先想完所有模块
- 再随便挑一个开始写

而是：

- 先让工程跑起来
- 再让配置和 Prompt 可控
- 再让数据库和状态可控
- 再让任务和事件可控
- 再让对话和 Agent 可用
- 再让分析和规划跑通
- 再让媒体生成跑通
- 再让返工、回退、版本切换成立

所以这份文档就是把计划重排成这种“真实执行顺序”。

---

## 2. 真实开发的主链路

整个项目最终会沿着这条链路成立：

```text
工程可启动
-> 配置、Prompt、日志、产物追溯可用
-> 数据库和状态机可用
-> 项目和输入可落库
-> 对话入口可用
-> Director Agent 可路由
-> 音频分析可运行
-> brief / style / shot plan 可产出
-> storyboard 可产出
-> clip 可产出
-> timeline 可产出
-> export 可产出
-> 局部返工和版本切换可用
-> 质检和 lipsync 作为增强补上
```

这条链路决定了开发顺序。

---

## 3. 任务书写模板

从这一份开始，每个任务都按下面的结构写。

### 模板

- 任务编号
- 当前为什么做
- 上一步输入
- 本步实现
- 产出结果
- 下一个使用者
- 目录与文件
- 验收标准
- 预计代码量

---

## 4. 第 0 组：把项目启动起来

这一组不解决业务问题，只解决“能不能开始开发”。

### 任务 0-01：初始化仓库骨架 **[完成]**

当前为什么做：

- 没有统一目录，后续所有代码和文档都会散

上一步输入：

- 无

本步实现：

- 创建根目录结构
- 建立 `backend/`、`frontend/`、`config/`、`prompts/`、`data/`、`logs/`、`docs/`

产出结果：

- 统一仓库骨架

下一个使用者：

- 所有后续任务

目录与文件：

- 根目录全部基础目录
- 根目录 `README.md`

验收标准：

- 仓库结构与文档约定一致

预计代码量：

- `100 ~ 300` 行

**执行记录**：
- 执行者：harvai-developer-a
- 完成时间：2026-03-29
- 产出：`backend/.gitkeep`、`data/projects/.gitkeep`、更新 `README.md`

### 任务 0-02：初始化后端脚手架 **[完成]**

当前为什么做：

- 后端必须先有可启动入口，后面才能持续往里填模块

上一步输入：

- 任务 `0-01`

本步实现：

- 初始化 Python 项目
- 创建 FastAPI 启动入口
- 建立后端模块目录
- 编写 requirements.txt（含精确版本依赖）

产出结果：

- 可运行的后端骨架

下一个使用者：

- 配置系统、数据库连接、API 层

目录与文件：

- `backend/requirements.txt`
- `backend/app/main.py`
- `backend/app/__init__.py`
- `backend/app/api/__init__.py`
- `backend/app/api/v1/__init__.py`
- `backend/app/api/v1/health.py`
- `backend/app/core/__init__.py`
- `backend/app/core/settings.py`
- `backend/app/utils/__init__.py`
- `backend/app/utils/logging.py`
- `backend/tests/__init__.py`
- `backend/tests/test_health.py`

验收标准：

- 后端能启动并返回基础 health

预计代码量：

- `300 ~ 700` 行

**执行记录**：
- 执行者：Oz（重构修正）
- 完成时间：2026-03-29
- 产出：
  - `backend/requirements.txt`（langgraph==1.0.10, langchain==1.2.12 等精确版本，移除 pydantic-settings）
  - `backend/app/main.py`（asynccontextmanager lifespan，接入 ServiceManager，配置从 settings 读取）
  - `backend/app/core/settings.py`（重写：去掉 BaseSettings，纯从 config_loader 加载，暴露 postgres/redis/minio 全部连接字段）
  - `backend/app/bootstrap/services.py`（修复：minio_endpoint 直接传字符串，redis db/password 字段齐全）
  - `backend/app/utils/logging.py`（标记废弃，重定向到 app.core.logging）
  - `backend/app/api/v1/health.py`
  - `.env.example`（简化：只保留 POSTGRES_PASSWORD/MINIO_ACCESS_KEY/MINIO_SECRET_KEY）
  - 所有模块目录补全 `__init__.py`（agents/domain/events/models 等 12 个）

### 任务 0-03：初始化前端脚手架

当前为什么做：

- 后续需要尽早验证工作台骨架，但前端必须先能跑

上一步输入：

- 任务 `0-01`

本步实现：

- 初始化 Next.js 项目
- 建立前端目录骨架

产出结果：

- 可运行的前端骨架

下一个使用者：

- 登录页、项目列表、工作台骨架

目录与文件：

- `frontend/package.json`
- `frontend/src/...`

验收标准：

- 前端能启动并访问基础页面

预计代码量：

- `400 ~ 1000` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-31
- 产出：
  - `config/base/external_apis.yaml`（补充 hedra 段：api_key/base_url/timeout/poll_interval/max_poll_attempts）
  - `backend/app/core/config_loader.py`（新增 HedraConfig Pydantic model；ExternalApisConfig 添加 hedra 字段；load_external_apis_config() 加载 hedra 段）
  - `backend/app/providers/lipsync/__init__.py`
  - `backend/app/providers/lipsync/base.py`（LipSyncResult dataclass + LipSyncProviderAdapter Protocol + LipSyncError + get_lipsync_provider() 工厂函数）
  - `backend/app/providers/lipsync/hedra_adapter.py`（HedraAdapter：POST `/v1/characters` 提交 → 轮询 GET `/v1/characters/{id}` → 返回 video_url；Bearer API key 认证；多字段名容错）
- **修复记录 (2026-04-05)**：
  - 执行者：Warp AI (Oz)
  - 内容：恢复因 AI Studio 修改导致的前端 404 故障；清理 `vite.config.ts` 中的 AI Studio 遗留配置；恢复 HMR 热更新。

### 任务 0-04：建立单一后端启动入口 **[完成]**

当前为什么做：

- 你已经明确要求：后端只能有一个启动入口

上一步输入：

- 任务 `0-02`

本步实现：

- 设计统一开发启动命令
- 决定由该命令拉起：
  - API
  - worker
  - 事件发布器
  - 基础依赖服务编排

产出结果：

- 开发入口被固定

下一个使用者：

- 所有本地联调任务

目录与文件：

- `scripts/dev_up.ps1`
- `scripts/dev_down.ps1`
- `docker-compose.yml`
- `backend/app/bootstrap/__init__.py`
- `backend/app/bootstrap/services.py`

验收标准：

- 开发者只执行一个命令即可拉起后端系统

预计代码量：

- `300 ~ 900` 行

**执行记录**：
- 执行者：Oz（重构修正）
- 完成时间：2026-03-29
- 调整说明：组件已在服务器部署，无 Docker、无脚本。单一启动命令：`python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- 产出：
  - `backend/app/bootstrap/__init__.py`
  - `backend/app/bootstrap/services.py`（ServiceManager：异步检查 Postgres/Redis/MinIO 连通性，lifespan 接入）
  - `backend/migrations/.gitkeep`（为 task 2-02 Alembic 占位）
  - `scripts/.gitkeep`（清空 docker 脚本，目录保留供后续辅助脚本使用）

### 任务 0-05：接入本地基础依赖编排 **[完成]**

**调整说明**：数据库、Redis、MinIO 等组件已在服务器部署，改为创建配置文件接入。

当前为什么做：

- 后续所有服务都依赖配置，需要在开发初期建立配置体系

上一步输入：

- 任务 `0-04`

本步实现：

- 创建 config/base/ 目录下的配置文件
- 配置已部署的 Postgres、Redis、MinIO 服务连接

产出结果：

- 本地基础设施配置文件

下一个使用者：

- 配置系统、数据库连接、对象存储适配器

目录与文件：

- `config/base/app.yaml`
- `config/base/database.yaml`
- `config/base/redis.yaml`
- `config/base/storage.yaml`
- `backend/app/core/config_loader.py`

验收标准：

- 配置文件格式正确，后端可读取并连接服务

预计代码量：

- `100 ~ 200` 行

**执行记录**：
- 执行者：harvai-developer-a
- 完成时间：2026-03-29
- 产出：4个YAML配置文件（app/database/redis/storage）、配置加载器 config_loader.py

---

## 5. 第 1 组：把配置、Prompt、日志、产物追溯做出来

这一组决定后面代码是不是会变成一团。

### 任务 1-01：实现后端配置加载器 **[完成]**

当前为什么做：

- 后续所有服务都依赖配置，不能等到功能写到一半再补

上一步输入：

- 任务 `0-02`
- 任务 `0-05`

本步实现：

- 设计 `config/` 目录结构
- 实现配置文件读取器
- 提供统一配置访问接口

产出结果：

- 后端统一配置入口

下一个使用者：

- 数据库连接
- Redis 客户端
- MinIO 适配器
- provider registry

目录与文件：

- `config/base/*.yaml`
- `backend/app/core/config.py`

验收标准：

- 应用启动时能正确加载配置文件

预计代码量：

- `400 ~ 900` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `config/base/logging.yaml`（4 层日志配置：system/agent/tool/project，rotation/retention 策略）
  - `config/base/workflow.yaml`（状态机严格模式、自动重试、LangGraph checkpoint 后端）
  - `config/base/billing.yaml`（Credits 价格规则，覆盖全部 9 种工具）
  - `backend/app/core/config_loader.py`（新增 LoggingConfig/WorkflowConfig/BillingConfig 及 3 个 load 函数）
  - `backend/app/core/config.py`（VidMuseConfig frozen dataclass + get_config() 单例，聚合 7 个 section）

### 任务 1-02：实现 Prompt Registry **[完成]**

当前为什么做：

- Prompt 必须从第一天开始外部化，不然后面一定返工

上一步输入：

- 任务 `1-01`

本步实现：

- 设计 `prompts/` 目录规则
- 实现模板加载
- 实现变量渲染

产出结果：

- Prompt 外部化基础能力

下一个使用者：

- Director Agent
- 创意规划 Agent
- Prompt 编译服务

目录与文件：

- `prompts/**`
- `backend/app/core/prompt_registry.py`
- `backend/app/core/prompt_renderer.py`

验收标准：

- 可以按名称加载并渲染任意 prompt 模板

预计代码量：

- `500 ~ 1200` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `prompts/system/director.md`（导演 Agent 系统提示词，包含输出 JSON 格式约束）
  - `prompts/system/audio_analysis.md`、`creative_planning.md`、`consistency_guardian.md`
  - `prompts/tasks/clarify_missing_fields.md`、`generate_brief.md`、`generate_shot_plan.md`、`review_consistency.md`
  - `prompts/compiler/compile_image_prompt.md`、`compile_video_prompt.md`
  - `backend/app/core/prompt_registry.py`（自动扫描 prompts/ 建索引，YAML frontmatter 解析，name 唯一性校验）
  - `backend/app/core/prompt_renderer.py`（变量渲染，缺变量抛 MissingPromptVariableError）

### 任务 1-03：实现日志系统 **[完成]**

当前为什么做：

- 后续接 Agent、Tool、provider，没有日志基本无法开发

上一步输入：

- 任务 `1-01`

本步实现：

- 建立 `system / agent / tool / project` 日志分级
- 统一 JSON 日志格式

产出结果：

- 可观测的后端基础

下一个使用者：

- 所有后续 Service、Agent、Tool

目录与文件：

- `config/base/logging.yaml`
- `backend/app/core/logging.py`

验收标准：

- 后端启动、接口调用、任务执行都有结构化日志

预计代码量：

- `250 ~ 600` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `backend/app/core/logging.py`（4 层 loguru sink：system/agent/tool/project 分别写入对应子目录；get_logger/get_project_logger/get_agent_logger/get_tool_logger；自动建目录）
  - `backend/app/main.py` 接入（lifespan 中引入 get_logger，启动信息写入 logs/system/）
  - `backend/app/utils/logging.py`（标记废弃，重定向到 app.core.logging）

### 任务 1-04：实现本地产物目录规划器 **[完成]**

当前为什么做：

- 你要求阶段产物全部可追溯，这必须先做，不是后补

上一步输入：

- 任务 `1-01`

本步实现：

- 生成 `data/projects/{project_id}/...` 路径
- 提供 JSON / 文本 / 文件写入接口

产出结果：

- 本地追溯基础设施

下一个使用者：

- 音频分析
- brief 保存
- prompt bundle 保存
- clip 保存

目录与文件：

- `backend/app/storage/path_planner.py`
- `backend/app/storage/local_artifact_store.py`

|验收标准：

- 可按项目和阶段稳定写本地产物

|预计代码量：

- `300 ~ 700` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `backend/app/storage/path_planner.py`（ArtifactStage 常量 + ProjectPathPlanner；覆盖 01_input~10_export/logs/snapshots 全部阶段目录；build_filename 按规范生成带版本号和时间戳的文件名；ensure_all_dirs 项目初始化时一次性建全目录）
  - `backend/app/storage/local_artifact_store.py`（LocalArtifactStore：write_json/write_text/write_bytes/copy_file；read_json/read_text/read_bytes；list_stage_files/latest_in_stage；init_project_dirs；底层委托 ProjectPathPlanner）

### 任务 1-05：实现 MinIO 适配器 **[完成]**

当前为什么做：

- 后续上传、下载、导出全依赖对象存储

上一步输入：

- 任务 `1-01`
- 任务 `0-05`

本步实现：

- 实现统一对象存储接口
- 接入 MinIO

产出结果：

- 对象存储能力

下一个使用者：

- 资产上传
- 生成结果存储
- 导出存储

目录与文件：

- `backend/app/storage/object_storage.py`
- `backend/app/storage/minio_adapter.py`

验收标准：

|- 可上传文件、拿预签名地址、查询对象元信息

|预计代码量：

- `400 ~ 900` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `backend/app/storage/object_storage.py`（ObjectStorageAdapter Protocol + ObjectMetadata 数据类；Protocol 设计保证后续平滑替换 S3/阿里云 OSS 时业务层零改动）
  - `backend/app/storage/minio_adapter.py`（MinIOAdapter：同步 API + asyncio.to_thread 异步包装；upload_file/upload_bytes/download_file/download_bytes/get_presigned_url/object_exists/get_metadata/delete_object；get_storage() 全局懒加载单例）

### 任务 1-06：实现 Provider 注册中心 **[完成]**

当前为什么做：

- 真实开发里，provider 能力矩阵必须先固定，否则 Prompt 编译和 Tool 层后面会耦合炸掉

上一步输入：

- 任务 `1-01`

本步实现：

- 读取图片/视频/音频/lipsync provider 配置
- 暴露统一查询接口

产出结果：

- provider profile 能力矩阵

下一个使用者：

- Prompt 编译服务
- Tool 层
- 成本估算服务

目录与文件：

- `config/providers/*.yaml`
- `backend/app/core/provider_registry.py`

验收标准：

- 可以按 provider 名称查询能力与默认参数

预计代码量：

- `300 ~ 800` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-31
- 产出：
  - `backend/app/agents/consistency_guardian_agent.py`（ConsistencyGuardianAgent：加载 consistency_guardian_system + review_consistency 两层 prompt → ChatOpenAI → safe_parse_json 三层解析 → 空 issues 兜底；build_shots_summary 辅助函数）
  - `backend/app/api/v1/consistency.py`（POST `/consistency/check`；前置校验 storyboard_ready+；读取 style_bible + shots → 调用 Agent）
  - `backend/app/main.py`（注册 consistency_router）

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `config/providers/image_providers.yaml`（flux_schnell/flux_dev/stable_diffusion_xl，含 capabilities/default_params/prompt_style）
  - `config/providers/video_providers.yaml`（kling_v2/minimax_video/wan_video，含 generation_modes/field_mapping）
  - `config/providers/audio_providers.yaml`（librosa_local/whisperx_local，本地工具）
  - `config/providers/lipsync_providers.yaml`（hedra_character/musetalk_local/sync_labs）
  - `backend/app/core/provider_registry.py`（ProviderProfile/ProviderCapabilities；ProviderRegistry.load() 自动扫描；get/get_default/list_providers/supports_mode；get_provider_registry() 单例）

---

### 第 0-1 组复棄修复 **[完成]**

在第 2 组开始前，对第 0-1 组进行了工程级架构复棄，发现并修复以下问题：

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 修复内容：
  - `backend/requirements.txt`：补充缺失的 `python-ulid>=2.0.0` 依赖（任务 2-03 ULID 生成器的前置依赖）
  - `config/base/workflow.yaml` + `core/config_loader.py`：WorkflowConfig 补全 `decision_expire_seconds` / `checkpoint_backend` / `checkpoint_sqlite_path` 三个遗漏字段（LangGraph checkpoint 配置指向正确位置）
  - `core/settings.py`：消除配置双路径问题，改为委托 `get_config()` 单例，不再自行重复调用各 `load_xxx_config()`
  - `bootstrap/services.py`：`check_all()` 改用 `asyncio.gather()` 并发检查；所有 `print()` 替换为结构化日志（`get_logger`）
  - `core/logging.py`：修复 `event_type` 被静默丢弃问题（`_bind()` 方法显式传入）；文件 sink `format` 改为 `_json_formatter` 实现结构化 JSON 输出；移除未使用的 `_fmt()` 方法

---

## 6. 第 2 组：把后端基础数据层做出来

现在开始，所有任务都以数据库和业务对象为中心。

### 任务 2-01：实现数据库连接与事务会话 **[完成]**

当前为什么做：

- 后面所有 Repository 和模型都依赖它

上一步输入：

- 任务 `1-01`
- 任务 `0-05`

本步实现：

- 建立数据库连接
- 实现会话工厂
- 提供事务上下文

产出结果：

- 数据库访问基础设施

下一个使用者：

- ORM 模型
- Repository
- API Service

目录与文件：

- `backend/app/core/database.py`

验收标准：

- 后端能连接数据库并执行基础查询

预计代码量：

- `150 ~ 350` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `backend/app/core/database.py`（`_build_engine()` 基于 settings 构建异步引擎；`AsyncSessionFactory` asyncpg 全局单例；`get_db_session()` FastAPI Depends 用，请求级自动 commit/rollback/close；`transaction()` asynccontextmanager 供 Service 层显式事务；pool_pre_ping=True 防僵尸连接）

### 任务 2-02：数据库初始化方案 **[调整 → SQL 脚本]**

**调整说明（2026-03-30）**：
移除 Alembic。数据库结构统一通过 `scripts/init_schema.sql` 手动执行初始化，不依赖迁移工具。
原因：项目当前阶段数据库由开发者直接管控，SQL 脚本方式更直接，减少依赖链复杂度；
后续若需版本化迁移，可在生产阶段再引入。

**已执行**：
- 删除 `backend/alembic.ini`
- 删除 `backend/migrations/` 目录（含全部迁移文件）
- 从 `backend/requirements.txt` 移除 `alembic>=1.13.1`

数据库初始化入口：`scripts/init_schema.sql`（任务 第 0-3 组补充架构产出 已产出）

### 任务 2-03：建立 ORM 基类和 ULID **[完成]**

当前为什么做：

- 后面的所有模型都依赖统一主键和时间戳机制

上一步输入：

- 任务 `2-01`

本步实现：

- ULID 生成器
- ORM 基类
- 创建时间、更新时间统一策略

产出结果：

- 模型统一基座

下一个使用者：

- 所有模型定义

目录与文件：

- `backend/app/models/base.py`
- `backend/app/utils/ids.py`

验收标准：

- 新模型都可继承统一基类

预计代码量：

- `150 ~ 300` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `backend/app/utils/ids.py`（`generate_ulid()` 基于 python-ulid，返回 26 位大写 ULID 字符串）
  - `backend/app/models/base.py`（`Base` DeclarativeBase；`ULIDMixin`（default= Python 层生成不用 server_default=，INSERT 前即可拿到 id）；`TimestampMixin`/`CreatedAtMixin`/`UpdatedAtMixin` 三种时间戣 Mixin；`BaseModel` __abstract__ 标准业务模型基类）

### 任务 2-04：建立共享 DTO / Schema 层 **[完成]**

当前为什么做：

- 真实开发里，如果不先定共享对象，API、Agent、前端会各写一份结构，后面必炸

上一步输入：

- 任务 `2-03`

本步实现：

- 建立 `ProjectSnapshot`
- 建立 `ShotSemanticSpec`
- 建立 `PromptBundle`
- 建立 `ProjectEvent`

产出结果：

- 统一领域对象结构

下一个使用者：

- API
- LangGraph
- Agent
- 前端

目录与文件：

- `backend/app/schemas/*.py`

验收标准：

- 后续模块可直接复用 schema，不再重复定义

预计代码量：

- `300 ~ 800` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `backend/app/schemas/project.py`（`ActiveVersions` / `PendingDecisionRef` / `ProjectSnapshot`；`model_config = ConfigDict(frozen=True)` 不可变快照；对应 doc03 §5.2）
  - `backend/app/schemas/shot.py`（`ShotSemanticSpec`；`ShotRole`/`PaceType` Literal 枚举；duration_sec 必填且有边界校验；对应 doc06 §9.2）
  - `backend/app/schemas/prompt.py`（`PromptBundle` / `PromptTargetType`；bundle_id 自动生成 ULID；对应 doc06 §10.2）
  - `backend/app/schemas/event.py`（`ProjectEvent` / `EventCategory`；对应 doc04 §8 事件系统）
  - `backend/app/schemas/__init__.py`（统一导出全部共享 schema）

### 任务 2-05：实现用户与项目基础模型 **[完成]**

当前为什么做：

- 登录、项目、会话必须先落库，否则后续ไม่มี业务容器

上一步输入：

- 任务 `2-02`
- 任务 `2-03`

本步实现：

- `users`
- `user_preferences`
- `projects`
- `conversation_sessions`
- `conversation_messages`
- `session_contexts`

产出结果：

- 最小业务数据骨架

下一个使用者：

- 登录接口
- 项目 API
- 对话存储

目录与文件：

- `backend/app/models/user.py`
- `backend/app/models/project.py`
- `backend/app/models/conversation_*.py`

验收标准：

- 这些基础表完成迁移并可访问

预计代码量：

- `600 ~ 1400` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `backend/app/models/user.py`（`User` + `UserPreferences`；CheckConstraint / UniqueConstraint；JSONB `favorite_style_tags`；`last_login_at` 显式 `DateTime(timezone=True)`）
  - `backend/app/models/project.py`（`Project` 主聚合根；10 个 `active_xxx_version_id` 指针字段；`current_stage` CheckConstraint 覆盖全部 11 个状态机阶段；高频查询索引）
  - `backend/app/models/conversation.py`（`ConversationSession` / `ConversationMessage` / `SessionContext`；messages append-only 无 `updated_at`；session_contexts 以 `session_id` 为 PK；`order_by=lambda: ConversationMessage.created_at` 避免字符串 SQL 解析错误）
  - `backend/app/models/__init__.py`（导入全部模型，触发 Alembic `Base.metadata` 注册）

### 任务 2-06：实现 Repository 基类与 Unit of Work **[完成]**

当前为什么做：

- 如果 Repository 和事务边界不先统一，后面 Service 层会非常乱

上一步输入：

- 任务 `2-01`
- 任务 `2-05`

本步实现：

- Repository 基类
- Unit of Work
- 最小查询接口模板

产出结果：

- 数据访问统一方式

下一个使用者：

- Auth Service
- Project Service
- Conversation Service

目录与文件：

- `backend/app/repositories/base.py`
- `backend/app/repositories/unit_of_work.py`

验收标准：

- Service 层可以通过统一方式访问仓库和事务

预计代码量：

- `250 ~ 700` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 产出：
  - `backend/app/repositories/base.py`（`BaseRepository[T]` 泛型；`get_by_id`/`get_all`/`exists`/`add`/`add_all`/`delete`/`flush`/`refresh`；`session` 属性暴露给子类复杂查询使用）
  - `backend/app/repositories/unit_of_work.py`（`UnitOfWork` async context manager；begin/commit/rollback/close 生命周期；`session` 属性验证已开启；支持手动控制模式）
  - `backend/app/repositories/__init__.py`（导出 `BaseRepository` / `UnitOfWork`）

### 第 2 组复棄修复 **[完成]**

第 2 组完成后对全部代码进行了工程级复棄，共发现并修复 6 个问题：

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-29
- 修复内容：
  - `models/user.py`：`last_login_at` 补充 `DateTime(timezone=True)` 显式类型，防止 Alembic 迁移生成无时区 `TIMESTAMP` 列
  - `models/conversation.py`：`order_by` 从无效字符串 `"ConversationMessage.created_at"` 改为 `lambda: ConversationMessage.created_at`，防止运行时 SQL 语法错误
  - `core/database.py`：移除已废弃的 `future=True` 参数（SQLAlchemy 2.x 默认行为）
  - `models/user.py`：移除未使用的 `Text` import
  - `schemas/project.py`：移除未使用的 `Any` 和 `generate_ulid` import
  - `schemas/*.py`：Pydantic v2 中将 `class Config:` 旧语法统一改为 `model_config = ConfigDict(...)` 规范写法

---

## 7. 第 3 组

这里的目标是先具备“登录 -> 创建项目 -> 打开项目”的能力。

### 任务 3-01：实现密码哈希和 JWT **[完成]**

当前为什么做：

- 登录必须先有可用安全基础

上一步输入：

- 任务 `2-05`

本步实现：

- 密码哈希
- access token
- refresh token

产出结果：

- 登录安全能力

下一个使用者：

- 登录 API

目录与文件：

- `backend/app/core/security.py`

验收标准：

- 可签发和校验 token

预计代码量：

- `200 ~ 500` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-30
- 产出：
  - `backend/app/core/security.py`（bcrypt 哈希 / access+refresh 双 token / TokenDecodeError 自定义异常 / type 字段防 token 混用 / secret 从 settings 动态读取，无硬编码）
  - `backend/app/api/v1/deps.py`（同步产出：ok/err 统一响应帮助函数、get_request_id、get_current_user FastAPI 依赖）

### 任务 3-02：实现登录 API **[完成]**

当前为什么做：

- 没有登录，前端和业务链路都不能验证真实用户态

上一步输入：

- 任务 `3-01`
- 任务 `2-06`

本步实现：

- `/api/v1/auth/login`
- `/api/v1/auth/refresh`

产出结果：

- 基础鉴权入口

下一个使用者：

- 前端登录页
- 项目接口鉴权

目录与文件：

- `backend/app/api/auth.py`
- `backend/app/services/auth_service.py`

验收标准：

- 可登录并获得 token

预计代码量：

- `200 ~ 450` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-30
- 产出：
  - `backend/app/api/v1/auth.py`（POST `/auth/login` / `/auth/refresh` / `/auth/logout` 三条接口；AuthError 统一错误码；防用户名枚举）
  - `backend/app/services/auth_service.py`（`login` / `refresh_token` / `create_user`；UoW 管事务；`last_login_at` 更新；`status` 禁用拦截）
  - `backend/app/repositories/user_repository.py`（`get_by_username` / `get_by_id`）

### 任务 3-03：实现项目 CRUD 最小 API **[完成]**

当前为什么做：

- 必须先让“项目存在”，后面的输入、分析、Agent 才有容器

上一步输入：

- 任务 `2-06`
- 任务 `3-02`

本步实现：

- 创建项目
- 项目列表
- 项目详情

产出结果：

- 最小项目控制面

下一个使用者：

- 前端项目页
- 后续 ProjectSpec

目录与文件：

- `backend/app/api/projects.py`
- `backend/app/services/project_service.py`

验收标准：

- 用户可以创建和读取项目

预计代码量：

- `300 ~ 700` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-30
- 产出：
  - `backend/app/api/v1/projects.py`（POST/GET/GET `/{id}` / PATCH 四条接口；全量 `user_id` 隔离；游标分页 `has_more`）
  - `backend/app/services/project_service.py`（`create/get/list/update`；初始 `stage=created`；10 个 `active_version` 指针全量暴露）
  - `backend/app/repositories/project_repository.py`（`get_by_id_for_user` / `list_by_user` / `name_exists_for_user`）
  - `backend/app/api/v1/deps.py`（鉴权链路复检修正：修复 `UserRepository(session, User)` 多传参数运行时 Bug）

### 任务 3-04：实现前端登录页和项目列表 **[暂缓]**

**暂缓说明**：前端脚手架（任务 `0-03`）尚未启动，本任务待 `0-03` 完成后再执行。

当前为什么做：

- 现在已经有登录和项目 API，可以开始最早一轮前后端联调

上一步输入：

- 任务 `0-03`
- 任务 `3-02`
- 任务 `3-03`

本步实现：

- 登录页
- 项目列表页
- 新建项目

产出结果：

- 第一批可见页面

下一个使用者：

- 项目工作台

目录与文件：

- `frontend/src/app/login/*`
- `frontend/src/app/projects/*`

验收标准：

- 用户能登录并进入项目列表，创建新项目

预计代码量：

- `400 ~ 900` 行

### 第 0-3 组补充架构产出 **[完成]**

当前为什么做：

- 在第 4 组开始前，必须先把全量数据库 Schema 作为统一可信来源固定下来，避免后续按功能零散补表

上一步输入：

- 文档 `03` / `04` / `05`
- 任务 `2-02`
- 任务 `2-05`

本步实现：

- 按文档全量设计数据库初始化 SQL
- 明确全量表、字段、约束、索引、外键顺序

产出结果：

- 全量数据库 Schema 安装脚本

下一个使用者：

- 后续 Alembic 迁移
- 剩余 ORM 模型
- 第 4 组及之后的所有数据层任务

目录与文件：

- `scripts/init_schema.sql`

验收标准：

- 覆盖文档要求的全部核心表结构，可作为后续 migration/ORM 对齐基线

预计代码量：

- `700 ~ 1200` 行

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-30
- 产出：
  - `scripts/init_schema.sql`（全量 26 张表；覆盖 auth / project / conversation / assets / analysis / shots / generation / timeline / workflow / events 全部模块）
  - 设计决策已固化：`projects.active_*_version_id` 不建外键、`prompt_bundles.target_id` 多态不建外键、`credit_ledger.job_id` 逻辑引用不建外键、两处延迟外键通过 `ALTER TABLE` 补建

---

## 8. 第 4 组：把工作流控制面先搭出来

这里还不做真正的 AI 主链路，先做控制面。

### 任务 4-01：实现工作流辅助模型 **[完成]**

当前为什么做：

- 在有项目之后，必须尽快把任务、决策、事件、账本这些辅助表立起来

上一步输入：

- 任务 `2-02`
- 任务 `2-03`

本步实现：

- `pending_decisions`
- `agent_tasks`
- `tool_jobs`
- `event_logs`
- `outbox_events`
- `credit_ledger`

产出结果：

- 工作流控制表

下一个使用者：

- 状态机
- worker
- SSE
- 决策卡

目录与文件：

- `backend/app/models/*`

验收标准：

- 所有控制表创建完成

预计代码量：

- `700 ~ 1500` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/models/workflow.py`（PendingDecision / AgentTask / ToolJob）
  - `backend/app/models/events.py`（EventLog / OutboxEvent）
  - `backend/app/models/billing.py`（CreditLedger）
  - `backend/app/models/__init__.py`（新增 3 行导入）
  - `backend/migrations/versions/a4b7d9e2f1c8_workflow_control_tables.py`（6 张表 + FK 补建）

### 任务 4-02：实现事件日志服务与 Outbox **[完成]**

当前为什么做：

- 后续状态变化、SSE、任务执行都依赖事件系统

上一步输入：

- 任务 `4-01`

本步实现：

- event log 写入
- outbox 写入
- 发布器骨架

产出结果：

- 可传播的业务事件

下一个使用者：

- Project SSE
- 状态机
- worker

目录与文件：

- `backend/app/services/event_log_service.py`
- `backend/app/events/outbox_publisher.py`

验收标准：

- 业务动作后能写日志并生成 outbox

预计代码量：

- `300 ~ 800` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/repositories/event_log_repository.py`（EventLogRepository + OutboxRepository）
  - `backend/app/services/event_log_service.py`（EventLogService.emit() 接受外部 session）
  - `backend/app/events/outbox_publisher.py`（OutboxPublisher asyncio 后台任务）
  - `backend/app/events/__init__.py`（导出 OutboxPublisher）

### 任务 4-03：实现状态机服务 **[完成]**

当前为什么做：

- 在真实开发里，状态机要早于 Agent 和 Tool，不然所有判断会散落

上一步输入：

- 任务 `4-01`
- 任务 `4-02`

本步实现：

- 项目状态机
- 任务状态机
- shot 状态机基础
- stale 标记骨架

产出结果：

- 统一控制面

下一个使用者：

- ProjectSpec 输入
- Director Agent
- 音频分析节点

目录与文件：

- `backend/app/services/state_transition_service.py`

验收标准：

- 可执行合法性校验和状态推进

预计代码量：

- `500 ~ 1200` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/domain/states.py`（ProjectStage / TaskStatus / ShotStatus / StaleScope + ALLOWED_* 迁移表）
  - `backend/app/domain/__init__.py`（导出领域符号）
  - `backend/app/services/state_transition_service.py`（advance_project / transition_agent_task / transition_tool_job / mark_stale）

### 任务 4-04：实现 worker 骨架 **[完成]**

当前为什么做：

- 后续音频分析、图片、视频、导出都是长任务，不先有 worker 后面会重写

上一步输入：

- 任务 `0-04`
- 任务 `4-01`

本步实现：

- worker 启动逻辑
- task dispatcher
- task status 回写

产出结果：

- 后台异步执行能力

下一个使用者：

- 音频分析
- storyboard
- clip
- export

目录与文件：

- `backend/app/tasks/*`

验收标准：

- 能异步执行一个示例任务并回写状态

预计代码量：

- `400 ~ 1000` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/tasks/dispatcher.py`（TaskDispatcher：dispatch + push_to_queue + 幼等键判重）
  - `backend/app/tasks/worker.py`（TaskWorker：handler registry + asyncio循环 + BRPOP + 超时 + 自动重试）
  - `backend/app/tasks/__init__.py`（导出 + task_worker 单例）

### 任务 4-05：实现幼等与并发控制服务 **[完成]**

当前为什么做：

- 高成本生成类系统，如果不先做幂等和锁，后面很快乱套

上一步输入：

- 任务 `4-01`
- 任务 `4-04`

本步实现：

- idempotency key 校验
- 项目级锁
- shot 级锁
- 旧任务取消规则

产出结果：

- 高成本动作保护层

下一个使用者：

- 所有 Tool 任务
- 局部返工

目录与文件：

- `backend/app/services/idempotency_service.py`
- `backend/app/services/concurrency_guard_service.py`

验收标准：

- 相同请求不会重复跑高成本任务

预计代码量：

- `350 ~ 900` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-31
- 产出：
  - `backend/app/tools/lipsync_tool.py`（LipSyncTool：provider 调用 → 下载视频 → MinIO 上传 → Asset 落库 → 本地副本）
  - `backend/app/services/lipsync_service.py`（校验 lipsync_required + storyboard frame + 音频资产；Credits reserve/commit/refund；生成 `ClipVersion(generation_mode='lipsync')`；更新 timeline segment）
  - `backend/app/api/v1/lipsync.py`（POST `/shots/{shot_id}/lipsync` + GET `/shots/lipsync-candidates`）
  - `backend/app/services/cost_estimation_service.py`（新增 `estimate_lipsync()`）
  - `backend/app/main.py`（注册 lipsync_router）

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/services/idempotency_service.py`（ensure_unique 全量状态检查 + invalidate 旧 job 失效）
  - `backend/app/services/concurrency_guard_service.py`（Redis SET NX 分布式锁 + ConcurrencyError）

### 任务 4-06：实现 Project SSE **[完成]**

当前为什么做：

- 工作台必须实时显示阶段变化，这个不能拖到后面

上一步输入：

- 任务 `4-02`

本步实现：

- SSE 网关
- 事件分发

产出结果：

- 项目状态实时流

下一个使用者：

- 前端工作台

目录与文件：

- `backend/app/api/project_events.py`

验收标准：

- 前端可接收到项目状态变化事件

预计代码量：

- `300 ~ 700` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/api/v1/project_events.py`（SSE 端点，订阅 Redis pub-sub，30s 心跳）
  - `backend/app/main.py`（新增：启动 OutboxPublisher + TaskWorker 后台任务，注册 project_events 路由）

### 任务 4-07：实现健康检查与诊断接口 **[完成]**

当前为什么做：

- 到这一步服务已经不止一个了，没有诊断接口会很痛苦

上一步输入：

- 任务 `0-05`
- 任务 `1-05`
- 任务 `2-01`

本步实现：

- `/health`
- `/ready`
- 依赖检查

产出结果：

- 开发诊断入口

下一个使用者：

- 本地联调
- 启动脚本

目录与文件：

- `backend/app/api/health.py`

验收标准：

- 能准确判断 `Postgres/Redis/MinIO` 是否可用

预计代码量：

- `200 ~ 500` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/api/v1/health.py`（完全重写：/health Liveness + /ready Readiness，并发 Postgres/Redis/MinIO 检查 + asyncio 后台任务诊断）

### 第 4 组复棄修复 **[完成]**

第 4 组完成后对全部代码进行了工程级复棄，共发现并修复以下问题：

**执行记录**：
- 执行者：Oz
- 完成时间：2026-03-30
- 修复内容：
  - `backend/app/core/redis_utils.py`（**新建**：提取 `build_redis_url()` 共享工具，消除 5 处重复实现；后续若升级为 Redis Sentinel/Cluster 或增加 TLS 只需改此一处）
  - `backend/app/tasks/worker.py`：**修复功能性 Bug**——`_handle_failure()` 重试路径中缺失 `_requeue_job()` 调用，导致 ToolJob 标记为 `retrying` 后永远不会重新入队，重试机制完全失效；修复方式：引入 `should_requeue` 标志位，确保 UoW commit 之后（先落库再推队列，与 dispatcher 的 commit-after-push 模式一致）再调用 `_requeue_job()`；同时修复 `_fail_job()` 参数类型标注 `Any` → `AsyncSession | None`；替换本地 `_build_redis_url()`
  - `backend/app/tasks/dispatcher.py`：替换本地 `_build_redis_url()` → `from app.core.redis_utils import build_redis_url`
  - `backend/app/events/outbox_publisher.py`：替换本地 `_build_redis_url()`
  - `backend/app/services/concurrency_guard_service.py`：替换本地 `_build_redis_url()`
  - `backend/app/api/v1/project_events.py`：替换本地 `_build_redis_url()`
  - `backend/app/services/state_transition_service.py`：修正 `mark_stale()` 中“不发事件”误导性注释（阶段回退事件由 `advance_project` 正确发出，stale 标记是内部实现细节，注释已澄清）；在 `_mark_all_shots_stale()` 和 `_mark_single_shot_stale()` 内部捕获 `ProgrammingError`，防止 `shots` 表在 task `9-01` 完成前不存在时异常穿透事务导致业务数据回滚

---

## 9. 第 5 组

到这里，用户终于可以真正把内容放进项目里。

### 任务 5-01：实现资产表和资产上传接口 **[完成]**

当前为什么做：

- 没有资产上传，项目输入无法成立

上一步输入：

- 任务 `1-05`
- 任务 `2-06`

本步实现：

- `assets` 表
- 上传初始化
- 上传完成

产出结果：

- 音频和图片能进入系统

下一个使用者：

- ProjectSpec
- 音频分析

目录与文件：

- `backend/app/models/asset.py`
- `backend/app/api/assets.py`
- `backend/app/services/asset_service.py`

验收标准：

- 可上传音频和参考图，并落库

预计代码量：

- `400 ~ 900` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/models/asset.py`（Asset ORM，append-only，storage_uri 永久直链）
  - `backend/app/repositories/asset_repository.py`
  - `backend/app/services/asset_service.py`（upload_init/complete_upload/list_assets，两步式直传 MinIO）
  - `backend/app/api/v1/assets.py`（3个接口：upload-init/complete/list）
  - `backend/app/storage/minio_adapter.py`（新增 get_permanent_url/get_upload_presigned_url）

### 任务 5-02：实现上传后本地追溯副本 **[完成]**

当前为什么做：

- 你要求阶段产物和输入都必须本地保留

上一步输入：

- 任务 `5-01`
- 任务 `1-04`

本步实现：

- 上传完成后同步保存本地副本
- 写元数据 JSON

产出结果：

- 输入资产双份追溯

下一个使用者：

- 调试和问题排查

目录与文件：

- `backend/app/services/asset_sync_service.py`

验收标准：

- 上传后 MinIO 和本地都有可追溯副本

预计代码量：

- `250 ~ 600` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/services/asset_sync_service.py`（从 MinIO 下载副本到 01_input/，写元数据 JSON）
  - 仅同步 audio_original/image_reference/style_reference 三类用户输入资产

### 任务 5-03：实现 ProjectSpec 版本服务 **[完成]**

当前为什么做：

- 资产上传后，必须把项目输入规格固定成结构化版本对象

上一步输入：

- 任务 `5-01`
- 任务 `2-06`

本步实现：

- `project_spec_versions`
- 创建新版本
- 激活版本

产出结果：

- 项目输入规格版本化

下一个使用者：

- 状态机
- 音频分析
- Director Agent

目录与文件：

- `backend/app/models/project_spec_version.py`
- `backend/app/services/project_spec_service.py`

验收标准：

- 项目输入可版本化存储并激活

预计代码量：

- `300 ~ 700` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/models/project_spec_version.py`（ProjectSpecVersion ORM，append-only）
  - `backend/app/repositories/project_spec_repository.py`（get_active/deactivate_all/get_next_version_no）
  - `backend/app/services/project_spec_service.py`（create_version/activate_version/get_active_version）
  - `backend/app/api/v1/project_spec.py`（3个接口：versions/activate/active）

### 任务 5-04：实现输入完成后的状态推进 **[完成]**

当前为什么做：

- 到这一步才真正有了进入主流程的资格

上一步输入：

- 任务 `5-03`
- 任务 `4-03`

本步实现：

- 校验音频、区间、prompt 是否齐全
- 推进项目到 `input_ready`

产出结果：

- 项目具备进入 AI 流程的状态

下一个使用者：

- Director Agent
- 音频分析

目录与文件：

- `backend/app/services/project_service.py`

验收标准：

- 满足输入条件后项目状态自动变为 `input_ready`

预计代码量：

- `150 ~ 400` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - 嵌入在 `ProjectSpecService.activate_version()` 内，激活版本时同步检查 `_can_advance_to_input_ready()`
  - 条件：audio_asset_id 不为空 + audio_end_sec > audio_start_sec + user_prompt 不为空
  - 仅当 current_stage == created 时才推进，防止 input_ready→input_ready 非法转换
  - 状态推进与版本激活在同一 UoW 事务内原子完成

### 第 5 组复检修复 **[完成]**

第 5 组完成后对全部代码进行了工程级复检，发现并修复以下问题：

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 复检结论：功能正确，上下游关联正常，无偏离计划方向
- 修复内容：
  - `backend/app/services/asset_sync_service.py`：移除死代码变量 `meta_path`（该变量被赋值但从未使用，实际写入路径由 `store.write_json()` 内部生成，两者不同）
  - `backend/app/storage/minio_adapter.py`：新增 `default_bucket` 公共属性，替代外部直接访问 `_default_bucket` 私有属性
  - `backend/app/services/asset_service.py`：将 `storage._default_bucket` 改为 `storage.default_bucket`（使用公共接口）
  - `backend/app/storage/local_artifact_store.py`：新增 `project_dir` 公共属性（委托 ProjectPathPlanner.project_dir）
- 已知技术债（不影响当前功能，后续迁移时处理）：`models/asset.py` 中 ORM `Index("idx_assets_sha256", ...)` 声明为普通索引，但迁移用 `op.execute` 建的是 partial index（WHERE sha256 IS NOT NULL）；下次 Alembic autogenerate 时可能产生 drift 警告，需在迁移时手动消除

---

### 任务 5-05：实现前端工作台骨架 + 输入页 **[完成]**

当前为什么做：

- 到这一步前端终于有真实数据可接，不再只是空壳

上一步输入：

- 任务 `3-04`
- 任务 `5-01`
- 任务 `5-03`
- 任务 `4-06`

本步实现：

- 项目工作台三栏骨架
- 输入阶段页
- 接入 Project SSE

产出结果：

- 用户能在 UI 上完成输入

下一个使用者：

- 音频分析展示页
- Chat 面板

目录与文件：

- `frontend/src/app/projects/[projectId]/*`
- `frontend/src/components/layout/*`
- `frontend/src/components/input/*`

验收标准：

- 用户可在工作台中完成音频和图片输入并看到阶段状态

预计代码量：

- `600 ~ 1400` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-05
- 产出（UI/UX 修正批次）：
  - `frontend/src/pages/Workbench.tsx`（输入阶段改为单一入口：上传音频后显示文件信息和替换入口，不再自动触发分析；新增“开始创作”统一执行 ProjectSpec 创建、激活和音频分析；`created` 阶段右侧面板改为静态创作向导，聊天输入仅在 `audio_analyzed` 及之后阶段开放）
  - `frontend/src/components/workbench/AudioAnalysisView.tsx`（右侧新增“曲目结构”区块，渲染 `section_map` 的段落标签和时间范围，支持点击跳转播放位置）

---

## 10. 第 6 组：先把对话入口打通

因为这是对话式 workflow，不能等媒体能力全做完才接聊天。

### 任务 6-01：实现 OpenAI 兼容聊天接口 **[完成]**

当前为什么做：

- Director Agent 后面就要挂在这个入口上，必须先把协议通道打好

上一步输入：

- 任务 `3-02`

本步实现：

- `/v1/chat/completions`
- 非流式响应

产出结果：

- 兼容聊天入口

下一个使用者：

- Chat SSE
- Director Agent

目录与文件：

- `backend/app/api/openai_compat.py`

验收标准：

- 可接受标准 messages 并返回兼容响应

预计代码量：

- `300 ~ 700` 行

### 任务 6-02：实现 Chat SSE **[完成]**

当前为什么做：

- 工作台右侧聊天必须流式，不然体验和协议都不对

上一步输入：

- 任务 `6-01`

本步实现：

- `stream=true`
- `chat.completion.chunk`

产出结果：

- 流式聊天能力

下一个使用者：

- 前端 Chat 面板

目录与文件：

- `backend/app/api/openai_compat.py`

验收标准：

- 可流式输出 assistant 文本

预计代码量：

- `200 ~ 500` 行

### 任务 6-03：实现聊天消息持久化 **[完成]**

当前为什么做：

- 没有聊天历史，后续上下文和调试都不完整

上一步输入：

- 任务 `6-01`
- 任务 `2-05`

本步实现：

- 写入会话消息
- 维护 session 上下文

产出结果：

- 可追溯聊天历史

下一个使用者：

- Director Agent
- 前端聊天历史加载

目录与文件：

- `backend/app/services/conversation_service.py`

验收标准：

- 聊天记录可落库并查询

预计代码量：

- `200 ~ 500` 行

**执行记录（6-01 / 6-02 / 6-03）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/repositories/conversation_repository.py`（ConversationSessionRepository / ConversationMessageRepository / SessionContextRepository；touch_updated_at 保持会话活跃排序正确）
  - `backend/app/services/conversation_service.py`（get_or_create_session / save_user_message / save_assistant_message / load_history_for_llm / list_messages / list_sessions / update_session_context；Layer C 记忆边界清晰，不涉及 LangGraph checkpoint）
  - `backend/app/api/openai_compat.py`（POST /v1/chat/completions；支持 stream=false 和 stream=true；_generate_stub_reply() 占位，7-02 替换；消息持久化接入 ConversationService；OpenAI streaming chunk 格式完整）
  - `backend/app/api/v1/conversation.py`（控制面接口：GET/POST /sessions，GET /sessions/{id}/messages；前端加载历史会话和消息记录使用）
  - `backend/app/main.py`（新增：chat_router 挂载 /v1，conversation_router 挂载 /api/v1）
  - 顺手修复预存 bug：`backend/app/tasks/worker.py` 补充缺失的 `from app.core.config import get_config` 导入
- 路由验证：POST /v1/chat/completions、GET/POST /api/v1/projects/{id}/sessions、GET /api/v1/projects/{id}/sessions/{sid}/messages 全部注册正常

### 任务 6-04：实现前端 Chat 面板基础版

当前为什么做：

- 后端聊天接口已可用，现在需要用户能实际交互

上一步输入：

- 任务 `6-02`
- 任务 `6-03`
- 任务 `5-05`

本步实现：

- 聊天列表
- 输入框
- 流式渲染

产出结果：

- 右侧 Chat 初版

下一个使用者：

- Director Agent 真实接入

目录与文件：

- `frontend/src/components/chat/*`

验收标准：

- 用户可在工作台右侧与系统聊天

预计代码量：

- `400 ~ 900` 行

---

## 11. 第 7 组：把 Director Agent 挂上去

现在才轮到真正的 Agent，不然前面基础都不稳。

### 任务 7-01：定义 Graph State **[完成]**

当前为什么做：

- LangGraph 的第一步不是写 Agent，而是先固定状态输入输出

上一步输入：

- 任务 `2-04`
- 任务 `6-03`

本步实现：

- 定义 `ProjectGraphState`

产出结果：

- 图运行的统一状态对象

下一个使用者：

- Director Agent
- 主图节点

目录与文件：

- `backend/app/workflows/graph_state.py`

验收标准：

- 图状态结构固定且可序列化

预计代码量：

- `100 ~ 250` 行

### 任务 7-02：实现 Director Agent 最小版 **[完成]**

当前为什么做：

- 到这一步才有足够的项目上下文、聊天历史、状态基础来支撑 Director Agent

上一步输入：

- 任务 `1-02`
- 任务 `7-01`
- 任务 `5-04`

本步实现：

- 加载系统 prompt
- 读项目状态和输入规格
- 识别缺失字段
- 识别简单意图

产出结果：

- 最小可用 Director Agent

下一个使用者：

- intent resolution
- 主图

目录与文件：

- `backend/app/agents/director_agent.py`
- `prompts/system/director.md`

验收标准：

- Director Agent 能根据项目状态做最基本澄清和回复

预计代码量：

- `300 ~ 800` 行

### 任务 7-03：实现 Intent Resolution **[完成]**

当前为什么做：

- Director Agent 的自然语言输出必须尽快变成结构化动作，不然后面会乱

上一步输入：

- 任务 `7-02`

本步实现：

- `intent`
- `target`
- `patch`
- `requires_confirmation`

产出结果：

- 结构化意图对象

下一个使用者：

- LangGraph 主图
- 状态机服务

目录与文件：

- `backend/app/services/intent_resolution_service.py`

验收标准：

- 能识别最小意图集：创建、补充、修改、执行

预计代码量：

- `300 ~ 700` 行

### 任务 7-04：建立 LangGraph 最小主图 **[完成]**

当前为什么做：

- Director Agent 必须放进图里，后面才能加音频分析和规划节点

上一步输入：

- 任务 `7-01`
- 任务 `7-02`
- 任务 `7-03`

本步实现：

- `load_project_snapshot`
- `resolve_intent`
- `respond_to_user`

产出结果：

- 对话编排主图

下一个使用者：

- 音频分析节点
- 创意规划节点

目录与文件：

- `backend/app/workflows/main_graph.py`

验收标准：

- Director Agent 可通过 LangGraph 运行

预计代码量：

- `400 ~ 900` 行

### 任务 7-05：实现 OpenAI Tool Call 桥接 **[完成]**

当前为什么做：

- 真实项目中，对话系统不能只会说话，必须能把内部动作桥接到兼容协议

上一步输入：

- 任务 `6-01`
- 任务 `7-03`

本步实现：

- 输出 tool call
- 映射到内部 command / decision

产出结果：

- 对话协议与内部动作桥接

下一个使用者：

- 选项卡和确认卡
- 后续 workflow 触发

目录与文件：

- `backend/app/services/tool_call_bridge_service.py`

验收标准：

- OpenAI 兼容接口可返回标准 tool call

预计代码量：

- `250 ~ 700` 行

**执行记录（7-00 到 7-05 + 接入 Chat Completions）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `config/base/llm.yaml`（新增：provider/model/api_key_env/temperature/timeout 配置，支持 OpenAI / DeepSeek / 自定义 base_url）
  - `backend/app/core/config_loader.py`（新增 LLMConfig + load_llm_config，api_key 通过环境变量注入，绝不硬编码）
  - `backend/app/core/config.py`（VidMuseConfig 新增 llm 字段）
  - `backend/app/workflows/graph_state.py`（ProjectGraphState TypedDict，total=False 允许节点只返回修改的字段）
  - `backend/app/agents/director_agent.py`（渲染 director_system prompt + ChatOpenAI 调用 + _safe_parse_json 三层解析 + 全局兑底结构；API key 缺失时优雅降级）
  - `backend/app/services/intent_resolution_service.py`（DirectorOutput 翻译为 IntentResult；_EXECUTABLE_ACTIONS 白名单防止非法动作；多类 mode 映射策略）
  - `backend/app/workflows/main_graph.py`（3 节点线性图: load_project_snapshot → director_intake → respond_to_user；MemorySaver checkpoint + session_id 作为 thread_id；错误不抑发层，降级为错误文本）
  - `backend/app/services/tool_call_bridge_service.py`（next_action 映射到 OpenAI tool call 格式；_TOOL_SCHEMAS 白名单防止非法动作）
  - `backend/app/api/openai_compat.py`（移除 _generate_stub_reply，改用 invoke_director_graph；_make_non_stream_response + _stream_reply_generator 支持 tool_calls。流程：持久化 user → 调用图 → 构造 tool_calls → 持久化 assistant）
- 关键设计决策：
  - langgraph==1.0.10 没有 SQLite checkpoint，开发态使用 MemorySaver， workflow.yaml 中 sqlite 配置保留供后续切换
  - Director Agent 全局兑底保证任何异常（API key 缺失/LLM 故障/JSON 解析失败）都能返回可用文本
  - intent 执行白名单（_EXECUTABLE_ACTIONS）防止 Director 误解小 intent 发起未实现的动作
- 验证：`from app.api.openai_compat import ...` + `get_main_graph()` + `ToolCallBridgeService().build_tool_calls()` 全部通过编译检查

### 第 7 组复检修复 **[完成]**

第 7 组完成后对全部代码进行了工程级复检，发现并修复以下问题：

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 复检结论：功能正确，上下游关联正常，无偏离计划方向
- 修复内容：
  - `backend/app/agents/director_agent.py`：移除未使用的 `Optional` import（文件中所有函数均未使用 Optional[…] 类型注解）
- 已知限制（v1 期不影响功能，后续任务处理）：
  - `requires_confirmation` 字段已从图返回但未显式输出到客户端响应体，Director Agent 的 message 文本将通知用户需要确认；Task 12 确认卡实现后正式接入
- 逻辑断言验证通过：白名单过滤、JSON 三层解析、Tool Call 构造、图编译 全部通过断言检查

---

### 第 7-8 组衔接：doc10 调整说明 **[分析完成]**

在第 8 组开始前，阅读并分析了 `doc10_VidMuse集成ACE-Step音乐生成模块设计.md`。

**对 Group 8 的影响**：
- `audio_analysis_versions` ORM 和 `scripts/init_schema.sql` 中新增 5 个字段（全部 nullable，不影响现有链路）：
  - `key_scale VARCHAR(16)`、`time_signature VARCHAR(8)` — 调式/拍号，ACE-Step 分析结果预留
  - `style_caption TEXT` — 风格描述，ACE-Step 生成
  - `lrc_asset_id VARCHAR(26)` — 歌词 LRC 文件 asset_id
  - `analysis_provider JSONB` — 记录各分析项实际使用的 provider（双路融合追溯）
- `audio_analysis_service.py` 接口增加 `providers: dict | None = None` 参数，为扩展阶段 1（ACE-Step 双路）预留
- WhisperX try-import 降级策略不变（ACE-Step LRC 主要针对其自生成音乐，上传音频仍用 WhisperX）
- `scripts/init_schema.sql` 数据库未执行，直接补字段，无需后续 ALTER TABLE

**扩展阶段（Group 8 完成后执行）**：
- 部署 ACE-Step API Server → 实现 `ACEStepAdapter.audio_understanding()` → 双路融合分析
- 新增 `config/providers/music_providers.yaml`

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：`scripts/init_schema.sql` 补充 5 个字段，Plan `6bbf755a` 更新

---

## 12. 第 8 组：先打通第一个真正的 AI 功能闭环，音频分析

这是真正业务主链路的第一环。

### 任务 8-01：实现音频切段工具 **[完成]**

当前为什么做：

- ProjectSpec 已经有时间区间，必须先把音频片段生成出来，后续分析都依赖它

上一步输入：

- 任务 `5-03`

本步实现：

- 按时间切段
- 生成 trimmed asset
- 存 MinIO 和本地

产出结果：

- 标准化音频片段资产

下一个使用者：

- 音频分析工具

目录与文件：

- `backend/app/tools/audio_trim_tool.py`

验收标准：

- 项目音频可按选定区间切出片段

预计代码量：

- `200 ~ 500` 行

### 任务 8-02：接入音频分析底层工具 **[完成]**

当前为什么做：

- 没有底层 beat/section/lyrics 结果，后面的 Agent 没有原料

上一步输入：

- 任务 `8-01`
- 任务 `1-06`

本步实现：

- bpm
- beat map
- section map
- lyrics alignment

产出结果：

- 原始分析结果

下一个使用者：

- AudioAnalysis 版本保存
- 音乐分析 Agent

目录与文件：

- `backend/app/tools/audio_analysis_tool.py`
- `backend/app/tools/lyrics_alignment_tool.py`

验收标准：

- 给一段音频可返回完整分析结构

预计代码量：

- `600 ~ 1500` 行

### 任务 8-03：实现 AudioAnalysis 版本保存 **[完成]**

当前为什么做：

- 原始分析不能只存在内存里，必须落库和落本地

上一步输入：

- 任务 `8-02`

本步实现：

- 写 `audio_analysis_versions`
- 写本地 JSON 快照
- 激活版本

产出结果：

- 音频分析事实进入项目记忆

下一个使用者：

- 音乐分析 Agent
- 状态机推进

目录与文件：

- `backend/app/services/audio_analysis_service.py`

验收标准：

- 音频分析结果可在数据库和本地追溯

预计代码量：

- `300 ~ 700` 行

### 任务 8-04：实现音乐分析 Agent **[完成]**

当前为什么做：

- 底层分析数据只有“数值”，真正创作用的“结构摘要”需要 Agent 解释

上一步输入：

- 任务 `8-03`
- 任务 `1-02`

本步实现：

- 输出音乐结构摘要
- 输出节奏建议

产出结果：

- 创意规划可消费的音乐语义

下一个使用者：

- 创意规划 Agent

目录与文件：

- `backend/app/agents/audio_analysis_agent.py`
- `prompts/system/audio_analysis.md`

验收标准：

- 能输出结构化音乐摘要对象

预计代码量：

- `250 ~ 600` 行

### 任务 8-05：主图接入音频分析节点 **[完成]**

当前为什么做：

- 只有把音频分析接入主图，项目主链路才真正开始跑

上一步输入：

- 任务 `7-04`
- 任务 `8-03`
- 任务 `8-04`

本步实现：

- 主图节点
- 状态推进到 `audio_analyzed`
- 发事件

产出结果：

- 第一个 AI 主链路节点可用

下一个使用者：

- 创意规划
- 前端音频分析页

目录与文件：

- `backend/app/workflows/nodes/audio_analysis_node.py`

验收标准：

- 项目能从输入推进到音频分析完成

预计代码量：

- `300 ~ 700` 行

**执行记录（8-01 ~ 8-05）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/models/audio_analysis.py`（AudioAnalysisVersion ORM，含 doc10 扩展字段）
  - `backend/migrations/versions/b3d9f2a7c1e5_audio_analysis_versions.py`
  - `backend/app/repositories/audio_analysis_repository.py`
  - `backend/app/tools/audio_trim_tool.py`（librosa + soundfile 裁切，不依赖 ffmpeg）
  - `backend/app/tools/audio_analysis_tool.py`（BPM / beat / section / energy，纯信号分析）
  - `backend/app/tools/lyrics_alignment_tool.py`（WhisperX try-import 降级）
  - `backend/app/services/audio_analysis_service.py`（落库 + 激活 + 快照 + 状态推进）
  - `backend/app/agents/audio_analysis_agent.py`（LLM 摘要 + 规则兆底）
  - `backend/app/workflows/nodes/__init__.py`
  - `backend/app/workflows/nodes/audio_analysis_node.py`（主图节点）
  - `backend/app/models/__init__.py`（+AudioAnalysisVersion 导入）
  - `backend/app/workflows/main_graph.py`（条件路由 analyze_audio → audio_analysis_node）
- 关键设计决策：
  - librosa 裁切不依赖 ffmpeg；段落检测基于 RMS 能量 + 启发式标签，LLM Agent 做语义论断
  - WhisperX try-import，未安装时返回空片段 + reason，主链路不中断
  - Agent LLM 失败时基于 BPM 规则自动兆底，不抓局不推进主链路
  - 主图添加条件路由 `_route_after_director`：`analyze_audio` → audio_analysis_node
  - doc10 扩展字段（key_scale / time_signature / style_caption / lrc_asset_id / analysis_provider）全部已建好，待 ACE-Step 接入时填入
- 编译检查：全部模块导入正常，图节点 [audio_analysis_node, director_intake, load_project_snapshot, respond_to_user] 注册正常，条件路由验证通过

### 第 8 组复棄修复 **[完成]**

第 8 组完成后对全部代码进行了工程级复棄，发现并修复以下问题：

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 复棄结论：功能正确，上下游关联正常，无偏离计划方向
- 修复内容：
  - `backend/app/services/audio_analysis_service.py`：
    1. **修复功能性 Bug** —— `_persist` 中 `advance_project` 在重新分析场景（项目已是 `audio_analyzed`）会触发非法状态转换导致分析结果无法落库；修复：层加 `if project.current_stage != AUDIO_ANALYZED` 防护
    2. `from app.storage.minio_adapter import get_storage` 居局导入移到文件顶部
  - `backend/app/tools/audio_analysis_tool.py`：移除未使用的 `from pathlib import Path` import（`from __future__ import annotations` 后类型注解不需要实际导入）
  - `backend/app/workflows/nodes/audio_analysis_node.py`：移除模块级 `AudioAnalysisAgent()` / `AudioAnalysisService()` 单例（`__init__` 调用 `get_config()`，测试时难以 mock），改为在函数内实例化（与 DirectorAgent 保持一致）
  - `backend/app/workflows/main_graph.py`：更新文件顶部 docstring 节点链路说明，反映实障条件路由逻辑

---

### 任务 8-06：建立规划相关 ORM 模型 **[新增]**

当前为什么做：

- 任务 9 的规划持久化服务需要写入 brief / style / shot plan / shots 表，必须先有 ORM 模型

上一步输入：

- 任务 `2-03`（ORM 基类）

本步实现：

- `creative_brief_versions` ORM
- `style_bible_versions` ORM
- `scene_plan_versions` ORM
- `shot_plan_versions` ORM
- `shots` ORM（含 shot_index、start_ms/end_ms、duration_ms、section_type、lyric_text、emotion、shot_type、camera_language、visual_energy、lipsync_required、character_binding、style_binding、status 全字段，对应 doc05 §11.1）

产出结果：

- 规划数据层基础设施

下一个使用者：

- 任务 9-02 / 9-03（规划持久化服务）

目录与文件：

- `backend/app/models/planning.py`（creative_brief_versions + style_bible_versions + scene_plan_versions + shot_plan_versions + shots）
- `backend/app/repositories/planning_repositories.py`（各版本表基础查询）

验收标准：

- 所有规划表 ORM 可通过 SQLAlchemy 正常映射，与 scripts/init_schema.sql 一致

预计代码量：

- `500 ~ 1000` 行

**执行记录（8-06）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/models/planning.py`（5个 ORM 类：`CreativeBriefVersion` / `StyleBibleVersion` / `ScenePlanVersion` / `ShotPlanVersion` / `Shot`；版本表继承 `ULIDMixin + CreatedAtMixin + Base`（append-only）；`Shot` 继承 `BaseModel`（含 updated_at）；Shot 含15个业务字段 + 3 个索引 + status CheckConstraint）
  - `backend/app/repositories/planning_repositories.py`（5个 Repository 类，各版本表均提供 `get_active` / `get_next_version_no` / `deactivate_all` / `get_by_id_for_project`；`ShotRepository` 额外提供 `list_by_plan` / `list_by_project` / `count_by_project`）
  - `backend/app/models/__init__.py`（新增 5 个规划模型导入和 `__all__` 注册）
- 复检修复：`ScenePlanRepository` 补充缺失的 `get_by_id_for_project` 方法（与其他 4 个版本 Repository 保持一致）
- 编译验证：5 张规划表全部注册到 `Base.metadata`，5 个 Repository 方法完整，导入正常

### 任务 8-07：实现 PendingDecision 服务 + API **[从 12-01 提前]**

当前为什么做：

- 任务 9 中风格选择 / brief 确认 / shot plan 确认均依赖选项卡和确认卡机制
- 若等到 12-01 再实现，任务 9–11 所有用户交互节点都无法正确实现
- 原 12-01 内容在此统一实现，12-01 作废

上一步输入：

- 任务 `4-01`（pending_decisions 表已建）

本步实现：

- `DecisionService`：create_decision / get_pending_decisions / submit_decision / expire_decision
- `GET /api/v1/projects/{project_id}/decisions`（查询 open 状态的待确认决策）
- `POST /api/v1/projects/{project_id}/decisions/{decision_id}/select`（提交选择）

产出结果：

- 选项卡与确认卡完整闭环，任务 9 起可用

下一个使用者：

- 任务 9-01（Director Agent 风格选项展示）
- 任务 10（storyboard 高成本确认）
- 任务 11（clip 批量生成高成本确认）

目录与文件：

- `backend/app/services/decision_service.py`
- `backend/app/api/v1/decisions.py`

验收标准：

- 创建 pending_decision → 前端可查询 → 提交选择后 status 变为 selected

预计代码量：

- `300 ~ 700` 行

**执行记录（8-07）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/models/workflow.py`（`PendingDecision` 新增 `selected_option_id VARCHAR(64) NULL` 字段，`submit_decision` 时写入用户选择结果）
  - `scripts/init_schema.sql`（`pending_decisions` 表同步补充 `selected_option_id` 字段）
  - `backend/app/repositories/decision_repository.py`（`DecisionRepository`：`list_open` / `get_by_id_for_project` / `list_by_type`）
  - `backend/app/services/decision_service.py`（`DecisionService`：`create_decision` / `get_pending_decisions` / `get_decision` / `submit_decision` / `expire_decision` / `cancel_decision`；含 `options_payload` 选项合法性校验；`has_open_decision_of_type` 幂等检查；`_decision_to_dict` 序列化帮助函数）
  - `backend/app/api/v1/decisions.py`（3 条接口：`GET /decisions` 查询 open 列表 / `GET /decisions/{id}` 查单条 / `POST /decisions/{id}/select` 提交选择；错误码：`not_found` / `invalid_status` / `invalid_option`）
  - `backend/app/main.py`（注册 `decisions_router` 到 `/api/v1`）
- 关键设计决策：
  - `selected_option_id` 新增字段而非复用 `default_option_id`，语义清晰，Director Agent 可直接读取判断用户意图
  - 选项合法性校验仅在 `options_payload` 含结构化 `id` 时生效，允许确认卡（无选项）类型的决策
  - `has_open_decision_of_type` 供 Director Agent 在 9-01 改造时做幂等检查，防止重复弹出同类选项卡
- 编译验证：`selected_option_id` 字段正确注册到 `PendingDecision.__table__.columns`；`decisions_router` 前缀 `/projects/{project_id}/decisions` 正确；全部模块导入通过

---

## 13. 第 9 组：创意规划与用户风格交互闭环（架构修正版）

**架构修正说明（2026-03-30）**：
本组基于架构审查从「一步产出全部规划产物」重构为「阶段感知驱动 + 分步用户交互」：
- Director Agent 改为主动基于项目阶段驱动，而非被动等待用户命令
- `audio_analyzed` → 主动展示音乐摘要 + 提供风格选项（通过 pending_decisions）
- 用户选定风格 → 自动生成 brief/style → 展示确认
- 用户确认 brief → 自动生成 shot plan → 展示确认
- 新增 `human_confirmation_gate` 节点：高成本操作前图执行真正暂停等待用户决策
- 新增查询 API 和工作流触发 API，前端不依赖聊天历史解析产物

### 任务 9-01：Director Agent 阶段感知改造 **[完成]**

当前为什么做：

- 当前 Director Agent 是纯命令响应型，不符合文档要求的「主动阶段驱动」架构
- 需要让 Director 根据 project_stage 主动决定下一步，而不是只解析用户说了什么

上一步输入：

- 任务 `8-04`（quality_summary 音乐摘要）
- 任务 `8-07`（PendingDecision 服务）
- 任务 `7-01`（ProjectGraphState）

本步实现：

- 重构 `prompts/system/director.md`：加入阶段优先原则和各阶段主动行为规则
  - `input_ready` → 不等用户说话，自动触发音频分析
  - `audio_analyzed` + 无风格选择 → 展示音乐摘要 + 创建风格 pending_decision
  - `brief_ready` + 未确认 → 展示 brief 摘要 + 创建确认 pending_decision
  - `shot_plan_ready` + 未确认 → 展示 shot list + 请求确认
- 修改 Director Agent `run()` 方法：stage 判断优先于 intent 解析

产出结果：

- Director Agent 具备主动驱动能力，用户不再需要手动发命令触发各阶段

下一个使用者：

- 任务 9-04（主图重构时配合阶段感知路由）

目录与文件：

- `backend/app/agents/director_agent.py`（重构）
- `prompts/system/director.md`（更新）

验收标准：

- 项目处于 `audio_analyzed` 时，用户发任意消息， Director 自动展示音乐摘要 + 风格选项卡
- 项目处于 `input_ready` 时，系统不等用户说“分析”，自动路由到音频分析

预计代码量：

- `300 ~ 600` 行（主要是 prompt 重写 + 逻辑调整）

**执行记录（9-01）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `prompts/system/director.md`（v2：加入阶段优先原则、各阶段主动行为规则、结构化 JSON 输出格式约束）
  - `backend/app/agents/director_agent.py`（阶段感知扩展变量：`quality_summary_text` / `style_direction` / `brief_confirmed` / `shot_plan_confirmed` / `open_decisions_text`）
  - `backend/app/workflows/graph_state.py`（新增快照扩展字段组）

### 任务 9-02：实现 brief + style 生成服务 **[完成]**

当前为什么做：

- 用户通过 pending_decision 选定风格方向后，系统需根据音频分析 + 风格生成 brief

上一步输入：

- 任务 `8-06`（ORM 模型）
- 任务 `8-07`（PendingDecision 服务，提供风格选择结果）
- 任务 `1-02`（Prompt Registry）

本步实现：

- `CreativePlanningAgent`（阶段一）：
  - 输入：audio_analysis.quality_summary + style_direction（来自 decision 选择结果）+ user_prompt + reference_assets
  - 输出：creative_brief + style_bible
- `BriefPersistenceService`：
  - 保存 `creative_brief_versions` + `style_bible_versions`
  - activate + 更新 `projects.active_brief_version_id` + `active_style_version_id`
  - 写本地 JSON 快照（03_brief/ + 04_style/）
  - 推进状态 → `brief_ready`

产出结果：

- brief + style 进入项目记忆，项目推进到 brief_ready

下一个使用者：

- 任务 9-03（shot plan 生成）

目录与文件：

- `backend/app/agents/creative_planning_agent.py`（阶段一）
- `backend/app/services/brief_persistence_service.py`
- `prompts/system/creative_planning.md`
- `prompts/tasks/generate_brief.md`

验收标准：

- 给定风格方向，能生成结构化 brief + style_bible，落库并激活

预计代码量：

- `500 ~ 1000` 行

**执行记录（9-02）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/agents/creative_planning_agent.py`（phase-1: `generate_brief_and_style()`；外部 prompt 加载 + 渲染；API key 缺失兆底输出）
  - `backend/app/services/brief_persistence_service.py`（`BriefPersistenceService.generate_and_save()`；两段式 UoW；落库 brief/style + 激活指针 + 本地快照 + 推进状态）
  - `prompts/system/creative_planning.md`（v2：加入 phase-1/phase-2 字段映射说明）
  - `prompts/tasks/generate_brief.md`（v2：强调 palette 必须为 JSON 对象）

### 任务 9-03：实现 shot plan 生成服务 **[完成]**

当前为什么做：

- 用户确认 brief 后，系统根据 brief + audio_analysis 生成 shot 列表

上一步输入：

- 任务 `9-02`（brief/style 已有）
- 任务 `8-06`（shots ORM）

本步实现：

- `CreativePlanningAgent`（阶段二）：
  - 输入：creative_brief + style_bible + audio_analysis（beat/section 数据）
  - 输出：scene_plan + shot_plan（含每个 shot 的 ShotSemanticSpec）
- `ShotPlanPersistenceService`：
  - 保存 `scene_plan_versions` + `shot_plan_versions`
  - 展开每个 shot → 写入 `shots` 表（全字段含 start_ms/end_ms/lipsync_required 等）
  - 写本地 JSON 快照（05_shot_plan/）
  - 推进状态 → `shot_plan_ready`

产出结果：

- shot plan 进入项目记忆，shots 表每行一个镜头，项目推进到 shot_plan_ready

下一个使用者：

- 任务 10-01（Prompt 编译服务）

目录与文件：

- `backend/app/agents/creative_planning_agent.py`（阶段二）
- `backend/app/services/shot_plan_persistence_service.py`
- `backend/app/repositories/shot_repository.py`
- `prompts/tasks/generate_shot_plan.md`

验收标准：

- 给定 brief，能生成结构化 shot list 并落库，shots 表每行对应一个镜头

预计代码量：

- `500 ~ 1000` 行

**执行记录（9-03）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/agents/creative_planning_agent.py`（phase-2: `generate_shot_plan()`；LLM 失败返回空列表降级而非抛异常）
  - `backend/app/services/shot_plan_persistence_service.py`（字段映射 `_map_shot_fields()`；展开 shots 表批量写入；本地快照包含 ShotSemanticSpec）
  - `backend/app/repositories/planning_repositories.py`（`ShotRepository` 已包含，无需新建）
  - `prompts/tasks/generate_shot_plan.md`（v1：完整字段映射说明 + 约束参数）

**复检修复记录（9-03）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-03
- 修复内容：
  - `backend/app/models/planning.py`（Shot 表新增 `subject TEXT` + `location TEXT` 列）
  - `scripts/init_schema.sql`（shots 表同步加列）
  - `backend/app/services/shot_plan_persistence_service.py`（`_map_shot_fields` 提取 subject/location 写入 Shot）
  - `backend/app/agents/creative_planning_agent.py`（`run_phase2` task_msg 补全必填字段 + `emotion_intensity` 必须来自 emotion_arc 约束）
  - `prompts/system/creative_planning.md`（Phase-2 必填字段列表补全：scene_id/subject/location/emotion_intensity/lyric_text/visual_energy）

### 任务 9-04：主图重构 + human_confirmation_gate 节点 **[完成]**

当前为什么做：

- 主图当前是「命令解析 → 路由」模式，需要改为「阶段感知 + 高成本操作等待」模式
- 风格选择、brief 确认、shot plan 确认都需要图真正暂停等待用户

上一步输入：

- 任务 `9-01` / `9-02` / `9-03`
- 任务 `8-07`（PendingDecision 服务）

本步实现：

- 新增 `human_confirmation_gate` 节点：
  - 当 `requires_confirmation = true` 时，图暂停执行
  - 将 pending_decision ID 写入 GraphState，返回用户消息
  - 用户通过 decisions API 提交选择后，由工作流触发 API 重新唤醒图继续执行
- 重构 `_route_after_director` 为阶段感知路由：
  - `input_ready` → `audio_analysis_node`（不等用户命令）
  - `audio_analyzed` + 无 style_direction → `human_confirmation_gate`（风格选项）
  - `audio_analyzed` + 有 style_direction → `generate_brief_node`
  - `brief_ready` + 待确认 → `human_confirmation_gate`（brief 确认）
  - `brief_ready` + 已确认 → `generate_shot_plan_node`
  - `shot_plan_ready` + 待确认 → `human_confirmation_gate`（shot list 确认）
- `graph_state.py` 新增字段：style_direction / brief_confirmed / shot_plan_confirmed

产出结果：

- 主图具备阶段感知能力，高成本操作有真正的等待机制

目录与文件：

- `backend/app/workflows/main_graph.py`（重构）
- `backend/app/workflows/nodes/creative_planning_node.py`
- `backend/app/workflows/graph_state.py`（新增字段）

验收标准：

- `input_ready` → 用户发任意消息 → 自动触发音频分析
- `audio_analyzed` → 系统主动给出风格选项卡，图等待 decision
- `requires_confirmation=true` 时图确实暂停，decision 提交后继续执行

预计代码量：

- `500 ~ 1000` 行

**执行记录（9-04）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/workflows/main_graph.py`（v2 阶段感知版：`load_project_snapshot` 扩展决策读取；`_route_after_snapshot` 预路由；`_route_after_director` 阶段备用路由）
  - `backend/app/workflows/nodes/creative_planning_node.py`（`generate_brief_node` + `generate_shot_plan_node`）
  - `backend/app/workflows/nodes/human_confirmation_gate.py`（幂等创建决策；默认风格选项 / confirm 选项；阶段备用路由）
  - `backend/app/workflows/graph_state.py`（新增 `quality_summary` / `open_decisions` / `selected_decisions` / `style_direction` / `brief_confirmed` / `shot_plan_confirmed` / `pending_decision_id`）

### 任务 9-05：规划产物查询 API + 工作流触发 API **[完成]**

当前为什么做：

- 前端工作台各阶段展示需要 REST 接口获取结构化产物
- 前端 Pipeline 每个节点的「触发」按鈕需要对应的控制面 API

上一步输入：

- 任务 `9-02` / `9-03`

本步实现：

- 产物查询接口：
  - `GET /api/v1/projects/{id}/audio-analysis/active`
  - `GET /api/v1/projects/{id}/brief/active`
  - `GET /api/v1/projects/{id}/style/active`
  - `GET /api/v1/projects/{id}/shots`（列表 + 分页）
  - `GET /api/v1/projects/{id}/shots/{shot_id}`
- 工作流触发接口：
  - `POST /api/v1/projects/{id}/workflow/analyze-audio`
  - `POST /api/v1/projects/{id}/workflow/generate-brief`
  - `POST /api/v1/projects/{id}/workflow/generate-shot-plan`

产出结果：

- 前端可直接读取音频分析、brief、shot 数据，不依赖聊天历史解析

下一个使用者：

- 任务 9-06（前端页面）

目录与文件：

- `backend/app/api/v1/audio_analysis.py`
- `backend/app/api/v1/planning.py`（brief + style）
- `backend/app/api/v1/shots.py`
- `backend/app/api/v1/workflow.py`

验收标准：

- GET /brief/active 返回当前激活的 brief 内容
- POST /workflow/generate-brief 触发生成并返回状态

预计代码量：

- `400 ~ 900` 行

**执行记录（9-05）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/api/v1/audio_analysis.py`（`GET /audio-analysis/active`）
  - `backend/app/api/v1/planning.py`（`GET /brief/active` + `GET /style/active`）
  - `backend/app/api/v1/shots.py`（`GET /shots` 分页 + `GET /shots/{id}`；`status` 过滤参数）
  - `backend/app/api/v1/workflow.py`（`POST /workflow/analyze-audio` / `generate-brief` / `generate-shot-plan`；`generate-brief` 前置校验 `select_style_direction` 决策；`generate-shot-plan` 前置校验 `confirm_brief` 决策 + 防止 regenerate 项续行）
  - `backend/app/main.py`（注册 4 个新路由器）

### 任务 9-06：实现前端音频分析页 / brief 页 / shot plan 页

当前为什么做：

- 后端规划产物和查询 API 已就绪，前端工作台中间区域可以正式展示

上一步输入：

- 任务 `9-05`（产物查询 API）
- 任务 `8-07`（decisions API）

本步实现：

- 音频分析视图：BPM / 段落 / 歌词展示
- brief 视图：brief 内容 + 确认按鈕（通过 decisions API）
- shot plan 视图：shot 卡片列表 + 时长/情绪/lipsync 标记
- 风格选项卡组件 `OptionCard`：渲染 pending_decision 的 options_payload 为可点击卡片
- 确认卡组件 `ConfirmationCard`：展示影响范围 + 确认/取消按鈕

产出结果：

- 前端第一次能完整展示 AI 规划链路，用户可通过点选而非打字完成关键决策

下一个使用者：

- 任务 10（storyboard 阶段）

目录与文件：

- `frontend/src/components/audio/*`
- `frontend/src/components/brief/*`
- `frontend/src/components/shots/*`
- `frontend/src/components/chat/OptionCard.tsx`
- `frontend/src/components/chat/ConfirmationCard.tsx`

验收标准：

- 工作台中间区域能展示 BPM、brief 内容、shot 列表
- 聊天区能渲染风格选项卡，用户点击即提交 decision

预计代码量：

- `900 ~ 2000` 行

---

## 14. 第 10 组：先把 Prompt 编译和 storyboard 做出来

因为这是从“语义”走向“视觉”的第一步。

**架构修正说明（2026-03-30）**：
本组在任务 10-03（Storyboard 服务）完成后、任务 10-04（主图接入 storyboard 节点）必须依照任务 9 的模式：
- storyboard 生成是高成本操作，必须通过 `human_confirmation_gate` 展示预计成本 + 等待用户确认后再执行
- 需配套 storyboard 产物查询 API：`GET /api/v1/projects/{id}/storyboard/active`、`GET .../storyboard-frames`
- 需配套工作流触发 API：`POST /api/v1/projects/{id}/workflow/generate-storyboard`

### 任务 10-01：实现 Prompt 编译服务 **[完成]**

当前为什么做：

- 现在已经有 `ShotSemanticSpec`，终于到了把语义编译成 prompt 的时机

上一步输入：

- 任务 `1-02`
- 任务 `1-06`
- 任务 `9-02`

本步实现：

- 从 brief/style/shot/refs 生成 `PromptBundle`
- 写本地 bundle 快照

产出结果：

- provider 无关的统一 prompt bundle

下一个使用者：

- 图片 provider
- 视频 provider

目录与文件：

- `backend/app/services/prompt_compiler_service.py`
- `prompts/compiler/*.md`

验收标准：

- 给一个 shot 能稳定生成一份 `PromptBundle`

预计代码量：

- `400 ~ 900` 行

**执行记录（10-01）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/models/prompt_bundle.py`（PromptBundleModel ORM，append-only，含溯源字段）
  - `backend/app/repositories/prompt_bundle_repository.py`（get_latest_for_target / list_for_project）
  - `backend/app/services/prompt_compiler_service.py`（compile_for_shot()：读 Shot+brief+style → 渲染 compile_image_prompt.md → LLM → 三层解析兜底 → 落库 + 本地快照）
  - `backend/app/models/__init__.py`（+PromptBundleModel）
- 关键设计：LLM 失败时规则兜底（取 style_direction + emotion 直接拼 prompt），保证 storyboard 流程不被 LLM 故障阻断

**复检修复记录（10-01）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-03
- 修复内容：
  - `backend/app/services/prompt_compiler_service.py`（`_shot_to_spec_text` 加 subject/location；新增 `_build_character_set_text` 函数从 CharacterSetVersion 构建角色外貌/造型描述；`compile_for_shot` 步骤 2.5 加载 active CharacterSetVersion 并传入 `_call_llm`；`character_set` 变量不再硬编码为空字符串）

**提示词优化批次执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-03
- 产出：
  - `prompts/compiler/compile_image_prompt.md`（v2→v3：中文化输出；删除英文映射词典；增加 txt2img/img2img 场景自动分支；路径 B 明确三张参考图权重分工，不重复描述参考图已展示的内容）
  - `prompts/system/visual_development.md`（v1.0→v2.0：增加场景 A/B/C 显式决策树；场景 C 不描述面部，场景 A 完整描述，场景 B 基于图片分析推断意图；中文 prompt 输出）
  - `backend/app/services/prompt_compiler_service.py`（`_make_fallback_bundle` 兜底 prompt 改中文拼接，默认景别/运镜改中文）
  - `prompts/tasks/generate_brief.md`（v2→v3：增加 narrative_mode 4 条判断标准；增加 section_outline 字段（段落级叙事概述）；performance_ratio 推导依据说明）
  - `prompts/system/creative_planning.md`（补充 narrative_mode 4 条判断规则；performance_ratio 必须基于音频分析推导）
  - `prompts/tasks/omni_costume_derivation.md`（v1→v2：generation_prompt 明确中文输出；增加风格圣经色调/质感对齐约束）
  - `prompts/compiler/compile_video_prompt.md`（中文优先；运动词汇保留英文或中英均可）

**角色优化记录（10-01）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-04
- 修改内容：
  - `prompts/compiler/compile_video_prompt.md`（v2→v3：角色帧从「编译器」重写为「MV 视觉执行导演/聚合者」；明确 5 层全部来源于输入数据，不虚构；第 4 层运动语言提升为核心层并强化「4 维度必填」约束；emotion_intensity 新增 very_high→0.9 映射；负向词全面中文化；删除原英文运动示例说明段落，替换为结构化示例格式说明；参数说明补充 very_high 强度映射）

### 任务 10-02：实现图片 provider 适配器与图片工具 **[完成]**

当前为什么做：

- storyboard 是第一批视觉产物，先从图片开始风险最低

上一步输入：

- 任务 `10-01`
- 任务 `1-06`

本步实现：

- 图片 provider adapter
- 图片生成 tool

产出结果：

- 图片生成能力

下一个使用者：

- storyboard 服务

目录与文件：

- `backend/app/providers/image/*`
- `backend/app/tools/image_generation_tool.py`

验收标准：

- `PromptBundle` 可生成图片

预计代码量：

- `500 ~ 1200` 行

**执行记录（10-02）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `config/base/external_apis.yaml`（FAL.ai 凭据配置文件，api_key/base_url 直接填写，不依赖 os.getenv）
  - `backend/app/core/config_loader.py`（+FalAIConfig / ExternalApisConfig / load_external_apis_config()）
  - `backend/app/core/config.py`（VidMuseConfig +external_apis 字段）
  - `backend/app/providers/image/base.py`（ImageResult dataclass + ImageProviderAdapter Protocol + get_image_provider() 工厂）
  - `backend/app/providers/image/fal_adapter.py`（FalAIAdapter：api_key 全从 get_config().external_apis.fal_ai 读取；flux_schnell 同步/flux_dev 轮询；aspect_ratio 自动映射）
  - `backend/app/providers/image/__init__.py`
  - `backend/app/tools/image_generation_tool.py`（generate_for_bundle()：生成→下载→MinIO→Asset 落库→本地副本）
- 关键设计：绝无 os.getenv() 直接用于 API key，全部通过 config 系统

### 任务 10-03：实现 Storyboard 服务 **[完成]**

当前为什么做：

- 已经有 shot 和图片能力，可以形成第一版 storyboard

上一步输入：

- 任务 `10-02`

本步实现：

- 生成 storyboard frames
- 保存 `storyboard_versions`
- 保存 `storyboard_frames`

产出结果：

- storyboard 成为正式项目产物

下一个使用者：

- 视频生成
- 前端 storyboard 页

目录与文件：

- `backend/app/services/storyboard_service.py`

验收标准：

- 项目可生成 storyboard 并落库、本地、MinIO

预计代码量：

- `400 ~ 1000` 行

**执行记录（10-03）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/models/storyboard.py`（StoryboardVersion + StoryboardFrame ORM，均 append-only）
  - `backend/app/repositories/storyboard_repositories.py`（StoryboardVersionRepository + StoryboardFrameRepository）
  - `backend/app/services/storyboard_service.py`（generate_and_save()：逐 shot 串行处理；单 shot 失败不终止整体；_persist() 统一落库+状态推进）
  - `backend/app/api/v1/storyboard.py`（GET /storyboard/active + GET /storyboard-frames）
  - `backend/app/api/v1/workflow.py`（+POST /workflow/generate-storyboard，前置校验 confirm_shot_plan 决策）
  - `backend/app/models/__init__.py` + `main.py`（storyboard 模型注册 + storyboard_router 挂载）
- 验证：全部 11 个新文件语法检查通过（py_compile）

### 任务 10-04：主图接入 storyboard 节点 **[完成]**

当前为什么做：

- 项目主链路需要推进到 `storyboard_ready`

上一步输入：

- 任务 `10-03`

本步实现：

- 将 storyboard 生成纳入主图

产出结果：

- 主链路推进到 storyboard 阶段

下一个使用者：

- clip 生成

目录与文件：

- `backend/app/workflows/nodes/storyboard_node.py`

验收标准：

- 项目能推进到 `storyboard_ready`

预计代码量：

- `250 ~ 600` 行

**执行记录（10-04）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：
  - `backend/app/workflows/nodes/storyboard_node.py`（新建：调用 StoryboardService.generate_and_save()，业务/意外异常均降级为错误消息）
  - `backend/app/workflows/main_graph.py`（v3：注册 storyboard_node；`_ACTION_NODE_MAP` +`generate_storyboard`；`_route_after_director` +`shot_plan_ready+confirmed→storyboard_node` 阶段兜底；补边 storyboard_node→respond_to_user；更新链路注释到2 v3）
  - `prompts/system/director.md`（v3：shot_plan_ready 已确认分支由 explain 改为 execute + generate_storyboard）
- 验证：AST 解析通过，关键字断言通过，图编译逻辑正确

### 任务 10-05

当前为什么做：

- 现在 storyboard 已存在，用户需要能看到视觉中间产物

上一步输入：

- 任务 `10-04`

本步实现：

- storyboard 网格
- frame 查看
- 基础状态显示

产出结果：

- 前端可视化 storyboard

下一个使用者：

- clip 阶段

目录与文件：

- `frontend/src/components/storyboard/*`

验收标准：

- 用户能查看各 shot 的 storyboard frame

预计代码量：

- `400 ~ 900` 行

---

## 15. 第 11 组：把 clip、timeline、export 主闭环做出来

这组做完，MVP 的主闭环就成立了。

### 任务 11-01：实现视频 provider 适配器 **[完成]**

当前为什么做：

- storyboard 只是静态视觉，下一步必须进入视频阶段

上一步输入：

- 任务 `10-01`
- 任务 `1-06`

本步实现：

- 视频 provider adapter
- 文生视频 / 图生视频统一接口

产出结果：

- 视频生成能力

下一个使用者：

- clip 服务

目录与文件：

- `backend/app/providers/video/*`
- `backend/app/tools/video_generation_tool.py`

验收标准：

- `PromptBundle` 可生成 clip

预计代码量：

- `600 ~ 1400` 行

### 任务 11-02：实现成本估算服务 **[完成]**

当前为什么做：

- 到 storyboard 和 clip 阶段，确认卡和账本都必须拿到真实估算

上一步输入：

- 任务 `1-06`
- 任务 `4-01`

本步实现：

- 基于 provider profile 和 billing config 估算成本

产出结果：

- 可展示的 credits 估算值

下一个使用者：

- 决策卡
- credits 服务

目录与文件：

- `backend/app/services/cost_estimation_service.py`

验收标准：

- 能对 storyboard / clip / export 给出估算

预计代码量：

- `250 ~ 700` 行

### 任务 11-03：实现 credits 服务 **[完成]**

当前为什么做：

- 高成本动作没有预占/提交/回滚，就不是真实可控系统

上一步输入：

- 任务 `11-02`
- 任务 `4-01`

本步实现：

- grant
- reserve
- commit
- refund

产出结果：

- 成本闭环

下一个使用者：

- storyboard
- clip
- export

目录与文件：

- `backend/app/services/credit_service.py`

验收标准：

- 高成本动作执行前后账本能正确变化

预计代码量：

- `300 ~ 800` 行

### 任务 11-04：实现 Clip 服务 **[完成]**

当前为什么做：

- 已有视频生成能力和 storyboard，clip 现在可以成为正式版本产物

上一步输入：

- 任务 `11-01`
- 任务 `11-03`

本步实现：

- 调视频工具
- 保存 clip 版本
- 更新 active clip

产出结果：

- 每个 shot 有正式 clip

下一个使用者：

- timeline composer
- 前端 clip 页

目录与文件：

- `backend/app/services/clip_service.py`

验收标准：

- 某个 shot 可生成 clip 并版本化保存

预计代码量：

- `350 ~ 800` 行

**架构补充修复记录（11-04）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-03
- 问题：`ClipService` 串行逐 shot 生成 clip，但每个 clip 完成后没有发事件。前端只能等所有 clip 全部完成后收到 `clips_ready` 阶段事件，无法实时感知单个 clip 就绪，导致前端时间轴无法逐渐填充
- 修复：在 `_process_single_shot()` 落库成功后新增 SSE 事件 `clip.shot.completed`，携带 `shot_id / shot_index / start_ms / end_ms / duration_ms / storage_uri / clip_version_id`。用 `try/except` 包裹，SSE 失败不阻断主流程
- 前端收到此事件后可直接用 `storage_uri` 将 clip 填入时间轴对应位置，无需额外调用 API

### 任务 11-05：主图接入 clip 节点 **[完成]**

当前为什么做：

- 项目必须能从 storyboard 推进到 clips

上一步输入：

- 任务 `11-04`

本步实现：

- 批量生成 clip
- 推进项目状态

产出结果：

- `clips_ready`

下一个使用者：

- timeline

目录与文件：

- `backend/app/workflows/nodes/clip_node.py`

验收标准：

- 项目可推进到 `clips_ready`

预计代码量：

- `250 ~ 600` 行

### 任务 11-06：实现时间线合成服务 **[完成]**

当前为什么做：

- clip 已经有了，现在要把成片拼出来

上一步输入：

- 任务 `11-04`

本步实现：

- timeline payload
- timeline version
- preview 合成

产出结果：

- 可预览时间线

下一个使用者：

- export
- 前端 timeline 页

目录与文件：

- `backend/app/services/timeline_composer_service.py`
- `backend/app/tools/ffmpeg_timeline_tool.py`

验收标准：

- 一组 clip 可合成为 timeline preview

预计代码量：

- `500 ~ 1200` 行

**架构补充修复记录（11-06 / 11-07）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-03
- **架构方向纠正：拼接位置明确分工**

  原执行记录中将 ffmpeg 拼接定位为「编辑预览」，实际上是多余的。正确架构如下：

  | 阶段 | 拼接方式 | 执行位置 |
  |------|---------|-----------|
  | 编辑预览 | 虚拟调度（音频时钟 + clip src 切换） | **前端** |
  | 最终导出 | ffmpeg concat + mux | **后端** |

  前端时间轴编辑器以音频播放器为主时钟，按 `start_ms/end_ms` 逐个切换 `<video>` 的 `src`，实现虚拟拼接预览，**全程不需要后端就可看到滚动预览效果**。ffmpeg 只应在用户主动触发导出时才运行。

- **新增：用户主动触发时间线合成接口**

  `POST /workflow/generate-timeline`（旧）：Director AI 对话流中内部触发，同步执行，依然保留

  `POST /api/v1/projects/{id}/timeline/compose`（**新**）：前端「合成完整视频」按鈕直接调用，异步 dispatch 到 Worker，完成后由 SSE `project_timeline_ready` 通知。列表：

  - 前置校验：`clips_ready` 或 `timeline_ready` 阶段
  - 平等进入 Worker 队列，已有任务运行时返回 `is_new=false`
  - 文件：`backend/app/api/v1/timeline.py`（+84行）

- **两种产物永久保留，互不覆盖：**
  - 分片产物：每个 shot 独立 clip，存 `clip_versions` 表 + MinIO `08_clips/`
  - 合成产物：ffmpeg 拼接后完整 mp4，存 `timeline_versions` 表 + MinIO `timeline_preview/`

### 任务 11-07：主图接入 timeline 节点 **[完成]**

当前为什么做：

- 主链路要推进到 `timeline_ready`

上一步输入：

- 任务 `11-06`

本步实现：

- 生成 timeline
- 推进状态

产出结果：

- timeline 阶段可用

下一个使用者：

- export
- 前端 timeline 页

目录与文件：

- `backend/app/workflows/nodes/timeline_node.py`

验收标准：

- 项目可推进到 `timeline_ready`

预计代码量：

- `250 ~ 600` 行

> 备注：`timeline_node`（主图内）对应 Director AI 对话流中自动触发的路径。用户主动点按的路径已改为 `POST /timeline/compose`（任务 11-06 架构补充修复记录）。

### 任务 11-08：实现 export 服务与 API **[完成]**

当前为什么做：

- 只有导出成功，主闭环才算真的成立

上一步输入：

- 任务 `11-06`
- 任务 `11-03`

本步实现：

- export version
- export 文件写入
- export API

产出结果：

- 最终导出能力

下一个使用者：

- 前端导出页

目录与文件：

- `backend/app/services/export_service.py`
- `backend/app/api/exports.py`

验收标准：

- 项目可导出预览版和正式版

预计代码量：

- `400 ~ 900` 行

**执行记录（11-01 ~ 11-08）**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 分 5 个批次完成，所有新建文件均通过语法验证
- 关键产出：
  - `providers/video/base.py + kling_adapter.py`（Kling JWT+轮询，复用 python-jose）
  - `tools/video_generation_tool.py`
  - `services/cost_estimation_service.py + credit_service.py`（grant/reserve/commit/refund）
  - `models/clip.py + repositories/clip_repository.py + services/clip_service.py`
  - `workflows/nodes/clip_node.py + timeline_node.py`
  - `models/timeline.py + timeline_repository.py`
  - `tools/ffmpeg_timeline_tool.py`（ffmpeg 不可用明确报错）
  - `services/timeline_composer_service.py + export_service.py`
  - `models/export.py + repositories/export_repository.py`
  - `api/v1/clips.py + timeline.py + exports.py`
  - `api/v1/workflow.py`（+generate-clips/generate-timeline）
  - `main_graph.py`（v6：完整主链路 storyboard→clip→timeline）
  - `prompts/system/director.md`（v4：storyboard_ready 自动输出 generate_clips）

### 第 11 组复检修复 **[完成]**

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 共发现 12 个问题，全部修复，所有文件通过语法验证
- 修复内容：
  - **[Bug1]本地文件命名不匹配**：`video_generation_tool.py` 保存 `clip_{asset_id}.mp4`；`timeline_composer_service.py` 查找时改用 `clip_{asset.id}*` 匹配
  - **[Bug2]ClipVersion.duration_ms 用实际时长**：`video_generation_tool.py` 返回 `(asset_id, duration_ms)` tuple；`clip_service.py` 拆包并优先使用 provider 返回的实际时长
  - **[Bug3]Clip 生成确认门控**：`graph_state.py` 加 `storyboard_confirmed`；`human_confirmation_gate.py` 加 `confirm_storyboard` 映射；`main_graph.py` v7 加路由判断；`workflow.py` `generate-clips` 加 `_require_selected_decision('confirm_storyboard')`
  - **[Bug4]API 安全**：`clips.py` + `timeline.py` 所有接口加项目归属校验
  - **[Bug5]CreditService 接入**：`clip_service.py` + `export_service.py` 均接入 reserve/commit/refund 流程
  - **[Bug5]ffmpeg 方法重构**：`ffmpeg_timeline_tool.py` 新增公共方法 `transcode_to_resolution()`；export 移除内嵌 import
  - **[Bug6]commit/refund 幂等性**：`credit_repository.py` 新增 `get_reservation_any_status()`；`credit_service.py` commit/refund 加已处理状态判断
  - **[Bug7]类型提示修复**：`export_service.py` `_get_preview_path`/`_persist` 第 string `object` 改为 `Asset` / `Any`
  - **[Bug8]内嵌 import 移除**：`export_service.py` `_transcode` 方法内 import 全部移到文件顶部
  - **[Bug9]JWT 轮询刷新**：`kling_adapter.py` 轮询期间超过 1500s 自动刷新 token
  - **[Bug10]未使用变量**：`timeline_composer_service.py` `_collect_clip_paths` 移除 `shot_index = 0`
  - **[Bug11]大文件内存**：`timeline_composer_service.py` + `export_service.py` 均改用 `stat().st_size` + `async_upload_file()`
  - **[Bug12]轮询错误日志**：`kling_adapter.py` `except RequestError` 改为输出 warning 日志

### 任务 11-09：实现前端 clip / timeline / export 页

当前为什么做：

- 后端主闭环已成，前端必须完整展现结果

上一步输入：

- 任务 `11-05`
- 任务 `11-07`
- 任务 `11-08`

本步实现：

- clip 列表
- timeline 视图
- export 面板

产出结果：

- MVP 的主流程界面完整

下一个使用者：

- 局部返工

目录与文件：

- `frontend/src/components/clips/*`
- `frontend/src/components/timeline/*`
- `frontend/src/components/export/*`

验收标准：

- 用户能从工作台看到 clip、preview、export

预计代码量：

- `800 ~ 1800` 行

---

## 16. 第 12 组：把返工和回退做出来

这组做完，系统才真正从“生成器”变成“工作流工具”。

### 任务 12-01：~~实现 pending decision API~~ **[已移至任务 8-07]**

**调整说明（2026-03-30）**：本任务已提前至任务 `8-07` 实现。
原因：任务 9 起所有用户交互节点（风格选择 / brief 确认 / shot plan 确认）均依赖 pending_decisions 机制，
如等到本任务再实现会导致任务 9–11 无法正确运行。请直接查看任务 `8-07` 实现记录。

### 任务 12-02：实现 shot patch 服务 **[完成]**

当前为什么做：

- 局部返工的第一步不是重生成，而是先把用户修改转成结构化 patch

上一步输入：

- 任务 `9-02`
- 任务 `4-03`

本步实现：

- 修改 `ShotSemanticSpec`
- 标记相关对象 stale

产出结果：

- 局部语义修改能力

下一个使用者：

- prompt 重编译

目录与文件：

- `backend/app/services/shot_patch_service.py`
- `backend/app/api/shots.py`

验收标准：

- 单个 shot 可被结构化修改

预计代码量：

- `300 ~ 800` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：`services/shot_patch_service.py`（白名单字段校验 + SINGLE_SHOT_CHANGED stale 传播），`api/v1/shots.py`（+PATCH 接口）

### 任务 12-03：实现单镜头重编译与重生成 **[完成]**

当前为什么做：

- patch 之后必须形成真正的返工闭环

上一步输入：

- 任务 `12-02`
- 任务 `10-01`
- 任务 `11-04`

本步实现：

- 重编译 prompt bundle
- 重生成 clip
- 替换 timeline segment

产出结果：

- 单镜头返工能力

下一个使用者：

- 前端局部返工 UI

目录与文件：

- `backend/app/services/shot_regeneration_service.py`

验收标准：

- 改一个 shot 后能看到 timeline 局部更新

预计代码量：

- `400 ~ 1000` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：`services/shot_regeneration_service.py`（复用 PromptCompiler+VideoTool， Timeline segment 更新， credits 两阶退款保护），`api/v1/shots.py`（+POST regenerate 接口），`repositories/timeline_repository.py`（+get_by_shot）

### 任务 12-04：实现版本切换服务 **[完成]**

当前为什么做：

- 返工之后，用户还需要能回到旧版本，这才叫工作流工具

上一步输入：

- 任务 `4-03`
- 各版本表已存在

本步实现：

- 查询版本
- 切换 active version
- 标记下游 stale

产出结果：

- 回退机制

下一个使用者：

- 前端版本面板

目录与文件：

- `backend/app/services/version_switch_service.py`
- `backend/app/api/versions.py`

验收标准：

- brief/style/storyboard/timeline 可切版本

预计代码量：

- `350 ~ 900` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-30
- 产出：`services/version_switch_service.py`（brief/style/storyboard/timeline 四类切换，各自 stale 传播这符合 doc04 失效矩阵），`api/v1/versions.py`（GET版本列表 + POST activate），`domain/states.py`（+export_ready/timeline_ready 回退路径），`main.py`（注册 versions_router）

### 任务 12-05：实现前端确认卡、返工、版本切换 UI

当前为什么做：

- 后端返工闭环已经成立，现在前端要把它真正用起来

上一步输入：

- 任务 `12-01`
- 任务 `12-03`
- 任务 `12-04`

本步实现：

- 确认卡
- 选项卡
- 版本面板
- shot 局部操作

产出结果：

- 用户真正能做多轮修改

下一个使用者：

- 一致性质检

目录与文件：

- `frontend/src/components/chat/*`
- `frontend/src/components/shots/*`
- `frontend/src/components/common/version-panel/*`

验收标准：

- 用户可以确认动作、修改单个 shot、切换版本

预计代码量：

- `700 ~ 1600` 行

---

## 17. 第 13 组：增强能力

这组不阻塞 MVP 主闭环，但会提高产品完成度。

### 任务 13-01：实现一致性质检 Agent **[完成]**

当前为什么做：

- 主闭环已经成立，现在该补“看起来像专业工具”的质量能力

上一步输入：

- storyboard
- clips
- style
- character set

本步实现：

- 角色漂移检测
- 风格漂移检测
- 问题清单和修复建议

产出结果：

- 质检报告

下一个使用者：

- 前端问题面板

目录与文件：

- `backend/app/agents/consistency_guardian_agent.py`

验收标准：

- 可对项目产物输出结构化问题列表

预计代码量：

- `300 ~ 800` 行

### 任务 13-02：实现前端质检展示

当前为什么做：

- 质检必须被用户看见，否则没有产品价值

上一步输入：

- 任务 `13-01`

本步实现：

- 问题列表
- 建议动作入口

产出结果：

- 质量反馈面板

下一个使用者：

- lipsync 或更细质量提升

目录与文件：

- `frontend/src/components/common/quality-panel/*`

验收标准：

- 用户可查看一致性问题和建议

预计代码量：

- `250 ~ 700` 行

### 任务 13-03：实现 lipsync provider 适配器 **[完成]**

当前为什么做：

- 主闭环已有，现在可以做高价值但不阻塞主链路的增强

上一步输入：

- 任务 `1-06`
- 任务 `10-01`

本步实现：

- lipsync provider adapter
- lipsync tool

产出结果：

- 口型生成能力

下一个使用者：

- 单镜头 lipsync 流程

目录与文件：

- `backend/app/providers/lipsync/*`
- `backend/app/tools/lipsync_tool.py`

验收标准：

- 可对指定输入生成 lipsync clip

预计代码量：

- `400 ~ 1000` 行

### 任务 13-04：实现单镜头 lipsync 流程 **[完成]**

当前为什么做：

- provider 已接好，才能把 lipsync 真正挂到项目流程里

上一步输入：

- 任务 `13-03`
- 任务 `12-03`

本步实现：

- 指定 shot 生成 lipsync clip
- 替换 timeline segment

产出结果：

- 局部演唱镜头增强能力

下一个使用者：

- 后续产品增强

目录与文件：

- `backend/app/services/lipsync_service.py`
- 对应 API

验收标准：

- 指定 shot 可切换为 lipsync 版本

预计代码量：

- `350 ~ 900` 行

---

## 17.1 doc11 批次1：叙事剧本层 + 视觉资产类型 + 新阶段状态机 **[完成]**

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-31
- 产出：
  - `app/domain/states.py`（新增 `NARRATIVE_READY` / `VISUAL_BIBLE_READY` 枚举 + 迁移表 + `NARRATIVE_CHANGED` / `VISUAL_BIBLE_CHANGED` StaleScope）
  - `app/models/asset.py`（扩展 `_ASSET_TYPE_VALUES`：+character_reference/scene_reference/prop_reference）
  - `app/models/project.py`（扩展 `_STAGE_VALUES` + 新增 `active_narrative_script_version_id` 字段）
  - `app/models/visual_bible.py`（**新建**：`CharacterSetVersion` + `NarrativeScriptVersion` ORM）
  - `app/models/__init__.py`（导出两个新 ORM 类）
  - `app/repositories/visual_bible_repository.py`（**新建**：两个 Repository，各提供 get_active/get_next_version_no/deactivate_all/get_by_id_for_project）
  - `app/schemas/project.py`（`ActiveVersions` 新增 `narrative_script` 字段）
  - `app/agents/narrative_script_agent.py`（**新建**：NarrativeScriptAgent + _safe_parse_json + 规则兆底）
  - `app/services/narrative_script_service.py`（**新建**：生成+落库+激活+推进状态）
  - `app/workflows/nodes/narrative_node.py`（**新建**：LangGraph 节点）
  - `app/workflows/graph_state.py`（新增 `narrative_confirmed` / `visual_bible_confirmed` 字段）
  - `app/workflows/main_graph.py`（注册 narrative_node + 新路由逻辑，读取两个新决策类型）
  - `app/api/v1/narrative.py`（**新建**：GET /narrative/active + POST /workflow/generate-narrative）
  - `app/main.py`（注册 narrative_router）
  - `prompts/system/narrative_script.md`（**新建**）
  - `prompts/tasks/generate_narrative_script.md`（**新建**）
  - `scripts/init_schema.sql`（新增 `narrative_script_versions` 表 + `active_narrative_script_version_id` 字段 + 更新两处 CHECK 约束）

---

## 17.2 doc11 批次2：VisualDevelopmentAgent + img2img + VisualBibleService + Director 多模态 **[完成]**

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-31
- 产出：
  - `prompts/system/visual_development.md`（**新建**：VisualDevelopmentAgent 系统提示词）
  - `app/providers/image/base.py`（扩展 `ImageProviderAdapter` Protocol：新增 `generate_img2img()` 方法）
  - `app/providers/image/fal_adapter.py`（新增 `generate_img2img()` 实现，支持 `fal-ai/flux/dev/image-to-image` 端点）
  - `app/tools/image_generation_tool.py`（新增 `generate_reference_image()` 方法，支持 character_reference/scene_reference/prop_reference 三种资产类型落库）
  - `app/agents/visual_development_agent.py`（**新建**：VisualDevelopmentAgent，角色/场景描述 → 结构化图片生成规格 JSON，含规则兜底）
  - `app/services/visual_bible_service.py`（**新建**：init_from_narrative / generate_character_reference / generate_scene_reference / confirm_visual_bible 四个能力）
  - `app/api/v1/visual_bible.py`（**新建**：5 个 REST 接口：GET active / POST init-from-narrative / POST generate-character-ref / POST generate-scene-ref / POST confirm）
  - `app/workflows/graph_state.py`（新增 `reference_image_urls` / `audio_url` 两个状态字段）
  - `app/workflows/main_graph.py`（load_project_snapshot 新增加载 image_reference + audio_original URL 逻辑；invoke_director_graph 初始状态补充两个新字段）
  - `app/agents/director_agent.py`（新增 `_build_multimodal_message()` 函数，有图/音频时将最后一条 HumanMessage 替换为多模态格式）
  - `app/main.py`（注册 visual_bible_router）

---

## 17.3 doc11 批次3：长任务异步化 + ShotPlan绑定VisualBible + PromptCompiler参考图URL + Storyboard img2img **[完成]**

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-31
- 产出：
  - `app/schemas/prompt.py`（`PromptBundle` 新增 `reference_image_url` / `reference_weight` 两个字段）
  - `app/tools/image_generation_tool.py`（`generate_for_bundle()` 当 bundle 有 `reference_image_url` 时自动切换为 img2img 模式）
  - `app/services/shot_plan_persistence_service.py`（新增 `_build_visual_bible_map()`；`_map_shot_fields()` 写入富结构 `character_binding`；允许 `visual_bible_ready` / `narrative_ready` 阶段生成）
  - `app/services/prompt_compiler_service.py`（读 `character_binding`，加载 Asset URL，写入 `reference_image_url` / `reference_asset_ids` / `ref_assets_text`）
  - `app/workflows/nodes/storyboard_node.py`（**改为 dispatch 异步**：创建 `generate_storyboard` ToolJob 入队，立即返回）
  - `app/workflows/nodes/clip_node.py`（**改为 dispatch 异步**：创建 `generate_clips` ToolJob）
  - `app/workflows/nodes/timeline_node.py`（**改为 dispatch 异步**：创建 `generate_timeline` ToolJob）
  - `app/tasks/worker.py`（新增 `_handle_generate_storyboard` / `_handle_generate_clips` / `_handle_generate_timeline` 三个 handler 函数，并在单例注册）

---

## 17.4 doc11 批次4：DirectorReport服务 + 双模式导演 + CostGate + Asset不变性 **[完成]**

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-31
- 产出：
  - `app/services/asset_service.py`（新增 `ImmutabilityViolationError` + `update_asset()` 强制拒绝守卫）
  - `app/workflows/graph_state.py`（新增 `system_trigger: Optional[dict]` 字段）
  - `app/workflows/main_graph.py`（`invoke_director_graph` initial_state 新增 `system_trigger=None`）
  - `prompts/system/director.md`（新增 Mode B 行为规范、三段式汇报协议、Mode B 与任务类型对应表）
  - `app/agents/director_agent.py`（新增 `_build_trigger_result_summary()`，读取 `system_trigger` 并给 prompt 注入 `mode / trigger_task_type / trigger_result_summary` 变量）
  - `app/services/director_report_service.py`（**新建**：`DirectorReportService` + 模块单例，完整实现加载项目→对话→Mode B汇报→落库流程）
  - `app/tasks/worker.py`（`_succeed_job` 完成 DB 回写后创建 `asyncio.Task` 触发 Director 汇报）
  - `app/services/cost_gate_service.py`（**新建**：`CostGateService.estimate_and_gate()`，广幂寻找已有决策 → 创建新决策 + 费用明细）
  - `app/workflows/nodes/clip_node.py`（集成 CostGate，费用未确认时返回确认消息而不 dispatch）

---

## 18. 真正的第一批开工顺序

如果现在马上开始，我建议真正第一批只做下面这些，不要同时开太多面：

1. `0-01`
2. `0-02`
3. `0-03`
4. `0-04`
5. `0-05`
6. `1-01`
7. `1-02`
8. `1-03`
9. `1-04`
10. `1-05`
11. `1-06`
12. `2-01`
13. `2-02`
14. `2-03`
15. `2-04`
16. `2-05`
17. `2-06`
18. `3-01`
19. `3-02`
20. `3-03`

原因：

- 这 20 个任务做完后，你的项目才真正拥有“可开发的地基”
- 再往后做状态机、事件、SSE、Agent，成本才合理

---

## 19. 这个版本和上一个版本的差异

这个重构版相比 [09_VidMuse详细开发执行计划](C:\Users\Administrator\Desktop\面试简历\09_VidMuse详细开发执行计划.md)，最大的不同是：

- 不再按“模块看起来属于谁”来写
- 改成按“真实开发时谁先依赖谁”来写
- 每个任务都显式写了：
  - 上一步输入
  - 本步产出
  - 下一个使用者

这才更接近真实工程实施。

---

## 20. 现在的最终判断

如果从“我已经在脑子里把项目做完一遍”的角度看，这个项目正确的开发顺序只有一句话：

> **先把运行底座、配置、Prompt、数据和状态控制面打牢，再做对话和 Agent，再做音频分析和规划，再做视觉生成和时间线，最后再做返工、回退和增强。**

如果反过来做，后面每一层都会返工。


---

## 多 Agent 架构改造批次 B [**完成**]

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-31
- 产出：
  - `app/tools/shared/artifact_tools.py`（新增 `read_artifact_tool` / `write_artifact_tool` / `get_asset_url_tool` 三个 `@tool` 包装）
  - `app/tools/shared/generation_tools.py`（新增 `generate_reference_image_tool` `@tool` 包装）
  - `app/agents/narrative_script_agent.py`（增加 `run(task_spec)` 新接口：`create_react_agent` + `write_artifact_tool`，保留旧 `generate()` 兼容别名）
  - `app/agents/creative_planning_agent.py`（新增 `run_phase1()` / `run_phase2()` / `_fallback_phase1_refs()` / `_fallback_phase2_ref()`）
  - `app/agents/visual_development_agent.py`（新增 `run(task_spec)` + `_fallback_run()`，直接调用 `generate_reference_image_tool`）
  - `app/services/narrative_script_service.py`（改用 `agent.run()` + `read_artifact()`）
  - `app/services/brief_persistence_service.py`（改用 `agent.run_phase1()` + `read_artifact()`）
  - `app/services/shot_plan_persistence_service.py`（改用 `agent.run_phase2()` + `read_artifact()`）
  - `app/services/visual_bible_service.py`（改用 `agent.run()` 直接获取 `asset_id`）
  - `prompts/system/narrative_script.md` / `creative_planning.md` / `visual_development.md`（各自补充 Batch B 工具使用协议）
- 关键设计决策：
  - 工具层采用 `@tool` 装饰 + 字符串序列化方式兼容 `create_react_agent` schema
  - Agent 接幓 task_spec 文本内容（未要求全量 ArtifactRef），减少对 Service 层的侵入
  - 三个 Agent 均保留旧接口为塔底兼容别名，存量升级无破坏性变更
- 语法检查：全部 9 个 Python 文件通过 py_compile

---

## 多 Agent 架构改造批次C [完成]

**批次定位**：A（ArtifactRef协议）→ B（Sub-Agent 接口）→ C（Director工具层 + Mode B读产物 + 音频分析异步化 + Character stale传播）

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-31
- 产出：
  - `app/domain/states.py`（新增 `StaleScope.CHARACTER_REF_CHANGED`）
  - `app/workflows/graph_state.py`（新增 `artifact_ref_for_review` 字段）
  - `app/services/state_transition_service.py`（新增 `mark_character_ref_changed_stale()` 方法和 `_mark_shots_by_character_stale()` SQL 辅助）
  - `app/workflows/nodes/audio_analysis_node.py`（改为 dispatch 异步模式，参考 storyboard_node）
  - `app/tasks/worker.py`（新增 `_handle_analyze_audio` handler、`_propagate_character_ref_stale` 异步传播函数、注册 `analyze_audio` 到 task_worker）
  - `app/agents/director_agent.py`（Mode B 主动读取 `artifact_ref_for_review`，注入 `artifact_content_for_review` prompt 变量）
  - `app/services/director_report_service.py`（将 `analyze_audio` 纳入白名单；根据 task_type 加载 ArtifactRef；保存汇报消息后写入 `director.report` SSE 事件）
  - `app/tools/director/__init__.py`（**新建**）
  - `app/tools/director/director_tools.py`（**新建**：`dispatch_agent_tool` / `read_artifact_for_review` / `create_decision_tool` / `get_project_state_tool` / `estimate_cost_tool`）
  - `app/tools/__init__.py`（新增 director 工具层导出）
- 关键设计决策：
  - Director 工具层采用骨架实现，@tool 装饰已就位，不改变 Director 主流程（停留在 LLM 直调模式）
  - `_propagate_character_ref_stale` 作为 fire-and-forget asyncio.Task，失败不影响 Worker 任务状态
  - SSE 推送通过 Outbox 模式（EventLogService 写 outbox_events → OutboxPublisher 发布），符合现有架构
  - ArtifactRef 加载失败时降级为文本摘要，不阻断汇报流程
- 语法检验：全部 10 个文件通过 `py_compile`

---

## 多 Agent 架构改造批次 A [完成]

### 批次 A：共享工具层 + ArtifactRef 协议基础

当前为什么做：

- docs/12 偏差 6 确认当前系统是 Director-led workflow，Agent 间通过进程内函数返回值传递产物原文，没有产物引用协议
- 批次 A 是多 Agent 架构改造的基础协议层，后续批次 B/C/D 都依赖它

上一步输入：

- docs/12 偏差 6 §6.2（ArtifactRef 协议、共享工具层设计规范）
- 已有 LocalArtifactStore / ProjectPathPlanner / ImageGenerationTool / VideoGenerationTool

本步实现：

- 新建 backend/app/tools/shared/ 共享工具层（ArtifactRef 读写 + 生成模型统一包装）
- ProjectGraphState 新增五个 ArtifactRef 引用字段（不删现有字段）
- audio_analysis_node / generate_brief_node / generate_shot_plan_node / narrative_node 成功路径补充 ArtifactRef 返回

产出结果：

- rom app.tools.shared import read_artifact, write_artifact, generate_image 可用
- 各节点成功后返回 brief_ref / shot_plan_ref / narrative_ref / audio_analysis_ref
- 后续 Sub-agent 可通过引用读取上游产物，不再依赖进程内内容传递

验收标准：

- 全部模块导入通过（python 语法检查通过）
- graph_state 含 audio_analysis_ref / brief_ref / narrative_ref / shot_plan_ref / visual_bible_ref

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-03-31
- 产出：
  - ackend/app/tools/shared/__init__.py（共享工具层统一导出）
  - ackend/app/tools/shared/artifact_tools.py（ArtifactRef 结构 + make_artifact_ref / read_artifact / write_artifact / get_asset_url / build_ref_from_latest）
  - ackend/app/tools/shared/generation_tools.py（generate_image / generate_reference_image / generate_video 薄包装）
  - ackend/app/tools/__init__.py（新增 shared 子包导出）
  - ackend/app/workflows/graph_state.py（新增 5 个 ArtifactRef 引用字段）
  - ackend/app/workflows/nodes/creative_planning_node.py（generate_brief_node 补 brief_ref / generate_shot_plan_node 补 shot_plan_ref）
  - ackend/app/workflows/nodes/narrative_node.py（补 narrative_ref）
  - ackend/app/workflows/nodes/audio_analysis_node.py（补 audio_analysis_ref）

---

## 多 Agent 架构改造偏差 6 收口修复 [完成]

当前为什么做：

- docs/12 偏差 6 的 A/B/C/D 虽已落地主骨架，但仍存在协议不纯、确认链路缺口、Director 审核层未真正收口的问题
- 本次修复只聚焦偏差 6，不处理另外两个任务

上一步输入：

- docs/12 偏差 6 的目标架构定义
- docs/09 已完成的 A/B/C 与 17.4（D 对应能力）执行记录
- 现状复检得到的 P0 / P1 问题清单

本步实现：

- 修复 Director 工具层与 Intent 白名单，让 create_decision、narrative/visual/storyboard 确认链路可执行
- 将 brief / narrative / shot_plan / visual 引导改为 ArtifactRef 驱动，Sub-Agent 通过 read_artifact_tool 读取上游产物
- 让 brief / narrative / shot_plan 在生成后回到 Director 做 Mode B 审核与确认，而不是节点直接对用户说话
- 修复 visual_bible_confirmed 的状态感知，兼容 confirmed_at 与决策卡两条路径

产出结果：

- Director 已具备 read_artifact_tool + create_decision_tool 的可运行工具层
- 文本类 Sub-Agent 不再依赖服务层直接塞入原文摘要，而是读取 ArtifactRef
- brief / narrative / shot_plan 生成完成后会刷新快照并重新进入 Director 汇报闭环
- visual 参考图链路改为读取 style_bible ArtifactRef，Mode B 规则与阶段确认补齐

验收标准：

- backend/app 全量 compileall 通过
- request_narrative_confirmation / request_visual_bible_confirmation / generate_storyboard 等动作可被 IntentResolutionService 放行
- human_confirmation_gate 可创建 confirm_narrative / confirm_visual_bible / confirm_storyboard
- brief / narrative / shot_plan / visual 相关 Agent 的 task_spec 只传引用，不传完整产物正文

预计代码量：

- `900 ~ 1500` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-01
- 产出：
  - `backend/app/tools/director/director_tools.py`
  - `backend/app/agents/director_agent.py`
  - `backend/app/services/intent_resolution_service.py`
  - `backend/app/workflows/main_graph.py`
  - `backend/app/workflows/nodes/human_confirmation_gate.py`
  - `backend/app/workflows/nodes/creative_planning_node.py`
  - `backend/app/workflows/nodes/narrative_node.py`
  - `backend/app/agents/narrative_script_agent.py`
  - `backend/app/agents/creative_planning_agent.py`
  - `backend/app/agents/visual_development_agent.py`
  - `backend/app/services/brief_persistence_service.py`
  - `backend/app/services/narrative_script_service.py`
  - `backend/app/services/shot_plan_persistence_service.py`
  - `backend/app/services/visual_bible_service.py`
  - `prompts/system/director.md`
  - `prompts/system/visual_development.md`

---

## 多 Agent 架构终态收口任务 P6-01 / P6-02 **[完成]**

当前为什么做：

- docs/12 已补充偏差 6 终态收口计划，但当前主图仍掌握 brief / narrative / shot plan 的文本主线路由权
- 需要先完成 P6-01 与 P6-02，把文本主线的运行时控制权回收到 Director

上一步输入：

- docs/12 附录 A 中的 P6-01 / P6-02 目标定义
- 已完成的偏差 6 收口修复主骨架

本步实现：

- 将 `dispatch_agent_tool` 的核心逻辑提取为可复用的内部 dispatch / create_decision 能力
- 在 `director_intake` 中增加文本主线自动 dispatch：当 Director 决定 `generate_brief` / `generate_narrative` / `generate_shot_plan` 时，直接执行 dispatch，再以 synthetic Mode B 回到 Director 审核
- 审核完成后由 Director 主路径直接创建确认决策，不再把文本生成主线继续路由到 graph node
- 从主图 `_ACTION_NODE_MAP` 与阶段 fallback 中移除 brief / narrative / shot plan 的主路径业务路由
- 新增单测与脚本级验证，确保文本主线已切离旧的 node 主路径

产出结果：

- Director 成为文本主线的实际调度入口
- brief / narrative / shot plan 不再经由主图业务节点执行
- gate 退回到确认兜底层，文本生成后的确认由 Director 主路径优先创建

下一个使用者：

- P6-03（统一 ArtifactRef 协议与纯引用态）

目录与文件：

- `backend/app/tools/director/director_tools.py`
- `backend/app/workflows/main_graph.py`
- `backend/tests/test_main_graph_director_dispatch.py`

验收标准：

- `generate_brief` / `generate_narrative` / `generate_shot_plan` 不再出现在主图 `_ACTION_NODE_MAP`
- `director_intake` 可直接完成文本主线 dispatch → 审核 → 创建确认决策
- 相关文件通过 `py_compile`
- 核心脚本验证通过：文本主线不再回到旧的 graph 业务节点

预计代码量：

- `300 ~ 700` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-01
- 产出：
  - `backend/app/tools/director/director_tools.py`
  - `backend/app/workflows/main_graph.py`
  - `backend/tests/test_main_graph_director_dispatch.py`

---

## 多 Agent 架构终态收口任务 P6-03 / P6-04 **[完成]**

当前为什么做：

- P6-01 / P6-02 已把文本主线调度权回收到 Director，但系统仍缺少统一 ArtifactRef 协议、纯引用态 state 和统一 Mode B 闭环
- 需要继续完成 docs/12 中的 P6-03 / P6-04，避免文本链路和 Worker 链路再次分叉

上一步输入：

- 已完成的 P6-01 / P6-02
- docs/12 附录 A 中的 P6-03 / P6-04 目标定义

本步实现：

- 为文本/规划类 artifact 扩展统一 `asset_type` 集合，并把 schema/init script 同步补齐
- 重写 `write_artifact`，让文本 artifact 在本地落盘后同步登记 Asset 记录，返回带 `asset_id` 的 ArtifactRef
- 新增 `build_ref_from_asset_latest()`，优先从资产记录回构 ArtifactRef，再回退到本地目录扫描
- 将音频分析、brief、narrative、shot plan、style、visual 等关键路径切换到 DB-backed ArtifactRef 读取
- 清理 GraphState 里的 `quality_summary` / `director_output`，改为 `audio_analysis_ref` + `decision_options`
- 调整 `DirectorAgent` 与 `human_confirmation_gate`，让 Director 从 artifact ref 读取音频摘要，gate 只消费轻量选项
- 统一 Mode B 逻辑：`system_trigger` 进入 `director_intake` 后直接走 Director 审核 + create_decision，同一套逻辑同时服务文本 synthetic Mode B 和 Worker 异步 Mode B
- 扩展 `DirectorReportService` 的任务白名单和 artifact 映射，覆盖 brief / narrative / shot_plan / analyze_audio 等主线任务

产出结果：

- ArtifactRef 不再只是本地文件指针，而是带 Asset 记录的 DB-backed 引用
- GraphState 从“中间内容态”收缩为“引用 + 轻状态态”
- 文本完成回审和 Worker 完成汇报共享同一套 Mode B 决策创建逻辑
- ArtifactRef 协议说明、Director 主调度路径与持久化 checkpointer 接入一起完成终态收口

下一个使用者：

- P6-05（全链路回归与无已知 bug 验收）

目录与文件：

- `backend/app/models/asset.py`
- `backend/app/services/asset_service.py`
- `scripts/init_schema.sql`
- `backend/app/tools/shared/artifact_tools.py`
- `backend/app/services/audio_analysis_service.py`
- `backend/app/services/brief_persistence_service.py`
- `backend/app/services/narrative_script_service.py`
- `backend/app/services/shot_plan_persistence_service.py`
- `backend/app/services/visual_bible_service.py`
- `backend/app/agents/director_agent.py`
- `backend/app/workflows/graph_state.py`
- `backend/app/workflows/nodes/human_confirmation_gate.py`
- `backend/app/workflows/nodes/creative_planning_node.py`
- `backend/app/workflows/nodes/narrative_node.py`
- `backend/app/workflows/main_graph.py`
- `backend/app/services/director_report_service.py`
- `backend/tests/test_main_graph_mode_b.py`

验收标准：

- 关键文本产物写入后可返回带 `asset_id` 的 ArtifactRef
- `quality_summary` 与 `director_output` 已不再出现在 GraphState 主字段中
- `director_intake` 在 `system_trigger` 下可直接完成 Director 审核 → 创建 decision → 返回汇报
- `DirectorReportService` 已覆盖文本主线任务类型并复用统一 Mode B 路径
- 相关文件通过 `py_compile`
- 核心脚本验证通过：文本 dispatch 路径和统一 Mode B 路径都能创建正确 decision

预计代码量：

- `900 ~ 1700` 行

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-01
- 产出：
  - `backend/app/models/asset.py`
  - `backend/app/services/asset_service.py`
  - `scripts/init_schema.sql`
  - `backend/app/tools/shared/artifact_tools.py`
  - `backend/app/services/audio_analysis_service.py`
  - `backend/app/services/brief_persistence_service.py`
  - `backend/app/services/narrative_script_service.py`
  - `backend/app/services/shot_plan_persistence_service.py`
  - `backend/app/services/visual_bible_service.py`
  - `backend/app/agents/director_agent.py`
  - `backend/app/workflows/graph_state.py`
  - `backend/app/workflows/nodes/human_confirmation_gate.py`
  - `backend/app/workflows/nodes/creative_planning_node.py`
  - `backend/app/workflows/nodes/narrative_node.py`
  - `backend/app/workflows/main_graph.py`
  - `backend/app/services/director_report_service.py`
  - `backend/tests/test_main_graph_mode_b.py`

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-01
- 产出：
  - `backend/app/agents/director_agent.py`
  - `backend/app/workflows/main_graph.py`
  - `backend/app/tools/shared/artifact_tools.py`
  - `backend/requirements.txt`
  - `prompts/system/director.md`


---

## 偏差 3、4、5 联合执行计划（Qwen3.5 Omni 驱动的多造型架构升级）

> **背景**：根据 docs/12，偏差 3（同一角色多套造型）、偏差 4（音频分析引入 Qwen3.5 Omni）、偏差 5（Omni 驱动角色图判断与多造型生成）是深度绑定、相互依赖的。必须将这三个偏差作为一个连贯的整体进行执行。执行顺序遵循"底层能力打底 -> 数据结构铺路 -> 业务逻辑闭环"的原则，拆分为三个连续的批次。
>
> **版本**：v2.0（2026-04-02 基于实际代码逐文件分析后纠正）

### 任务 P4-01：音频分析底层能力升级（解决偏差 4）

当前为什么做：
- Omni 模型能够直接接收音频输出完整结构化音乐分析，替代原有 librosa + WhisperX + AudioAnalysisAgent 繁琐的串行链路，为后续的图片和视频理解打下全模态基础。

上一步输入：
- 现有的 `AudioAnalysisVersion` 模型和音频分析节点

本步实现：
- 修改 `AudioAnalysisVersion` 数据库模型，新增 `chord_progression`、`instrumentation`、`five_second_analysis` 等 JSONB 字段。
- 精简 `audio_analysis_tool.py`，只保留 `librosa` 的 `beat_track` 功能用于提取精确毫秒级时间戳。
- 重写 `AudioAnalysisAgent`，调用 Qwen3.5 Omni 直接输出完整的音乐摘要 JSON。
- 调整 `AudioAnalysisService` 的 `run_and_save` 方法，实现 librosa 节拍提取与 Omni 语义分析的两步并发。
- 删除 `lyrics_alignment_tool.py` 的调用（Omni 直接输出歌词，WhisperX 不再需要）。

产出结果：
- 更高精度的段落检测，新增和弦、乐器等音乐维度，全链路耗时大幅缩短。

下一个使用者：
- 任务 P3-01

目录与文件：
- `backend/app/models/audio_analysis.py` — 新增 3 个 JSONB 字段
- `scripts/init_schema.sql` — CREATE TABLE 中直接添加新列
- `backend/app/tools/audio_analysis_tool.py` — 删除段落切分/能量曲线，只保留 beat_track
- `backend/app/agents/audio_analysis_agent.py` — 完全重写为 Omni 多模态调用
- `backend/app/services/audio_analysis_service.py` — 改为两步并发，删除 lyrics 调用和 quality_summary 回写
- `backend/app/tools/lyrics_alignment_tool.py` — 标记为废弃（保留文件但不再调用）
- `config/providers/` — 新建目录，配置 Omni 模型路由

验收标准：
- 音频分析服务能够并发执行，并正确将新增加的字段落库。
- `section_map` 由 Omni 输出（真正的 verse/chorus/bridge 识别），不再是 librosa 启发式切分。
- WhisperX 调用已移除，歌词由 Omni 直接输出。

预计代码量：
- `500 ~ 800` 行

---

### 任务 P3-01：多套造型数据结构与基础接口（解决偏差 3）

当前为什么做：
- 后续 Omni 将自动推导出角色在不同段落的多套造型，在此之前必须先在数据库和基础服务中铺好路，准备好存储结构和生成单套造型的接口。

上一步输入：
- 任务 P4-01

本步实现：
- 扩展 `CharacterSetVersion.characters` 的 JSONB 结构定义，补充 `costumes`、`image_analysis`、`base_face_asset_id` 字段的规范。
- 修改 `VisualBibleService`，新增 `analyze_reference_image()` 接口（用于调用 Omni 看图）和 `generate_costume_reference()` 接口（基于原图生成特定造型的定妆图）。
- 调整 `ShotPlanPersistenceService`，在生成 Shot 时根据 `section_type` 动态匹配角色对应的造型，将 `character_ref_asset_id` 指向具体的造型定妆图。
- 新增对应的 REST API，供后续系统调用。

产出结果：
- 系统具备了存储多造型数据和单次生成特定造型参考图的底层能力。

下一个使用者：
- 任务 P5-01

目录与文件：
- `backend/app/models/visual_bible.py` — 更新 docstring，新增 JSONB 字段结构说明
- `backend/app/services/visual_bible_service.py` — 改造 init_from_narrative / _update_character_ref，新增 4 个方法
- `backend/app/api/v1/visual_bible.py` — 新增 2 个接口 + Body 模型
- `backend/app/services/shot_plan_persistence_service.py` — 改造 _build_visual_bible_map（模块级函数）和 _map_shot_fields（模块级函数）

验收标准：
- 数据库 `character_set_versions` 能够正确存储和读取包含 `costumes` 的数据。
- Shot 能够根据段落正确绑定不同造型的 `asset_id`。

预计代码量：
- `600 ~ 900` 行

---

### 任务 P5-01：Omni 业务驱动闭环（解决偏差 5）

当前为什么做：
- 底层能力和数据结构已经就绪，现在需要用 Omni 把它们串联起来，实现真正的自动化看图和多造型生成。

上一步输入：
- 任务 P3-01

本步实现：
- 在 `tools/director/director_tools.py` 中新增 Director 工具（`analyze_reference_image_tool` 和 `setup_costumes_tool`），让 Director 通过 ReAct tool-calling 自动触发。
- 在 `VisualBibleService` 中新增业务编排方法 `auto_analyze_and_setup_costumes()`，将图片分析 → 造型推导 → 批量生成串联为完整闭环。
- 新增 Omni 相关 prompt 模板（放在 `prompts/tasks/` 目录下）。
- 新增一键自动设置多造型的 REST API。

产出结果：
- 完整的角色多造型自动化闭环，极大提升了 MV 生成的细节表现力。

下一个使用者：
- 无（偏差 3、4、5 闭环完成）

目录与文件：
- `backend/app/tools/director/director_tools.py` — 新增 2 个 Director 工具
- `backend/app/services/visual_bible_service.py` — 新增 auto_analyze_and_setup_costumes / _derive_costumes_from_narrative
- `backend/app/api/v1/visual_bible.py` — 新增 auto-setup-costumes 接口
- `prompts/tasks/omni_image_analysis.md` — 新增
- `prompts/tasks/omni_costume_derivation.md` — 新增

验收标准：
- 上传不合格的角色图能被系统自动识别并打回/转图生图。
- 同一角色在 Verse 和 Chorus 段落能自动生成并挂载两套不同的服装造型。

预计代码量：
- `400 ~ 700` 行

---

## 附录 B：偏差 3、4、5 详细代码级改造计划（代码分析版）

> **来源**：2026-04-02 逐文件代码分析。对比项包括 `audio_analysis_tool.py`（165行）、`audio_analysis_agent.py`（265行）、`audio_analysis_service.py`（263行）、`audio_analysis.py`（106行）、`visual_bible.py` 模型（177行）、`visual_bible_service.py`（534行）、`visual_bible.py` API（296行）、`shot_plan_persistence_service.py`（498行）、`director_agent.py`（400+行）、`lyrics_alignment_tool.py`（135行）、`init_schema.sql`。
>
> **与 v1.0 差异说明**：v1.0 版本（2026-04-01）存在若干与实际代码不符的描述，本版逐项纠正。主要差异：
> 1. `audio_analysis_tool.py` 不需要新增 `extract_beat_only()` 函数，直接改造 `analyze()` 即可
> 2. `audio_analysis_agent.py` 遗漏了 `_estimate_target_duration()` 静态方法需删除
> 3. `audio_analysis_service.py` 遗漏了删除 `align_lyrics()` 调用和 `lyrics_alignment_tool` 导入
> 4. `init_schema.sql` 是初始化脚本，应直接修改 CREATE TABLE 而非追加 ALTER TABLE
> 5. P5-01 中 Director 已经是 ReAct Agent 模式，新增能力应通过新增 Director 工具实现
> 6. Omni prompt 模板应放在 `prompts/tasks/` 而非 `prompts/system/`
> 7. `shot_plan_persistence_service.py` 中 `_build_visual_bible_map` 和 `_map_shot_fields` 是模块级函数，不是类方法

---

### P4-01：音频分析底层能力升级（解决偏差 4）

**当前代码分析结论**（2026-04-02 实际代码核实）：

- `audio_analysis_tool.py`（165行）：`analyze()` 函数做了四件事：tempo + beat_map + section_map（RMS启发式切分）+ energy_curve。内部有三个私有函数：`_detect_sections()`、`_label_sections()`、`_compute_energy_curve()`。常量 `_ENERGY_SAMPLES_PER_SEC` 和 `_HOP_LENGTH` 也仅被这些函数使用（`_HOP_LENGTH` 被 beat_track 和 _detect_sections 共用）。
- `audio_analysis_agent.py`（265行）：接收 `AudioAnalysisVersion` 对象，从 `raw_payload.signal` 中提取 librosa 数值，送入 LLM 生成 quality_summary。类方法包括 `run()`、`_estimate_target_duration()`、`_build_analysis_summary()`、`_fallback_system_prompt()`、`_rule_based_summary()`。模块级函数 `_safe_parse_json()` 需保留。
- `audio_analysis_service.py`（263行）：`run_and_save()` 顺序执行 7 步：读取规格 → 裁切音频 → librosa 信号分析 → 歌词对齐（`align_lyrics`） → 落库。还有 `update_quality_summary()` 方法供 Agent 回写。当前导入了 `lyrics_alignment_tool.align_lyrics` 和 `audio_analysis_tool.analyze`。
- `AudioAnalysisVersion` 模型（106行）：已有 `key_scale`/`time_signature`/`style_caption`/`lrc_asset_id`/`analysis_provider` 扩展字段，缺少 `chord_progression`/`instrumentation`/`five_second_analysis`。
- `lyrics_alignment_tool.py`（135行）：使用 WhisperX 做 ASR+对齐，有优雅降级（WhisperX 未安装时返回 `available=False`）。Omni 替代后此工具的调用应从 service 中移除。

#### P4-01 本步改造清单

**1. `backend/app/models/audio_analysis.py`**（当前 106 行）

| 操作 | 具体内容 | 代码位置 |
|------|---------|---------|
| **新增字段** | `chord_progression: Mapped[dict]` — JSONB，整体和弦走向 | 在 `quality_summary` 字段之后 |
| **新增字段** | `instrumentation: Mapped[dict]` — JSONB，乐器列表 | 同上 |
| **新增字段** | `five_second_analysis: Mapped[dict]` — JSONB，五秒粒度详细分析 | 同上 |
| **改造注释** | 文件头部 docstring 和 `key_scale` 等字段上方注释：删除 "ACE-Step 双路分析预留" 描述，改为 "Qwen3.5 Omni 全模态分析" | 第1-12行, 第82行注释块 |
| **语义变更** | `section_map` 字段保留，但语义从 "librosa RMS 启发式切分" 变为 "Omni 真实段落结构（verse/chorus/bridge）" | 更新第66行注释 |
| **语义变更** | `energy_curve` 字段保留但不再由 librosa 写入，Omni 如有能量数据可写入，否则留空 | 更新第67行注释 |
| **保留** | `analysis_provider` 字段保留，语义从 "双路记录" 变为 "Omni 分析元数据" | 更新第90行注释 |

**2. `backend/app/tools/audio_analysis_tool.py`**（当前 165 行）

| 操作 | 具体内容 | 代码位置 |
|------|---------|---------|
| **删除函数** | `_detect_sections(y, sr)` — RMS 启发式段落切分 | 第93-140行 |
| **删除函数** | `_label_sections(sections)` — 段落标注逻辑 | 第143-165行 |
| **删除函数** | `_compute_energy_curve(y, sr)` — 能量曲线计算 | 第84-90行 |
| **删除常量** | `_ENERGY_SAMPLES_PER_SEC` — 仅被 `_compute_energy_curve` 使用 | 第31行 |
| **改造函数** | `analyze(audio_path)` — 删除对 `_detect_sections` 和 `_compute_energy_curve` 的调用，返回值中去掉 `section_map` 和 `energy_curve`，只保留 `bpm`、`beat_map`、`duration_sec`、`sample_rate` | 第37-80行 |
| **改造注释** | 文件头部 docstring 更新：说明只做 beat_track，段落检测和歌词由 Omni 负责 | 第1-24行 |
| **保留** | `_HOP_LENGTH` 常量 — beat_track 仍需使用 | 第33行 |

**注意**：不需要新增 `extract_beat_only()` 函数。`analyze()` 本身就是唯一的公开接口，直接精简它即可。服务层调用 `analyze()` 的地方不需要改接口签名。

**3. `backend/app/agents/audio_analysis_agent.py`**（当前 265 行）

| 操作 | 具体内容 | 代码位置 |
|------|---------|---------|
| **完全重写类** | `AudioAnalysisAgent` — 从 "LLM 解读 librosa 数值" 改为 "Omni 直接分析音频文件" | 第38-218行（整个类） |
| **删除方法** | `run(self, version: AudioAnalysisVersion)` — 当前接收 ORM 对象的实现 | 第42-106行 |
| **删除方法** | `_estimate_target_duration(raw_signal)` — 静态方法，不再需要 | 第112-113行 |
| **删除方法** | `_build_analysis_summary(raw_signal, version)` — librosa 数值摘要构建 | 第115-145行 |
| **删除方法** | `_fallback_system_prompt(raw_signal, user_prompt)` — 规则兜底提示词 | 第147-152行 |
| **删除方法** | `_rule_based_summary(raw_signal, version)` — 规则兜底摘要（含复杂 BPM 推断逻辑） | 第154-218行 |
| **保留** | `_safe_parse_json(content)` — 模块级函数，三层 JSON 解析，Omni 返回也需要 | 第225-261行 |
| **新增方法** | `async run(self, audio_file_path: str) -> dict` — 直接接收音频文件路径，调用 Omni 多模态接口 | 新实现 |
| **新增方法** | `async run_with_omni(self, audio_file_path: str) -> dict` — Omni 多模态分析核心逻辑 | 新实现 |
| **新增导入** | Omni provider 相关导入（取代 `AudioAnalysisVersion` 导入） | 第20行 |

**Omni 调用方式**：通过百炼平台 OpenAI 兼容接口。音频文件以 URL 或 base64 方式传入多模态消息。参考 doc13 验证过的 prompt。

**Omni 输出结构**（合并 quality_summary + 新增字段）：
```json
{
  "music_structure_summary": {
    "bpm": 128,
    "key_scale": "D major",
    "time_signature": "4/4",
    "sections": [
      {"label": "intro", "start": 0.0, "end": 8.5, "description": "..."},
      {"label": "verse", "start": 8.5, "end": 32.0, "description": "..."}
    ]
  },
  "chord_progression": [
    {"section": "verse", "chords": ["Dm", "Am", "Bb", "C"]},
    {"section": "chorus", "chords": ["F", "C", "Dm", "Bb"]}
  ],
  "instrumentation": ["acoustic_guitar", "drums", "bass", "synth_pad"],
  "five_second_analysis": [
    {"start": 0.0, "end": 5.0, "energy": 0.3, "mood": "calm", "instruments": ["guitar"]},
    {"start": 5.0, "end": 10.0, "energy": 0.5, "mood": "building", "instruments": ["guitar", "drums"]}
  ],
  "lyrics": {
    "language": "zh",
    "lines": [
      {"start": 8.5, "end": 12.0, "text": "第一句歌词"},
      {"start": 12.0, "end": 16.0, "text": "第二句歌词"}
    ]
  },
  "emotion_arc": {
    "overall": "melancholy_to_uplifting",
    "segments": [...]
  },
  "editing_guidance": {
    "per_section": [...]
  }
}
```

**4. `backend/app/services/audio_analysis_service.py`**（当前 263 行）

| 操作 | 具体内容 | 代码位置 |
|------|---------|---------|
| **删除导入** | `from app.tools.lyrics_alignment_tool import align_lyrics` | 第18行 |
| **改造导入** | `from app.tools.audio_analysis_tool import analyze as _signal_analyze` → 保留但改名为 `_beat_analyze`（语义更准确） | 第17行 |
| **新增导入** | `from app.agents.audio_analysis_agent import AudioAnalysisAgent` | 新增 |
| **改造方法** | `run_and_save()` 步骤 3+4 — 从 "librosa 全分析 + lyrics 对齐" 改为 "librosa beat_track 与 Omni 并发" | 第115-140行 |
| **删除步骤** | 步骤 4 中 `lyrics_result = await align_lyrics(audio_path)` 整段删除 | 第131行 |
| **删除逻辑** | `if not lyrics_result["available"]` 降级日志块删除 | 第133-137行 |
| **新增并发** | 使用 `asyncio.gather()` 并发执行 `asyncio.to_thread(_beat_analyze, audio_path)` 和 `agent.run_with_omni(audio_path)` | 替换步骤 3+4 |
| **改造方法** | `_persist()` — 新增 `chord_progression`、`instrumentation`、`five_second_analysis` 字段写入 ORM | 第158-170行 |
| **改造方法** | `_persist()` — `section_map` 从 librosa 输出改为 Omni 输出（字段保留，数据来源变更） | 第164行 |
| **改造方法** | `_persist()` — `lyrics_alignment` 从 WhisperX 输出改为 Omni 输出的歌词数据 | 第165行 |
| **改造方法** | `_persist()` — `quality_summary` 直接由 Omni 输出填充，不再留空等 Agent 回写 | 第167行 |
| **删除方法** | `update_quality_summary()` — Omni 在分析阶段直接输出完整结果，不需要二次回写 | 第216-237行 |

**并发执行伪代码**：
```python
agent = AudioAnalysisAgent()
beat_result, omni_result = await asyncio.gather(
    asyncio.to_thread(_beat_analyze, audio_path),  # librosa: 只返回 bpm + beat_map
    agent.run_with_omni(audio_path),                # Omni: 完整语义分析
)
# 合并：beat_map 来自 librosa（精确毫秒级），其余来自 Omni
merged = {
    "bpm": beat_result["bpm"],
    "beat_map": beat_result["beat_map"],
    "section_map": omni_result["music_structure_summary"]["sections"],
    "chord_progression": omni_result["chord_progression"],
    "instrumentation": omni_result["instrumentation"],
    "five_second_analysis": omni_result["five_second_analysis"],
    "lyrics": omni_result.get("lyrics", {}),
    "quality_summary": omni_result,
    ...
}
```

**5. `backend/app/tools/lyrics_alignment_tool.py`**（当前 135 行）

| 操作 | 具体内容 |
|------|---------|
| **标记废弃** | 在文件头部 docstring 添加 `DEPRECATED` 标注，说明已被 Omni 替代 |
| **不删除文件** | 保留为备用降级路径（WhisperX 本身已有优雅降级，文件本身无害） |
| **删除调用** | 在 `audio_analysis_service.py` 中移除对此工具的 import 和调用 |

**6. `scripts/init_schema.sql`**

| 操作 | 具体内容 | 代码位置 |
|------|---------|---------|
| **新增列** | `chord_progression JSONB NOT NULL DEFAULT '{}'` | 在 `audio_analysis_versions` 的 CREATE TABLE 内，`analysis_provider` 之前 |
| **新增列** | `instrumentation JSONB NOT NULL DEFAULT '{}'` | 同上 |
| **新增列** | `five_second_analysis JSONB NOT NULL DEFAULT '{}'` | 同上 |
| **改造注释** | 删除 "doc10 §4.4 扩展字段（ACE-Step 双路分析预留）" 注释，改为 "Qwen3.5 Omni 扩展字段" | 第316行附近 |

**重要纠正**：`init_schema.sql` 是全新安装初始化脚本（`CREATE TABLE IF NOT EXISTS`），应直接在 CREATE TABLE 语句中添加新列定义，**不是**追加 ALTER TABLE。ALTER TABLE 只在已有运行数据库需要迁移时使用，不写在 init_schema 中。

**7. Omni Provider 配置**

| 操作 | 具体内容 |
|------|---------|
| **新建目录** | `config/providers/` — 当前不存在，需要创建 |
| **新建文件** | `config/providers/omni.yaml` — 配置 Qwen3.5 Omni 模型路由 |
| **配置内容** | endpoint（百炼平台 OpenAI 兼容 API）、model_name、api_key_env、timeout、多模态参数 |

#### P4-01 文件行数评估

| 文件 | 当前行数 | 改造后行数 | 增量 |
|------|---------|-----------|------|
| `audio_analysis.py` | 106 | ~130 | +24 |
| `audio_analysis_tool.py` | 165 | ~60 | **-105**（删除 section/energy/label 三个函数 + 常量） |
| `audio_analysis_agent.py` | 265 | ~150 | **-115**（删除 5 个方法，新增 2 个 Omni 方法） |
| `audio_analysis_service.py` | 263 | ~230 | **-33**（删除 lyrics 调用 + quality_summary 回写，新增并发逻辑） |
| `init_schema.sql` | 直接修改 | — | +3（3 个新列定义） |
| `config/providers/omni.yaml` | 0 | ~30 | +30 |
| **合计净变化** | ~799 | ~600 | **-199** |

#### P4-01 验收标准

1. `audio_analysis_tool.py` 中 `analyze()` 只返回 `bpm`、`beat_map`、`duration_sec`、`sample_rate`，不再包含 `section_map` 和 `energy_curve`
2. `AudioAnalysisAgent` 能通过 Omni 直接分析音频文件并返回结构化 JSON（包含 `chord_progression`/`instrumentation`/`five_second_analysis`/`lyrics`）
3. `AudioAnalysisService.run_and_save()` 使用 `asyncio.gather` 并发执行 librosa beat_track 和 Omni 分析
4. `AudioAnalysisVersion` 模型能正确存储和读取三个新字段
5. `lyrics_alignment_tool.align_lyrics()` 不再被 service 调用
6. `update_quality_summary()` 方法已删除
7. `init_schema.sql` 的 CREATE TABLE 中直接包含新列定义

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-03
- 产出：
  - `backend/app/agents/audio_analysis_agent.py` — 重写为 Omni 多模态调用；修复 render() 变量名错误；补充 style_caption 到 fallback prompt
  - `backend/app/services/audio_analysis_service.py` — 补充 style_caption 字段映射
  - `backend/app/utils/omni_config.py` — 新建，提取共享 Omni 配置加载逻辑
  - `prompts/system/audio_analysis.md` — 重写为 Omni 直接分析格式，移除旧 librosa 处理变量引用

---

### P3-01：多套造型数据结构与基础接口（解决偏差 3）

**当前代码分析结论**（2026-04-02 实际代码核实）：

- `CharacterSetVersion`（visual_bible.py 177行）：`characters` JSONB 当前每项只有 `character_id`/`character_name`/`description`/`reference_asset_ids`/`active_reference_asset_id`/`appears_in_sections`，缺少 `base_face_asset_id`、`image_analysis`、`costumes`。`raw_payload` 的示例注释也未包含这些字段。
- `VisualBibleService`（534行）：`init_from_narrative()` 在第 127-136 行构建 characters 列表时没有 costumes 相关字段。`_update_character_ref()` 在第 375-398 行直接修改 `reference_asset_ids` 和 `active_reference_asset_id`，没有 costumes 保护逻辑。`generate_character_reference()` 通过 `self._agent.run(task_spec)` 调用 VisualDevelopmentAgent。
- `visual_bible.py` API（296行）：当前有 5 个接口（GET active / POST init / POST generate-character-ref / POST generate-scene-ref / POST confirm）。`generate-character-ref` 和 `generate-scene-ref` 已改为异步 dispatch（通过 `task_dispatcher`）。
- `shot_plan_persistence_service.py`（498行）：`_build_visual_bible_map()` 和 `_map_shot_fields()` 是**模块级函数**（不是类方法），分别在第 85 行和第 127 行定义。`_build_visual_bible_map` 返回 `scene_ref_map`/`character_ref_map`/`section_chars_map`。`_map_shot_fields` 构建 `character_binding` 时只取 `active_reference_asset_id`，没有 costumes 匹配逻辑。

#### P3-01 本步改造清单

**1. `backend/app/models/visual_bible.py` — CharacterSetVersion 注释更新**（当前 177 行）

| 操作 | 具体内容 | 代码位置 |
|------|---------|---------|
| **改造注释** | 更新 `CharacterSetVersion` 类的 docstring，`raw_payload` 示例结构加入 `base_face_asset_id`、`image_analysis`、`costumes` | 第36-57行 |
| **无需改代码** | JSONB 是 schemaless，ORM 层字段定义无需修改 | — |

**更新后的 CharacterSetVersion.characters 每项结构规范**：
```json
{
  "character_id": "char_001",
  "character_name": "主角",
  "description": "20岁短发女生",
  "appears_in_sections": ["verse", "chorus"],
  "reference_asset_ids": ["asset_001"],
  "active_reference_asset_id": "asset_001",
  "base_face_asset_id": null,
  "image_analysis": null,
  "costumes": [
    {
      "costume_id": "costume_verse",
      "label": "日常穿搭",
      "applies_to_sections": ["intro", "verse"],
      "reference_asset_id": null,
      "generation_prompt": null,
      "user_confirmed": false
    }
  ]
}
```

**2. `backend/app/services/visual_bible_service.py`**（当前 534 行）

| 操作 | 具体内容 | 代码位置 |
|------|---------|---------|
| **改造方法** | `init_from_narrative()` — 在 characters 列表构建中新增 `"base_face_asset_id": None, "image_analysis": None, "costumes": []` | 第127-136行 |
| **改造方法** | `_update_character_ref()` — 更新 `reference_asset_ids` 和 `active_reference_asset_id` 时显式保留 `costumes`/`base_face_asset_id`/`image_analysis` 字段不被覆盖 | 第375-398行 |
| **新增方法** | `async analyze_reference_image(self, asset_id: str, project_id: str, user_id: str) -> dict` — 调用 Omni 看图分析用户上传的参考图，返回图片类型判断结构 | 新增，约 50 行 |
| **新增方法** | `async generate_costume_reference(self, project_id, user_id, character_id, costume_id, *, generation_mode, source_image_url) -> str` — 基于基础脸图生成特定造型的定妆图，返回 asset_id | 新增，约 60 行 |
| **新增方法** | `async _update_costume_ref(self, project_id, csv_id, character_id, costume_id, new_asset_id) -> None` — 更新指定 costume 的 reference_asset_id | 新增，约 30 行 |
| **新增方法** | `_get_costume_for_section(character_item: dict, section_type: str) -> dict | None` — 静态/辅助方法，根据段落类型在 costumes 列表中匹配对应造型 | 新增，约 15 行 |

**analyze_reference_image() 返回结构**：
```python
{
    "image_type": "realistic_photo",
    "usable_directly": False,
    "reason": "用户自拍照，面部特征清晰但服装/背景不符合MV风格",
    "recommended_mode": "image_to_image",
    "face_quality": "high",
    "requires_costume_generation": True
}
```

**3. `backend/app/api/v1/visual_bible.py`**（当前 296 行）

| 操作 | 具体内容 | 代码位置 |
|------|---------|---------|
| **新增 Body** | `AnalyzeReferenceImageBody(BaseModel)` — `asset_id: str` | 在现有 Body 定义之后 |
| **新增 Body** | `GenerateCostumeRefBody(BaseModel)` — `character_id: str, costume_id: str, generation_mode: str = "image_to_image", source_image_url: Optional[str] = None` | 同上 |
| **新增接口** | `POST /projects/{project_id}/visual-bible/analyze-reference-image` — 调用 `svc.analyze_reference_image()`，返回图片类型判断 | 新增，约 30 行 |
| **新增接口** | `POST /projects/{project_id}/visual-bible/generate-costume-ref` — 异步 dispatch 造型参考图生成任务（与 generate-character-ref 同模式） | 新增，约 35 行 |

**注意**：这两个接口是偏差5的前置接口，P3-01 先把接口和基础方法铺好，P5-01 再实现 Director 自动触发。

**4. `backend/app/services/shot_plan_persistence_service.py`**（当前 498 行）

**重要纠正**：`_build_visual_bible_map` 和 `_map_shot_fields` 都是**模块级函数**（第 85 行和第 127 行定义），不是 `ShotPlanPersistenceService` 的方法。改造时直接修改这两个函数签名和内部逻辑即可。

| 操作 | 具体内容 | 代码位置 |
|------|---------|---------|
| **改造函数** | `_build_visual_bible_map(narrative, char_set_version)` — 返回结构新增 `costume_ref_map` | 第85-123行 |
| **改造函数** | `_map_shot_fields(raw, idx, ref_binding_map)` — character_binding 新增 `costume_id` 和 `costume_ref_asset_id`。当 costume_ref_map 中有该角色在该 section_type 的造型时，优先使用造型的 reference_asset_id | 第126-195行 |

**_build_visual_bible_map() 改造：新增造型映射构建**（在 character_ref_map 构建逻辑之后）：
```python
# 新增：构建 costume_ref_map
costume_ref_map: dict[str, dict[str, dict]] = {}
if char_set_version is not None:
    for c in (char_set_version.characters or []):
        cid = c.get("character_id")
        costumes = c.get("costumes") or []
        if cid and costumes:
            costume_ref_map[cid] = {}
            for costume in costumes:
                for section in (costume.get("applies_to_sections") or []):
                    if costume.get("reference_asset_id"):
                        costume_ref_map[cid][section] = {
                            "costume_id": costume["costume_id"],
                            "reference_asset_id": costume["reference_asset_id"],
                        }
result["costume_ref_map"] = costume_ref_map
```

**_map_shot_fields() 改造：造型匹配逻辑**：
```python
# 在 character_binding 构建中新增
costume_match = None
costume_ref_map = ref_binding_map.get("costume_ref_map", {})
for cid in char_ids:
    match = costume_ref_map.get(cid, {}).get(section_type)
    if match:
        costume_match = match
        break  # 取第一个匹配的角色造型

character_binding["costume_id"] = costume_match["costume_id"] if costume_match else None
character_binding["costume_ref_asset_id"] = costume_match["reference_asset_id"] if costume_match else None
# 当有造型参考图时，优先使用造型图替代统一的 active_reference_asset_id
if costume_match and costume_match.get("reference_asset_id"):
    character_binding["character_ref_asset_id"] = costume_match["reference_asset_id"]
```

#### P3-01 文件行数评估

| 文件 | 当前行数 | 改造后行数 | 增量 |
|------|---------|-----------|------|
| `visual_bible.py`（模型） | 177 | ~195 | +18（注释更新） |
| `visual_bible_service.py` | 534 | ~690 | +156（改造2个方法 + 新增4个方法） |
| `visual_bible.py`（API） | 296 | ~365 | +69（新增2个接口 + 2个Body） |
| `shot_plan_persistence_service.py` | 498 | ~545 | +47（改造2个模块级函数） |
| **合计** | 1505 | ~1795 | **+290** |

#### P3-01 验收标准

1. `init_from_narrative()` 创建的 characters 每项包含 `base_face_asset_id: null`、`image_analysis: null`、`costumes: []`
2. `_update_character_ref()` 更新参考图后不会丢失已有的 `costumes`/`base_face_asset_id`/`image_analysis` 字段
3. `analyze_reference_image()` 能返回图片类型判断结构
4. `generate_costume_reference()` 能为角色生成特定造型图并通过 `_update_costume_ref()` 回写对应 costume 的 reference_asset_id
5. `_build_visual_bible_map()` 返回的 dict 包含 `costume_ref_map`
6. `_map_shot_fields()` 生成的 character_binding 包含 `costume_id` 和 `costume_ref_asset_id`
7. 同一角色在 verse 生成的 Shot 和 chorus 生成的 Shot，character_binding 指向不同造型的 asset_id

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-03
- 产出：
  - `backend/app/services/visual_bible_service.py` — 修复 `_update_scene_ref()` 重复添加 Bug；替换重复的 `_load_omni_config()` 为共享导入；修复 `generate_costume_reference()` 硬编码 version_no；移除死代码 `_get_costume_for_section()`；修复 costume_id 包含中文字符问题

---

### P5-01：Omni 业务驱动闭环（解决偏差 5）

**前置条件**：P4-01（Omni 音频分析能力）和 P3-01（多造型数据结构）已完成

**当前代码分析结论**（2026-04-02 实际代码核实）：

- `director_agent.py`（400+行）：Director 已经是 ReAct Agent 模式（通过 `create_react_agent` 构建），拥有 `dispatch_agent_tool`、`read_artifact_tool`、`create_decision_tool`、`get_project_state_tool`、`estimate_cost_tool` 五个工具。新增能力**必须通过新增 Director 工具实现**，不能在 `director_agent.py` 中硬编码调用点。
- `tools/director/director_tools.py`：已有上述5个工具的实现。新增的 `analyze_reference_image_tool` 和 `setup_costumes_tool` 应在此文件中定义，并注册到 Director 的工具列表中。
- `director_agent.py` 第 303-310 行：Director 的 tools 列表定义在 `run()` 方法内部，新增工具时需要在这里注册。

**重要纠正**：v1.0 版本计划在 `director_agent.py` 中"新增调用点"是错误的。当前 Director 是 ReAct Agent，所有能力扩展都应通过新增 `@tool` 装饰的工具函数来实现。Director 的 LLM 会根据 system prompt 中的工具说明自动决定何时调用。

#### P5-01 本步改造清单

**1. `backend/app/tools/director/director_tools.py` — 新增 Director 工具**

| 操作 | 具体内容 |
|------|---------|
| **新增工具** | `@tool analyze_reference_image_tool(project_id, user_id, asset_id) -> dict` — 调用 `VisualBibleService.analyze_reference_image()`，返回图片类型判断结果 |
| **新增工具** | `@tool setup_costumes_tool(project_id, user_id, skip_image_analysis=False) -> dict` — 调用 `VisualBibleService.auto_analyze_and_setup_costumes()`，完成图片分析→造型推导→批量生成的完整闭环 |

**2. `backend/app/agents/director_agent.py` — 注册新工具**

| 操作 | 具体内容 | 代码位置 |
|------|---------|---------|
| **新增导入** | `from app.tools.director.director_tools import analyze_reference_image_tool, setup_costumes_tool` | 文件头部 import 区 |
| **改造列表** | 在 `tools = [...]` 列表中追加 `analyze_reference_image_tool` 和 `setup_costumes_tool` | 第303-310行 |

**3. `backend/app/services/visual_bible_service.py` — 业务编排方法**

| 操作 | 具体内容 |
|------|---------|
| **新增方法** | `async auto_analyze_and_setup_costumes(self, project_id, user_id, *, skip_image_analysis=False) -> dict` — 完整的 Omni 驱动多造型设置流程 |
| **新增方法** | `async _derive_costumes_from_narrative(self, project_id, narrative, character_item, style_bible) -> list[dict]` — 调用 Omni 从叙事剧本+风格圣经推导角色在各段落的造型列表 |

**auto_analyze_and_setup_costumes() 流程**：
```text
1. 读取 active NarrativeScript + CharacterSetVersion + StyleBible
2. 对每个角色：
   a. 如果有用户上传的参考图 → 调用 analyze_reference_image()
   b. 根据分析结果设置 base_face_asset_id 和 generation_mode
   c. 调用 _derive_costumes_from_narrative() 推导造型列表
   d. 将推导出的 costumes 写入角色的 JSONB
   e. 对每套造型调用 generate_costume_reference() 生成定妆图
3. 返回处理结果摘要
```

**4. `prompts/tasks/` — Omni 相关 prompt 模板**

| 操作 | 具体内容 |
|------|---------|
| **新增文件** | `prompts/tasks/omni_image_analysis.md` — Omni 看图判断图片类型的任务 prompt |
| **新增文件** | `prompts/tasks/omni_costume_derivation.md` — Omni 从叙事剧本推导角色造型的任务 prompt |

**重要纠正**：这些是**任务级 prompt**（用于特定任务的指令），应放在 `prompts/tasks/` 而非 `prompts/system/`。`prompts/system/` 存放的是 Agent 系统提示词（如 `director.md`）。

**5. `prompts/system/director.md` — 更新 Director 系统提示词**

| 操作 | 具体内容 |
|------|---------|
| **新增工具说明** | 在 available_tools 部分追加 `analyze_reference_image_tool` 和 `setup_costumes_tool` 的使用说明和触发时机 |

**6. `backend/app/api/v1/visual_bible.py` — 完整 API 链路**

| 操作 | 具体内容 |
|------|---------|
| **新增 Body** | `AutoSetupCostumesBody(BaseModel)` — `skip_image_analysis: bool = False` |
| **新增接口** | `POST /projects/{project_id}/visual-bible/auto-setup-costumes` — 一键自动设置多造型（异步 dispatch） |

#### P5-01 文件行数评估

| 文件 | 当前行数 | 改造后行数 | 增量 |
|------|---------|-----------|------|
| `director_tools.py` | 现有 | +60 | +60（2个新工具） |
| `director_agent.py` | 400+ | +5 | +5（导入+注册） |
| `visual_bible_service.py` | P3-01后~690 | ~790 | +100（2个业务编排方法） |
| `visual_bible.py`（API） | P3-01后~365 | ~400 | +35（1个接口+Body） |
| `prompts/tasks/omni_image_analysis.md` | 0 | ~80 | +80 |
| `prompts/tasks/omni_costume_derivation.md` | 0 | ~100 | +100 |
| `prompts/system/director.md` | 现有 | +30 | +30 |
| **合计** | | | **+410** |

#### P5-01 验收标准

1. Director ReAct Agent 的 tools 列表包含 `analyze_reference_image_tool` 和 `setup_costumes_tool`
2. Director 在 VisualBible 初始化前能通过 tool-calling 自动调用 `analyze_reference_image_tool` 分析用户上传的参考图
3. 上传不合适的角色参考图时，工具返回 `usable_directly=False, recommended_mode="image_to_image"`
4. Director 在叙事剧本确认后能通过 tool-calling 自动调用 `setup_costumes_tool` 触发多造型设置
5. `auto_analyze_and_setup_costumes()` 能一次性完成：图片分析→造型推导→批量生成→回写落库
6. 同一角色在 verse 和 chorus 段落有不同的造型定妆图
7. `prompts/tasks/` 下的两个 Omni prompt 模板存在且格式正确

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-03
- 产出：
  - `backend/app/tools/director/director_tools.py` — 修复 `analyze_reference_image_tool` 缺少 character_id 参数导致分析结果无法回写 DB 的 Bug
  - `backend/app/services/director_report_service.py` — 补凅 `generate_costume_ref` 和 `auto_setup_costumes` 到 `_REPORT_TASK_TYPES` 和 `_TASK_TO_ARTIFACT`
  - `backend/app/agents/director_agent.py` — `_build_trigger_result_summary()` 补充造型任务的汇报文案

---

### P4-01 + P3-01 + P5-01 联合验收标准

1. **Omni 音频分析**：偏差4完成后，音频分析通过 Omni 输出完整结构（含 chord_progression/instrumentation/five_second_analysis/lyrics），librosa 只负责 beat_map
2. **多造型数据**：偏差3完成后，CharacterSetVersion.characters 能存储多套造型数据，Shot 生成时按段落匹配造型
3. **业务闭环**：偏差5完成后，Director 通过 ReAct tool-calling 自动触发图片分析和多造型生成
4. **无破坏性变更**：旧版单造型功能不受影响，costumes 为空列表时 fallback 到 `active_reference_asset_id`
5. **WhisperX 移除**：`lyrics_alignment_tool.py` 的调用已从 service 链路中删除

---

### 风险与注意事项

1. **Omni 模型可用性**：偏差4依赖 Qwen3.5 Omni 模型在百炼平台的可用性，需要提前确认 API key 和 endpoint 配置。`config/providers/` 目录当前不存在，需要新建。
2. **JSONB 向前兼容**：CharacterSetVersion.characters 的 JSONB 结构扩展是向前兼容的，不需要 migration。旧数据中没有 costumes 字段时，代码需做空值保护。
3. **数据库变更方式**：`init_schema.sql` 是全新安装脚本，直接修改 CREATE TABLE。如果有已运行的数据库需要迁移，需要额外编写 migration SQL。
4. **并行改造风险**：三个任务必须按顺序执行，P5-01 依赖 P3-01 和 P4-01 的成果。
5. **Director 工具注册**：P5-01 新增的两个工具必须同步更新 `prompts/system/director.md`，否则 Director LLM 不知道何时调用它们。
6. **`_build_visual_bible_map` 和 `_map_shot_fields` 是模块级函数**：改造时注意这两个不是类方法，不需要 self 参数。



---

## 任务 16：支持完整歌曲 MV 生成改造 [完成]

**来源文档**：docs/16_VidMuse支持完整歌曲MV改造计划.md（独立计划，不在原 09 序列内）

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-04
- 批次说明：
  - **16-01**：打通完整歌曲入口（audio_end_sec 自动检测 + 30s 兜底清理）
  - **16-02**：突破镜头上限（max_shots 24→80）+ 修复并发锁（storyboard/clip）
  - **16-03**：稳定长音频分析（Omni URL 传输 + timeout/max_tokens 配置 + timeline 锁）
- 产出文件：15 个（详见 docs/16 执行记录）
- 实际改动量：约 180 行（新增 ~165，修改 ~15，无删除）

**执行记录**：
- 执行者：Warp AI (Oz)
- 产出：清理 frontend/vite.config.ts 与 package.json 代理配置，实现纯净分离前端。

### 任务 16-04：工作台交互闭环与 SSE 推送优化 [完成]

**当前为什么做**：
- 解决工作台交互瓶颈，消除冗余的决策提示和 UI 回环。
- 实现决策提交后直接触发后端工作流，确保产物即时推送并自动刷新。

**执行记录**：
- 执行者：Warp AI (Oz)
- 完成时间：2026-04-05
- 产出：
  - `frontend/src/pages/Workbench.tsx`：重构 `handleDecision` 自动映射逻辑，点击决策即触发后端任务（Style/Brief/ShotPlan/Storyboard/Clips）。
  - `frontend/src/lib/sse.ts`：补全 `REFRESH_EVENTS` 事件总线，支持所有阶段 Ready 信号的自动刷新。
  - `backend/app/services/decision_service.py`：新增 `has_selected_decision_of_type` 幂等查询方法。
  - `backend/app/workflows/nodes/human_confirmation_gate.py`：增加已选决策拦截逻辑，防止工作流回滚导致的决策重复弹出。

