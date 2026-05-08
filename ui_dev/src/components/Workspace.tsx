import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock,
  Download,
  ImagePlus,
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
  AUTH_TOKEN_REFRESHED_EVENT,
  ApiError,
  assetApi,
  getProjectEventsStreamUrl,
  isNotFoundError,
  projectApi,
  workflowApi,
} from '../api';
import type { AssetRecord, ExportRecord, NarrativeShot, Shot, ViewState, WorkspaceData } from '../types';

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
  clips_ready: 5,
  clips_generating: 5,
  timeline_ready: 6,
  export_ready: 6,
  completed: 6,
};

const WORKFLOW_STEPS = [
  { step: 1, title: '输入需求', description: '填写视频目标' },
  { step: 2, title: '创意剧本包', description: '审稿并确认' },
  { step: 3, title: '导演分镜图', description: '查看 Director Shot List' },
  { step: 4, title: '确认生成', description: '进入视频生成' },
  { step: 5, title: '视频生成', description: '播放片段' },
  { step: 6, title: '拼接导出', description: '生成最终视频' },
];

const resolveWorkspaceStep = (workspace: WorkspaceData | null): number => {
  if (!workspace) return 1;

  const stage = workspace.project.current_stage;
  if (stage !== 'failed') {
    return STAGE_TO_STEP[stage] || 1;
  }

  if (workspace.latestExport || workspace.timeline) return 6;

  const hasVideoStageEvidence =
    workspace.clips.length > 0
    || workspace.storyboardGrids.length > 0
    || workspace.shots.some((shot) => ['failed', 'clip_ready', 'stale'].includes(String(shot.status || '')));
  if (hasVideoStageEvidence) return 5;

  if (workspace.narrative) return 3;
  if (workspace.spec) return 2;
  return 1;
};

const DEFAULT_FORM = {
  prompt: '',
  platform: 'tiktok',
  duration: 60,
  audience: '',
  style: '知识口播，专业、亲和、干净护肤科普，纯净无字幕画面',
  humanOnCamera: true,
  productReferenceAssetIds: [] as string[],
  sceneReferenceAssetId: '',
};

const FIXED_ASPECT_RATIO = '9:16';
const FIXED_VIDEO_RESOLUTION = '1080p';
const FIXED_IMAGE_RESOLUTION = '2K';
const TALKING_HEAD_PROFILE = 'talking_head_production_board';
const TALKING_HEAD_LAYOUT = 'talking_head_story_overview_board';
const TALKING_HEAD_SEGMENT_DURATION_SEC = 15;
const TALKING_HEAD_STORY_BOARD_ASPECT_RATIO = '21:9';
const TALKING_HEAD_STYLE_PREFERENCE = '知识口播，专业、亲和、干净护肤科普，纯净无字幕画面';
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

const isPlainRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const FIELD_LABELS: Record<string, string> = {
  title: '标题',
  summary: '创意摘要',
  style_direction: '风格方向',
  mood_tags: '情绪标签',
  story_arc: '故事弧线',
  target_audience: '目标受众',
  audience: '目标受众',
  platform: '发布平台',
  duration: '视频时长',
  duration_sec: '视频时长',
  objective: '创作目标',
  goal: '创作目标',
  concept: '核心概念',
  logline: '一句话创意',
  hook: '开场钩子',
  core_message: '核心信息',
  key_message: '关键信息',
  selling_points: '卖点',
  product_name: '产品名称',
  product_benefits: '产品利益点',
  pain_points: '用户痛点',
  call_to_action: '行动引导',
  cta: '行动引导',
  tone: '表达语气',
  visual_style: '视觉风格',
  emotional_tone: '情绪基调',
  constraints: '创作约束',
  section_mapping: '结构节奏',
  character: '人物',
  characters: '人物设定',
  scenes: '场景设定',
  scene: '场景',
  role: '角色',
  name: '名称',
  description: '说明',
  traits: '特征',
  motivation: '动机',
  location: '地点',
  lighting: '光线',
  props: '道具',
};

const fieldLabel = (key: string) => FIELD_LABELS[key] || '';

const formatRichValue = (value: unknown, fallback = '待生成') => {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    const items = value
      .map((item) => formatRichValue(item, ''))
      .filter(Boolean);
    return items.length ? items.join('、') : fallback;
  }
  if (isPlainRecord(value)) {
    const text = Object.entries(value)
      .filter(([, entryValue]) => entryValue !== null && entryValue !== undefined && entryValue !== '')
      .map(([key, entryValue]) => `${fieldLabel(key) || '补充'}：${formatRichValue(entryValue, '')}`)
      .join('；');
    return text || fallback;
  }
  return fallback;
};

const rawPayloadEntries = (payload?: Record<string, unknown> | null, exclude: string[] = []) =>
  Object.entries(payload ?? {})
    .filter(([key, value]) => !exclude.includes(key) && value !== null && value !== undefined && value !== '')
    .slice(0, 12);

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
  document.body.appendChild(link);
  link.click();
  link.remove();
};

const triggerBlobDownload = (blob: Blob, filename: string) => {
  const objectUrl = URL.createObjectURL(blob);
  try {
    triggerBrowserDownload(objectUrl, filename);
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
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
  const [step6LockedAction, setStep6LockedAction] = useState<'compose-timeline' | 'trigger-export' | 'download-export' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedShotIndex, setSelectedShotIndex] = useState(0);
  const [playMode, setPlayMode] = useState<'selected' | 'sequence'>('selected');
  const [shouldAutoPlay, setShouldAutoPlay] = useState(false);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [productAssets, setProductAssets] = useState<AssetRecord[]>([]);
  const [sceneAsset, setSceneAsset] = useState<AssetRecord | null>(null);
  const [uploadingProducts, setUploadingProducts] = useState(false);
  const [uploadingScene, setUploadingScene] = useState(false);
  const [activeStep, setActiveStep] = useState(1);
  const [imagePreview, setImagePreview] = useState<{ title: string; url: string; description?: string } | null>(null);
  const [creativePackageFeedback, setCreativePackageFeedback] = useState('');
  const [storyboardFeedback, setStoryboardFeedback] = useState('');
  const [stablePreviewSource, setStablePreviewSource] = useState<{ key: string; url: string }>({
    key: '',
    url: '',
  });
  const videoRef = useRef<HTMLVideoElement>(null);
  const productInputRef = useRef<HTMLInputElement>(null);
  const sceneInputRef = useRef<HTMLInputElement>(null);
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
    setStep6LockedAction(null);
  }, [projectId]);

  useEffect(() => {
    if (!workspace || !step6LockedAction) return;
    if (workspace.project.current_stage === 'failed') {
      setStep6LockedAction(null);
      return;
    }
    if (step6LockedAction === 'compose-timeline' && workspace.timeline) {
      setStep6LockedAction(null);
      return;
    }
    if (step6LockedAction === 'trigger-export' && workspace.latestExport) {
      setStep6LockedAction(null);
    }
  }, [step6LockedAction, workspace?.latestExport, workspace?.project.current_stage, workspace?.timeline]);

  useEffect(() => {
    let eventSource: EventSource | null = null;

    const scheduleWorkspaceRefresh = () => {
      if (eventRefreshTimerRef.current !== null) {
        window.clearTimeout(eventRefreshTimerRef.current);
      }
      eventRefreshTimerRef.current = window.setTimeout(() => {
        eventRefreshTimerRef.current = null;
        void loadWorkspaceRef.current(false);
      }, 350);
    };

    const connectEventSource = () => {
      eventSource?.close();
      eventSource = new EventSource(getProjectEventsStreamUrl(projectId));

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
    };

    connectEventSource();
    window.addEventListener(AUTH_TOKEN_REFRESHED_EVENT, connectEventSource);

    return () => {
      window.removeEventListener(AUTH_TOKEN_REFRESHED_EVENT, connectEventSource);
      eventSource?.close();
      if (eventRefreshTimerRef.current !== null) {
        window.clearTimeout(eventRefreshTimerRef.current);
        eventRefreshTimerRef.current = null;
      }
      stopAutoRefreshPolling();
    };
  }, [projectId]);

  useEffect(() => {
    if (!workspace?.spec) return;
    const productReferenceAssetIds = workspace.spec.output_config?.product_reference_asset_ids || [];
    const sceneReferenceAssetId = workspace.spec.output_config?.scene_reference_asset_id || '';
    setForm({
      prompt: workspace.spec.user_prompt || '',
      platform: workspace.spec.output_config?.platform || 'tiktok',
      duration: Number(workspace.spec.output_config?.target_duration_sec || 30),
      audience: workspace.spec.output_config?.target_audience || '',
      style: workspace.spec.output_config?.style_preference || TALKING_HEAD_STYLE_PREFERENCE,
      humanOnCamera: Boolean(workspace.spec.output_config?.human_on_camera),
      productReferenceAssetIds,
      sceneReferenceAssetId,
    });
    if (!productReferenceAssetIds.length && !sceneReferenceAssetId) {
      setProductAssets([]);
      setSceneAsset(null);
      return;
    }

    let cancelled = false;
    void assetApi.listAssets(projectId, { asset_type: 'image_reference', limit: 200 }).then((result) => {
      if (cancelled) return;
      const assetsById = new Map(result.items.map((asset) => [asset.id, asset]));
      setProductAssets(
        productReferenceAssetIds
          .map((assetId) => assetsById.get(assetId))
          .filter((asset): asset is AssetRecord => Boolean(asset))
      );
    }).catch(() => {
      if (!cancelled) setProductAssets([]);
    });
    void assetApi.listAssets(projectId, { asset_type: 'scene_reference', limit: 50 }).then((result) => {
      if (cancelled) return;
      const asset = result.items.find((item) => item.id === sceneReferenceAssetId) || null;
      setSceneAsset(asset);
    }).catch(() => {
      if (!cancelled) setSceneAsset(null);
    });

    return () => {
      cancelled = true;
    };
  }, [projectId, workspace?.spec]);

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

  const currentStep = resolveWorkspaceStep(workspace);

  useEffect(() => {
    setActiveStep((prev) => {
      if (currentStep > prev) return currentStep;
      if (prev > Math.max(currentStep, 1) && currentStep < 6) return currentStep;
      return prev;
    });
  }, [currentStep]);

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

  const readImageSize = (file: File) =>
    new Promise<{ width: number; height: number }>((resolve) => {
      const url = URL.createObjectURL(file);
      const image = new Image();
      image.onload = () => {
        resolve({ width: image.naturalWidth, height: image.naturalHeight });
        URL.revokeObjectURL(url);
      };
      image.onerror = () => {
        resolve({ width: 0, height: 0 });
        URL.revokeObjectURL(url);
      };
      image.src = url;
    });

  const uploadProductFile = async (file: File) => {
    const size = await readImageSize(file);
    return assetApi.uploadFile(projectId, {
      file,
      asset_type: 'image_reference',
      width: size.width || undefined,
      height: size.height || undefined,
    });
  };

  const uploadSceneFile = async (file: File) => {
    const size = await readImageSize(file);
    return assetApi.uploadFile(projectId, {
      file,
      asset_type: 'scene_reference',
      width: size.width || undefined,
      height: size.height || undefined,
    });
  };

  const handleProductUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []).filter((file) => file.type.startsWith('image/'));
    event.target.value = '';
    if (!files.length) return;
    const remaining = Math.max(0, 3 - form.productReferenceAssetIds.length);
    if (remaining <= 0) {
      setError('产品图最多上传 3 张。');
      return;
    }
    if (files.length > remaining) {
      setError(`产品图最多 3 张，本次只会上传前 ${remaining} 张。`);
    } else {
      setError(null);
    }
    setUploadingProducts(true);
    try {
      const uploaded: AssetRecord[] = [];
      for (const file of files.slice(0, remaining)) {
        uploaded.push(await uploadProductFile(file));
      }
      setProductAssets((prev) => [...prev, ...uploaded].slice(0, 3));
      setForm((prev) => ({
        ...prev,
        productReferenceAssetIds: [
          ...prev.productReferenceAssetIds,
          ...uploaded.map((asset) => asset.id),
        ].slice(0, 3),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '产品图上传失败');
    } finally {
      setUploadingProducts(false);
    }
  };

  const handleRemoveProductAsset = (assetId: string) => {
    setProductAssets((prev) => prev.filter((asset) => asset.id !== assetId));
    setForm((prev) => ({
      ...prev,
      productReferenceAssetIds: prev.productReferenceAssetIds.filter((id) => id !== assetId),
    }));
  };

  const handleSceneUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = Array.from(event.target.files || []).find((item) => item.type.startsWith('image/'));
    event.target.value = '';
    if (!file) return;
    setUploadingScene(true);
    try {
      const uploaded = await uploadSceneFile(file);
      setSceneAsset(uploaded);
      setForm((prev) => ({
        ...prev,
        sceneReferenceAssetId: uploaded.id,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '场地图上传失败');
    } finally {
      setUploadingScene(false);
    }
  };

  const handleRemoveSceneAsset = () => {
    setSceneAsset(null);
    setForm((prev) => ({
      ...prev,
      sceneReferenceAssetId: '',
    }));
  };

  const handleGeneratePlan = async () => {
    setActiveStep(2);
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
        product_reference_asset_ids: form.productReferenceAssetIds,
        scene_reference_asset_id: form.sceneReferenceAssetId || undefined,
      });
      await projectApi.activateSpec(projectId, version.id);
      await workflowApi.generateCreativePackage(projectId);
    });
  };

  const handleConfirmCreativePackage = async () => {
    setActiveStep(3);
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
    const feedback = creativePackageFeedback.trim();
    if (!feedback) {
      setError('请先填写对当前创意剧本包的不满意点，系统会用这段反馈重新生成。');
      return;
    }
    setActiveStep(2);
    await handleAction('regenerate-creative-package', async () => {
      if (creativePackageDecision) {
        await projectApi.selectDecision(projectId, creativePackageDecision.id, 'regenerate', feedback);
      }
      await workflowApi.generateCreativePackage(projectId);
      setCreativePackageFeedback('');
    });
  };

  const handleRegenerateKeyframes = async () => {
    const feedback = storyboardFeedback.trim();
    if (!feedback) {
      setError('请先填写对当前导演分镜图/关键帧的不满意点，系统会用这段反馈重新生成。');
      return;
    }
    setActiveStep(3);
    await handleAction('regenerate-storyboard', async () => {
      if (storyboardDecision) {
        await projectApi.selectDecision(projectId, storyboardDecision.id, 'regenerate', feedback);
      }
      await workflowApi.generateStoryboard(projectId);
      setStoryboardFeedback('');
    });
  };

  const handleRegenerateShot = async (shotId: string) => {
    await handleAction(`regenerate-shot-${shotId}`, async () => {
      await projectApi.regenerateShot(projectId, shotId);
    });
  };

  const handleRetryClipStage = async () => {
    setActiveStep(5);
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
      setActiveStep(5);
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
    if (!workspace || isStep6Locked) return;
    setActiveStep(6);
    if (!workspace.timeline && workspace.clips.length) {
      setStep6LockedAction('compose-timeline');
      await handleAction('compose-timeline', () => workflowApi.composeTimeline(projectId));
      return;
    }
    if (!workspace.latestExport && workspace.timeline) {
      setStep6LockedAction('trigger-export');
      const exportRecord = await handleAction('trigger-export', () => workflowApi.triggerExport(projectId, '1080p'));
      if (exportRecord) {
        const blob = await handleAction('download-export', () => projectApi.downloadLatestExport(projectId));
        if (blob) {
          triggerBlobDownload(blob, makeExportFilename(projectId, exportRecord));
          setStep6LockedAction('download-export');
        }
      }
      return;
    }
    if (workspace.latestExport) {
      const blob = await handleAction('download-export', () => projectApi.downloadLatestExport(projectId));
      if (blob) {
        triggerBlobDownload(blob, makeExportFilename(projectId, workspace.latestExport));
        setStep6LockedAction('download-export');
      }
      return;
    }
    if (workspace.timeline?.preview_uri) {
      triggerBrowserDownload(workspace.timeline.preview_uri, `vidmuse_${projectId}_timeline_preview.mp4`);
      setStep6LockedAction('download-export');
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
    ? isTalkingHeadProject ? '重试导演分镜图生成' : '重试关键帧生成'
    : !workspace.storyboardGrids.length
    ? '等待创意剧本确认'
    : storyboardDecision
      ? (storyboardConfirmOption?.title || storyboardConfirmOption?.label || (isTalkingHeadProject ? '确认导演分镜图并开始生成视频' : '确认关键帧并开始生成视频'))
    : isClipStageActive
      ? '视频生成中'
    : isProjectFailed
      ? '重新生成失败视频'
    : workspace.clips.length < sortedShots.length
        ? storyboardConfirmed
          ? workspace.clips.length ? '继续生成视频' : '生成视频'
          : isTalkingHeadProject ? '等待导演分镜图确认' : '等待关键帧确认'
        : '下一镜头';
  const primaryStep6Label = !workspace.timeline
    ? '本地拼接'
    : !workspace.latestExport
      ? '导出视频'
      : '下载视频';
  const step6EffectiveAction = actionLoading === 'compose-timeline' || actionLoading === 'trigger-export'
    ? actionLoading
    : step6LockedAction;
  const isStep6Locked = Boolean(step6EffectiveAction);
  const step6ButtonLabel = step6EffectiveAction === 'compose-timeline'
    ? '拼接中...'
    : step6EffectiveAction === 'trigger-export'
      ? '导出中...'
      : step6EffectiveAction === 'download-export'
        ? '已下载'
        : primaryStep6Label;
  const step2PrimaryLabel = creativePackageDecision
    ? (creativePackageConfirmOption?.title || creativePackageConfirmOption?.label || '确认创意剧本包并生成关键帧')
    : workspace.narrative
      ? '创意剧本包已生成'
      : '等待生成';
  const step3PrimaryLabel = primaryStep3Label;
  const briefRawEntries = rawPayloadEntries(workspace.brief?.raw_payload, [
    'title',
    'summary',
    'style_direction',
    'mood_tags',
  ]);
  const narrativeRawEntries = rawPayloadEntries(workspace.narrative?.raw_payload, [
    'shots',
    'story_arc',
    'characters',
    'scenes',
    'section_mapping',
  ]);
  const creativeSupplementEntries = [...briefRawEntries, ...narrativeRawEntries]
    .map(([key, value]) => ({ label: fieldLabel(key), value }))
    .filter((item) => item.label)
    .slice(0, 8);
  const narrativeCharacters = (
    workspace.narrative?.characters?.length
      ? workspace.narrative.characters
      : Array.isArray(workspace.narrative?.raw_payload?.characters)
        ? workspace.narrative.raw_payload.characters
        : []
  ).slice(0, 4);
  const narrativeScenes = (
    workspace.narrative?.scenes?.length
      ? workspace.narrative.scenes
      : Array.isArray(workspace.narrative?.raw_payload?.scenes)
        ? workspace.narrative.raw_payload.scenes
        : []
  ).slice(0, 4);
  const sectionMappings = (
    workspace.narrative?.section_mapping?.length
      ? workspace.narrative.section_mapping
      : Array.isArray(workspace.narrative?.raw_payload?.section_mapping)
        ? workspace.narrative.raw_payload.section_mapping
        : []
  ).slice(0, 6);
  const creativeOverviewCards = [
    { label: '视频主题', value: workspace.brief?.title },
    { label: '创意摘要', value: workspace.brief?.summary },
    { label: '风格方向', value: workspace.brief?.style_direction || form.style },
    { label: '情绪标签', value: workspace.brief?.mood_tags },
    { label: '故事弧', value: workspace.narrative?.story_arc || workspace.narrative?.raw_payload?.story_arc },
    { label: '发布平台', value: getPlatformLabel(form.platform) },
    { label: '目标受众', value: form.audience || workspace.spec?.output_config?.target_audience },
    { label: '视频规格', value: `${workspace.spec?.output_config?.aspect_ratio || FIXED_ASPECT_RATIO} · ${workspace.spec?.output_config?.video_resolution || FIXED_VIDEO_RESOLUTION} · ${form.duration}秒` },
  ];
  const highestReachableStep = Math.max(currentStep, activeStep);
  const completedShotCount = workspace.clips.length;
  const totalShotCount = sortedShots.length;
  const allClipsReady = totalShotCount > 0 && completedShotCount >= totalShotCount;
  const isWorkflowStepComplete = (step: number) => {
    if (step === 1) return Boolean(workspace.spec);
    if (step === 2) return Boolean(workspace.narrative) && !creativePackageDecision;
    if (step === 3) return Boolean(workspace.storyboardGrids.length);
    if (step === 4) return storyboardConfirmed || currentStep >= 5 || Boolean(workspace.clips.length);
    if (step === 5) return allClipsReady;
    if (step === 6) return Boolean(workspace.latestExport || workspace.timeline);
    return false;
  };

  const renderLoadingState = (title: string, description: string) => (
    <div className="flex min-h-[360px] flex-1 flex-col items-center justify-center rounded-2xl border border-violet-100 bg-violet-50/40 px-8 text-center">
      <motion.div
        className="mb-5 h-16 w-16 rounded-full border-4 border-violet-200 border-t-violet-600"
        animate={{ rotate: 360 }}
        transition={{ duration: 1.1, repeat: Infinity, ease: 'linear' }}
      />
      <div className="text-lg font-bold text-gray-900">{title}</div>
      <div className="mt-2 max-w-md text-sm text-gray-500">{description}</div>
      <button
        onClick={() => void handleAction('refresh-workspace', () => loadWorkspace(false))}
        className="mt-5 inline-flex items-center gap-2 rounded-xl border border-violet-100 bg-white px-4 py-2 text-sm font-medium text-violet-700 hover:bg-violet-50"
      >
        <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} /> 刷新数据
      </button>
    </div>
  );

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

      <div className="mt-10 flex min-h-0 flex-1 flex-col gap-3">
        {error ? (
          <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600">
            {error}
          </div>
        ) : null}

        <div className="rounded-2xl border border-gray-100 bg-white px-4 py-3 shadow-sm shadow-gray-200/50">
          <div className="grid grid-cols-6 gap-2">
            {WORKFLOW_STEPS.map((item) => {
              const isActive = activeStep === item.step;
              const isComplete = isWorkflowStepComplete(item.step);
              const canOpen = item.step <= highestReachableStep;
              return (
                <button
                  key={item.step}
                  type="button"
                  onClick={() => canOpen && setActiveStep(item.step)}
                  disabled={!canOpen}
                  className={`flex min-w-0 items-center gap-2 rounded-xl border px-3 py-2 text-left transition-colors ${
                    isActive
                      ? 'border-violet-200 bg-violet-50 text-violet-800 shadow-sm'
                      : isComplete
                        ? 'border-emerald-100 bg-emerald-50/60 text-emerald-800'
                        : canOpen
                          ? 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                          : 'border-gray-100 bg-gray-50 text-gray-300'
                  }`}
                >
                  <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    isComplete ? 'bg-emerald-500 text-white' : isActive ? 'bg-violet-600 text-white' : 'bg-gray-200 text-gray-500'
                  }`}>
                    {isComplete ? <CheckCircle2 className="h-4 w-4" /> : item.step}
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold">{item.title}</div>
                    <div className="truncate text-[11px] opacity-70">{item.description}</div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <Card className="flex-1 overflow-hidden p-5">
          {activeStep === 1 ? (
            <>
              <StepBadge step="1" title="输入需求" />
              <div className="grid min-h-0 flex-1 grid-cols-[1.2fr_0.8fr] gap-5 overflow-hidden">
                <div className="flex min-h-0 flex-col rounded-2xl border border-gray-100 bg-gray-50 p-4">
                  <div className="mb-4 flex gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-100">
                      <Bot className="h-5 w-5 text-indigo-600" />
                    </div>
                    <div className="rounded-2xl rounded-tl-none bg-white p-3 text-sm text-gray-700 shadow-sm">
                      你好！我是AI视频创作助手<br />请描述你想要制作的视频内容
                    </div>
                  </div>
                  <textarea
                    value={form.prompt}
                    onChange={(e) => setForm((prev) => ({ ...prev, prompt: e.target.value }))}
                    className="min-h-36 flex-1 resize-none rounded-2xl border border-gray-200 bg-white p-4 text-sm text-gray-800 outline-none focus:border-violet-300"
                    placeholder="请输入你的视频需求..."
                  />
                  <div className="mt-4 grid grid-cols-3 gap-3">
                    <select
                      value={PLATFORM_OPTIONS.some((item) => item.value === form.platform) ? form.platform : '__custom__'}
                      onChange={(e) => setForm((prev) => ({ ...prev, platform: e.target.value === '__custom__' ? '' : e.target.value }))}
                      className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 outline-none"
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
                      className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 outline-none"
                      aria-label="视频时长"
                    >
                      {TALKING_HEAD_DURATION_OPTIONS.map((duration) => (
                        <option key={duration} value={duration}>{duration}s</option>
                      ))}
                    </select>
                    <select
                      value={AUDIENCE_OPTIONS.includes(form.audience) ? form.audience : '__custom__'}
                      onChange={(e) => setForm((prev) => ({ ...prev, audience: e.target.value === '__custom__' ? '' : e.target.value }))}
                      className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 outline-none"
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
                      className="col-span-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 outline-none"
                      placeholder="也可以直接输入目标受众"
                    />
                    <label className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={form.humanOnCamera}
                        onChange={(e) => setForm((prev) => ({ ...prev, humanOnCamera: e.target.checked }))}
                        className="h-4 w-4 rounded border-gray-300 text-violet-600"
                      />
                      真人入镜
                    </label>
                    <div className="col-span-3 rounded-2xl border border-gray-200 bg-white p-3">
                      <div className="mb-2 flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-gray-900">产品图</div>
                          <div className="text-xs text-gray-400">最多 3 张，上传后会作为真实产品参考进入图片和视频提示词</div>
                        </div>
                        <button
                          type="button"
                          onClick={() => productInputRef.current?.click()}
                          disabled={uploadingProducts || form.productReferenceAssetIds.length >= 3}
                          className="inline-flex items-center gap-1 rounded-lg border border-violet-100 bg-violet-50 px-3 py-2 text-xs font-medium text-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <ImagePlus className="h-4 w-4" />
                          {uploadingProducts ? '上传中' : '上传'}
                        </button>
                        <input
                          ref={productInputRef}
                          type="file"
                          accept="image/*"
                          multiple
                          className="hidden"
                          onChange={handleProductUpload}
                        />
                      </div>
                      {productAssets.length ? (
                        <div className="grid grid-cols-3 gap-2">
                          {productAssets.map((asset, index) => (
                            <div key={asset.id} className="group relative aspect-[4/3] overflow-hidden rounded-lg border border-gray-100 bg-gray-50">
                              <img src={asset.storage_uri} alt={`产品图 ${index + 1}`} className="h-full w-full object-cover" />
                              <button
                                type="button"
                                onClick={() => handleRemoveProductAsset(asset.id)}
                                className="absolute right-1 top-1 rounded-md bg-white/90 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 opacity-0 shadow-sm transition group-hover:opacity-100"
                              >
                                移除
                              </button>
                            </div>
                          ))}
                        </div>
                      ) : form.productReferenceAssetIds.length ? (
                        <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500">
                          已关联 {form.productReferenceAssetIds.length} 张产品图
                        </div>
                      ) : (
                        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-3 py-4 text-center text-xs text-gray-400">
                          可选上传；上传后创作、导演分镜图、视频提示词都会明确引用产品图。
                        </div>
                      )}
                    </div>
                    <div className="col-span-3 rounded-2xl border border-gray-200 bg-white p-3">
                      <div className="mb-2 flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-gray-900">场地图</div>
                          <div className="text-xs text-gray-400">当前项目的空间、桌面、背景和光线参考；每个项目可单独替换</div>
                        </div>
                        <button
                          type="button"
                          onClick={() => sceneInputRef.current?.click()}
                          disabled={uploadingScene}
                          className="inline-flex items-center gap-1 rounded-lg border border-violet-100 bg-violet-50 px-3 py-2 text-xs font-medium text-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <ImagePlus className="h-4 w-4" />
                          {uploadingScene ? '上传中' : sceneAsset ? '替换' : '上传'}
                        </button>
                        <input
                          ref={sceneInputRef}
                          type="file"
                          accept="image/*"
                          className="hidden"
                          onChange={handleSceneUpload}
                        />
                      </div>
                      {sceneAsset ? (
                        <div className="group relative aspect-[16/9] overflow-hidden rounded-lg border border-gray-100 bg-gray-50">
                          <img src={sceneAsset.storage_uri} alt="场地图" className="h-full w-full object-cover" />
                          <button
                            type="button"
                            onClick={handleRemoveSceneAsset}
                            className="absolute right-1 top-1 rounded-md bg-white/90 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 opacity-0 shadow-sm transition group-hover:opacity-100"
                          >
                            移除
                          </button>
                        </div>
                      ) : form.sceneReferenceAssetId ? (
                        <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500">
                          已关联场地图
                        </div>
                      ) : (
                        <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-3 py-4 text-center text-xs text-gray-400">
                          未上传时使用系统兜底场地图；上传后创意剧本包会按“产品图在前、场地图最后”的顺序传给模型。
                        </div>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex min-h-0 flex-col">
                  <div className="mb-4 rounded-2xl border border-gray-100 bg-gray-50 p-4">
                    <h4 className="mb-3 text-sm font-bold text-gray-900">AI 理解的创作方向</h4>
                    <div className="grid grid-cols-2 gap-3">
                      {directionCards.map((item) => (
                        <div key={item.label} className="rounded-xl border border-gray-100 bg-white p-3 shadow-sm">
                          <div className="mb-1 text-xs font-medium text-violet-500">{item.label}</div>
                          <div className="line-clamp-3 text-sm text-gray-800">{item.value}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="mb-4 rounded-2xl border border-gray-100 bg-white p-4 text-sm text-gray-600">
                    <div className="mb-1 text-xs font-medium text-gray-400">固定口播风格</div>
                    <div className="font-medium text-gray-900">{TALKING_HEAD_STYLE_PREFERENCE}</div>
                  </div>
                  <button
                    onClick={() => void handleGeneratePlan()}
                    disabled={actionLoading === 'generate-creative-package' || !form.prompt.trim()}
                    className="mt-auto flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 py-3 text-sm font-medium text-white shadow-lg shadow-violet-200 transition-colors hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {actionLoading === 'generate-creative-package' ? '生成中...' : '生成创意剧本包'} <ArrowRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </>
          ) : null}

          {activeStep === 2 ? (
            <>
              <StepBadge step="2" title="创意剧本包" />
              {!workspace.narrative ? renderLoadingState('创意剧本包生成中', '前端会停留在当前阶段等待后端写入剧本包数据，数据到达后自动展示确认界面。') : (
                <div className="flex min-h-0 flex-1 flex-col">
                  <div className="mb-4 grid grid-cols-4 gap-3">
                    {creativeOverviewCards.map((item) => (
                      <div key={item.label} className="rounded-2xl border border-gray-100 bg-gray-50 p-3">
                        <div className="mb-1 text-xs font-medium text-gray-400">{item.label}</div>
                        <div className="line-clamp-3 text-sm font-semibold text-gray-900">{formatRichValue(item.value)}</div>
                      </div>
                    ))}
                  </div>
                  {creativePackageDecision ? (
                    <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                      创意剧本包已生成，确认后进入导演分镜图生成；也可以重新生成当前剧本包。
                    </div>
                  ) : null}
                  <div className="min-h-0 flex-1 overflow-y-auto rounded-2xl border border-gray-100 bg-white">
                    <div className="border-b border-gray-100 bg-gray-50 p-4">
                      <div className="mb-3 flex items-center justify-between">
                        <div>
                          <div className="text-sm font-bold text-gray-900">1. 创意方向总览</div>
                          <div className="text-xs text-gray-500">先看主题、风格、受众和最终交付规格是否正确。</div>
                        </div>
                        <div className="rounded-full bg-white px-3 py-1 text-xs font-medium text-violet-600">
                          {scriptShots.length} 个 Segment
                        </div>
                      </div>
                      <div className="grid grid-cols-4 gap-3">
                        {creativeOverviewCards.map((item) => (
                          <div key={`overview-${item.label}`} className="rounded-xl bg-white p-3 shadow-sm">
                            <div className="mb-1 text-xs font-medium text-gray-400">{item.label}</div>
                            <div className="line-clamp-3 text-sm font-semibold text-gray-900">{formatRichValue(item.value)}</div>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="border-b border-gray-100 p-4">
                      <div className="mb-3 text-sm font-bold text-gray-900">2. 人物、场景与创作策略</div>
                      <div className="grid grid-cols-3 gap-3">
                        <div className="rounded-2xl border border-gray-100 bg-gray-50 p-3">
                          <div className="mb-2 text-xs font-bold text-gray-900">人物设定</div>
                          <div className="space-y-2">
                            {narrativeCharacters.length ? narrativeCharacters.map((item, index) => (
                              <div key={index} className="rounded-xl bg-white p-3 text-xs leading-5 text-gray-600 shadow-sm">
                                {formatRichValue(item)}
                              </div>
                            )) : (
                              <div className="rounded-xl bg-white p-3 text-xs text-gray-400">未返回独立人物设定，以下方分段脚本为准。</div>
                            )}
                          </div>
                        </div>
                        <div className="rounded-2xl border border-gray-100 bg-gray-50 p-3">
                          <div className="mb-2 text-xs font-bold text-gray-900">场景设定</div>
                          <div className="space-y-2">
                            {narrativeScenes.length ? narrativeScenes.map((item, index) => (
                              <div key={index} className="rounded-xl bg-white p-3 text-xs leading-5 text-gray-600 shadow-sm">
                                {formatRichValue(item)}
                              </div>
                            )) : (
                              <div className="rounded-xl bg-white p-3 text-xs text-gray-400">未返回独立场景设定，以下方分段脚本为准。</div>
                            )}
                          </div>
                        </div>
                        <div className="rounded-2xl border border-gray-100 bg-gray-50 p-3">
                          <div className="mb-2 text-xs font-bold text-gray-900">创作策略补充</div>
                          <div className="space-y-2">
                            {creativeSupplementEntries.length ? creativeSupplementEntries.map((item) => (
                              <div key={item.label} className="rounded-xl bg-white p-3 text-xs leading-5 text-gray-600 shadow-sm">
                                <span className="font-semibold text-gray-900">{item.label}：</span>{formatRichValue(item.value)}
                              </div>
                            )) : (
                              <div className="rounded-xl bg-white p-3 text-xs text-gray-400">暂无可翻译的补充字段。</div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>

                    {sectionMappings.length ? (
                      <div className="border-b border-gray-100 p-4">
                        <div className="mb-3 text-sm font-bold text-gray-900">3. 内容结构节奏</div>
                        <div className="grid grid-cols-3 gap-3">
                          {sectionMappings.map((item, index) => (
                            <div key={index} className="rounded-xl border border-gray-100 bg-gray-50 p-3 text-xs leading-5 text-gray-600">
                              <div className="mb-1 font-bold text-gray-900">段落 {index + 1}</div>
                              {formatRichValue(item)}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    <div className="border-b border-gray-100 bg-gray-50 px-4 py-3 text-sm font-bold text-gray-900">
                      {sectionMappings.length ? '4' : '3'}. 分段脚本明细
                    </div>
                    {scriptShots.map((shot, index) => (
                      <div key={`${shot.shot_index ?? index}-${index}`} className="border-b border-gray-50 p-4">
                        <div className="mb-3 flex flex-wrap items-center gap-3">
                          <div className="rounded-full bg-violet-50 px-3 py-1 text-sm font-bold text-violet-700">S{(shot.shot_index ?? index) + 1}</div>
                          <div className="text-sm font-medium text-gray-500">{formatScriptTimeRange(shot, scriptShots, index)}</div>
                          {shot.duration_sec || shot.duration_ms ? (
                            <div className="text-xs text-gray-400">时长：{shot.duration_sec ? `${shot.duration_sec}s` : formatDurationLabel(shot.duration_ms)}</div>
                          ) : null}
                          {shot.location ? <div className="text-xs text-gray-400">场景：{shot.location}</div> : null}
                        </div>
                        <div className="grid grid-cols-[1fr_1fr_1.2fr] gap-3">
                          <div className="rounded-xl bg-gray-50 p-3">
                            <div className="mb-1 text-xs font-medium text-gray-400">镜头内容</div>
                            <div className="text-sm leading-6 text-gray-800">{getScriptShotContent(shot)}</div>
                          </div>
                          <div className="rounded-xl bg-gray-50 p-3">
                            <div className="mb-1 text-xs font-medium text-gray-400">视觉 / 动作 / 镜头语言</div>
                            <div className="space-y-2 text-sm leading-6 text-gray-700">
                              {shot.visual_description ? <div>{shot.visual_description}</div> : null}
                              {shot.action_description ? <div>{shot.action_description}</div> : null}
                              {shot.camera_language ? <div>{shot.camera_language}</div> : null}
                              {!shot.visual_description && !shot.action_description && !shot.camera_language ? <div className="text-gray-400">暂无展开字段</div> : null}
                            </div>
                          </div>
                          <div className="rounded-xl bg-gray-50 p-3">
                            <div className="mb-1 text-xs font-medium text-gray-400">口播台词</div>
                            <div className="text-sm leading-6 text-gray-800">{safeText(shot.dialogue || shot.lyric_text)}</div>
                          </div>
                        </div>
                        {(shot.start_frame_description || shot.middle_frame_description || shot.end_frame_description) ? (
                          <div className="mt-3 grid grid-cols-3 gap-3">
                            <div className="rounded-xl border border-gray-100 bg-white p-3 text-xs text-gray-600"><span className="font-semibold text-gray-900">起始帧：</span>{safeText(shot.start_frame_description)}</div>
                            <div className="rounded-xl border border-gray-100 bg-white p-3 text-xs text-gray-600"><span className="font-semibold text-gray-900">中间帧：</span>{safeText(shot.middle_frame_description)}</div>
                            <div className="rounded-xl border border-gray-100 bg-white p-3 text-xs text-gray-600"><span className="font-semibold text-gray-900">结束帧：</span>{safeText(shot.end_frame_description)}</div>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                  <div className="mt-4 space-y-3">
                    <textarea
                      value={creativePackageFeedback}
                      onChange={(event) => setCreativePackageFeedback(event.target.value)}
                      rows={3}
                      maxLength={4000}
                      placeholder="如果不满意，请写下希望调整的方向，例如：剧情更直接、口播更少、产品卖点更前置、节奏更紧凑。"
                      className="w-full resize-none rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm leading-6 text-gray-800 outline-none transition focus:border-violet-300 focus:ring-4 focus:ring-violet-100"
                    />
                    <div className="flex justify-end gap-3">
                    <button
                      onClick={() => void handleRegenerateCreativePackage()}
                      disabled={Boolean(actionLoading) || !workspace.spec}
                      className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-5 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <RefreshCw className={`h-4 w-4 ${actionLoading === 'regenerate-creative-package' ? 'animate-spin' : ''}`} /> 重新生成
                    </button>
                    <button
                      onClick={() => void handleConfirmCreativePackage()}
                      disabled={Boolean(actionLoading) || !creativePackageDecision}
                      className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-medium text-white shadow-lg shadow-violet-200 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {actionLoading === 'generate-storyboard' ? '导演分镜图生成中...' : step2PrimaryLabel} <ArrowRight className="h-4 w-4" />
                    </button>
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : null}

          {activeStep === 3 ? (
            <>
              <StepBadge step="3" title={isTalkingHeadProject ? '导演分镜图 / Director Shot List' : '关键帧画面'} />
              {!workspace.storyboardGrids.length && !isStoryboardFailed ? renderLoadingState('导演分镜图生成中', '前端正在等待后端返回 Director Shot List。生成完成后会在这里展示大图与 shot 行读取说明。') : (
                <div className="flex min-h-0 flex-1 flex-col">
                  <div className="mb-4 grid gap-3">
                    <div className="flex items-center justify-between gap-3">
                    <div className="text-sm text-gray-600">
                      {isTalkingHeadProject
                        ? `一张 21:9 导演分镜图 · ${storyOverviewSegments.length || scriptShots.length || 0} 个 shot`
                        : `镜头 ${(activeShot?.shot_index ?? activeNarrativeShot?.shot_index ?? selectedShotIndex) + 1}`}
                    </div>
                    <button
                      onClick={() => void handleRegenerateKeyframes()}
                      disabled={Boolean(actionLoading) || (!workspace.storyboardGrids.length && !isStoryboardFailed)}
                      className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <RefreshCw className={`h-4 w-4 ${actionLoading === 'regenerate-storyboard' ? 'animate-spin' : ''}`} /> 重新生成
                    </button>
                    </div>
                    <textarea
                      value={storyboardFeedback}
                      onChange={(event) => setStoryboardFeedback(event.target.value)}
                      rows={3}
                      maxLength={4000}
                      placeholder="如果不满意，请写下希望调整的画面反馈，例如：人物更像参考图、构图更干净、产品更突出、整体少一些杂乱元素。"
                      className="w-full resize-none rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm leading-6 text-gray-800 outline-none transition focus:border-violet-300 focus:ring-4 focus:ring-violet-100"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => storyOverviewUrl && setImagePreview({ title: 'Director Shot List', url: storyOverviewUrl, description: selectedSegment?.reading_instruction || '口播导演分镜图' })}
                    disabled={!storyOverviewUrl}
                    className="relative min-h-0 flex-1 overflow-hidden rounded-2xl bg-gray-100 text-left disabled:cursor-default"
                  >
                    {storyOverviewUrl ? (
                      <img src={storyOverviewUrl} className="h-full w-full object-contain bg-black" alt="Director Shot List" />
                    ) : (
                      <div className="flex h-full items-center justify-center text-sm text-gray-400">等待导演分镜图</div>
                    )}
                    {storyOverviewSegments.length ? (
                      <div className="absolute bottom-3 left-3 right-3 rounded-xl bg-white/90 px-4 py-3 text-sm text-gray-700 shadow-sm">
                        {storyOverviewSegments.length} 个 shot 已写入同一张导演分镜图，视频阶段逐行读取对应镜头。
                      </div>
                    ) : null}
                  </button>
                  <div className="mt-4 flex justify-end">
                    <button
                      onClick={() => setActiveStep(4)}
                      disabled={!workspace.storyboardGrids.length}
                      className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-5 py-2.5 text-sm font-medium text-white shadow-lg shadow-violet-200 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      确认导演分镜图 <ArrowRight className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : null}

          {activeStep === 4 ? (
            <>
              <StepBadge step="4" title="确认进入视频生成" />
              <div className="grid min-h-0 flex-1 grid-cols-[1fr_360px] gap-5 overflow-hidden">
                <div className="relative overflow-hidden rounded-2xl bg-gray-100">
                  {storyOverviewUrl ? (
                    <img src={storyOverviewUrl} className="h-full w-full object-contain bg-black" alt="Director Shot List" />
                  ) : renderLoadingState('等待导演分镜图', '需要先完成导演分镜图后才能确认进入视频生成。')}
                </div>
                <div className="flex flex-col rounded-2xl border border-gray-100 bg-gray-50 p-5">
                  <h4 className="text-lg font-bold text-gray-900">生成前确认</h4>
                  <p className="mt-2 text-sm leading-6 text-gray-600">
                    当前导演分镜图会作为所有 15 秒 shot 的统一视觉参考。确认后，系统会开始生成每个视频片段，这是高成本阶段。
                  </p>
                  <div className="mt-5 space-y-3 text-sm text-gray-600">
                    <div className="rounded-xl bg-white p-3">Shot 数：{storyOverviewSegments.length || scriptShots.length || 0}</div>
                    <div className="rounded-xl bg-white p-3">目标时长：{form.duration}秒</div>
                    <div className="rounded-xl bg-white p-3">最终比例：{workspace.spec?.output_config?.aspect_ratio || FIXED_ASPECT_RATIO}</div>
                  </div>
                  <button
                    onClick={() => void handleStep3Primary()}
                    disabled={Boolean(actionLoading) || !workspace.storyboardGrids.length || isClipStageActive}
                    className="mt-auto inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-5 py-3 text-sm font-medium text-white shadow-lg shadow-violet-200 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {actionLoading === 'generate-clips' ? '视频生成启动中...' : step3PrimaryLabel} <ArrowRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </>
          ) : null}

          {activeStep === 5 ? (
            <>
              <StepBadge step="5" title={isProjectFailed && !isStoryboardFailed ? '视频生成失败' : allClipsReady ? '视频片段已生成' : '视频生成中'} />
              <div className="grid min-h-0 flex-1 grid-cols-[1fr_360px] gap-5 overflow-hidden">
                <div className="flex min-h-0 flex-col">
                  <div className="relative min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-black">
                    {previewMedia && previewIsVideo ? (
                      <video ref={videoRef} src={previewMedia} className="absolute inset-0 h-full w-full bg-black object-contain" controls playsInline onEnded={handlePreviewEnded} onError={handlePreviewError} />
                    ) : (
                      <div className="flex h-full flex-col items-center justify-center text-sm text-gray-300">
                        {isProjectFailed && !isStoryboardFailed
                          ? '视频生成失败，请查看右侧失败原因后重试'
                          : workspace.clips.length
                            ? '选择右侧片段播放'
                            : '视频片段生成中'}
                      </div>
                    )}
                  </div>
                  <div className="mt-4">
                    <div className="mb-1.5 flex justify-between text-sm font-bold text-gray-900">
                      <span>总体进度</span>
                      <span>{clipProgress}%</span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
                      <div className="h-full rounded-full bg-violet-600" style={{ width: `${clipProgress}%` }} />
                    </div>
                    <div className="mt-1.5 text-xs text-gray-500">预计剩余时间：{estimatedRemaining}</div>
                  </div>
                </div>
                <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-gray-100 bg-gray-50 p-4">
                  {isProjectFailed && !isStoryboardFailed ? (
                    <div className="mb-3 shrink-0 rounded-xl border border-red-100 bg-red-50 p-3 text-xs text-red-700">
                      <div className="mb-1 font-semibold text-red-800">视频生成阶段失败</div>
                      <div className="mb-2 leading-5">后端已进入 failed，失败镜头可单独重试，也可以重新触发整个视频生成阶段。</div>
                      <button
                        onClick={() => void handleRetryClipStage()}
                        disabled={Boolean(actionLoading)}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <RefreshCw className={`h-3 w-3 ${actionLoading === 'retry-generate-clips' ? 'animate-spin' : ''}`} /> 重试视频生成阶段
                      </button>
                    </div>
                  ) : null}
                  <h4 className="mb-3 text-sm font-bold text-gray-900">片段列表</h4>
                  <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
                    {sortedShots.map((shot, index) => {
                      const clip = workspace.clips.find((item) => item.shot_id === shot.id);
                      const shotCells = shotCellsByShotId.get(shot.id) ?? [];
                      const thumb = isTalkingHeadProject ? storyOverviewUrl : shotCells[0]?.asset_url;
                      const isFailed = shot.status === 'failed' && !clip;
                      const failureMessage = shot.last_failure?.message || '视频生成失败，后端未返回更详细原因。';
                      const shotActionKey = `regenerate-shot-${shot.id}`;
                      return (
                        <div
                          key={shot.id}
                          className={`rounded-xl border p-3 ${
                            isFailed
                              ? 'border-red-100 bg-red-50/60'
                              : shot.id === activeShot?.id
                                ? 'border-violet-200 bg-violet-50'
                                : 'border-gray-100 bg-white'
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            <div className="h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-gray-100">
                              {thumb ? <img src={thumb} className={`h-full w-full object-cover ${clip ? '' : 'opacity-50 grayscale'}`} alt="" /> : null}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-sm font-medium text-gray-900">{isTalkingHeadProject ? `Shot ${shot.shot_index + 1} · Segment ${shot.shot_index + 1}` : `镜头 ${shot.shot_index + 1}`}</div>
                              <div className="text-xs text-gray-400">{formatTimeRange(shot)} · {clip ? '已生成' : isFailed ? '生成失败' : '等待生成'}</div>
                              {isFailed ? (
                                <div className="mt-1 truncate text-xs text-red-600" title={failureMessage}>
                                  失败原因：{failureMessage}
                                </div>
                              ) : null}
                            </div>
                            {clip ? (
                              <button
                                type="button"
                                onClick={() => {
                                  setSelectedShotIndex(index);
                                  setPlayMode('selected');
                                  setShouldAutoPlay(true);
                                }}
                                className="inline-flex items-center gap-1 rounded-lg border border-emerald-100 bg-white px-3 py-2 text-xs font-medium text-emerald-600 hover:bg-emerald-50"
                              >
                                <Play className="h-3 w-3" /> 播放
                              </button>
                            ) : isFailed ? (
                              <button onClick={() => void handleRegenerateShot(shot.id)} disabled={Boolean(actionLoading)} className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60">
                                <RefreshCw className={`h-3 w-3 ${actionLoading === shotActionKey ? 'animate-spin' : ''}`} /> 重试
                              </button>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <button
                    onClick={() => setActiveStep(6)}
                    disabled={!allClipsReady && !workspace.timeline && !workspace.latestExport}
                    className="mt-4 inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-5 py-3 text-sm font-medium text-white shadow-lg shadow-violet-200 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    进入拼接与导出 <ArrowRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </>
          ) : null}

          {activeStep === 6 ? (
            <>
              <StepBadge step="6" title="拼接与导出" />
              <div className="grid min-h-0 flex-1 grid-cols-[1fr_260px] gap-5 overflow-hidden">
                <div className="relative min-h-0 overflow-hidden rounded-2xl border border-gray-200 bg-black">
                  {previewMedia ? (
                    previewIsVideo ? (
                      <video ref={videoRef} src={previewMedia} className="absolute inset-0 h-full w-full bg-black object-contain" controls playsInline onEnded={handlePreviewEnded} onError={handlePreviewError} />
                    ) : (
                      <img src={previewMedia} className="absolute inset-0 h-full w-full object-contain" alt="Preview" />
                    )
                  ) : (
                    <div className="flex h-full items-center justify-center text-sm text-gray-300">等待拼接或导出结果</div>
                  )}
                </div>
                <div className="flex min-h-0 flex-col overflow-y-auto rounded-2xl border border-gray-100 bg-gray-50 p-4">
                  <h4 className="mb-3 text-sm font-bold text-gray-900">视频信息</h4>
                  <div className="mb-4 space-y-2 border-b border-gray-200 pb-4 text-sm text-gray-600">
                    <div>预览：{activeClip?.storage_uri ? selectedShotLabel : workspace.latestExport ? '最终导出' : workspace.timeline ? '拼接时间线' : '片段'}</div>
                    <div>时长：{formatDurationLabel(workspace.timeline?.total_duration_ms || activeClip?.duration_ms || 30000)}</div>
                    <div>分辨率：{ratioToResolution(workspace.spec?.output_config?.aspect_ratio, workspace.spec?.output_config?.video_resolution || workspace.latestExport?.resolution)}</div>
                    <div>最终比例：{workspace.spec?.output_config?.aspect_ratio || '--'}</div>
                    {isTalkingHeadProject ? <div>导演分镜图：{workspace.spec?.output_config?.story_board_aspect_ratio || '21:9'}</div> : null}
                    <div>生成时间：{new Date(workspace.latestExport?.created_at || workspace.project.updated_at).toLocaleString()}</div>
                  </div>
                  <div className="flex flex-col gap-2">
                    <button onClick={handlePlaySelectedShot} disabled={!activeClip?.storage_uri || !previewIsVideo} className="inline-flex items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60">
                      <Play className="h-4 w-4" /> 播放当前片段
                    </button>
                    <button onClick={handlePlaySequence} disabled={!playableShots.length} className="inline-flex items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60">
                      <Video className="h-4 w-4" /> 顺序播放全部片段
                    </button>
                    <button onClick={() => void handleExportPrimary()} disabled={Boolean(actionLoading) || isStep6Locked} className="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-medium text-white shadow-md shadow-violet-200 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60">
                      <Download className="h-4 w-4" /> {step6ButtonLabel}
                    </button>
                    <button
                      onClick={() => {
                        const shareUrl = workspace.latestExport?.storage_uri || workspace.timeline?.preview_uri || activeClip?.storage_uri;
                        if (shareUrl) navigator.clipboard.writeText(shareUrl).catch(() => undefined);
                      }}
                      className="inline-flex items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                    >
                      <Share className="h-4 w-4" /> 分享视频
                    </button>
                  </div>
                </div>
              </div>
            </>
          ) : null}
        </Card>
      </div>

      {/* legacy multi-card workspace layout removed
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
                  <div className="col-span-3 rounded-xl border border-gray-200 bg-white p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div>
                        <div className="text-xs font-semibold text-gray-900">产品图</div>
                        <div className="text-[10px] text-gray-400">最多 3 张，上传后会作为产品参考传入图片和视频提示词</div>
                      </div>
                      <button
                        type="button"
                        onClick={() => productInputRef.current?.click()}
                        disabled={uploadingProducts || form.productReferenceAssetIds.length >= 3}
                        className="inline-flex items-center gap-1 rounded-lg border border-violet-100 bg-violet-50 px-2.5 py-1.5 text-[11px] font-medium text-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <ImagePlus className="h-3.5 w-3.5" />
                        {uploadingProducts ? '上传中' : '上传'}
                      </button>
                      <input
                        ref={productInputRef}
                        type="file"
                        accept="image/*"
                        multiple
                        className="hidden"
                        onChange={handleProductUpload}
                      />
                    </div>
                    {productAssets.length ? (
                      <div className="grid grid-cols-3 gap-2">
                        {productAssets.map((asset, index) => (
                          <div key={asset.id} className="group relative aspect-square overflow-hidden rounded-lg border border-gray-100 bg-gray-50">
                            <img src={asset.storage_uri} alt={`产品图 ${index + 1}`} className="h-full w-full object-cover" />
                            <button
                              type="button"
                              onClick={() => handleRemoveProductAsset(asset.id)}
                              className="absolute right-1 top-1 rounded-md bg-white/90 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 opacity-0 shadow-sm transition group-hover:opacity-100"
                            >
                              移除
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : form.productReferenceAssetIds.length ? (
                      <div className="rounded-lg bg-gray-50 px-2 py-1.5 text-[11px] text-gray-500">
                        已关联 {form.productReferenceAssetIds.length} 张产品图
                      </div>
                  ) : (
                      <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-3 py-4 text-center text-[11px] text-gray-400">
                          可选上传；上传后创作、导演分镜图、视频提示词都会明确引用产品图。
                      </div>
                    )}
                  </div>
                  <div className="col-span-3 rounded-xl border border-gray-200 bg-white p-3">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div>
                        <div className="text-xs font-semibold text-gray-900">场地图</div>
                        <div className="text-[10px] text-gray-400">当前项目的空间、桌面、背景和光线参考，可随项目替换</div>
                      </div>
                      <button
                        type="button"
                        onClick={() => sceneInputRef.current?.click()}
                        disabled={uploadingScene}
                        className="inline-flex items-center gap-1 rounded-lg border border-violet-100 bg-violet-50 px-2.5 py-1.5 text-[11px] font-medium text-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <ImagePlus className="h-3.5 w-3.5" />
                        {uploadingScene ? '上传中' : sceneAsset ? '替换' : '上传'}
                      </button>
                      <input
                        ref={sceneInputRef}
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={handleSceneUpload}
                      />
                    </div>
                    {sceneAsset ? (
                      <div className="group relative aspect-video overflow-hidden rounded-lg border border-gray-100 bg-gray-50">
                        <img src={sceneAsset.storage_uri} alt="场地图" className="h-full w-full object-cover" />
                        <button
                          type="button"
                          onClick={handleRemoveSceneAsset}
                          className="absolute right-1 top-1 rounded-md bg-white/90 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 opacity-0 shadow-sm transition group-hover:opacity-100"
                        >
                          移除
                        </button>
                      </div>
                    ) : form.sceneReferenceAssetId ? (
                      <div className="rounded-lg bg-gray-50 px-2 py-1.5 text-[11px] text-gray-500">
                        已关联场地图
                      </div>
                    ) : (
                      <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-3 py-4 text-center text-[11px] text-gray-400">
                        未上传时使用系统兜底场地图；上传后创意剧本包会按“产品图在前、场地图最后”的顺序传给模型。
                      </div>
                    )}
                  </div>
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
              <p className="text-gray-500 text-xs mb-3 shrink-0">AI 一次性生成口播创意方向和 15 秒分段脚本，确认后进入导演分镜图生成</p>

              <div className="flex items-center gap-3 text-xs text-gray-600 mb-3 bg-gray-50 p-2.5 rounded-lg border border-gray-100 shrink-0 overflow-x-auto">
                <div><span className="text-gray-400">视频主题:</span> <span className="font-medium text-gray-900">{safeText(workspace.brief?.title, '待生成')}</span></div>
                <div><span className="text-gray-400">时长:</span> <span className="font-medium text-gray-900">{form.duration}秒</span></div>
                <div><span className="text-gray-400">风格:</span> <span className="font-medium text-gray-900">{safeText(workspace.brief?.style_direction, form.style)}</span></div>
                <div><span className="text-gray-400">平台:</span> <span className="font-medium text-gray-900">{getPlatformLabel(form.platform)}</span></div>
              </div>

              {creativePackageDecision ? (
                <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 shrink-0">
                  <div className="font-semibold mb-1">创意剧本包已生成，等待确认</div>
                  <div className="text-amber-700">确认后会进入导演分镜图生成；选择重新生成会重新生成创意方向和分段脚本。</div>
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
              <StepBadge step="3" title={isTalkingHeadProject ? '导演分镜图 / Director Shot List' : '生成关键帧画面'} />
              <p className="text-gray-500 text-xs mb-3 shrink-0">
                {isTalkingHeadProject
                  ? 'AI 生成一张覆盖完整视频的 21:9 导演分镜图，后续每个 15 秒 clip 读取对应 shot 行'
                  : 'AI 为每个镜头生成起始 / 中间 / 结尾三张关键帧，后续将按多图融合模式生成视频'}
              </p>

              <div className="flex items-center justify-between mb-3 shrink-0 gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-sm text-gray-600 shrink-0">
                    {isTalkingHeadProject ? 'Director Shot List：' : '镜头选择：'}
                  </span>
                  {isTalkingHeadProject ? (
                    <span className="rounded-full bg-violet-50 px-3 py-1 text-xs font-medium text-violet-700">
                      一张导演图 · {scriptShots.length || storyOverviewSegments.length || 0} 个 15s shot
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
                  <div className="text-amber-700">确认 Step 2 后会开始生成导演分镜图。</div>
                </div>
              ) : null}

              {storyboardDecision ? (
                <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 shrink-0">
                  <div className="font-semibold mb-1">{isTalkingHeadProject ? '导演分镜图已生成，等待确认' : '关键帧已生成，等待确认'}</div>
                  <div className="text-amber-700">确认后会进入视频生成；选择重新生成会重新生成{isTalkingHeadProject ? '导演分镜图' : '关键帧'}。</div>
                </div>
              ) : null}

              {isStoryboardFailed ? (
                <div className="mb-3 rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700 shrink-0">
                  <div className="font-semibold text-red-800 mb-1">{isTalkingHeadProject ? '导演分镜图生成失败' : '关键帧生成失败'}</div>
                  <div className="mb-2">上一次{isTalkingHeadProject ? '导演分镜图' : '三宫格生图'}没有生成可用结果，可以直接重试图片生成阶段。</div>
                  <button
                    onClick={() => void handleRegenerateKeyframes()}
                    disabled={Boolean(actionLoading)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <RefreshCw className={`w-3 h-3 ${actionLoading === 'regenerate-storyboard' ? 'animate-spin' : ''}`} /> 重试{isTalkingHeadProject ? '导演分镜图' : '关键帧生成'}
                  </button>
                </div>
              ) : null}

              <div className="flex-1 border border-violet-100 bg-violet-50/30 rounded-2xl p-3 mb-3 flex flex-col min-h-0">
                <div className="flex items-center gap-2 text-violet-600 font-medium text-xs mb-2 shrink-0">
                  <span className="w-1 h-3 border-l-2 border-violet-600 rounded"></span>
                  {isTalkingHeadProject
                    ? `Director Shot List · ${storyOverviewSegments.length || scriptShots.length || 0} 个 shot`
                    : `${activeShot ? '镜头' : '镜头'} ${activeShot ? activeShot.shot_index + 1 : activeNarrativeShot ? (activeNarrativeShot.shot_index ?? selectedShotIndex) + 1 : '--'}：${activeShot ? formatTimeRange(activeShot) : activeNarrativeShot ? formatScriptTimeRange(activeNarrativeShot, narrativeShots, selectedShotIndex) : '--'}`}
                  <span className="text-gray-400 font-normal ml-2">
                    | {isTalkingHeadProject ? '同一张导演分镜图供后续每个 15 秒 clip 读取对应行' : safeText(startCell?.scene_description || activeShot?.subject || activeNarrativeShot?.action_description || activeNarrativeShot?.scene_description)}
                  </span>
                </div>

                {isTalkingHeadProject ? (
                  <button
                    type="button"
                    onClick={() => {
                      if (!storyOverviewUrl) return;
                      setImagePreview({
                        title: 'Director Shot List',
                        url: storyOverviewUrl,
                        description: selectedSegment?.reading_instruction || '口播导演分镜图',
                      });
                    }}
                    disabled={!storyOverviewUrl}
                    className="relative group rounded-xl overflow-hidden mb-3 flex-1 min-h-0 bg-gray-100 text-left disabled:cursor-default"
                  >
                    {storyOverviewUrl ? (
                      <img src={storyOverviewUrl} className="w-full h-full object-contain bg-gray-950" alt="Director Shot List" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center px-3 text-center text-xs text-gray-500">等待生成导演分镜图</div>
                    )}
                    <div className="absolute top-2 left-2 rounded-lg bg-black/55 px-2 py-1 text-[10px] font-medium text-white">
                      Director Shot List · 21:9
                    </div>
                    {storyOverviewSegments.length ? (
                      <div className="absolute bottom-2 left-2 right-2 rounded-lg bg-white/90 px-3 py-2 text-[11px] text-gray-700 shadow-sm">
                        {storyOverviewSegments.length} 个 shot 已写入同一张导演分镜图，视频阶段逐行读取对应镜头。
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
                        '导演分镜图会覆盖所有 shot 的口播文案'
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
                        title: isTalkingHeadProject ? 'Director Shot List' : `三宫格原图${activeGrid?.grid_index ? ` ${activeGrid.grid_index}` : ''}`,
                        url: activeGridOriginalUrl,
                        description: isTalkingHeadProject ? '后端返回的口播导演分镜图' : '后端返回的三宫格原始大图',
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
                  ? 'AI 根据固定人物参考、同一导演分镜图和声色参考生成每个 15 秒口播视频片段，并准备拼接时间线'
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
                              {formatTimeRange(shot)} · {isTalkingHeadProject ? '导演图复用' : '三图融合'}
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
                          ? '先完成导演分镜图与每个 shot 的视频生成，随后才能拼接导出。'
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
                      <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><Maximize className="w-3 h-3" /></div>导演分镜图：{workspace.spec?.output_config?.story_board_aspect_ratio || '21:9'}</div>
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
                      disabled={Boolean(actionLoading) || isStep6Locked}
                      className="w-full bg-violet-600 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60 text-white rounded-lg py-2 text-xs font-medium transition-colors shadow-md shadow-violet-200 flex items-center justify-center gap-1.5"
                    >
                      <Download className="w-3 h-3" /> {step6ButtonLabel}
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
      */}

      {imagePreview ? (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-2 md:p-4"
          onClick={() => setImagePreview(null)}
        >
          <div
            className="flex h-[92vh] w-[96vw] max-w-[1800px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
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
            <div className="flex flex-1 min-h-0 items-center justify-center bg-gray-950 p-2 md:p-4">
              <img src={imagePreview.url} alt={imagePreview.title} className="h-full max-h-full w-full max-w-full object-contain" />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};
