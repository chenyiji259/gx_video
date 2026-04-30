-- patch_004_prompt_bundle_nine_grid_target.sql
--
-- 目的：
--   放开 prompt_bundles.target_type 对 nine_grid_image 的约束，
--   修复九宫格 prompt 落库时报：
--     Input should be 'storyboard_frame', 'shot_clip' or 'lipsync_clip'
--
-- 影响：
--   仅更新 CHECK 约束，不改历史数据。

BEGIN;

ALTER TABLE prompt_bundles
    DROP CONSTRAINT IF EXISTS ck_prompt_bundles_target_type;

ALTER TABLE prompt_bundles
    ADD CONSTRAINT ck_prompt_bundles_target_type
    CHECK (
        target_type IN (
            'storyboard_frame',
            'shot_clip',
            'lipsync_clip',
            'nine_grid_image'
        )
    );

COMMIT;
