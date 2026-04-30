# VidMuse 工程约束与执行计划设计

> 文档目标：定义项目落地阶段必须遵守的工程规则，以及基于前置依赖关系的开发执行顺序。
>
> 这份文档不是详细排期表，而是“开发怎么组织、模块怎么拆、产物怎么保存、提示词怎么管理、开发顺序怎么推进”的总规范。

---

## 1. 文档定位

前面的文档已经完成了：

- 产品定位与逆向理解
- 多 Agent 架构与 `LangGraph` 选型
- 数据库、消息与项目级记忆
- 状态机与事件流
- 表结构与 API
- 多 Agent 协议与 Prompt 编译
- 前端工作台初步设计

现在要进入“可开发”阶段，就必须先定工程约束。

这份文档解决的问题是：

- 代码目录怎么组织
- 配置怎么管理
- Prompt 怎么管理
- 阶段产物怎么保存
- 日志怎么分级
- 本地追溯文件怎么存
- 后端应该先做什么、后做什么
- 前端应该在哪个阶段介入什么程度

---

## 2. 工程原则

### 2.1 所有阶段产物必须可追溯

不仅数据库里要有版本和引用，**本地也必须保留阶段产物**。

至少包括：

- 输入音频
- 音频分析结果
- brief
- style bible
- shot plan
- storyboard
- prompt bundle
- clip 生成输入输出
- timeline
- export
- 执行日志

### 2.2 所有 Prompt 必须外部化

硬性规则：

- 不允许在业务代码中硬编码系统 prompt
- 不允许在代码中硬编码任务 prompt
- 不允许在代码中硬编码 provider prompt 模板

必须做到：

- Prompt 模板全部在外部文件中维护
- 支持版本化
- 支持按 Agent、按任务、按 provider 分类

### 2.3 所有业务配置必须从配置文件读取

硬性规则：

- 不通过环境变量承载业务参数
- 业务参数全部从配置文件读取

环境变量只允许承载：

- 极少量运行时底层信息
- 例如 Python path、容器基础变量这类非业务项

但本项目业务上应当默认：

> 配置文件为主，环境变量不是主配置来源。

### 2.4 日志必须分级

必须区分：

- 系统日志
- Agent 日志
- Tool 执行日志
- Prompt 编译日志
- 项目阶段产物日志

### 2.5 开发顺序必须遵守依赖链

这个项目不是平铺开发，而是有明显的前置关系。

例如：

- 没有项目与状态机，就不能稳定做 Agent
- 没有表结构与 API，就不能稳定做前端工作台
- 没有 Prompt 编译与 provider 适配，就不能稳定做生成链路

---

## 3. 总体工程目录建议

第一版建议采用单仓库结构，但要按模块边界拆清楚。

```text
vidmuse/
  docs/
  config/
  prompts/
  data/
  logs/
  backend/
  frontend/
  scripts/
  tests/
```

### 3.1 各顶层目录职责

#### `docs/`

存放所有架构、设计、协议、API、原型说明文档。

#### `config/`

存放全部配置文件。

#### `prompts/`

存放全部外部化 Prompt 模板。

#### `data/`

存放本地产物、调试产物、阶段结果快照。

#### `logs/`

存放日志文件。

#### `backend/`

后端服务代码。

#### `frontend/`

前端工作台代码。

#### `scripts/`

初始化、导入、运维辅助、调试脚本。

#### `tests/`

测试代码。

---

## 4. 后端目录结构建议

```text
backend/
  app/
    api/
    core/
    domain/
    services/
    agents/
    tools/
    providers/
    workflows/
    repositories/
    schemas/
    models/
    storage/
    events/
    tasks/
    utils/
  migrations/
  main.py
```

### 4.1 目录职责说明

#### `api/`

放：

- `/api/v1` 控制面接口
- `/v1/chat/completions` 推理接口
- SSE 接口

#### `core/`

放：

- 应用初始化
- 配置加载
- 日志初始化
- 基础异常
- 安全组件

#### `domain/`

放：

- 项目状态枚举
- 领域规则
- 核心领域对象定义

#### `services/`

放：

- 状态机服务
- Prompt 编译服务
- 时间线合成服务
- 决策服务
- 版本切换服务

#### `agents/`

放：

- 导演 Agent
- 音乐分析 Agent
- 创意规划 Agent
- 一致性质检 Agent

#### `tools/`

放：

- 标准化 Tool 接口
- 工具执行器
- Tool schema

#### `providers/`

放：

- 图片 provider 适配器
- 视频 provider 适配器
- lipsync provider 适配器
- 音频分析 provider 适配器

#### `workflows/`

放：

- LangGraph 图定义
- 节点逻辑
- graph state

#### `repositories/`

放：

- 数据访问层

#### `schemas/`

放：

- Pydantic 请求/响应模型
- DTO
- command / event / decision schema

#### `models/`

放：

- SQLAlchemy ORM 模型

#### `storage/`

放：

- MinIO 适配器
- 本地产物存储器
- 文件路径规划器

#### `events/`

放：

- Outbox publisher
- 事件消费者
- 事件封装器

#### `tasks/`

放：

- Celery / RQ 任务
- 长耗时后台任务

---

## 5. 前端目录结构建议

前端目录初步建议前面文档已写，这里从工程执行角度再强调一次。

```text
frontend/
  src/
    app/
    components/
    features/
    lib/
    stores/
    hooks/
    types/
    styles/
  public/
```

前端重点原则：

- 页面路由和业务 feature 分开
- SSE 处理集中
- API 调用集中
- 类型定义统一

---

## 6. 配置文件规范

### 6.1 总原则

所有业务配置都从配置文件读取，不从环境变量读取。

### 6.2 配置目录建议

```text
config/
  base/
    app.yaml
    database.yaml
    redis.yaml
    storage.yaml
    logging.yaml
    workflow.yaml
    billing.yaml
  prompts/
    prompt_registry.yaml
  providers/
    image_providers.yaml
    video_providers.yaml
    audio_providers.yaml
    lipsync_providers.yaml
  frontend/
    app.json
```

### 6.3 配置分类

#### `app.yaml`

放：

- 应用名
- 运行模式
- API 前缀
- 默认分页

#### `database.yaml`

放：

- 数据库连接
- 连接池
- 超时

#### `redis.yaml`

放：

- Redis 地址
- 队列名
- 过期时间

#### `storage.yaml`

放：

- MinIO 连接信息
- bucket 配置
- 本地产物根目录
- 本地调试文件保存策略

#### `workflow.yaml`

放：

- 状态机规则开关
- 自动重试次数
- 是否允许 provider fallback

#### `billing.yaml`

放：

- credits 价格规则
- 各工具单价
- 免费额度

#### `image_providers.yaml / video_providers.yaml`

放：

- provider 名称
- 调用地址
- 支持能力
- 参数映射
- 默认参数

### 6.4 配置读取方式

后端统一做：

- `ConfigLoader`
- `SettingsRegistry`

前端统一做：

- 运行配置读取器

禁止：

- 业务代码里到处直接读配置文件

---

## 7. Prompt 外部化规范

### 7.1 Prompt 目录建议

```text
prompts/
  system/
    director.md
    audio_analysis.md
    creative_planning.md
    consistency_guardian.md
  tasks/
    clarify_missing_fields.md
    generate_brief.md
    generate_shot_plan.md
    review_consistency.md
  compiler/
    compile_image_prompt.md
    compile_video_prompt.md
    compile_lipsync_prompt.md
  providers/
    image/
      provider_a.md
      provider_b.md
    video/
      provider_x.md
      provider_y.md
    lipsync/
      provider_z.md
```

### 7.2 Prompt 分类规则

#### `system/`

放 Agent 的系统提示词。

#### `tasks/`

放 Agent 某类任务的任务提示词模板。

#### `compiler/`

放 Prompt 编译服务内部模板。

#### `providers/`

放 provider 特定适配模板。

### 7.3 Prompt 文件格式建议

建议采用：

- Markdown 模板
- 配合 YAML metadata

例如：

```markdown
---
name: director_system
version: 1
variables:
  - project_stage
  - available_tools
---

你是系统中的导演 Agent...
```

### 7.4 Prompt 渲染机制

需要统一做：

- `PromptRegistry`
- `PromptLoader`
- `PromptRenderer`

作用：

- 根据名字加载模板
- 校验变量是否齐全
- 输出最终 prompt

### 7.5 不允许的做法

- 在 Python 代码里直接写多行 prompt 字符串
- 在 Tool 层临时拼 prompt
- 不留版本号直接手改

---

## 8. 本地产物保存规范

这是你特别强调的重点，必须单独定义。

### 8.1 为什么本地也要保存

因为数据库只保存：

- 结构化索引
- 元数据
- 版本关系

但开发和调试还需要：

- 原始 prompt
- provider 原始请求/响应
- 原始阶段文件
- 调试日志
- 对比结果

### 8.2 本地产物根目录

建议：

```text
data/
  projects/
```

### 8.3 项目级目录结构

```text
data/
  projects/
    {project_id}/
      01_input/
      02_audio_analysis/
      03_brief/
      04_style/
      05_shot_plan/
      06_storyboard/
      07_prompt_bundles/
      08_clips/
      09_timeline/
      10_export/
      logs/
      snapshots/
```

### 8.4 各目录保存内容

#### `01_input/`

- 原始音频副本
- 切段音频
- 参考图副本
- 初始输入 JSON

#### `02_audio_analysis/`

- beat map JSON
- section map JSON
- lyrics alignment JSON
- 音频分析摘要

#### `03_brief/`

- brief JSON
- brief 文本导出

#### `04_style/`

- style bible JSON
- 角色集 JSON

#### `05_shot_plan/`

- shot plan JSON
- 每个 shot semantic spec JSON

#### `06_storyboard/`

- storyboard 图片
- storyboard 元数据 JSON

#### `07_prompt_bundles/`

- 每个 shot 的 prompt bundle JSON
- provider 最终请求 payload

#### `08_clips/`

- 生成 clip 文件副本
- clip 执行结果 JSON

#### `09_timeline/`

- timeline JSON
- 字幕轨文件
- preview 文件

#### `10_export/`

- 导出结果文件
- 导出元数据

#### `logs/`

- 项目级日志
- agent 日志
- tool 日志

#### `snapshots/`

- graph snapshot
- 项目 memory snapshot

### 8.5 命名规范

文件名建议：

```text
{阶段}_{对象名}_{版本号}_{时间戳}.json
```

例如：

```text
shot_plan_v3_20260327_103000.json
prompt_bundle_shot_008_v2_20260327_104210.json
```

---

## 9. 日志分级规范

### 9.1 日志层级

至少分四层：

- `system`
- `agent`
- `tool`
- `project`

### 9.2 日志目录建议

```text
logs/
  system/
  agent/
  tool/
  project/
```

### 9.3 系统日志

记录：

- 服务启动
- 配置加载
- 全局异常
- SSE 连接异常

### 9.4 Agent 日志

记录：

- 输入上下文摘要
- 加载的 prompt 模板名
- 输出结构化结果
- 决策路径

注意：

- 不要无边界打印全量隐私内容
- 但调试阶段可保留本地详细版

### 9.5 Tool 日志

记录：

- provider
- 输入 hash
- 请求参数摘要
- 返回状态
- 重试次数
- 产物路径

### 9.6 项目日志

按项目记录：

- 阶段推进
- 回退
- stale 标记
- 重要决策
- 导出事件

### 9.7 日志格式

建议：

- 统一 JSON 日志

至少包含：

- `timestamp`
- `level`
- `module`
- `project_id`
- `task_id`
- `event_type`
- `message`

---

## 10. 本地追溯与数据库追溯的关系

### 10.1 数据库负责什么

- 结构化查询
- 版本关系
- active 指针
- 任务状态
- 事件索引

### 10.2 本地文件负责什么

- 调试
- 原始产物保留
- prompt 快照
- 原始 provider payload
- 问题排查

### 10.3 两者如何关联

数据库记录中应尽量保存：

- 本地路径
- MinIO 对象路径
- artifact snapshot id

这样前后能互相追溯。

---

## 11. 开发执行顺序的原则

### 11.1 先做基础设施，再做智能能力

不能一开始就先接模型。  
正确顺序是：

- 先工程骨架
- 再数据与状态
- 再 Agent 与 workflow
- 再 Tool 和 provider
- 再前端联调

### 11.2 先做“稳定对象”，再做“复杂界面”

要先确定：

- `ProjectSpec`
- `AudioAnalysis`
- `CreativeBrief`
- `Shot`
- `PromptBundle`
- `Clip`
- `Timeline`

然后前端才有稳定对象可以绑定。

### 11.3 先做“低风险闭环”，再做“高成本生成”

建议先打通：

- 登录
- 项目
- 输入
- 音频分析
- brief
- shot plan
- Chat + SSE

再接：

- storyboard
- 视频生成
- lipsync
- export

---

## 12. 基于依赖链的开发阶段

这里不是详细排期，而是依赖驱动的阶段划分。

### 阶段 1：工程骨架

目标：

- 项目可运行
- 配置可加载
- 日志可用
- Prompt 可外部读取
- 基础目录结构建立

必须完成：

- monorepo / 单仓库结构
- backend / frontend 基础脚手架
- 配置加载器
- Prompt Registry
- 日志初始化
- MinIO 适配器骨架

### 阶段 2：数据与状态骨架

目标：

- 数据库模型可用
- 状态机可运行
- 项目与会话可管理

必须完成：

- `users`、`projects`、`conversation_sessions`
- 版本表骨架
- `agent_tasks`、`tool_jobs`、`event_logs`
- 状态机服务
- Outbox 骨架

### 阶段 3：控制面 API

目标：

- 前端和后端可以对接基础业务流

必须完成：

- 登录
- 项目 CRUD
- 资产上传
- 项目详情
- 版本查询
- 决策提交
- 项目事件 SSE

### 阶段 4：多 Agent 编排骨架

目标：

- Director Agent 跑起来
- LangGraph 主图跑起来

必须完成：

- graph state
- 导演 Agent
- 音乐分析 Agent
- 创意规划 Agent
- 一致性质检 Agent 占位
- intent resolution

### 阶段 5：分析与规划闭环

目标：

- 从输入到 shot plan 完整可跑

必须完成：

- 音频分析工具接入
- brief 生成
- shot plan 生成
- Prompt 编译服务骨架
- 本地产物保存

### 阶段 6：前端工作台骨架

目标：

- 用户能在 UI 上看到完整流程骨架

必须完成：

- 登录页
- 项目列表页
- 项目工作台三栏
- Pipeline
- Chat
- 输入页
- 音频分析页
- brief / shot plan 页

### 阶段 7：媒体生成闭环

目标：

- storyboard、clip、timeline 跑通

必须完成：

- 图片工具接入
- 视频工具接入
- storyboard
- prompt bundle 落库
- timeline 合成服务

### 阶段 8：导出与返工闭环

目标：

- 局部返工和导出可用

必须完成：

- shot 局部重生成
- timeline 替换 segment
- 导出
- 回退
- stale 传播

---

## 13. 前后端协同顺序

### 13.1 前端不应过早进入高保真

原因：

- API 未稳定时，原型容易白做
- 对象模型未稳定时，UI 容易返工

### 13.2 正确顺序

建议：

1. 先完成前端骨架页
2. 接控制面 API
3. 接 SSE
4. 接对话
5. 接阶段详情
6. API 稳定后再做高保真原型和 UI 细化

这点和你说的方向一致。

---

## 14. 代码级执行规则

### 14.1 不允许的做法

- 把 prompt 写死在代码里
- 在业务逻辑里散落读配置文件
- Tool 层直接改数据库
- Agent 直接绕过状态机
- 阶段产物只存数据库不落本地
- provider 调用无本地日志和 payload 快照

### 14.2 必须做到的做法

- Prompt 统一从 `prompts/` 加载
- 配置统一从 `config/` 加载
- 本地产物统一从 `data/projects/{project_id}` 落盘
- 本地日志统一从 `logs/` 管理
- provider 调用统一走 Tool 和 ProviderAdapter
- 状态推进统一走 StateTransitionService

---

## 15. 当前阶段的开发优先级判断

如果从现在开始正式进入开发，我建议最先做的不是 UI，而是：

1. 后端目录结构与配置体系
2. Prompt 外部化体系
3. MinIO + 本地产物保存体系
4. 数据模型与迁移
5. 状态机服务
6. 控制面 API
7. LangGraph 主图骨架

然后再进入前端联调。

这是因为这个项目的真正稳定性来自：

- 数据与状态
- 配置与 prompt
- 产物追溯

而不是先把页面搭出来。

---

## 16. 现在可以拍板的工程结论

- 仓库采用单仓库结构
- 配置全部走 `config/`
- Prompt 全部走 `prompts/`
- 阶段产物全部落 `data/projects/{project_id}/...`
- 日志统一走 `logs/`
- 对象存储第一版用 `MinIO`
- 开发顺序必须按依赖链推进
- 前端先做骨架，后做高保真原型

---

## 17. 下一步建议

在这份文档之后，已经具备进入“真正执行计划设计”的条件了。

下一份文档建议是：

- `09_VidMuse后端实施顺序与模块拆分.md`

它应该更具体地写：

- 后端先实现哪些模块
- 每个模块的输入输出
- 哪些模块可以并行
- 哪些模块必须按顺序
- 每阶段完成后的验收标准

然后再写：

- `10_VidMuse前端实施顺序与原型设计准备.md`

