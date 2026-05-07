-- patch_007_prompt_bundle_talking_head_target.sql
--
-- 目的：
--   放开 prompt_bundles.target_type 对 talking_head_story_overview_board 的约束，
--   用于口播类 Production Board 主链路中的 21:9 Story Overview Board 生图 prompt。
--
-- 影响：
--   仅更新 CHECK 约束，不改历史数据。
--
-- 执行状态：
--   本地数据库已执行并验证通过。
--   服务器数据库后续发布前同步执行同一脚本：
--     psql -h <host> -p <port> -U <user> -d <database> -f scripts/sql/patch_007_prompt_bundle_talking_head_target.sql

BEGIN;

ALTER TABLE prompt_bundles
    ALTER COLUMN target_type TYPE VARCHAR(64);

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
