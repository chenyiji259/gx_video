-- patch_008_prompt_bundle_target_type_128.sql
--
-- 目的：
--   将 prompt_bundles.target_type 从 VARCHAR(32/64) 扩展到 VARCHAR(128)，
--   避免口播 Production Board 的 target_type
--   talking_head_story_overview_board 因长度超过 32 导致落库失败。
--
-- 影响：
--   无损扩容字段长度，不改历史数据。
--   同步保留 talking_head_story_overview_board 的 CHECK 约束。
--
-- 本地执行记录：
--   2026-05-06 已在本地 vidmuse 数据库执行并验证 target_type=VARCHAR(128)。
--
-- 服务器后续执行：
--   psql -h <host> -p <port> -U <user> -d <database> -f scripts/sql/patch_008_prompt_bundle_target_type_128.sql

BEGIN;

ALTER TABLE prompt_bundles
    ALTER COLUMN target_type TYPE VARCHAR(128);

ALTER TABLE prompt_bundles
    DROP CONSTRAINT IF EXISTS ck_prompt_bundles_target_type;

ALTER TABLE prompt_bundles
    ADD CONSTRAINT ck_prompt_bundles_target_type
    CHECK (
        target_type IN (
            'storyboard_frame',
            'shot_clip',
            'lipsync_clip',
            'nine_grid_image',
            'talking_head_story_overview_board'
        )
    );

COMMIT;
