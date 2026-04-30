import { useCallback, useEffect, useMemo, useState } from 'react';

import { exportService, projectService } from '@/services/api';
import { useProjectStore } from '@/stores/projectStore';

import type {
  ClipItem,
  ExportData,
  GridCell,
  GridItem,
  QueueShot,
  ShotItem,
  TimelineData,
  TimelineSegment,
} from './videoStageTypes';

const safeText = (value: unknown, fallback = '暂无信息') => {
  if (value == null) return fallback;
  if (typeof value === 'string') return value.trim() || fallback;
  return String(value);
};

type VideoStageData = {
  loading: boolean;
  clips: ClipItem[];
  shots: ShotItem[];
  grids: GridItem[];
  timeline: TimelineData | null;
  timelineSegments: TimelineSegment[];
  latestExport: ExportData | null;
  generatedCount: number;
  queueShots: QueueShot[];
  completedClips: QueueShot[];
  pendingShots: QueueShot[];
  currentGeneratingShot: QueueShot | null;
  totalDurationMs: number;
  refreshAll: () => Promise<void>;
  refreshClipsOnly: () => Promise<void>;
};

export const useVideoStageData = (projectId: string): VideoStageData => {
  const refreshFlag = useProjectStore((state) => state.refreshFlag);
  const clipRefreshFlag = useProjectStore((state) => state.clipRefreshFlag);
  const shotRunStates = useProjectStore((state) => state.shotRunStates);

  const [loading, setLoading] = useState(true);
  const [clips, setClips] = useState<ClipItem[]>([]);
  const [shots, setShots] = useState<ShotItem[]>([]);
  const [grids, setGrids] = useState<GridItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [timelineSegments, setTimelineSegments] = useState<TimelineSegment[]>([]);
  const [latestExport, setLatestExport] = useState<ExportData | null>(null);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);

  const refreshClipsOnly = useCallback(async () => {
    const [clipsRes, shotsRes] = await Promise.all([
      projectService.getClips(projectId).catch(() => ({ success: false, data: { clips: [] } })),
      projectService.getShots(projectId).catch(() => ({ success: false, data: { items: [] } })),
    ]);

    const fetchedShots = shotsRes.success ? shotsRes.data?.items ?? [] : [];
    const shotStartMap: Record<string, number> = {};
    for (const shot of fetchedShots) {
      shotStartMap[shot.id] = shot.start_ms ?? 0;
    }

    const fetchedClips = (clipsRes.success ? clipsRes.data?.clips ?? [] : [])
      .map((clip: any) => ({
        ...clip,
        start_ms: shotStartMap[clip.shot_id] ?? 0,
      }))
      .sort((a: ClipItem, b: ClipItem) => a.start_ms - b.start_ms);

    setShots([...fetchedShots].sort((a, b) => (a.shot_index ?? 0) - (b.shot_index ?? 0)));
    setClips(fetchedClips);
  }, [projectId]);

  const refreshAll = useCallback(async () => {
    if (!hasLoadedOnce) {
      setLoading(true);
    }
    try {
      const [clipsRes, timelineRes, shotsRes, exportRes, gridsRes, segmentsRes] = await Promise.all([
        projectService.getClips(projectId).catch(() => ({ success: false, data: { clips: [] } })),
        projectService.getTimeline(projectId).catch(() => ({ success: false, data: null })),
        projectService.getShots(projectId).catch(() => ({ success: false, data: { items: [] } })),
        exportService.getLatestExport(projectId).catch(() => ({ success: false, data: null })),
        projectService.getStoryboardGrids(projectId).catch(() => ({ success: false, data: { grids: [] } })),
        projectService.getTimelineSegments(projectId).catch(() => ({ success: false, data: { segments: [] } })),
      ]);

      const fetchedShots = shotsRes.success ? shotsRes.data?.items ?? [] : [];
      const shotStartMap: Record<string, number> = {};
      for (const shot of fetchedShots) {
        shotStartMap[shot.id] = shot.start_ms ?? 0;
      }

      const fetchedClips = (clipsRes.success ? clipsRes.data?.clips ?? [] : [])
        .map((clip: any) => ({
          ...clip,
          start_ms: shotStartMap[clip.shot_id] ?? 0,
        }))
        .sort((a: ClipItem, b: ClipItem) => a.start_ms - b.start_ms);

      setShots([...fetchedShots].sort((a, b) => (a.shot_index ?? 0) - (b.shot_index ?? 0)));
      setClips(fetchedClips);
      setTimeline(timelineRes.success ? timelineRes.data : null);
      setTimelineSegments(segmentsRes.success ? segmentsRes.data?.segments ?? [] : []);
      setLatestExport(exportRes.success ? exportRes.data : null);
      setGrids(gridsRes.success ? gridsRes.data?.grids ?? [] : []);
      setHasLoadedOnce(true);
    } finally {
      setLoading(false);
    }
  }, [hasLoadedOnce, projectId]);

  useEffect(() => {
    void refreshAll();
  }, [projectId, refreshFlag, refreshAll]);

  useEffect(() => {
    if (!hasLoadedOnce) return;
    void refreshClipsOnly();
  }, [projectId, clipRefreshFlag, hasLoadedOnce, refreshClipsOnly]);

  const clipByShotId = useMemo(() => {
    const map = new Map<string, ClipItem>();
    for (const clip of clips) map.set(clip.shot_id, clip);
    return map;
  }, [clips]);

  const shotBoundaryInfo = useMemo(() => {
    const map = new Map<string, { first?: GridCell; last?: GridCell; gridIndex?: number }>();
    for (const grid of grids) {
      for (const cell of grid.cells ?? []) {
        if (!cell.shot_id) continue;
        const nextCell = (grid.cells ?? []).find((item) => item.shot_index === (cell.shot_index ?? -1) + 1);
        map.set(cell.shot_id, {
          first: cell,
          last: nextCell,
          gridIndex: grid.grid_index,
        });
      }
    }
    return map;
  }, [grids]);

  const queueShots = useMemo(() => {
    return shots.map((shot) => {
      const clip = clipByShotId.get(shot.id);
      const boundary = shotBoundaryInfo.get(shot.id);
      const runtimeState = shotRunStates[shot.id];
      const isCompleted = !!clip;
      const statusLabel = isCompleted
        ? '已完成'
        : runtimeState === 'failed'
          ? '失败'
          : runtimeState === 'running'
            ? '生成中'
            : runtimeState === 'submitted'
              ? '已提交'
              : '等待中';

      return {
        ...shot,
        clip,
        firstFrame: boundary?.first?.asset_url,
        lastFrame: boundary?.last?.asset_url,
        gridIndex: boundary?.gridIndex,
        statusLabel,
      };
    });
  }, [shots, clipByShotId, shotBoundaryInfo, shotRunStates]);

  const completedClips = useMemo(() => queueShots.filter((shot) => shot.clip), [queueShots]);
  const pendingShots = useMemo(() => queueShots.filter((shot) => !shot.clip), [queueShots]);
  const currentGeneratingShot = pendingShots[0] || queueShots[queueShots.length - 1] || null;
  const totalDurationMs = useMemo(() => {
    if (timeline?.total_duration_ms) return timeline.total_duration_ms;
    return clips.reduce((acc, clip) => Math.max(acc, clip.start_ms + clip.duration_ms), 0);
  }, [clips, timeline]);

  return {
    loading,
    clips,
    shots,
    grids,
    timeline,
    timelineSegments,
    latestExport,
    generatedCount: completedClips.length,
    queueShots,
    completedClips,
    pendingShots,
    currentGeneratingShot,
    totalDurationMs,
    refreshAll,
    refreshClipsOnly,
  };
};

export { safeText };
