-- =============================================================================
-- Patch 001: 补充 ORM 模型中存在但建表时遗漏的列
--
-- 涉及表：
--   projects        → cover_url
--   prompt_bundles  → reference_image_url, reference_asset_ids
--
-- 幂等：使用 ADD COLUMN IF NOT EXISTS，可重复执行
--
-- 使用方式：
--   psql -U <user> -d <dbname> -f scripts/sql/patch_001_missing_columns.sql
--
-- 日期：2026-04-04
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. projects.cover_url
-- -----------------------------------------------------------------------------
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS cover_url VARCHAR(1024) DEFAULT NULL;


-- -----------------------------------------------------------------------------
-- 2. prompt_bundles.reference_image_url / reference_asset_ids
-- -----------------------------------------------------------------------------
ALTER TABLE prompt_bundles
    ADD COLUMN IF NOT EXISTS reference_image_url  TEXT  DEFAULT NULL;

ALTER TABLE prompt_bundles
    ADD COLUMN IF NOT EXISTS reference_asset_ids  JSONB DEFAULT '[]';
