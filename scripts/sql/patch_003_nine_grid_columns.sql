-- ===========================================================================
-- patch_003_nine_grid_columns.sql
-- 来源：docs/21_VidMuse九宫格分镜重构方案.md §1.3 + §1.4
-- 日期：2026-04-30
-- 内容：StoryboardFrame 加 3 列 + assets 加 nine_grid_image 类型
-- 执行顺序：在 patch_002 之后执行
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. storyboard_frames 加 3 列（九宫格架构）
-- ---------------------------------------------------------------------------
ALTER TABLE storyboard_frames
    ADD COLUMN IF NOT EXISTS parent_asset_id VARCHAR(26),
    ADD COLUMN IF NOT EXISTS cell_position INTEGER,
    ADD COLUMN IF NOT EXISTS grid_index INTEGER;

-- 外键：parent_asset_id → assets.id（RESTRICT 防止误删大图）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_storyboard_frames_parent_asset'
    ) THEN
        ALTER TABLE storyboard_frames
            ADD CONSTRAINT fk_storyboard_frames_parent_asset
            FOREIGN KEY (parent_asset_id) REFERENCES assets(id) ON DELETE RESTRICT;
    END IF;
END $$;

-- 检查约束：cell_position ∈ [1,9] 或为 NULL
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_storyboard_frames_cell_position'
    ) THEN
        ALTER TABLE storyboard_frames
            ADD CONSTRAINT ck_storyboard_frames_cell_position
            CHECK (cell_position IS NULL OR (cell_position >= 1 AND cell_position <= 9));
    END IF;
END $$;

-- 高频查询索引
CREATE INDEX IF NOT EXISTS idx_storyboard_frames_grid
    ON storyboard_frames (storyboard_version_id, grid_index, cell_position);

-- ---------------------------------------------------------------------------
-- 2. shot_id 改为 nullable（九宫格大图自身不绑定 shot）
-- ⚠️  此操作不可自动回退（一旦有 NULL 行，再加 NOT NULL 会失败）
-- ---------------------------------------------------------------------------
ALTER TABLE storyboard_frames
    ALTER COLUMN shot_id DROP NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. assets 表加 nine_grid_image 类型
-- ---------------------------------------------------------------------------
ALTER TABLE assets DROP CONSTRAINT IF EXISTS ck_assets_type;

ALTER TABLE assets ADD CONSTRAINT ck_assets_type
    CHECK (asset_type IN (
        'audio_original', 'audio_trimmed',
        'image_reference', 'style_reference',
        'storyboard_frame', 'clip_video',
        'export_video', 'subtitle_file', 'thumbnail',
        'character_reference', 'scene_reference', 'prop_reference',
        'audio_analysis', 'creative_brief', 'style_bible',
        'narrative_script', 'scene_plan', 'shot_plan',
        'visual_bible', 'storyboard', 'prompt_bundle', 'timeline',
        'nine_grid_image'  -- doc 21 §5.4 新增：九宫格大图
    ));

COMMIT;

-- ===========================================================================
-- 回滚脚本（手动执行，不可自动）
-- 注意：如果已经有 cell_position IS NULL 的行（九宫格大图），shot_id 不可回退
-- ===========================================================================
-- BEGIN;
-- ALTER TABLE storyboard_frames DROP CONSTRAINT IF EXISTS fk_storyboard_frames_parent_asset;
-- ALTER TABLE storyboard_frames DROP CONSTRAINT IF EXISTS ck_storyboard_frames_cell_position;
-- DROP INDEX IF EXISTS idx_storyboard_frames_grid;
-- ALTER TABLE storyboard_frames DROP COLUMN IF EXISTS parent_asset_id;
-- ALTER TABLE storyboard_frames DROP COLUMN IF EXISTS cell_position;
-- ALTER TABLE storyboard_frames DROP COLUMN IF EXISTS grid_index;
-- -- shot_id 回退（仅在所有行 shot_id 非 NULL 时可执行）
-- -- ALTER TABLE storyboard_frames ALTER COLUMN shot_id SET NOT NULL;
-- ALTER TABLE assets DROP CONSTRAINT ck_assets_type;
-- ALTER TABLE assets ADD CONSTRAINT ck_assets_type CHECK (asset_type IN (
--     'audio_original', 'audio_trimmed',
--     'image_reference', 'style_reference',
--     'storyboard_frame', 'clip_video',
--     'export_video', 'subtitle_file', 'thumbnail',
--     'character_reference', 'scene_reference', 'prop_reference',
--     'audio_analysis', 'creative_brief', 'style_bible',
--     'narrative_script', 'scene_plan', 'shot_plan',
--     'visual_bible', 'storyboard', 'prompt_bundle', 'timeline'
-- ));
-- COMMIT;
