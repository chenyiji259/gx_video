-- 允许新视频流程在无外部音频时也能完成时间线合成。
-- 旧音乐 MV 流程仍可继续写入 audio_asset_id。

ALTER TABLE timeline_versions
    ALTER COLUMN audio_asset_id DROP NOT NULL;
