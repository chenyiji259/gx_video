import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock,
  Download,
  Lightbulb,
  Maximize,
  PenSquare,
  Play,
  RefreshCw,
  Share,
  Video,
} from 'lucide-react';
import { motion } from 'motion/react';
import {
  ApiError,
  getProjectEventsStreamUrl,
  isNotFoundError,
  projectApi,
  workflowApi,
} from '../api';
import type { ExportRecord, NarrativeShot, Shot, ViewState, WorkspaceData } from '../types';

interface WorkspaceProps {
  projectId: string;
  onNavigate: (view: ViewState) => void;
}

const STAGE_TO_STEP: Record<string, number> = {
  created: 1,
  input_ready: 1,
  brief_ready: 2,
  narrative_ready: 2,
  shot_plan_ready: 2,
  storyboard_ready: 3,
  clips_generating: 5,
  clips_ready: 5,
  timeline_ready: 6,
  export_ready: 6,
  completed: 6,
};

const DEFAULT_FORM = {
  prompt: '',
  platform: 'tiktok',
  duration: 60,
  audience: '',
  style: '专家知识口播，专业、亲和、干净护肤科普，纯净无字幕画面',
  humanOnCamera: true,
};

const FIXED_ASPECT_RATIO = '9:16';
const FIXED_VIDEO_RESOLUTION = '1080p';
const FIXED_IMAGE_RESOLUTION = '2K';
const TALKING_HEAD_PROFILE = 'talking_head_production_board';
const TALKING_HEAD_LAYOUT = 'talking_head_story_overview_board';
const TALKING_HEAD_SEGMENT_DURATION_SEC = 15;
const TALKING_HEAD_STORY_BOARD_ASPECT_RATIO = '21:9';
const TALKING_HEAD_STYLE_PREFERENCE = '专家知识口播，专业、亲和、干净护肤科普，纯净无字幕画面';
const TALKING_HEAD_DURATION_OPTIONS = [15, 30, 45, 60, 75, 90];
const WORKSPACE_REFRESH_EVENT_TYPES = new Set([
  'project_created',
  'creative_package.generating',
  'project_input_ready',
  'project_brief_ready',
  'project_narrative_ready',
  'project_shot_plan_ready',
  'storyboard.generating',
  'storyboard.grid.generating',
  'storyboard.grid.generated',
  'storyboard.story_overview.generating',
  'storyboard.story_overview.ready',
  'storyboard.grid.split_done',
  'storyboard.all_grids_completed',
  'project_storyboard_ready',
  'storyboard.failed',
  'director.report',
  'clip.shot.started',
  'clip.shot.completed',
  'clip.shot.failed',
  'clips.all_completed',
  'clips.stage.failed',
  'project_clips_ready',
  'timeline_ready',
  'project_timeline_ready',
  'export_ready',
  'project_export_ready',
  'project_failed',
]);
const WORKSPACE_AUTO_REFRESH_ACTION_KEYS = new Set([
  'generate-creative-package',
  'regenerate-creative-package',
  'generate-storyboard',
  'regenerate-storyboard',
  'generate-clips',
  'retry-generate-clips',
  'compose-timeline',
  'trigger-export',
]);
const WORKSPACE_AUTO_REFRESH_POLL_INTERVAL_MS = 2500;
const WORKSPACE_AUTO_REFRESH_WINDOW_MS = 15 * 60 * 1000;

const AUDIENCE_OPTIONS = [
  '大众用户',
  '年轻女性',
  '年轻男性',
  '学生群体',
  '职场新人',
  '上班族',
  '宝妈群体',
  '品牌客户',
  '电商消费者',
  '科技爱好者',
  '设计从业者',
  '创业者',
  '中小企业主',
  '高净值人群',
  '中老年用户',
  '小白入门用户',
  '专业用户',
  '短视频用户',
  '社媒种草人群',
];

const PLATFORM_OPTIONS = [
  { value: 'tiktok', label: '抖音 / TikTok' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'bilibili', label: 'B站 / Bilibili' },
  { value: 'youtube', label: 'YouTube 横版' },
  { value: 'youtube_shorts', label: 'YouTube Shorts' },
  { value: 'instagram', label: 'Instagram Reels' },
  { value: 'kuaishou', label: '快手' },
  { value: 'wechat_channels', label: '视频号' },
  { value: 'douyin_shop', label: '抖音电商' },
  { value: 'taobao', label: '淘宝 / 天猫' },
];

const formatDurationLabel = (ms?: number | null) => {
  if (!ms) return '--';
  const sec = Math.round(ms / 1000);
  return `${sec}秒`;
};

const formatTimeRange = (shot: Shot) => {
  const startSec = Math.floor((shot.start_ms || 0) / 1000);
  const endSec = Math.ceil((shot.end_ms || 0) / 1000);
  return `${startSec}-${endSec}s`;
};

const getScriptShotStartSec = (shots: Array<NarrativeShot | Shot>, index: number) =>
  shots
    .slice(0, index)
    .reduce((sum, shot) => {
      if ('duration_sec' in shot && typeof shot.duration_sec === 'number') return sum + shot.duration_sec;
      if (typeof shot.duration_ms === 'number') return sum + shot.duration_ms / 1000;
      return sum + Math.max(0, ((shot.end_ms || 0) - (shot.start_ms || 0)) / 1000);
    }, 0);

const getScriptShotDurationSec = (shot: NarrativeShot | Shot) => {
  if ('duration_sec' in shot && typeof shot.duration_sec === 'number' && shot.duration_sec > 0) return shot.duration_sec;
  if (typeof shot.duration_ms === 'number' && shot.duration_ms > 0) return shot.duration_ms / 1000;
  return Math.max(0, ((shot.end_ms || 0) - (shot.start_ms || 0)) / 1000);
};

const formatScriptTimeRange = (shot: NarrativeShot | Shot, shots: Array<NarrativeShot | Shot>, index: number) => {
  const explicitStartSec = typeof shot.start_ms === 'number' && shot.start_ms > 0 ? shot.start_ms / 1000 : null;
  const startSec = explicitStartSec ?? getScriptShotStartSec(shots, index);
  const endSec = typeof shot.end_ms === 'number' && shot.end_ms > 0
    ? shot.end_ms / 1000
    : startSec + getScriptShotDurationSec(shot);
  return `${startSec}-${endSec}s`;
};

const getScriptShotContent = (shot: NarrativeShot | Shot) =>
  safeText(
    ('action_description' in shot ? shot.action_description : null)
      || shot.subject
      || ('scene_description' in shot ? shot.scene_description : null)
      || shot.location
      || ('visual_description' in shot ? shot.visual_description : null)
      || ('start_frame_description' in shot ? shot.start_frame_description : null),
    '待生成'
  );

const ratioToResolution = (ratio?: string | null, resolution = '1080p') => {
  if (ratio === '9:16') return resolution === '1080p' ? '1080 × 1920' : ratio;
  if (ratio === '16:9') return resolution === '1080p' ? '1920 × 1080' : ratio;
  if (ratio === '1:1') return resolution === '1080p' ? '1080 × 1080' : ratio;
  return ratio || '--';
};

const StepBadge = ({ step, title }: { step: string; title: string }) => (
  <div className="flex items-center gap-3 mb-4 shrink-0">
    <div className="bg-gradient-to-r from-violet-400 to-violet-600 text-white font-bold italic text-sm px-3 py-1 rounded-full shadow-md shadow-violet-200">
      Step {step}
    </div>
    <span className="text-lg font-bold text-gray-900 tracking-tight">{title}</span>
  </div>
);

const Card = ({ children, className = '' }: { children: React.ReactNode; className?: string }) => (
  <div className={`bg-white rounded-2xl p-4 shadow-md shadow-gray-200/50 border border-gray-100 flex flex-col min-h-0 ${className}`}>
    {children}
  </div>
);

const safeText = (value: unknown, fallback = '待生成') => {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number') return String(value);
  return fallback;
};

const getPlatformLabel = (value: string) =>
  PLATFORM_OPTIONS.find((platform) => platform.value === value)?.label || value;

const isVideoUrl = (url?: string | null) => {
  if (!url) return false;
  const cleanUrl = url.split('?')[0].toLowerCase();
  return cleanUrl.endsWith('.mp4') || cleanUrl.endsWith('.mov') || cleanUrl.endsWith('.webm') || cleanUrl.endsWith('.m4v');
};

const makeExportFilename = (projectId: string, record: Pick<ExportRecord, 'export_version_id' | 'resolution'>) =>
  `vidmuse_${projectId}_${record.resolution}_${record.export_version_id}.mp4`;

const triggerBrowserDownload = (url: string, filename: string) => {
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  document.body.appendChild(link);
  link.click();
  link.remove();
};

async function maybeLoad<T>(loader: () => Promise<T>): Promise<T | null> {
  try {
    return await loader();
  } catch (error) {
    if (isNotFoundError(error)) return null;
    throw error;
  }
}

export const Workspace = ({ projectId, onNavigate }: WorkspaceProps) => {
  const [workspace, setWorkspace] = useState<WorkspaceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedShotIndex, setSelectedShotIndex] = useState(0);
  const [playMode, setPlayMode] = useState<'selected' | 'sequence'>('selected');
  const [shouldAutoPlay, setShouldAutoPlay] = useState(false);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [imagePreview, setImagePreview] = useState<{ title: string; url: string; description?: string } | null>(null);
  const [stablePreviewSource, setStablePreviewSource] = useState<{ key: string; url: string }>({
    key: '',
    url: '',
  });
  const videoRef = useRef<HTMLVideoElement>(null);
  const eventRefreshTimerRef = useRef<number | null>(null);
  const autoRefreshPollTimerRef = useRef<number | null>(null);
  const autoRefreshStopAtRef = useRef<number | null>(null);
  const loadWorkspaceRef = useRef<(showSkeleton?: boolean) => Promise<void>>(async () => undefined);

  const loadWorkspace = async (showSkeleton = false) => {
    if (showSkeleton) setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const project = await projectApi.getProject(projectId);
      const [
        spec,
        brief,
        style,
        narrative,
        shots,
        storyboard,
        clips,
        timeline,
        timelineSegments,
        latestExport,
        decisions,
      ] = await Promise.all([
        maybeLoad(() => projectApi.getActiveSpec(projectId)),
        maybeLoad(() => projectApi.getBrief(projectId)),
        maybeLoad(() => projectApi.getStyle(projectId)),
        maybeLoad(() => projectApi.getNarrative(projectId)),
        maybeLoad(() => projectApi.getShots(projectId)),
        maybeLoad(() => projectApi.getStoryboardGrids(projectId)),
        maybeLoad(() => projectApi.getClips(projectId)),
        maybeLoad(() => projectApi.getTimeline(projectId)),
        maybeLoad(() => projectApi.getTimelineSegments(projectId)),
        maybeLoad(() => projectApi.getLatestExport(projectId)),
        maybeLoad(() => projectApi.listDecisions(projectId)),
      ]);

      setWorkspace({
        project,
        spec,
        brief,
        style,
        narrative,
        shots: shots?.items ?? [],
        storyboardGrids: storyboard?.grids ?? [],
        clips: clips?.clips ?? [],
        timeline,
        timelineSegments: timelineSegments?.segments ?? [],
        latestExport,
        decisions: decisions?.items ?? [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载工作台失败');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };
  loadWorkspaceRef.current = loadWorkspace;

  const stopAutoRefreshPolling = () => {
    if (autoRefreshPollTimerRef.current !== null) {
      window.clearTimeout(autoRefreshPollTimerRef.current);
      autoRefreshPollTimerRef.current = null;
    }
    autoRefreshStopAtRef.current = null;
  };

  const startAutoRefreshPolling = () => {
    autoRefreshStopAtRef.current = Date.now() + WORKSPACE_AUTO_REFRESH_WINDOW_MS;
    if (autoRefreshPollTimerRef.current !== null) return;

    const tick = () => {
      const stopAt = autoRefreshStopAtRef.current;
      if (!stopAt || Date.now() > stopAt) {
        stopAutoRefreshPolling();
        return;
      }

      void loadWorkspaceRef.current(false).finally(() => {
        const nextStopAt = autoRefreshStopAtRef.current;
        if (!nextStopAt || Date.now() > nextStopAt) {
          stopAutoRefreshPolling();
          return;
        }
        autoRefreshPollTimerRef.current = window.setTimeout(
          tick,
          WORKSPACE_AUTO_REFRESH_POLL_INTERVAL_MS
        );
      });
    };

    autoRefreshPollTimerRef.current = window.setTimeout(tick, 0);
  };

  useEffect(() => {
    void loadWorkspace(true);
  }, [projectId]);

  useEffect(() => {
    const eventSource = new EventSource(getProjectEventsStreamUrl(projectId));

    const scheduleWorkspaceRefresh = () => {
      if (eventRefreshTimerRef.current !== null) {
        window.clearTimeout(eventRefreshTimerRef.current);
      }
      eventRefreshTimerRef.current = window.setTimeout(() => {
        eventRefreshTimerRef.current = null;
        void loadWorkspaceRef.current(false);
      }, 350);
    };

    eventSource.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as { event_type?: string };
        if (event.event_type && WORKSPACE_REFRESH_EVENT_TYPES.has(event.event_type)) {
          scheduleWorkspaceRefresh();
        }
      } catch {
        // 忽略无法解析的 SSE 消息，后端心跳不会进入 onmessage。
      }
    };

    eventSource.onerror = () => {
      // EventSource 会自动重连，不能在这里 close，否则一次短暂断线后就不会再收到生成完成事件。
    };

    return () => {
      eventSource.close();
      if (eventRefreshTimerRef.current !== null) {
        window.clearTimeout(eventRefreshTimerRef.current);
        eventRefreshTimerRef.current = null;
      }
      stopAutoRefreshPolling();
    };
  }, [projectId]);

  useEffect(() => {
    if (!workspace?.spec) return;
    setForm({
      prompt: workspace.spec.user_prompt || '',
      platform: workspace.spec.output_config?.platform || 'tiktok',
      duration: Number(workspace.spec.output_config?.target_duration_sec || 30),
      audience: workspace.spec.output_config?.target_audience || '',
      style: workspace.spec.output_config?.style_preference || TALKING_HEAD_STYLE_PREFERENCE,
      humanOnCamera: Boolean(workspace.spec.output_config?.human_on_camera),
    });
  }, [workspace?.spec]);

  const sortedShots = useMemo(
    () => [...(workspace?.shots ?? [])].sort((a, b) => a.shot_index - b.shot_index),
    [workspace?.shots]
  );
  const narrativeShots = useMemo(
    () =>
      [...(workspace?.narrative?.raw_payload?.shots ?? [])].sort(
        (a, b) => (a.shot_index ?? 0) - (b.shot_index ?? 0)
      ),
    [workspace?.narrative]
  );
  const scriptShots = sortedShots.length ? sortedShots : narrativeShots;
  const isTalkingHeadProject = workspace?.spec?.output_config?.storyboard_layout === TALKING_HEAD_LAYOUT
    || workspace?.spec?.output_config?.generation_profile === TALKING_HEAD_PROFILE;
  const storyOverviewGrid = workspace?.storyboardGrids.find((grid) => grid.board_type === TALKING_HEAD_LAYOUT) ?? null;
  const storyOverviewSegments = storyOverviewGrid?.segments ?? [];

  const storyboardCells = useMemo(
    () =>
      [...(workspace?.storyboardGrids ?? [])]
        .flatMap((grid) => grid.cells || [])
        .filter((cell) => cell.shot_index !== null && cell.shot_index !== undefined)
        .sort((a, b) => {
          const shotDiff = (a.shot_index ?? 0) - (b.shot_index ?? 0);
          if (shotDiff !== 0) return shotDiff;
          return (a.cell_position ?? 0) - (b.cell_position ?? 0);
        }),
    [workspace?.storyboardGrids]
  );

  const activeShot = sortedShots[selectedShotIndex] ?? null;
  const activeNarrativeShot = narrativeShots[selectedShotIndex] ?? null;
  const selectedSegment = storyOverviewSegments.find((segment) => segment.shot_index === activeShot?.shot_index)
    ?? storyOverviewSegments[selectedShotIndex]
    ?? null;
  const shotCellsByShotId = useMemo(() => {
    const map = new Map<string, typeof storyboardCells>();
    for (const cell of storyboardCells) {
      if (!cell.shot_id) continue;
      const current = map.get(cell.shot_id) ?? [];
      current.push(cell);
      map.set(cell.shot_id, current);
    }
    for (const [key, cells] of map.entries()) {
      map.set(
        key,
        [...cells].sort((a, b) => (a.cell_position ?? 0) - (b.cell_position ?? 0))
      );
    }
    return map;
  }, [storyboardCells]);
  const activeShotCells = activeShot ? shotCellsByShotId.get(activeShot.id) ?? [] : [];
  const startCell = activeShotCells[0] ?? null;
  const middleCell = activeShotCells[1] ?? startCell;
  const endCell = activeShotCells[2] ?? middleCell ?? startCell;
  const activeGrid = workspace?.storyboardGrids.find((grid) =>
    grid.cells?.some((cell) => cell.shot_id === activeShot?.id || cell.shot_index === activeShot?.shot_index)
  ) ?? storyOverviewGrid ?? workspace?.storyboardGrids[0] ?? null;
  const activeGridOriginalUrl = activeGrid?.parent_asset_url || null;
  const narrativeFramePlaceholders = [
    activeNarrativeShot?.start_frame_description,
    activeNarrativeShot?.middle_frame_description,
    activeNarrativeShot?.end_frame_description,
  ];
  const activeClip = workspace?.clips.find((clip) => clip.shot_id === activeShot?.id) ?? null;
  const clipsByShotId = useMemo(
    () => new Map((workspace?.clips ?? []).map((clip) => [clip.shot_id, clip])),
    [workspace?.clips]
  );
  const playableShots = useMemo(
    () =>
      sortedShots
        .map((shot, index) => ({ shot, index, clip: clipsByShotId.get(shot.id) ?? null }))
        .filter((item) => Boolean(item.clip?.storage_uri)),
    [sortedShots, clipsByShotId]
  );
  const storyOverviewUrl = storyOverviewGrid?.parent_asset_url || '';
  const previewSource = useMemo(() => {
    if (activeClip?.storage_uri) {
      return {
        key: `clip:${activeClip.asset_id}`,
        url: activeClip.storage_uri,
      };
    }

    if (workspace?.latestExport?.storage_uri) {
      return {
        key: `export:${workspace.latestExport.asset_id}`,
        url: workspace.latestExport.storage_uri,
      };
    }

    if (workspace?.timeline?.preview_uri) {
      return {
        key: `timeline:${workspace.timeline.version_id}`,
        url: workspace.timeline.preview_uri,
      };
    }

    if (isTalkingHeadProject && storyOverviewUrl) {
      return {
        key: `story-overview:${storyOverviewGrid?.parent_asset_id || storyOverviewGrid?.grid_index || 'unknown'}`,
        url: storyOverviewUrl,
      };
    }

    if (startCell?.asset_url) {
      return {
        key: `storyboard-cell:${startCell.asset_id}`,
        url: startCell.asset_url,
      };
    }

    return { key: '', url: '' };
  }, [
    activeClip?.asset_id,
    activeClip?.storage_uri,
    isTalkingHeadProject,
    startCell?.asset_id,
    startCell?.asset_url,
    storyOverviewGrid?.grid_index,
    storyOverviewGrid?.parent_asset_id,
    storyOverviewUrl,
    workspace?.latestExport?.asset_id,
    workspace?.latestExport?.storage_uri,
    workspace?.timeline?.preview_uri,
    workspace?.timeline?.version_id,
  ]);
  const previewMedia = stablePreviewSource.url || previewSource.url;
  const previewIsVideo = isVideoUrl(previewMedia);

  const currentStep = workspace ? STAGE_TO_STEP[workspace.project.current_stage] || 1 : 1;

  const clipProgress = useMemo(() => {
    const total = sortedShots.length || 0;
    const completed = workspace?.clips.length || 0;
    if (!total) return workspace?.latestExport ? 100 : workspace?.timeline ? 90 : 0;
    if (workspace?.latestExport) return 100;
    if (workspace?.timeline) return 88;
    return Math.round((completed / total) * 72);
  }, [sortedShots.length, workspace?.clips.length, workspace?.timeline, workspace?.latestExport]);

  const estimatedRemaining = useMemo(() => {
    if (!workspace?.clips.length || !sortedShots.length) return '等待生成';
    const avgSec =
      workspace.clips
        .map((clip) => clip.duration_ms || 0)
        .reduce((sum, item) => sum + item, 0) /
      1000 /
      workspace.clips.length;
    const remainingShots = Math.max(0, sortedShots.length - workspace.clips.length);
    const estimate = Math.max(1, Math.round((avgSec * remainingShots) / 60));
    return remainingShots === 0 ? '即将完成' : `约 ${estimate} 分钟`;
  }, [workspace?.clips, sortedShots.length]);

  const creativePackageDecision = workspace?.decisions.find(
    (decision) => decision.decision_type === 'confirm_narrative' && decision.status === 'open'
  ) ?? null;
  const storyboardDecision = workspace?.decisions.find(
    (decision) => decision.decision_type === 'confirm_storyboard' && decision.status === 'open'
  ) ?? null;
  const storyboardConfirmed = workspace?.decisions.some(
    (decision) =>
      decision.decision_type === 'confirm_storyboard'
      && decision.status === 'selected'
      && decision.selected_option_id === 'confirm'
  ) ?? false;
  const isClipStageActive = Boolean(
    workspace
    && !['storyboard_ready', 'failed'].includes(workspace.project.current_stage)
    && workspace.clips.length < sortedShots.length
  );
  const creativePackageConfirmOption = creativePackageDecision?.options_payload?.find((option) => option.id === 'confirm')
    ?? creativePackageDecision?.options_payload?.[0]
    ?? null;
  const storyboardConfirmOption = storyboardDecision?.options_payload?.find((option) => option.id === 'confirm')
    ?? storyboardDecision?.options_payload?.[0]
    ?? null;

  const handleAction = async <T,>(key: string, task: () => Promise<T>): Promise<T | null> => {
    setActionLoading(key);
    setError(null);
    try {
      const result = await task();
      await loadWorkspace(false);
      if (WORKSPACE_AUTO_REFRESH_ACTION_KEYS.has(key) || key.startsWith('regenerate-shot-')) {
        startAutoRefreshPolling();
      }
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
      return null;
    } finally {
      setActionLoading(null);
    }
  };

  const handleGeneratePlan = async () => {
    await handleAction('generate-creative-package', async () => {
      const version = await projectApi.createSpecVersion(projectId, {
        user_prompt: form.prompt,
        platform: form.platform,
        target_audience: form.audience,
        style_preference: TALKING_HEAD_STYLE_PREFERENCE,
        human_on_camera: form.humanOnCamera,
        target_duration_sec: form.duration,
        aspect_ratio: FIXED_ASPECT_RATIO,
        video_resolution: FIXED_VIDEO_RESOLUTION,
        image_resolution: FIXED_IMAGE_RESOLUTION,
        generation_profile: TALKING_HEAD_PROFILE,
        storyboard_layout: TALKING_HEAD_LAYOUT,
        segment_duration_sec: TALKING_HEAD_SEGMENT_DURATION_SEC,
        story_board_aspect_ratio: TALKING_HEAD_STORY_BOARD_ASPECT_RATIO,
        style_preset_locked: true,
        subtitles_enabled: false,
      });
      await projectApi.activateSpec(projectId, version.id);
      await workflowApi.generateCreativePackage(projectId);
    });
  };

  const handleConfirmCreativePackage = async () => {
    await handleAction('generate-storyboard', async () => {
      if (creativePackageDecision) {
        await projectApi.selectDecision(
          projectId,
          creativePackageDecision.id,
          creativePackageConfirmOption?.id || 'confirm'
        );
      }
      await workflowApi.generateStoryboard(projectId);
    });
  };

  const handleRegenerateCreativePackage = async () => {
    await handleAction('regenerate-creative-package', async () => {
      if (creativePackageDecision) {
        await projectApi.selectDecision(projectId, creativePackageDecision.id, 'regenerate');
      }
      await workflowApi.generateCreativePackage(projectId);
    });
  };

  const handleRegenerateKeyframes = async () => {
    await handleAction('regenerate-storyboard', async () => {
      if (storyboardDecision) {
        await projectApi.selectDecision(projectId, storyboardDecision.id, 'regenerate');
      }
      await workflowApi.generateStoryboard(projectId);
    });
  };

  const handleRegenerateShot = async (shotId: string) => {
    await handleAction(`regenerate-shot-${shotId}`, async () => {
      await projectApi.regenerateShot(projectId, shotId);
    });
  };

  const handleRetryClipStage = async () => {
    await handleAction('retry-generate-clips', async () => {
      await workflowApi.generateClips(projectId);
    });
  };

  const handleStep3Primary = async () => {
    if (!workspace) return;
    if (isStoryboardFailed) {
      await handleRegenerateKeyframes();
      return;
    }
    if (!workspace.storyboardGrids.length) {
      await handleConfirmCreativePackage();
      return;
    }
    if (
      workspace.project.current_stage === 'failed'
      || storyboardDecision
      || (storyboardConfirmed && workspace.clips.length < sortedShots.length)
    ) {
      await handleAction('generate-clips', async () => {
        if (storyboardDecision) {
          await projectApi.selectDecision(
            projectId,
            storyboardDecision.id,
            storyboardConfirmOption?.id || 'confirm'
          );
        }
        await workflowApi.generateClips(projectId);
      });
      return;
    }
    setSelectedShotIndex((prev) => Math.min(sortedShots.length - 1, prev + 1));
  };

  const handleExportPrimary = async () => {
    if (!workspace) return;
    if (!workspace.timeline && workspace.clips.length) {
      await handleAction('compose-timeline', () => workflowApi.composeTimeline(projectId));
      return;
    }
    if (!workspace.latestExport && workspace.timeline) {
      const exportRecord = await handleAction('trigger-export', () => workflowApi.triggerExport(projectId, '1080p'));
      if (exportRecord?.storage_uri) {
        triggerBrowserDownload(exportRecord.storage_uri, makeExportFilename(projectId, exportRecord));
      } else if (exportRecord) {
        setError('导出已完成，但后端没有返回可下载地址。请刷新后再试。');
      }
      return;
    }
    if (workspace.latestExport?.storage_uri) {
      triggerBrowserDownload(
        workspace.latestExport.storage_uri,
        makeExportFilename(projectId, workspace.latestExport)
      );
      return;
    }
    if (workspace.timeline?.preview_uri) {
      triggerBrowserDownload(workspace.timeline.preview_uri, `vidmuse_${projectId}_timeline_preview.mp4`);
    }
  };

  const playCurrentPreview = () => {
    if (!videoRef.current) return;
    videoRef.current.play().catch(() => undefined);
  };

  const handlePlaySelectedShot = () => {
    if (!activeClip?.storage_uri) return;
    setPlayMode('selected');
    setShouldAutoPlay(true);
  };

  const handlePlaySequence = () => {
    const firstPlayable = playableShots[0];
    if (!firstPlayable) return;
    setPlayMode('sequence');
    setSelectedShotIndex(firstPlayable.index);
    setShouldAutoPlay(true);
  };

  const handlePreviewEnded = () => {
    if (playMode !== 'sequence') return;
    const currentPlayableIndex = playableShots.findIndex((item) => item.shot.id === activeShot?.id);
    const nextPlayable = playableShots[currentPlayableIndex + 1];
    if (!nextPlayable) {
      setPlayMode('selected');
      return;
    }
    setSelectedShotIndex(nextPlayable.index);
    setShouldAutoPlay(true);
  };

  const handlePreviewError = () => {
    if (
      previewSource.key
      && previewSource.key === stablePreviewSource.key
      && previewSource.url
      && previewSource.url !== stablePreviewSource.url
    ) {
      setStablePreviewSource(previewSource);
    }
  };

  useEffect(() => {
    const sourceChanged = previewSource.key !== stablePreviewSource.key;
    if (sourceChanged) {
      setStablePreviewSource(previewSource);
    }
  }, [previewSource, stablePreviewSource.key]);

  useEffect(() => {
    const player = videoRef.current;
    if (!player) return;
    if (playMode === 'sequence' || shouldAutoPlay) {
      player.play().catch(() => undefined);
      setShouldAutoPlay(false);
    }
  }, [playMode, shouldAutoPlay, stablePreviewSource.key]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#f3f4f9] flex items-center justify-center">
        <div className="rounded-3xl bg-white border border-gray-100 px-8 py-6 shadow-xl shadow-gray-200/60 text-gray-700">
          正在加载项目工作台...
        </div>
      </div>
    );
  }

  if (!workspace) {
    return (
      <div className="min-h-screen bg-[#f3f4f9] flex items-center justify-center">
        <div className="rounded-3xl bg-white border border-red-100 px-8 py-6 shadow-xl shadow-red-100/60 text-red-600">
          {error || '项目加载失败'}
        </div>
      </div>
    );
  }

  const directionCards = [
    { label: '产品', value: workspace.brief?.title || safeText(form.prompt, '待填写') },
    { label: '风格', value: workspace.brief?.style_direction || form.style },
    { label: '时长', value: `${form.duration}秒左右` },
    { label: '平台', value: getPlatformLabel(form.platform) },
    { label: '规格', value: `${FIXED_ASPECT_RATIO} · ${FIXED_VIDEO_RESOLUTION}` },
  ];

  const selectedShotLabel = activeShot
    ? isTalkingHeadProject
      ? `Shot ${activeShot.shot_index + 1} · Segment ${activeShot.shot_index + 1}`
      : `镜头 ${activeShot.shot_index + 1}`
    : '当前镜头';
  const isProjectFailed = workspace.project.current_stage === 'failed';
  const isStoryboardFailed = isProjectFailed && !workspace.storyboardGrids.length;
  const primaryStep3Label = isStoryboardFailed
    ? isTalkingHeadProject ? '重试故事大图生成' : '重试关键帧生成'
    : !workspace.storyboardGrids.length
    ? '等待创意剧本确认'
    : storyboardDecision
      ? (storyboardConfirmOption?.title || storyboardConfirmOption?.label || (isTalkingHeadProject ? '确认故事大图并开始生成视频' : '确认关键帧并开始生成视频'))
    : isClipStageActive
      ? '视频生成中'
    : isProjectFailed
      ? '重新生成失败视频'
    : workspace.clips.length < sortedShots.length
        ? storyboardConfirmed
          ? workspace.clips.length ? '继续生成视频' : '生成视频'
          : isTalkingHeadProject ? '等待故事大图确认' : '等待关键帧确认'
        : '下一镜头';
  const primaryStep6Label = !workspace.timeline
    ? '本地拼接'
    : !workspace.latestExport
      ? '导出视频'
      : '下载视频';
  const step2PrimaryLabel = creativePackageDecision
    ? (creativePackageConfirmOption?.title || creativePackageConfirmOption?.label || '确认创意剧本包并生成关键帧')
    : workspace.narrative
      ? '创意剧本包已生成'
      : '等待生成';
  const step3PrimaryLabel = primaryStep3Label;

  return (
    <div className="h-screen bg-[#f3f4f9] text-gray-900 font-sans p-2 overflow-hidden flex flex-col w-full relative">
      <button
        onClick={() => onNavigate('projects')}
        className="absolute top-2 left-2 z-50 bg-white shadow-sm border border-gray-200 rounded-full p-2 hover:bg-gray-50 transition-colors text-gray-500 hover:text-gray-900"
      >
        <ArrowLeft className="w-5 h-5" />
      </button>

      <div className="absolute top-3 right-4 z-40 flex items-center gap-2 rounded-full bg-white/90 px-4 py-2 text-xs text-gray-500 shadow-sm border border-gray-100">
        <span>当前项目：{workspace.project.name}</span>
        <span className="h-3 w-px bg-gray-200" />
        <span>阶段：{workspace.project.current_stage}</span>
        {refreshing ? (
          <>
            <span className="h-3 w-px bg-gray-200" />
            <span>刷新中...</span>
          </>
        ) : null}
      </div>

      <div className="flex-1 w-full flex flex-col gap-2 mt-10 overflow-hidden">
        {error ? (
          <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600">
            {error}
          </div>
        ) : null}

        <div className="grid grid-cols-12 gap-2 min-h-0 items-stretch" style={{ flex: 1.3 }}>
          <div className="col-span-3 w-full h-full min-h-0">
            <Card className="w-full h-full overflow-hidden">
              <StepBadge step="1" title="输入需求" />
              <p className="text-gray-500 text-xs mb-4 shrink-0">用一句话描述你想要的视频，AI 帮你理解并生成创作方向</p>

              <div className="flex-1 space-y-3 mb-4 overflow-y-auto pr-2 min-h-0">
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center shrink-0">
                    <Bot className="w-5 h-5 text-indigo-600" />
                  </div>
                  <div className="bg-gray-50 rounded-2xl rounded-tl-none p-3 text-sm text-gray-700">
                    你好！我是AI视频创作助手<br />请描述你想要制作的视频内容
                    <div className="text-right text-xs text-gray-400 mt-1">10:30</div>
                  </div>
                </div>

                <div className="flex gap-3 justify-end">
                  <div className="bg-violet-50 rounded-2xl rounded-tr-none p-3 text-sm text-gray-800 max-w-[88%]">
                    <textarea
                      value={form.prompt}
                      onChange={(e) => setForm((prev) => ({ ...prev, prompt: e.target.value }))}
                      className="w-full min-h-20 resize-none bg-transparent outline-none"
                      placeholder="请输入你的视频需求..."
                    />
                    <div className="text-right text-xs text-gray-400 mt-1">实时编辑</div>
                  </div>
                  <div className="w-8 h-8 rounded-full shrink-0 border border-gray-200 bg-gray-900 text-white flex items-center justify-center text-[11px] font-semibold">
                    光希
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <select
                    value={PLATFORM_OPTIONS.some((item) => item.value === form.platform) ? form.platform : '__custom__'}
                    onChange={(e) => {
                      const value = e.target.value;
                      setForm((prev) => ({
                        ...prev,
                        platform: value === '__custom__' ? '' : value,
                      }));
                    }}
                    className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 outline-none"
                    aria-label="发布平台"
                  >
                    {PLATFORM_OPTIONS.map((platform) => (
                      <option key={platform.value} value={platform.value}>{platform.label}</option>
                    ))}
                    <option value="__custom__">自定义平台</option>
                  </select>
                  <select
                    value={form.duration}
                    onChange={(e) => setForm((prev) => ({ ...prev, duration: Number(e.target.value || 60) }))}
                    className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 outline-none"
                    aria-label="视频时长"
                  >
                    {TALKING_HEAD_DURATION_OPTIONS.map((duration) => (
                      <option key={duration} value={duration}>{duration}s</option>
                    ))}
                  </select>
                  <select
                    value={AUDIENCE_OPTIONS.includes(form.audience) ? form.audience : '__custom__'}
                    onChange={(e) => {
                      const value = e.target.value;
                      setForm((prev) => ({
                        ...prev,
                        audience: value === '__custom__' ? '' : value,
                      }));
                    }}
                    className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 outline-none"
                    aria-label="目标受众"
                  >
                    {AUDIENCE_OPTIONS.map((audience) => (
                      <option key={audience} value={audience}>{audience}</option>
                    ))}
                    <option value="__custom__">自定义受众</option>
                  </select>
                  <input
                    value={form.audience}
                    onChange={(e) => setForm((prev) => ({ ...prev, audience: e.target.value }))}
                    className="col-span-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 outline-none"
                    placeholder="也可以直接输入目标受众，例如：高消费美妆用户、B 端采购负责人、18-24 岁学生"
                  />
                  <input
                    value={form.platform}
                    onChange={(e) => setForm((prev) => ({ ...prev, platform: e.target.value }))}
                    className="col-span-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 outline-none"
                    placeholder="也可以直接输入发布平台，例如：tiktok、小红书、视频号、抖音电商"
                  />
                  <div className="col-span-2 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-700">
                    <div className="mb-1 text-[10px] font-medium text-gray-400">固定口播风格</div>
                    <div className="font-medium text-gray-900">{TALKING_HEAD_STYLE_PREFERENCE}</div>
                  </div>
                  <label className="col-span-2 flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700">
                    <input
                      type="checkbox"
                      checked={form.humanOnCamera}
                      onChange={(e) => setForm((prev) => ({ ...prev, humanOnCamera: e.target.checked }))}
                      className="h-4 w-4 rounded border-gray-300 text-violet-600"
                    />
                    需要真人主体入镜
                  </label>
                </div>
              </div>

              <div className="bg-gray-50 rounded-xl p-3 mb-3 border border-gray-100 shrink-0">
                <h4 className="text-xs font-semibold text-gray-900 mb-2">AI 理解的创作方向</h4>
                <div className="grid grid-cols-2 gap-2">
                  {directionCards.map((item) => (
                    <div key={item.label} className="bg-white rounded-lg p-2 shadow-sm border border-gray-100">
                      <div className="text-indigo-500 text-[10px] font-medium mb-1">{item.label}</div>
                      <div className="text-xs text-gray-800 line-clamp-2">{item.value}</div>
                    </div>
                  ))}
                </div>
              </div>

              <button
                onClick={() => void handleGeneratePlan()}
                disabled={actionLoading === 'generate-creative-package' || !form.prompt.trim()}
                className="w-full shrink-0 bg-violet-600 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60 text-white rounded-xl py-2.5 text-sm font-medium transition-colors shadow-lg shadow-violet-200 flex items-center justify-center gap-2 mb-3"
              >
                {actionLoading === 'generate-creative-package' ? '生成中...' : '生成创意剧本包'} <ArrowRight className="w-4 h-4" />
              </button>

              <div className="flex items-start gap-2 text-[10px] text-gray-400 shrink-0">
                <Lightbulb className="w-4 h-4 text-violet-500 shrink-0 mt-0.5" />
                <p>小贴士：描述越详细，生成效果越符合你的预期哦~</p>
              </div>
            </Card>
          </div>

          <div className="col-span-4 w-full h-full min-h-0">
            <Card className="w-full h-full overflow-hidden">
              <StepBadge step="2" title="创意剧本包" />
              <p className="text-gray-500 text-xs mb-3 shrink-0">AI 一次性生成口播创意方向和 15 秒分段脚本，确认后进入故事大图生成</p>

              <div className="flex items-center gap-3 text-xs text-gray-600 mb-3 bg-gray-50 p-2.5 rounded-lg border border-gray-100 shrink-0 overflow-x-auto">
                <div><span className="text-gray-400">视频主题:</span> <span className="font-medium text-gray-900">{safeText(workspace.brief?.title, '待生成')}</span></div>
                <div><span className="text-gray-400">时长:</span> <span className="font-medium text-gray-900">{form.duration}秒</span></div>
                <div><span className="text-gray-400">风格:</span> <span className="font-medium text-gray-900">{safeText(workspace.brief?.style_direction, form.style)}</span></div>
                <div><span className="text-gray-400">平台:</span> <span className="font-medium text-gray-900">{getPlatformLabel(form.platform)}</span></div>
              </div>

              {creativePackageDecision ? (
                <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 shrink-0">
                  <div className="font-semibold mb-1">创意剧本包已生成，等待确认</div>
                  <div className="text-amber-700">确认后会进入故事大图生成；选择重新生成会重新生成创意方向和分段脚本。</div>
                </div>
              ) : null}

              <div className="flex-1 overflow-y-auto rounded-xl border border-gray-100 text-sm min-h-0">
                <div className="grid grid-cols-[64px_64px_1fr_1fr] gap-2 p-3 border-b border-gray-100 font-medium text-gray-500 bg-gray-50 text-xs">
                  <div>Segment</div>
                  <div>时间</div>
                  <div>镜头内容</div>
                  <div>口播台词</div>
                </div>
                {scriptShots.length ? (
                  scriptShots.map((shot, index) => (
                    <div key={`${shot.shot_index ?? index}-${index}`} className="grid grid-cols-[64px_64px_1fr_1fr] gap-2 p-3 border-b border-gray-50 items-center">
                      <div className="text-gray-400">S{(shot.shot_index ?? index) + 1}</div>
                      <div className="text-gray-500 text-xs">{formatScriptTimeRange(shot, scriptShots, index)}</div>
                      <div className="text-xs text-gray-800 line-clamp-3">{getScriptShotContent(shot)}</div>
                      <div className="text-xs text-gray-600 line-clamp-3">{safeText(shot.dialogue || shot.lyric_text)}</div>
                    </div>
                  ))
                ) : (
                  <div className="p-6 text-sm text-gray-400 text-center">还没有创意剧本包，先在 Step 1 生成。</div>
                )}
              </div>

              <div className="flex items-center gap-2 mt-4 shrink-0">
                <button
                  onClick={() => void handleRegenerateCreativePackage()}
                  disabled={Boolean(actionLoading) || !workspace.spec}
                  className="flex-1 border border-gray-200 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 text-gray-700 rounded-xl py-2.5 text-sm font-medium transition-colors flex items-center justify-center gap-2"
                >
                  <RefreshCw className={`w-4 h-4 ${actionLoading === 'regenerate-creative-package' ? 'animate-spin' : ''}`} /> 重新生成
                </button>
                <button
                  onClick={() => void handleConfirmCreativePackage()}
                  disabled={Boolean(actionLoading) || !creativePackageDecision}
                  className="flex-1 bg-violet-600 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60 text-white rounded-xl py-2.5 text-sm font-medium transition-colors shadow-lg shadow-violet-200 flex items-center justify-center gap-2"
                >
                  {actionLoading === 'generate-storyboard' ? '生成中...' : step2PrimaryLabel} <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </Card>
          </div>

          <div className="col-span-5 w-full h-full min-h-0">
            <Card className="w-full h-full overflow-hidden">
              <StepBadge step="3" title={isTalkingHeadProject ? '故事大图 / Production Board' : '生成关键帧画面'} />
              <p className="text-gray-500 text-xs mb-3 shrink-0">
                {isTalkingHeadProject
                  ? 'AI 生成一张覆盖完整视频的 21:9 故事大图，后续每个 15 秒 clip 读取对应 Segment 区域'
                  : 'AI 为每个镜头生成起始 / 中间 / 结尾三张关键帧，后续将按多图融合模式生成视频'}
              </p>

              <div className="flex items-center justify-between mb-3 shrink-0 gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-sm text-gray-600 shrink-0">
                    {isTalkingHeadProject ? 'Story Overview Board：' : '镜头选择：'}
                  </span>
                  {isTalkingHeadProject ? (
                    <span className="rounded-full bg-violet-50 px-3 py-1 text-xs font-medium text-violet-700">
                      一张大图 · {scriptShots.length || storyOverviewSegments.length || 0} 个 15s Segment
                    </span>
                  ) : (
                    <div className="flex gap-2 overflow-x-auto">
                      {scriptShots.map((shot, index) => (
                        <button
                          key={'id' in shot ? shot.id : `${shot.shot_index ?? index}-${index}`}
                          onClick={() => setSelectedShotIndex(index)}
                          className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors shrink-0 ${index === selectedShotIndex ? 'bg-violet-600 text-white shadow-md shadow-violet-200' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}
                        >
                          {(shot.shot_index ?? index) + 1}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="text-xs text-gray-500 shrink-0">当前步骤：{currentStep}/6</div>
              </div>

              {creativePackageDecision ? (
                <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 shrink-0">
                  <div className="font-semibold mb-1">等待确认创意剧本包</div>
                  <div className="text-amber-700">确认 Step 2 后会开始生成故事大图。</div>
                </div>
              ) : null}

              {storyboardDecision ? (
                <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 shrink-0">
                  <div className="font-semibold mb-1">{isTalkingHeadProject ? '故事大图已生成，等待确认' : '关键帧已生成，等待确认'}</div>
                  <div className="text-amber-700">确认后会进入视频生成；选择重新生成会重新生成{isTalkingHeadProject ? '故事大图' : '关键帧'}。</div>
                </div>
              ) : null}

              {isStoryboardFailed ? (
                <div className="mb-3 rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700 shrink-0">
                  <div className="font-semibold text-red-800 mb-1">{isTalkingHeadProject ? '故事大图生成失败' : '关键帧生成失败'}</div>
                  <div className="mb-2">上一次{isTalkingHeadProject ? '故事大图' : '三宫格生图'}没有生成可用结果，可以直接重试图片生成阶段。</div>
                  <button
                    onClick={() => void handleRegenerateKeyframes()}
                    disabled={Boolean(actionLoading)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <RefreshCw className={`w-3 h-3 ${actionLoading === 'regenerate-storyboard' ? 'animate-spin' : ''}`} /> 重试{isTalkingHeadProject ? '故事大图' : '关键帧生成'}
                  </button>
                </div>
              ) : null}

              <div className="flex-1 border border-violet-100 bg-violet-50/30 rounded-2xl p-3 mb-3 flex flex-col min-h-0">
                <div className="flex items-center gap-2 text-violet-600 font-medium text-xs mb-2 shrink-0">
                  <span className="w-1 h-3 border-l-2 border-violet-600 rounded"></span>
                  {isTalkingHeadProject
                    ? `Story Overview Board · ${storyOverviewSegments.length || scriptShots.length || 0} 个 Segment`
                    : `${activeShot ? '镜头' : '镜头'} ${activeShot ? activeShot.shot_index + 1 : activeNarrativeShot ? (activeNarrativeShot.shot_index ?? selectedShotIndex) + 1 : '--'}：${activeShot ? formatTimeRange(activeShot) : activeNarrativeShot ? formatScriptTimeRange(activeNarrativeShot, narrativeShots, selectedShotIndex) : '--'}`}
                  <span className="text-gray-400 font-normal ml-2">
                    | {isTalkingHeadProject ? '同一张故事大图供后续每个 15 秒 clip 读取对应区域' : safeText(startCell?.scene_description || activeShot?.subject || activeNarrativeShot?.action_description || activeNarrativeShot?.scene_description)}
                  </span>
                </div>

                {isTalkingHeadProject ? (
                  <button
                    type="button"
                    onClick={() => {
                      if (!storyOverviewUrl) return;
                      setImagePreview({
                        title: 'Story Overview Board',
                        url: storyOverviewUrl,
                        description: selectedSegment?.reading_instruction || '口播故事大图',
                      });
                    }}
                    disabled={!storyOverviewUrl}
                    className="relative group rounded-xl overflow-hidden mb-3 flex-1 min-h-0 bg-gray-100 text-left disabled:cursor-default"
                  >
                    {storyOverviewUrl ? (
                      <img src={storyOverviewUrl} className="w-full h-full object-contain bg-gray-950" alt="Story Overview Board" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center px-3 text-center text-xs text-gray-500">等待生成故事大图</div>
                    )}
                    <div className="absolute top-2 left-2 rounded-lg bg-black/55 px-2 py-1 text-[10px] font-medium text-white">
                      Story Overview Board · 21:9
                    </div>
                    {storyOverviewSegments.length ? (
                      <div className="absolute bottom-2 left-2 right-2 rounded-lg bg-white/90 px-3 py-2 text-[11px] text-gray-700 shadow-sm">
                        {storyOverviewSegments.length} 个 Segment 已写入同一张 Production Board，视频阶段逐段读取对应区域。
                      </div>
                    ) : null}
                  </button>
                ) : (
                  <div className="grid grid-cols-3 gap-3 mb-3 flex-1 min-h-0">
                    {[
                      { label: '起始帧', cell: startCell, placeholder: narrativeFramePlaceholders[0], active: true },
                      { label: '中间帧', cell: middleCell, placeholder: narrativeFramePlaceholders[1], active: false },
                      { label: '结束帧', cell: endCell, placeholder: narrativeFramePlaceholders[2], active: false },
                    ].map((frame, index) => (
                      <button
                        key={index}
                        type="button"
                        onClick={() => {
                          if (!frame.cell?.asset_url) return;
                          setImagePreview({
                            title: `镜头 ${(activeShot?.shot_index ?? activeNarrativeShot?.shot_index ?? selectedShotIndex) + 1} · ${frame.label}`,
                            url: frame.cell.asset_url,
                            description: frame.cell.frame_description || frame.cell.scene_description || frame.placeholder || '',
                          });
                        }}
                        disabled={!frame.cell?.asset_url}
                        className="relative group rounded-xl overflow-hidden h-full bg-gray-100 text-left disabled:cursor-default"
                      >
                        {frame.cell?.asset_url ? (
                          <img src={frame.cell.asset_url} className="w-full h-full object-cover" alt={frame.label} />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center px-3 text-center text-xs text-gray-500">
                            {safeText(frame.placeholder, '待生成')}
                          </div>
                        )}
                        <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent"></div>
                        <div className="absolute top-2 left-2 flex items-center gap-1.5">
                          <div className={`w-2.5 h-2.5 rounded-full border-2 border-white ${frame.active ? 'bg-violet-500' : 'bg-white/40'}`}></div>
                          <span className="text-white text-[10px] font-medium drop-shadow">{frame.label}</span>
                        </div>
                        {frame.cell?.asset_url ? (
                          <div className="absolute right-2 top-2 rounded-full bg-black/40 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100">
                            <Maximize className="h-3 w-3" />
                          </div>
                        ) : null}
                      </button>
                    ))}
                  </div>
                )}

                <div className="text-center text-xs font-medium text-gray-700 bg-white/70 py-1.5 rounded-lg backdrop-blur-sm border border-white shrink-0">
                  {isTalkingHeadProject
                    ? safeText(
                        scriptShots
                          .map((shot, index) => `S${(shot.shot_index ?? index) + 1}: ${shot.dialogue || shot.lyric_text || ''}`)
                          .filter(Boolean)
                          .join('  /  '),
                        '故事大图会覆盖所有 Segment 的口播文案'
                      )
                    : safeText(activeShot?.dialogue || activeShot?.lyric_text || activeNarrativeShot?.dialogue || activeNarrativeShot?.lyric_text, '当前镜头暂无文案')}
                </div>
              </div>

              <div className="flex items-center justify-between shrink-0">
                <button
                  onClick={() => setSelectedShotIndex((prev) => Math.max(0, prev - 1))}
                  disabled={isTalkingHeadProject}
                  className="flex items-center gap-1.5 text-gray-500 hover:text-gray-900 px-3 py-1.5 bg-gray-50 rounded-xl transition-colors font-medium text-xs disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ArrowLeft className="w-3 h-3" /> 上一镜头
                </button>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      if (!activeGridOriginalUrl) return;
                      setImagePreview({
                        title: isTalkingHeadProject ? 'Story Overview Board' : `三宫格原图${activeGrid?.grid_index ? ` ${activeGrid.grid_index}` : ''}`,
                        url: activeGridOriginalUrl,
                        description: isTalkingHeadProject ? '后端返回的口播故事大图' : '后端返回的三宫格原始大图',
                      });
                    }}
                    disabled={!activeGridOriginalUrl}
                    className="flex items-center gap-1.5 text-gray-600 hover:text-gray-900 px-3 py-1.5 bg-white border border-gray-200 rounded-xl transition-colors font-medium text-xs disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Maximize className="w-3 h-3" /> 看原图
                  </button>
                  <button
                    onClick={() => void handleRegenerateKeyframes()}
                    disabled={Boolean(actionLoading) || (!workspace.storyboardGrids.length && !isStoryboardFailed)}
                    className="flex items-center gap-1.5 text-gray-600 hover:text-gray-900 px-3 py-1.5 bg-white border border-gray-200 rounded-xl transition-colors font-medium text-xs disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <RefreshCw className={`w-3 h-3 ${actionLoading === 'regenerate-storyboard' ? 'animate-spin' : ''}`} /> 重新生成
                  </button>
                  <button className="flex items-center gap-1.5 text-gray-600 px-3 py-1.5 bg-white border border-gray-200 rounded-xl font-medium text-xs opacity-60 cursor-not-allowed">
                    <PenSquare className="w-3 h-3" /> 修改提示词
                  </button>
                </div>
                <button
                  onClick={() => void handleStep3Primary()}
                  disabled={
                    Boolean(actionLoading)
                    || isClipStageActive
                    || (!isStoryboardFailed && !workspace.storyboardGrids.length && !creativePackageDecision)
                    || (workspace.storyboardGrids.length > 0 && !workspace.clips.length && !storyboardDecision && !storyboardConfirmed && !isProjectFailed)
                  }
                  className="flex items-center gap-1.5 bg-violet-600 hover:bg-violet-700 text-white px-4 py-1.5 rounded-xl transition-all shadow-md shadow-violet-200 font-medium text-xs disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {actionLoading && ['generate-storyboard', 'generate-clips', 'regenerate-storyboard'].includes(actionLoading) ? '处理中...' : step3PrimaryLabel} <ArrowRight className="w-3 h-3" />
                </button>
              </div>
            </Card>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-2 flex-1 min-h-0 items-stretch">
          <div className="col-span-5 w-full h-full min-h-0">
            <Card className="w-full h-full overflow-hidden">
              <StepBadge step="5" title="视频生成中" />
              <p className="text-gray-500 text-xs mb-4 shrink-0">
                {isTalkingHeadProject
                  ? 'AI 根据固定人物参考、同一故事大图和声色参考生成每个 15 秒口播视频片段，并准备拼接时间线'
                  : 'AI 根据每个镜头的三张关键帧做多图融合生成视频片段，并准备拼接时间线'}
              </p>

              <div className="mb-4 shrink-0">
                <div className="flex justify-between text-xs font-bold text-gray-900 mb-1.5">
                  <span>总体进度</span>
                  <span>{clipProgress}%</span>
                </div>
                <div className="h-2 w-full bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full bg-violet-600 rounded-full" style={{ width: `${clipProgress}%` }}></div>
                </div>
                <div className="text-[10px] text-gray-500 mt-1.5">预计剩余时间：{estimatedRemaining}</div>
              </div>

              {isProjectFailed && !isStoryboardFailed ? (
                <div className="mb-3 rounded-xl border border-red-100 bg-red-50 p-3 text-xs text-red-700 shrink-0">
                  <div className="font-semibold text-red-800 mb-1">视频生成阶段失败</div>
                  <div className="mb-2">失败镜头可单独重新生成，也可以重试整个视频生成阶段。</div>
                  <button
                    onClick={() => void handleRetryClipStage()}
                    disabled={Boolean(actionLoading)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <RefreshCw className={`w-3 h-3 ${actionLoading === 'retry-generate-clips' ? 'animate-spin' : ''}`} /> 重试视频生成阶段
                  </button>
                </div>
              ) : null}

              <div className="flex-1 overflow-y-auto space-y-3 mb-4 relative pr-2 min-h-0">
                <div className="absolute left-5 top-5 bottom-5 w-[1.5px] bg-gray-100 z-0"></div>

                {sortedShots.length ? (
                  sortedShots.map((shot, index) => {
                    const clip = workspace.clips.find((item) => item.shot_id === shot.id);
                    const shotCells = shotCellsByShotId.get(shot.id) ?? [];
                    const thumb = isTalkingHeadProject ? storyOverviewUrl : shotCells[0]?.asset_url;
                    const isFailed = shot.status === 'failed' && !clip;
                    const failureMessage = shot.last_failure?.message || '视频生成失败，后端未返回更详细原因。';
                    const shotActionKey = `regenerate-shot-${shot.id}`;
                    const isSelected = shot.id === activeShot?.id;
                    return (
                      <div
                        key={shot.id}
                        className={`relative z-10 flex items-center justify-between border rounded-xl p-2 shadow-sm transition-colors ${
                          isFailed
                            ? 'border-red-100 bg-red-50/40'
                            : isSelected
                              ? 'border-violet-200 bg-violet-50/70'
                              : 'border-gray-100 bg-white'
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <div className="w-10 h-10 rounded-lg overflow-hidden bg-gray-100 shrink-0 border border-gray-200">
                            {thumb ? <img src={thumb} className={`w-full h-full object-cover ${clip ? '' : 'grayscale opacity-60'}`} alt="" /> : null}
                          </div>
                          <div className="min-w-0">
                            <div className="text-xs font-medium text-gray-900">
                              {isTalkingHeadProject ? `Shot ${shot.shot_index + 1} · Segment ${shot.shot_index + 1}` : `镜头 ${shot.shot_index + 1}`}
                            </div>
                            <div className="text-[10px] text-gray-400">
                              {formatTimeRange(shot)} · {isTalkingHeadProject ? '故事大图复用' : '三图融合'}
                            </div>
                            {isFailed ? (
                              <div className="mt-1 max-w-[260px] truncate text-[10px] text-red-600" title={failureMessage}>
                                失败原因：{failureMessage}
                              </div>
                            ) : null}
                          </div>
                        </div>
                        <div className="shrink-0">
                          {clip ? (
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedShotIndex(index);
                                setPlayMode('selected');
                                setShouldAutoPlay(true);
                              }}
                              className="flex items-center gap-1 rounded-lg border border-emerald-100 bg-white px-2.5 py-1.5 text-xs font-medium text-emerald-600 hover:bg-emerald-50"
                            >
                              <Play className="w-3 h-3" /> 播放
                            </button>
                          ) : isFailed ? (
                            <button
                              onClick={() => void handleRegenerateShot(shot.id)}
                              disabled={Boolean(actionLoading)}
                              className="flex items-center gap-1 rounded-lg border border-red-200 bg-white px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              <RefreshCw className={`w-3 h-3 ${actionLoading === shotActionKey ? 'animate-spin' : ''}`} /> 重新生成
                            </button>
                          ) : (
                            <div className="text-xs text-gray-400 font-medium mr-2">
                              {workspace.project.current_stage === 'clips_generating' ? '视频生成中...' : '等待生成'}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <div className="text-sm text-gray-400">还没有镜头数据，暂时无法生成视频。</div>
                )}
              </div>

              <div className="bg-violet-50/50 rounded-xl p-3 border border-violet-100/50 flex items-start gap-1.5 text-xs text-gray-600 shrink-0">
                <Lightbulb className="w-4 h-4 text-violet-500 shrink-0" />
                <div>
                  <p className="font-medium text-gray-800 mb-0.5">当前合成状态</p>
                  <p className="text-[10px] text-gray-500">
                    {workspace.timeline
                      ? `时间线已生成，共 ${workspace.timeline.segment_count || workspace.timelineSegments.length || 0} 段，可在 Step 6 导出。`
                      : workspace.clips.length
                        ? `${workspace.clips.length} 个视频片段已就绪，下一步可在 Step 6 触发拼接。`
                        : isTalkingHeadProject
                          ? '先完成故事大图与每个 Segment 的视频生成，随后才能拼接导出。'
                          : '先完成每个镜头的三图关键帧与融合生成，随后才能拼接导出。'}
                  </p>
                </div>
              </div>
            </Card>
          </div>

          <div className="col-span-7 w-full h-full min-h-0">
            <Card className="w-full h-full overflow-hidden">
              <StepBadge step="6" title="拼接与导出" />
              <p className="text-gray-500 text-xs mb-4 shrink-0">
                {isTalkingHeadProject
                  ? '所有 15 秒 Segment clip 会在这里拼接成时间线，并完成最终导出'
                  : '三图融合视频片段会在这里拼接成时间线，并完成最终导出'}
              </p>

              <div className="flex gap-4 flex-1 min-h-0">
                <div className="flex-1 h-full min-h-0">
                  <div className="relative h-full w-full bg-black rounded-xl overflow-hidden group shadow-md border border-gray-200 flex justify-center items-center">
                    {previewMedia ? (
                      previewIsVideo ? (
                        <video
                          ref={videoRef}
                          src={previewMedia}
                          className="absolute inset-0 w-full h-full object-contain bg-black"
                          controls
                          playsInline
                          onEnded={handlePreviewEnded}
                          onError={handlePreviewError}
                        />
                      ) : (
                        <img src={previewMedia} className="absolute inset-0 w-full h-full object-cover" alt="Preview" />
                      )
                    ) : (
                      <div className="text-sm text-gray-300">等待拼接或导出结果</div>
                    )}
                    {!previewIsVideo ? (
                      <div className="absolute inset-0 bg-black/20 flex items-center justify-center">
                        <div className="w-16 h-16 bg-white/20 backdrop-blur-md rounded-full flex items-center justify-center shadow-2xl border border-white/30">
                          <Play className="w-8 h-8 text-white ml-1 shadow-sm" />
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>

                <div className="w-[180px] flex flex-col shrink-0 overflow-y-auto pr-1">
                  <h4 className="font-bold text-gray-900 mb-3 text-sm">视频信息</h4>
                  <div className="space-y-2 text-xs text-gray-600 mb-4 border-b border-gray-100 pb-4">
                    <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><Play className="w-3 h-3" /></div>预览：{activeClip?.storage_uri ? selectedShotLabel : workspace.latestExport ? '最终导出' : workspace.timeline ? '拼接时间线' : '关键帧'}</div>
                    <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><Video className="w-3 h-3" /></div>时长：{formatDurationLabel(workspace.timeline?.total_duration_ms || activeClip?.duration_ms || 30000)}</div>
                    <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><CheckCircle2 className="w-3 h-3" /></div>分辨率：{ratioToResolution(workspace.spec?.output_config?.aspect_ratio, workspace.spec?.output_config?.video_resolution || workspace.latestExport?.resolution)}</div>
                    {isTalkingHeadProject ? (
                      <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><Maximize className="w-3 h-3" /></div>故事大图：{workspace.spec?.output_config?.story_board_aspect_ratio || '21:9'}</div>
                    ) : null}
                    <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><RefreshCw className="w-3 h-3" /></div>最终比例：{workspace.spec?.output_config?.aspect_ratio || '--'}</div>
                    {isTalkingHeadProject ? (
                      <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><CheckCircle2 className="w-3 h-3" /></div>字幕：无字幕</div>
                    ) : null}
                    <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><Clock className="w-3 h-3" /></div>生成时间：{new Date(workspace.latestExport?.created_at || workspace.project.updated_at).toLocaleString()}</div>
                  </div>

                  <h4 className="font-bold text-gray-900 mb-3 text-sm">操作</h4>
                  <div className="flex flex-col gap-2">
                    <button className="w-full bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 rounded-lg py-2 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 opacity-60 cursor-not-allowed">
                      <PenSquare className="w-3 h-3 text-gray-400" /> 编辑视频
                    </button>
                    <button
                      onClick={handlePlaySelectedShot}
                      disabled={!activeClip?.storage_uri || !previewIsVideo}
                      className="w-full bg-white border border-gray-200 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 text-gray-700 rounded-lg py-2 text-xs font-medium transition-colors flex items-center justify-center gap-1.5"
                    >
                      <Play className="w-3 h-3 text-gray-400" /> 播放当前镜头
                    </button>
                    <button
                      onClick={handlePlaySequence}
                      disabled={!playableShots.length}
                      className="w-full bg-white border border-gray-200 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 text-gray-700 rounded-lg py-2 text-xs font-medium transition-colors flex items-center justify-center gap-1.5"
                    >
                      <Video className="w-3 h-3 text-gray-400" /> 顺序播放全部镜头
                    </button>
                    <button
                      onClick={() => void handleAction('refresh-workspace', () => loadWorkspace(false))}
                      className="w-full bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 rounded-lg py-2 text-xs font-medium transition-colors flex items-center justify-center gap-1.5"
                    >
                      <RefreshCw className="w-3 h-3 text-gray-400" /> 刷新数据
                    </button>
                    <button
                      onClick={() => void handleExportPrimary()}
                      disabled={Boolean(actionLoading)}
                      className="w-full bg-violet-600 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60 text-white rounded-lg py-2 text-xs font-medium transition-colors shadow-md shadow-violet-200 flex items-center justify-center gap-1.5"
                    >
                      <Download className="w-3 h-3" /> {actionLoading === 'compose-timeline' || actionLoading === 'trigger-export' ? '处理中...' : primaryStep6Label}
                    </button>
                    <button
                      onClick={() => {
                        const shareUrl = workspace.latestExport?.storage_uri || workspace.timeline?.preview_uri || activeClip?.storage_uri;
                        if (shareUrl) navigator.clipboard.writeText(shareUrl).catch(() => undefined);
                      }}
                      className="w-full bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 rounded-lg py-2 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 mt-1"
                    >
                      <Share className="w-3 h-3 text-gray-400" /> 分享视频
                    </button>
                  </div>
                </div>
              </div>
            </Card>
          </div>
        </div>
      </div>

      {imagePreview ? (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-6"
          onClick={() => setImagePreview(null)}
        >
          <div
            className="max-h-full w-full max-w-5xl overflow-hidden rounded-2xl bg-white shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-gray-900">{imagePreview.title}</div>
                {imagePreview.description ? (
                  <div className="mt-0.5 line-clamp-1 text-xs text-gray-500">{imagePreview.description}</div>
                ) : null}
              </div>
              <button
                onClick={() => setImagePreview(null)}
                className="rounded-full border border-gray-200 px-3 py-1 text-xs text-gray-600 hover:bg-gray-50"
              >
                关闭
              </button>
            </div>
            <div className="flex max-h-[78vh] items-center justify-center bg-gray-950 p-3">
              <img src={imagePreview.url} alt={imagePreview.title} className="max-h-[74vh] max-w-full object-contain" />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};
