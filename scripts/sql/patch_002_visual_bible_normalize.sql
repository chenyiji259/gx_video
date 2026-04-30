-- =============================================================================
-- Patch 002: 视觉圣经 JSONB→独立表规范化
--
-- 新建 character_references + scene_references 表
-- character_set_versions.characters / scenes JSONB 列保留（兼容旧数据），
-- 但业务代码不再读写这两个 JSONB 列。
--
-- 幂等：使用 CREATE TABLE IF NOT EXISTS
-- 使用方式：psql -U <user> -d <dbname> -f scripts/sql/patch_002_visual_bible_normalize.sql
-- 日期：2026-04-07
-- =============================================================================

CREATE TABLE IF NOT EXISTS character_references (
    id                        VARCHAR(26) NOT NULL,
    version_id                VARCHAR(26) NOT NULL,
    project_id                VARCHAR(26) NOT NULL,
    character_id              VARCHAR(64) NOT NULL,
    character_name            VARCHAR(255) NOT NULL DEFAULT '',
    description               TEXT NOT NULL DEFAULT '',
    appears_in_sections       JSONB NOT NULL DEFAULT '[]',
    active_reference_asset_id VARCHAR(26) DEFAULT NULL,
    reference_asset_ids       JSONB NOT NULL DEFAULT '[]',
    base_face_asset_id        VARCHAR(26) DEFAULT NULL,
    image_analysis            JSONB DEFAULT NULL,
    costumes                  JSONB NOT NULL DEFAULT '[]',
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_character_references PRIMARY KEY (id),
    CONSTRAINT fk_character_references_version FOREIGN KEY (version_id)
        REFERENCES character_set_versions (id) ON DELETE CASCADE,
    CONSTRAINT fk_character_references_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT uq_character_references_version_char UNIQUE (version_id, character_id)
);

CREATE INDEX IF NOT EXISTS idx_character_references_version ON character_references (version_id);
CREATE INDEX IF NOT EXISTS idx_character_references_project ON character_references (project_id);

CREATE TABLE IF NOT EXISTS scene_references (
    id                        VARCHAR(26) NOT NULL,
    version_id                VARCHAR(26) NOT NULL,
    project_id                VARCHAR(26) NOT NULL,
    scene_id                  VARCHAR(64) NOT NULL,
    scene_name                VARCHAR(255) NOT NULL DEFAULT '',
    description               TEXT NOT NULL DEFAULT '',
    appears_in_sections       JSONB NOT NULL DEFAULT '[]',
    active_reference_asset_id VARCHAR(26) DEFAULT NULL,
    reference_asset_ids       JSONB NOT NULL DEFAULT '[]',
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_scene_references PRIMARY KEY (id),
    CONSTRAINT fk_scene_references_version FOREIGN KEY (version_id)
        REFERENCES character_set_versions (id) ON DELETE CASCADE,
    CONSTRAINT fk_scene_references_project FOREIGN KEY (project_id)
        REFERENCES projects (id) ON DELETE CASCADE,
    CONSTRAINT uq_scene_references_version_scene UNIQUE (version_id, scene_id)
);

CREATE INDEX IF NOT EXISTS idx_scene_references_version ON scene_references (version_id);
CREATE INDEX IF NOT EXISTS idx_scene_references_project ON scene_references (project_id);
