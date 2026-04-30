-- =============================================================================
-- VidMuse 完整数据库 Schema
--
-- 设计依据：
--   doc03 数据库消息与记忆系统设计
--   doc04 状态机与事件流规范
--   doc05 表结构与 API 字段规范（权威字段定义来源）
--
-- 约束规则：
--   1. 主键统一 VARCHAR(26) ULID，应用层生成
--   2. 状态字段使用 VARCHAR + CHECK 约束，不使用 Postgres ENUM
--   3. projects.active_*_version_id 指针字段不建外键（规避循环依赖），由应用层维护一致性
--   4. 所有 JSONB 字段提供有意义的 server_default
--   5. updated_at 由应用层 ORM 负责更新（SQLAlchemy onupdate）；
--      如需数据库级保障，可启用末尾的 update_updated_at 触发器（默认注释）
--
-- 建表顺序（严格按外键依赖链）：
--   1  users
--   2  user_preferences
--   3  projects
--   4  conversation_sessions
--   5  conversation_messages
--   6  session_contexts
--   7  assets
--   8  project_spec_versions
--   9  audio_analysis_versions
--   10 creative_brief_versions
--   11 style_bible_versions
--   12 character_set_versions
--   13 scene_plan_versions
--   14 shot_plan_versions
--   15 shots
--   16 storyboard_versions
--   17 storyboard_frames          （prompt_bundle_id FK 延迟到 #19 之后 ALTER）
--   18 prompt_bundles
--   19 ALTER storyboard_frames ADD FK prompt_bundle_id
--   20 clip_versions
--   21 timeline_versions
--   22 timeline_segments
--   23 export_versions
--   24 pending_decisions
--   25 ALTER conversation_sessions ADD FK pending_decision_id
--   26 agent_tasks
--   27 tool_jobs
--   28 event_logs
--   29 outbox_events
--   30 credit_ledger
--
-- 使用方式（全新安装）：
--   psql -U <user> -d <dbname> -f scripts/init_schema.sql
--
-- 版本：1.2   日期：2026-04-03（prompt_bundles 补齐 source_*_version_id + reference_image_url + reference_asset_ids）
-- =============================================================================


-- =============================================================================
-- 0. 扩展
-- =============================================================================

-- pgcrypto 供未来可能的服务端加密使用，现阶段可选
-- CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- =============================================================================
-- 1. AUTH — users / user_preferences
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(26)     NOT NULL,
    username        VARCHAR(64)     NOT NULL,
    password_hash   VARCHAR(255)    NOT NULL,
    status          VARCHAR(32)     NOT NULL    DEFAULT 'active',
    last_login_at   TIMESTAMPTZ                 DEFAULT NULL,
    credits         INTEGER         NOT NULL    DEFAULT 200,
    plan_type       VARCHAR(32)     NOT NULL    DEFAULT 'free',
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT uq_users_username UNIQUE (username),
    CONSTRAINT ck_users_status CHECK (status IN ('active', 'disabled'))
);

-- 补列（幂等，对已建库执行 ALTER；全新安装时上方 CREATE TABLE 已包含，IF NOT EXISTS 保证不报错）
ALTER TABLE users ADD COLUMN IF NOT EXISTS credits   INTEGER      NOT NULL DEFAULT 200;
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_type VARCHAR(32)  NOT NULL DEFAULT 'free';


CREATE TABLE IF NOT EXISTS user_preferences (
    id                      VARCHAR(26)     NOT NULL,
    user_id                 VARCHAR(26)     NOT NULL,
    default_language        VARCHAR(16)                 DEFAULT NULL,
    default_aspect_ratio    VARCHAR(16)                 DEFAULT NULL,
    default_resolution      VARCHAR(16)                 DEFAULT NULL,
    favorite_style_tags     JSONB           NOT NULL    DEFAULT '[]',
    created_at              TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_user_preferences PRIMARY KEY (id),
    CONSTRAINT uq_user_preferences_user UNIQUE (user_id),
    CONSTRAINT fk_user_preferences_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE CASCADE
);


-- =============================================================================
-- 2. PROJECT — projects
-- =============================================================================
-- active_*_version_id：应用层维护，不建 FK，规避循环依赖
-- =============================================================================

CREATE TABLE IF NOT EXISTS projects (
    id              VARCHAR(26)     NOT NULL,
    user_id         VARCHAR(26)     NOT NULL,
    name            VARCHAR(255)    NOT NULL,
    cover_url       VARCHAR(1024)               DEFAULT NULL,
    status          VARCHAR(32)     NOT NULL    DEFAULT 'active',
    current_stage   VARCHAR(32)     NOT NULL    DEFAULT 'created',

    -- Active version pointers（app-managed，no FK to avoid circular deps）
    active_project_spec_version_id      VARCHAR(26)     DEFAULT NULL,
    active_audio_analysis_version_id    VARCHAR(26)     DEFAULT NULL,
    active_brief_version_id             VARCHAR(26)     DEFAULT NULL,
    active_style_version_id             VARCHAR(26)     DEFAULT NULL,
    active_character_set_version_id     VARCHAR(26)     DEFAULT NULL,
    active_narrative_script_version_id  VARCHAR(26)     DEFAULT NULL,  -- doc11 新增
    active_scene_plan_version_id        VARCHAR(26)     DEFAULT NULL,
    active_shot_plan_version_id         VARCHAR(26)     DEFAULT NULL,
    active_storyboard_version_id        VARCHAR(26)     DEFAULT NULL,
    active_timeline_version_id          VARCHAR(26)     DEFAULT NULL,
    latest_export_version_id            VARCHAR(26)     DEFAULT NULL,

    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_projects PRIMARY KEY (id),
    CONSTRAINT fk_projects_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT ck_projects_status CHECK (
        status IN ('active', 'archived', 'failed')
    ),
    CONSTRAINT ck_projects_current_stage CHECK (
        current_stage IN (
            'created', 'input_ready', 'audio_analyzed', 'brief_ready',
            'narrative_ready', 'visual_bible_ready',
            'shot_plan_ready', 'storyboard_ready', 'clips_ready',
            'timeline_ready', 'export_ready', 'completed', 'failed'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_projects_user_updated
    ON projects (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_projects_stage
    ON projects (user_id, current_stage);


-- =============================================================================
-- 3. CONVERSATION — conversation_sessions / conversation_messages / session_contexts
-- =============================================================================
-- pending_decision_id FK 延迟到 pending_decisions 建完后 ALTER
-- =============================================================================

CREATE TABLE IF NOT EXISTS conversation_sessions (
    id                          VARCHAR(26)     NOT NULL,
    project_id                  VARCHAR(26)     NOT NULL,
    status                      VARCHAR(32)     NOT NULL    DEFAULT 'active',
    last_selected_entity_type   VARCHAR(32)                 DEFAULT NULL,
    last_selected_entity_id     VARCHAR(26)                 DEFAULT NULL,
    pending_decision_id         VARCHAR(26)                 DEFAULT NULL, -- FK added later
    created_at                  TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_conversation_sessions PRIMARY KEY (id),
    CONSTRAINT fk_conversation_sessions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT ck_conversation_sessions_status CHECK (
        status IN ('active', 'closed')
    )
);

CREATE INDEX IF NOT EXISTS idx_conversation_sessions_project
    ON conversation_sessions (project_id, updated_at DESC);


CREATE TABLE IF NOT EXISTS conversation_messages (
    id              VARCHAR(26)     NOT NULL,
    session_id      VARCHAR(26)     NOT NULL,
    role            VARCHAR(32)     NOT NULL,
    message_type    VARCHAR(32)     NOT NULL,
    content_text    TEXT                        DEFAULT NULL,
    content_json    JSONB                       DEFAULT NULL,
    model           VARCHAR(128)                DEFAULT NULL,
    token_usage     JSONB                       DEFAULT NULL,
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    -- append-only：无 updated_at

    CONSTRAINT pk_conversation_messages PRIMARY KEY (id),
    CONSTRAINT fk_conversation_messages_session FOREIGN KEY (session_id)
        REFERENCES conversation_sessions (id) ON DELETE CASCADE,
    CONSTRAINT ck_conversation_messages_role CHECK (
        role IN ('user', 'assistant', 'tool', 'system')
    ),
    CONSTRAINT ck_conversation_messages_type CHECK (
        message_type IN (
            'user_text', 'assistant_text', 'assistant_options',
            'assistant_confirmation', 'tool_call', 'tool_result',
            'system_event_summary'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_session_created
    ON conversation_messages (session_id, created_at);


CREATE TABLE IF NOT EXISTS session_contexts (
    session_id              VARCHAR(26)     NOT NULL,
    project_id              VARCHAR(26)     NOT NULL,
    selected_entity_type    VARCHAR(32)                 DEFAULT NULL,
    selected_entity_id      VARCHAR(26)                 DEFAULT NULL,
    pending_option_set_id   VARCHAR(26)                 DEFAULT NULL,
    pending_confirmation_id VARCHAR(26)                 DEFAULT NULL,
    recent_agent_summary    JSONB           NOT NULL    DEFAULT '{}',
    updated_at              TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    -- 以 session_id 为 PK，无 created_at（只跟踪最新状态）

    CONSTRAINT pk_session_contexts PRIMARY KEY (session_id),
    CONSTRAINT fk_session_contexts_session FOREIGN KEY (session_id)
        REFERENCES conversation_sessions (id) ON DELETE CASCADE,
    CONSTRAINT fk_session_contexts_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE
);


-- =============================================================================
-- 4. ASSETS — assets / project_spec_versions
-- =============================================================================

CREATE TABLE IF NOT EXISTS assets (
    id              VARCHAR(26)     NOT NULL,
    project_id      VARCHAR(26)     NOT NULL,
    asset_type      VARCHAR(32)     NOT NULL,
    bucket_name     VARCHAR(128)    NOT NULL,
    object_key      VARCHAR(512)    NOT NULL,
    storage_uri     VARCHAR(1024)   NOT NULL,
    mime_type       VARCHAR(128)    NOT NULL,
    size_bytes      BIGINT                      DEFAULT NULL,
    duration_ms     INTEGER                     DEFAULT NULL,
    width           INTEGER                     DEFAULT NULL,
    height          INTEGER                     DEFAULT NULL,
    sha256          VARCHAR(64)                 DEFAULT NULL,
    metadata        JSONB           NOT NULL    DEFAULT '{}',
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    -- 资产一经落库不允许修改（不可变）：无 updated_at

    CONSTRAINT pk_assets PRIMARY KEY (id),
    CONSTRAINT fk_assets_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT ck_assets_type CHECK (
        asset_type IN (
            'audio_original', 'audio_trimmed',
            'image_reference', 'style_reference',
            'storyboard_frame', 'clip_video',
            'export_video', 'subtitle_file', 'thumbnail',
            'character_reference', 'scene_reference', 'prop_reference',
            'audio_analysis', 'creative_brief', 'style_bible',
            'narrative_script', 'scene_plan', 'shot_plan',
            'visual_bible', 'storyboard', 'prompt_bundle', 'timeline'
            -- doc11 新增：character_reference（角色定妆图）/ scene_reference（场景参考图）/ prop_reference（道具）
            -- doc12 偏差6：文本产物与规划产物也纳入统一 ArtifactRef 持久化协议
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_assets_project_type_created
    ON assets (project_id, asset_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_assets_sha256
    ON assets (sha256)
    WHERE sha256 IS NOT NULL;  -- partial index，只索引有值行


CREATE TABLE IF NOT EXISTS project_spec_versions (
    id              VARCHAR(26)     NOT NULL,
    project_id      VARCHAR(26)     NOT NULL,
    version_no      INTEGER         NOT NULL,
    input_mode      VARCHAR(32)     NOT NULL,
    audio_asset_id  VARCHAR(26)                 DEFAULT NULL,
    audio_start_sec NUMERIC(10, 3)  NOT NULL    DEFAULT 0,
    audio_end_sec   NUMERIC(10, 3)  NOT NULL    DEFAULT 0,
    user_prompt     TEXT            NOT NULL    DEFAULT '',
    output_config   JSONB           NOT NULL    DEFAULT '{}',
    reference_image_asset_ids JSONB NOT NULL    DEFAULT '[]',  -- 用户上传的角色参考图，顺序即上传顺序
    constraints     JSONB           NOT NULL    DEFAULT '{}',
    created_by      VARCHAR(32)     NOT NULL    DEFAULT 'user',
    source_event_id VARCHAR(26)                 DEFAULT NULL,
    is_active       BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_project_spec_versions PRIMARY KEY (id),
    CONSTRAINT uq_project_spec_versions_no UNIQUE (project_id, version_no),
    CONSTRAINT fk_project_spec_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_project_spec_versions_audio FOREIGN KEY (audio_asset_id)
        REFERENCES assets (id) ON DELETE SET NULL,
    CONSTRAINT ck_project_spec_versions_mode CHECK (
        input_mode IN ('audio_text', 'audio_image_text')
    )
);

CREATE INDEX IF NOT EXISTS idx_project_spec_versions_project_active
    ON project_spec_versions (project_id, is_active);


-- =============================================================================
-- 5. ANALYSIS & PLANNING
--    audio_analysis_versions / creative_brief_versions / style_bible_versions /
--    character_set_versions / narrative_script_versions /
--    scene_plan_versions / shot_plan_versions
-- =============================================================================

CREATE TABLE IF NOT EXISTS audio_analysis_versions (
    id              VARCHAR(26)     NOT NULL,
    project_id      VARCHAR(26)     NOT NULL,
    version_no      INTEGER         NOT NULL,
    audio_asset_id  VARCHAR(26)                 DEFAULT NULL,
    bpm             NUMERIC(8, 3)               DEFAULT NULL,
    beat_map        JSONB           NOT NULL    DEFAULT '[]',
    section_map     JSONB           NOT NULL    DEFAULT '[]',
    energy_curve    JSONB           NOT NULL    DEFAULT '[]',
    lyrics_alignment JSONB          NOT NULL    DEFAULT '[]',
    raw_payload     JSONB           NOT NULL    DEFAULT '{}',
    quality_summary JSONB           NOT NULL    DEFAULT '{}',
    -- Qwen3.5 Omni 扩展字段
    chord_progression JSONB       NOT NULL    DEFAULT '[]',
    instrumentation   JSONB       NOT NULL    DEFAULT '[]',
    five_second_analysis JSONB    NOT NULL    DEFAULT '[]',
    key_scale       VARCHAR(16)                 DEFAULT NULL,  -- 调式，如 "D major"
    time_signature  VARCHAR(8)                  DEFAULT NULL,  -- 拍号，如 "4/4"
    style_caption   TEXT                        DEFAULT NULL,  -- Omni 自然语言风格描述
    genre           TEXT                        DEFAULT NULL,  -- Omni 结构化风格分类，如 "OST抒情" / "Hip-Hop"
    emotional_curve_graph JSONB     NOT NULL    DEFAULT '[]', -- 整体情绪曲线关键点数组
    lrc_asset_id    VARCHAR(26)                 DEFAULT NULL,  -- LRC 歌词文件 asset_id
    analysis_provider JSONB                     DEFAULT NULL,  -- 各分析项所用 provider 记录
    is_active       BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_audio_analysis_versions PRIMARY KEY (id),
    CONSTRAINT uq_audio_analysis_versions_no UNIQUE (project_id, version_no),
    CONSTRAINT fk_audio_analysis_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_audio_analysis_versions_asset FOREIGN KEY (audio_asset_id)
        REFERENCES assets (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_audio_analysis_versions_project_active
    ON audio_analysis_versions (project_id, is_active);


CREATE TABLE IF NOT EXISTS creative_brief_versions (
    id                  VARCHAR(26)     NOT NULL,
    project_id          VARCHAR(26)     NOT NULL,
    version_no          INTEGER         NOT NULL,
    title               VARCHAR(255)                DEFAULT NULL,
    summary             TEXT            NOT NULL    DEFAULT '',
    narrative_mode      VARCHAR(32)     NOT NULL    DEFAULT 'mixed',
    performance_ratio   NUMERIC(5, 2)   NOT NULL    DEFAULT 0.5,
    mood_tags           JSONB           NOT NULL    DEFAULT '[]',
    style_direction     TEXT            NOT NULL    DEFAULT '',
    raw_payload         JSONB           NOT NULL    DEFAULT '{}',
    is_active           BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at          TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_creative_brief_versions PRIMARY KEY (id),
    CONSTRAINT uq_creative_brief_versions_no UNIQUE (project_id, version_no),
    CONSTRAINT fk_creative_brief_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_creative_brief_versions_project_active
    ON creative_brief_versions (project_id, is_active);


CREATE TABLE IF NOT EXISTS style_bible_versions (
    id              VARCHAR(26)     NOT NULL,
    project_id      VARCHAR(26)     NOT NULL,
    version_no      INTEGER         NOT NULL,
    palette         JSONB           NOT NULL    DEFAULT '{}',
    lighting_style  TEXT            NOT NULL    DEFAULT '',
    camera_style    TEXT            NOT NULL    DEFAULT '',
    film_texture    TEXT                        DEFAULT NULL,
    reference_notes TEXT                        DEFAULT NULL,
    raw_payload     JSONB           NOT NULL    DEFAULT '{}',
    is_active       BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_style_bible_versions PRIMARY KEY (id),
    CONSTRAINT uq_style_bible_versions_no UNIQUE (project_id, version_no),
    CONSTRAINT fk_style_bible_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_style_bible_versions_project_active
    ON style_bible_versions (project_id, is_active);


-- character_set_versions（doc11 §4.4 VisualBible，补充 characters/scenes/confirmed_at 字段）
CREATE TABLE IF NOT EXISTS character_set_versions (
    id              VARCHAR(26)     NOT NULL,
    project_id      VARCHAR(26)     NOT NULL,
    version_no      INTEGER         NOT NULL,
    -- 角色列表（来自 NarrativeScript 的 characters，JSONB array）
    characters      JSONB           NOT NULL    DEFAULT '[]',
    -- 场景列表（来自 NarrativeScript 的 scenes，JSONB array）
    scenes          JSONB           NOT NULL    DEFAULT '[]',
    -- 用户逐一确认视觉圣经的时间戳（NULL 表示未确认）
    confirmed_at    VARCHAR(64)                 DEFAULT NULL,
    -- 完整原始载荷（供审阅和追溯）
    raw_payload     JSONB           NOT NULL    DEFAULT '{}',
    is_active       BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_character_set_versions PRIMARY KEY (id),
    CONSTRAINT uq_character_set_versions_no UNIQUE (project_id, version_no),
    CONSTRAINT ck_character_set_versions_no CHECK (version_no >= 1),
    CONSTRAINT fk_character_set_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_character_set_versions_project_active
    ON character_set_versions (project_id, is_active);


-- narrative_script_versions（doc11 §5.4 新增）
CREATE TABLE IF NOT EXISTS narrative_script_versions (
    id              VARCHAR(26)     NOT NULL,
    project_id      VARCHAR(26)     NOT NULL,
    version_no      INTEGER         NOT NULL,
    story_arc       TEXT            NOT NULL    DEFAULT '',
    characters      JSONB           NOT NULL    DEFAULT '[]',
    scenes          JSONB           NOT NULL    DEFAULT '[]',
    section_mapping JSONB           NOT NULL    DEFAULT '[]',
    raw_payload     JSONB           NOT NULL    DEFAULT '{}',
    is_active       BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_narrative_script_versions PRIMARY KEY (id),
    CONSTRAINT uq_narrative_script_versions_no UNIQUE (project_id, version_no),
    CONSTRAINT ck_narrative_script_versions_no CHECK (version_no >= 1),
    CONSTRAINT fk_narrative_script_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_narrative_script_versions_project_active
    ON narrative_script_versions (project_id, is_active);


CREATE TABLE IF NOT EXISTS scene_plan_versions (
    id          VARCHAR(26)     NOT NULL,
    project_id  VARCHAR(26)     NOT NULL,
    version_no  INTEGER         NOT NULL,
    raw_payload JSONB           NOT NULL    DEFAULT '{}',
    is_active   BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at  TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_scene_plan_versions PRIMARY KEY (id),
    CONSTRAINT uq_scene_plan_versions_no UNIQUE (project_id, version_no),
    CONSTRAINT fk_scene_plan_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scene_plan_versions_project_active
    ON scene_plan_versions (project_id, is_active);


CREATE TABLE IF NOT EXISTS shot_plan_versions (
    id          VARCHAR(26)     NOT NULL,
    project_id  VARCHAR(26)     NOT NULL,
    version_no  INTEGER         NOT NULL,
    raw_payload JSONB           NOT NULL    DEFAULT '{}',
    is_active   BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at  TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_shot_plan_versions PRIMARY KEY (id),
    CONSTRAINT uq_shot_plan_versions_no UNIQUE (project_id, version_no),
    CONSTRAINT fk_shot_plan_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_shot_plan_versions_project_active
    ON shot_plan_versions (project_id, is_active);


-- =============================================================================
-- 6. SHOTS & STORYBOARD
--    shots / storyboard_versions / storyboard_frames
-- =============================================================================

CREATE TABLE IF NOT EXISTS shots (
    id                      VARCHAR(26)     NOT NULL,
    project_id              VARCHAR(26)     NOT NULL,
    shot_plan_version_id    VARCHAR(26)     NOT NULL,
    scene_id                VARCHAR(64)                 DEFAULT NULL,
    shot_index              INTEGER         NOT NULL,
    start_ms                INTEGER         NOT NULL,
    end_ms                  INTEGER         NOT NULL,
    duration_ms             INTEGER         NOT NULL,
    section_type            VARCHAR(32)     NOT NULL    DEFAULT 'verse',
    lyric_text              TEXT                        DEFAULT NULL,
    dialogue                TEXT                        DEFAULT NULL,
    emotion                 VARCHAR(128)                DEFAULT NULL,
    emotion_intensity       VARCHAR(32)                 DEFAULT NULL,  -- low/medium/high/very_high，情绪强度等级
    shot_type               VARCHAR(32)     NOT NULL    DEFAULT 'medium',
    subject                 TEXT                        DEFAULT NULL,  -- 镜头视觉主体描述
    location                TEXT                        DEFAULT NULL,  -- 场景位置描述
    camera_language         TEXT                        DEFAULT NULL,
    visual_energy           VARCHAR(32)                 DEFAULT NULL,
    lipsync_required        BOOLEAN         NOT NULL    DEFAULT FALSE,
    character_binding       JSONB           NOT NULL    DEFAULT '[]',
    style_binding           JSONB           NOT NULL    DEFAULT '[]',
    status                  VARCHAR(32)     NOT NULL    DEFAULT 'planned',
    created_at              TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_shots PRIMARY KEY (id),
    CONSTRAINT fk_shots_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_shots_shot_plan_version FOREIGN KEY (shot_plan_version_id)
        REFERENCES shot_plan_versions (id) ON DELETE CASCADE,
    CONSTRAINT ck_shots_status CHECK (
        status IN (
            'planned', 'storyboard_ready', 'clip_pending',
            'clip_ready', 'approved', 'stale', 'failed'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_shots_project_index
    ON shots (project_id, shot_index);

CREATE INDEX IF NOT EXISTS idx_shots_plan
    ON shots (shot_plan_version_id, shot_index);

CREATE INDEX IF NOT EXISTS idx_shots_status
    ON shots (project_id, status);


CREATE TABLE IF NOT EXISTS storyboard_versions (
    id                      VARCHAR(26)     NOT NULL,
    project_id              VARCHAR(26)     NOT NULL,
    version_no              INTEGER         NOT NULL,
    shot_plan_version_id    VARCHAR(26)     NOT NULL,
    raw_payload             JSONB           NOT NULL    DEFAULT '{}',
    is_active               BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at              TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_storyboard_versions PRIMARY KEY (id),
    CONSTRAINT uq_storyboard_versions_no UNIQUE (project_id, version_no),
    CONSTRAINT fk_storyboard_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_storyboard_versions_shot_plan FOREIGN KEY (shot_plan_version_id)
        REFERENCES shot_plan_versions (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_storyboard_versions_project_active
    ON storyboard_versions (project_id, is_active);


-- prompt_bundle_id FK 此处暂不建，等 prompt_bundles 建完后 ALTER 补上
CREATE TABLE IF NOT EXISTS storyboard_frames (
    id                      VARCHAR(26)     NOT NULL,
    project_id              VARCHAR(26)     NOT NULL,
    storyboard_version_id   VARCHAR(26)     NOT NULL,
    shot_id                 VARCHAR(26)     NOT NULL,
    asset_id                VARCHAR(26)     NOT NULL,
    prompt_bundle_id        VARCHAR(26)                 DEFAULT NULL,
    frame_index             INTEGER         NOT NULL    DEFAULT 0,
    metadata                JSONB           NOT NULL    DEFAULT '{}',
    created_at              TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_storyboard_frames PRIMARY KEY (id),
    CONSTRAINT fk_storyboard_frames_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_storyboard_frames_storyboard_version FOREIGN KEY (storyboard_version_id)
        REFERENCES storyboard_versions (id) ON DELETE CASCADE,
    CONSTRAINT fk_storyboard_frames_shot FOREIGN KEY (shot_id)
        REFERENCES shots (id) ON DELETE CASCADE,
    CONSTRAINT fk_storyboard_frames_asset FOREIGN KEY (asset_id)
        REFERENCES assets (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_storyboard_frames_storyboard_shot
    ON storyboard_frames (storyboard_version_id, shot_id, frame_index);


-- =============================================================================
-- 7. PROMPT BUNDLES
-- =============================================================================
-- target_id 是多态引用（指向 storyboard_frame / shot / lipsync_clip），不建 FK
-- =============================================================================

CREATE TABLE IF NOT EXISTS prompt_bundles (
    id              VARCHAR(26)     NOT NULL,
    project_id      VARCHAR(26)     NOT NULL,
    target_type     VARCHAR(32)     NOT NULL,
    target_id       VARCHAR(26)     NOT NULL,   -- 多态，无 FK
    provider        VARCHAR(64)     NOT NULL,
    positive_prompt TEXT            NOT NULL,
    negative_prompt TEXT                        DEFAULT NULL,
    params          JSONB           NOT NULL    DEFAULT '{}',
    -- 编译溯源（可选，供调试和审阅）
    source_brief_version_id     VARCHAR(26)     DEFAULT NULL,
    source_style_version_id     VARCHAR(26)     DEFAULT NULL,
    source_shot_plan_version_id VARCHAR(26)     DEFAULT NULL,
    -- Bug 2 修复：参考图溯源（与 PromptBundle schema 对齐）
    reference_image_url         TEXT            DEFAULT NULL,
    reference_asset_ids         JSONB           DEFAULT '[]',
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_prompt_bundles PRIMARY KEY (id),
    CONSTRAINT fk_prompt_bundles_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT ck_prompt_bundles_target_type CHECK (
        target_type IN ('storyboard_frame', 'shot_clip', 'lipsync_clip', 'nine_grid_image')
    )
);

CREATE INDEX IF NOT EXISTS idx_prompt_bundles_target
    ON prompt_bundles (target_type, target_id, created_at DESC);


-- 现在补上 storyboard_frames.prompt_bundle_id 的外键
ALTER TABLE storyboard_frames
    ADD CONSTRAINT fk_storyboard_frames_prompt_bundle
    FOREIGN KEY (prompt_bundle_id)
    REFERENCES prompt_bundles (id) ON DELETE SET NULL;


-- =============================================================================
-- 8. CLIPS — clip_versions
-- =============================================================================

CREATE TABLE IF NOT EXISTS clip_versions (
    id                  VARCHAR(26)     NOT NULL,
    project_id          VARCHAR(26)     NOT NULL,
    shot_id             VARCHAR(26)     NOT NULL,
    version_no          INTEGER         NOT NULL,
    provider            VARCHAR(64)     NOT NULL,
    generation_mode     VARCHAR(32)     NOT NULL,
    asset_id            VARCHAR(26)     NOT NULL,
    duration_ms         INTEGER         NOT NULL,
    prompt_bundle_id    VARCHAR(26)                 DEFAULT NULL,
    quality_score       NUMERIC(6, 3)               DEFAULT NULL,
    status              VARCHAR(32)     NOT NULL    DEFAULT 'pending',
    is_active           BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at          TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_clip_versions PRIMARY KEY (id),
    CONSTRAINT uq_clip_versions_shot_no UNIQUE (shot_id, version_no),
    CONSTRAINT fk_clip_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_clip_versions_shot FOREIGN KEY (shot_id)
        REFERENCES shots (id) ON DELETE CASCADE,
    CONSTRAINT fk_clip_versions_asset FOREIGN KEY (asset_id)
        REFERENCES assets (id) ON DELETE RESTRICT,
    CONSTRAINT fk_clip_versions_prompt_bundle FOREIGN KEY (prompt_bundle_id)
        REFERENCES prompt_bundles (id) ON DELETE SET NULL,
    CONSTRAINT ck_clip_versions_mode CHECK (
        generation_mode IN (
            'image_to_video', 'text_to_video', 'video_to_video', 'lipsync'
        )
    ),
    CONSTRAINT ck_clip_versions_status CHECK (
        status IN ('pending', 'ready', 'failed', 'stale')
    )
);

CREATE INDEX IF NOT EXISTS idx_clip_versions_shot_active
    ON clip_versions (shot_id, is_active);

CREATE INDEX IF NOT EXISTS idx_clip_versions_project_created
    ON clip_versions (project_id, created_at DESC);


-- =============================================================================
-- 9. TIMELINE — timeline_versions / timeline_segments / export_versions
-- =============================================================================

CREATE TABLE IF NOT EXISTS timeline_versions (
    id              VARCHAR(26)     NOT NULL,
    project_id      VARCHAR(26)     NOT NULL,
    version_no      INTEGER         NOT NULL,
    audio_asset_id  VARCHAR(26)     NULL,
    subtitle_track  JSONB           NOT NULL    DEFAULT '[]',
    render_status   VARCHAR(32)     NOT NULL    DEFAULT 'draft',
    raw_payload     JSONB           NOT NULL    DEFAULT '{}',
    is_active       BOOLEAN         NOT NULL    DEFAULT FALSE,
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_timeline_versions PRIMARY KEY (id),
    CONSTRAINT uq_timeline_versions_no UNIQUE (project_id, version_no),
    CONSTRAINT fk_timeline_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_timeline_versions_audio FOREIGN KEY (audio_asset_id)
        REFERENCES assets (id) ON DELETE RESTRICT,
    CONSTRAINT ck_timeline_versions_render_status CHECK (
        render_status IN ('draft', 'ready', 'stale', 'rendering', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_timeline_versions_project_active
    ON timeline_versions (project_id, is_active);


CREATE TABLE IF NOT EXISTS timeline_segments (
    id                      VARCHAR(26)     NOT NULL,
    timeline_version_id     VARCHAR(26)     NOT NULL,
    shot_id                 VARCHAR(26)     NOT NULL,
    clip_version_id         VARCHAR(26)     NOT NULL,
    start_ms                INTEGER         NOT NULL,
    end_ms                  INTEGER         NOT NULL,
    transition_in           VARCHAR(32)                 DEFAULT NULL,
    transition_out          VARCHAR(32)                 DEFAULT NULL,
    metadata                JSONB           NOT NULL    DEFAULT '{}',
    created_at              TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_timeline_segments PRIMARY KEY (id),
    CONSTRAINT fk_timeline_segments_timeline_version FOREIGN KEY (timeline_version_id)
        REFERENCES timeline_versions (id) ON DELETE CASCADE,
    CONSTRAINT fk_timeline_segments_shot FOREIGN KEY (shot_id)
        REFERENCES shots (id) ON DELETE RESTRICT,
    CONSTRAINT fk_timeline_segments_clip_version FOREIGN KEY (clip_version_id)
        REFERENCES clip_versions (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_timeline_segments_timeline_start
    ON timeline_segments (timeline_version_id, start_ms);


CREATE TABLE IF NOT EXISTS export_versions (
    id                      VARCHAR(26)     NOT NULL,
    project_id              VARCHAR(26)     NOT NULL,
    timeline_version_id     VARCHAR(26)     NOT NULL,
    asset_id                VARCHAR(26)     NOT NULL,
    resolution              VARCHAR(16)     NOT NULL,
    status                  VARCHAR(32)     NOT NULL    DEFAULT 'pending',
    created_at              TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_export_versions PRIMARY KEY (id),
    CONSTRAINT fk_export_versions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_export_versions_timeline_version FOREIGN KEY (timeline_version_id)
        REFERENCES timeline_versions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_export_versions_asset FOREIGN KEY (asset_id)
        REFERENCES assets (id) ON DELETE RESTRICT,
    CONSTRAINT ck_export_versions_status CHECK (
        status IN ('pending', 'processing', 'completed', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_export_versions_project_created
    ON export_versions (project_id, created_at DESC);


-- =============================================================================
-- 10. WORKFLOW — pending_decisions / agent_tasks / tool_jobs
-- =============================================================================

CREATE TABLE IF NOT EXISTS pending_decisions (
    id                      VARCHAR(26)     NOT NULL,
    project_id              VARCHAR(26)     NOT NULL,
    session_id              VARCHAR(26)     NOT NULL,
    decision_type           VARCHAR(64)     NOT NULL,
    target_entity_type      VARCHAR(32)     NOT NULL,
    target_entity_id        VARCHAR(26)                 DEFAULT NULL,
    options_payload         JSONB           NOT NULL    DEFAULT '[]',
    default_option_id       VARCHAR(64)                 DEFAULT NULL,
    selected_option_id      VARCHAR(64)                 DEFAULT NULL,  -- submit_decision 写入
    status                  VARCHAR(32)     NOT NULL    DEFAULT 'open',
    expires_at              TIMESTAMPTZ                 DEFAULT NULL,
    created_at              TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_pending_decisions PRIMARY KEY (id),
    CONSTRAINT fk_pending_decisions_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_pending_decisions_session FOREIGN KEY (session_id)
        REFERENCES conversation_sessions (id) ON DELETE CASCADE,
    CONSTRAINT ck_pending_decisions_status CHECK (
        status IN ('open', 'selected', 'expired', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS idx_pending_decisions_project_status
    ON pending_decisions (project_id, status, created_at DESC);

-- 补上 conversation_sessions.pending_decision_id 的外键
ALTER TABLE conversation_sessions
    ADD CONSTRAINT fk_conversation_sessions_pending_decision
    FOREIGN KEY (pending_decision_id)
    REFERENCES pending_decisions (id) ON DELETE SET NULL;


CREATE TABLE IF NOT EXISTS agent_tasks (
    id                          VARCHAR(26)     NOT NULL,
    project_id                  VARCHAR(26)     NOT NULL,
    conversation_session_id     VARCHAR(26)                 DEFAULT NULL,
    task_type                   VARCHAR(64)     NOT NULL,
    requested_by_agent          VARCHAR(64)     NOT NULL,
    assigned_agent              VARCHAR(64)     NOT NULL,
    status                      VARCHAR(32)     NOT NULL    DEFAULT 'pending',
    input_ref                   JSONB           NOT NULL    DEFAULT '{}',
    output_ref                  JSONB                       DEFAULT NULL,
    error_payload               JSONB                       DEFAULT NULL,
    created_at                  TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_agent_tasks PRIMARY KEY (id),
    CONSTRAINT fk_agent_tasks_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_tasks_session FOREIGN KEY (conversation_session_id)
        REFERENCES conversation_sessions (id) ON DELETE SET NULL,
    CONSTRAINT ck_agent_tasks_status CHECK (
        status IN (
            'pending', 'running', 'waiting_human',
            'succeeded', 'failed', 'cancelled'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_project_status
    ON agent_tasks (project_id, status, created_at DESC);


CREATE TABLE IF NOT EXISTS tool_jobs (
    id                  VARCHAR(26)     NOT NULL,
    project_id          VARCHAR(26)     NOT NULL,
    agent_task_id       VARCHAR(26)                 DEFAULT NULL,
    tool_name           VARCHAR(64)     NOT NULL,
    provider            VARCHAR(64)                 DEFAULT NULL,
    status              VARCHAR(32)     NOT NULL    DEFAULT 'pending',
    input_payload       JSONB           NOT NULL    DEFAULT '{}',
    output_payload      JSONB                       DEFAULT NULL,
    error_payload       JSONB                       DEFAULT NULL,
    idempotency_key     VARCHAR(128)    NOT NULL,
    retry_count         INTEGER         NOT NULL    DEFAULT 0,
    created_at          TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_tool_jobs PRIMARY KEY (id),
    CONSTRAINT uq_tool_jobs_idempotency UNIQUE (idempotency_key),
    CONSTRAINT fk_tool_jobs_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT fk_tool_jobs_agent_task FOREIGN KEY (agent_task_id)
        REFERENCES agent_tasks (id) ON DELETE SET NULL,
    CONSTRAINT ck_tool_jobs_status CHECK (
        status IN (
            'pending', 'running', 'waiting_human',
            'succeeded', 'failed', 'retrying', 'cancelled'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_tool_jobs_project_status
    ON tool_jobs (project_id, status, created_at DESC);


-- =============================================================================
-- 11. EVENTS & BILLING — event_logs / outbox_events / credit_ledger
-- =============================================================================

CREATE TABLE IF NOT EXISTS event_logs (
    id              VARCHAR(26)     NOT NULL,
    project_id      VARCHAR(26)     NOT NULL,
    aggregate_type  VARCHAR(32)     NOT NULL,
    aggregate_id    VARCHAR(26)     NOT NULL,
    event_type      VARCHAR(64)     NOT NULL,
    payload         JSONB           NOT NULL    DEFAULT '{}',
    causation_id    VARCHAR(26)                 DEFAULT NULL,
    correlation_id  VARCHAR(26)                 DEFAULT NULL,
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    -- append-only：无 updated_at

    CONSTRAINT pk_event_logs PRIMARY KEY (id),
    CONSTRAINT fk_event_logs_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_event_logs_project_created
    ON event_logs (project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_logs_aggregate
    ON event_logs (aggregate_type, aggregate_id, created_at DESC);


-- outbox_events 不需要硬 FK（与业务表同事务写入，靠 DB 事务保一致性，查询走 aggregate_id）
CREATE TABLE IF NOT EXISTS outbox_events (
    id              VARCHAR(26)     NOT NULL,
    aggregate_type  VARCHAR(32)     NOT NULL,
    aggregate_id    VARCHAR(26)     NOT NULL,
    event_type      VARCHAR(64)     NOT NULL,
    payload         JSONB           NOT NULL    DEFAULT '{}',
    status          VARCHAR(32)     NOT NULL    DEFAULT 'pending',
    available_at    TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    published_at    TIMESTAMPTZ                 DEFAULT NULL,
    created_at      TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),

    CONSTRAINT pk_outbox_events PRIMARY KEY (id),
    CONSTRAINT ck_outbox_events_status CHECK (
        status IN ('pending', 'published', 'failed')
    )
);

-- 发布器轮询高频访问此索引
CREATE INDEX IF NOT EXISTS idx_outbox_status_available
    ON outbox_events (status, available_at)
    WHERE status = 'pending';  -- partial index，只扫未发布行


CREATE TABLE IF NOT EXISTS credit_ledger (
    id          VARCHAR(26)     NOT NULL,
    user_id     VARCHAR(26)     NOT NULL,
    project_id  VARCHAR(26)                 DEFAULT NULL,
    job_id      VARCHAR(26)                 DEFAULT NULL,   -- 逻辑引用，tool_jobs.id，无 FK（高吞吐）
    entry_type  VARCHAR(32)     NOT NULL,
    tool_name   VARCHAR(64)                 DEFAULT NULL,
    units       NUMERIC(12, 3)  NOT NULL    DEFAULT 0,
    unit_price  NUMERIC(12, 3)  NOT NULL    DEFAULT 0,
    delta       NUMERIC(12, 3)  NOT NULL,
    status      VARCHAR(32)     NOT NULL    DEFAULT 'pending',
    metadata    JSONB           NOT NULL    DEFAULT '{}',
    created_at  TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    -- append-only 账本：无 updated_at

    CONSTRAINT pk_credit_ledger PRIMARY KEY (id),
    CONSTRAINT fk_credit_ledger_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_credit_ledger_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE SET NULL,
    CONSTRAINT ck_credit_ledger_entry_type CHECK (
        entry_type IN ('grant', 'reserve', 'commit', 'refund')
    ),
    CONSTRAINT ck_credit_ledger_status CHECK (
        status IN ('pending', 'applied', 'reverted')
    )
);

CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_created
    ON credit_ledger (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_credit_ledger_project_created
    ON credit_ledger (project_id, created_at DESC)
    WHERE project_id IS NOT NULL;


-- =============================================================================
-- 12. 可选：updated_at 自动更新触发器
--
-- 说明：
--   ORM 层（SQLAlchemy onupdate）已负责 updated_at 的更新。
--   如果需要数据库层面保证（管理员直接 UPDATE、migration 脚本等），
--   取消以下注释即可。
--
-- 需要挂载触发器的表：
--   users / user_preferences / projects / conversation_sessions /
--   shots / agent_tasks / tool_jobs
-- =============================================================================

/*
CREATE OR REPLACE FUNCTION fn_update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users', 'user_preferences', 'projects', 'conversation_sessions',
        'shots', 'agent_tasks', 'tool_jobs'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%s_updated_at
             BEFORE UPDATE ON %s
             FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();',
            t, t
        );
    END LOOP;
END $$;
*/


-- =============================================================================
-- END OF SCHEMA
-- =============================================================================
-- 表总计：26
--   auth          : users, user_preferences
--   project       : projects
--   conversation  : conversation_sessions, conversation_messages, session_contexts
--   assets        : assets, project_spec_versions
--   analysis      : audio_analysis_versions, creative_brief_versions,
--                   style_bible_versions, character_set_versions,
--                   scene_plan_versions, shot_plan_versions
--   shots         : shots, storyboard_versions, storyboard_frames
--   generation    : prompt_bundles, clip_versions
--   timeline      : timeline_versions, timeline_segments, export_versions
--   workflow      : pending_decisions, agent_tasks, tool_jobs
--   events        : event_logs, outbox_events, credit_ledger
-- =============================================================================
