-- patch_005_shots_dialogue.sql
--
-- 目的：
--   为 shots 表增加 dialogue 字段，用于承载视频台词 / 配音稿。
--   数据链路：narrative_script.shots[*].dialogue -> shot_plan -> shots.dialogue
--   -> compile_video_prompt -> 视频模型提示词。

BEGIN;

ALTER TABLE shots
    ADD COLUMN IF NOT EXISTS dialogue TEXT DEFAULT NULL;

COMMIT;
