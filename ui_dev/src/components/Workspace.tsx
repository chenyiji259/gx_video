import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CheckCircle2,
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
  isNotFoundError,
  projectApi,
  workflowApi,
} from '../api';
import type { Shot, ViewState, WorkspaceData } from '../types';

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
  duration: 30,
  audience: '',
  style: 'apple_keynote',
  humanOnCamera: false,
};

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

const ratioToResolution = (ratio?: string | null, resolution = '1080p') => {
  if (ratio === '9:16') return resolution === '1080p' ? '1080 × 1920' : ratio;
  if (ratio === '16:9') return resolution === '1080p' ? '1920 × 1080' : ratio;
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
  const [form, setForm] = useState(DEFAULT_FORM);

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
        shots,
        storyboard,
        clips,
        timeline,
        timelineSegments,
        latestExport,
      ] = await Promise.all([
        maybeLoad(() => projectApi.getActiveSpec(projectId)),
        maybeLoad(() => projectApi.getBrief(projectId)),
        maybeLoad(() => projectApi.getStyle(projectId)),
        maybeLoad(() => projectApi.getShots(projectId)),
        maybeLoad(() => projectApi.getStoryboardGrids(projectId)),
        maybeLoad(() => projectApi.getClips(projectId)),
        maybeLoad(() => projectApi.getTimeline(projectId)),
        maybeLoad(() => projectApi.getTimelineSegments(projectId)),
        maybeLoad(() => projectApi.getLatestExport(projectId)),
      ]);

      setWorkspace({
        project,
        spec,
        brief,
        style,
        shots: shots?.items ?? [],
        storyboardGrids: storyboard?.grids ?? [],
        clips: clips?.clips ?? [],
        timeline,
        timelineSegments: timelineSegments?.segments ?? [],
        latestExport,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载工作台失败');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    void loadWorkspace(true);
  }, [projectId]);

  useEffect(() => {
    if (!workspace?.spec) return;
    setForm({
      prompt: workspace.spec.user_prompt || '',
      platform: workspace.spec.output_config?.platform || 'tiktok',
      duration: Number(workspace.spec.output_config?.target_duration_sec || 30),
      audience: workspace.spec.output_config?.target_audience || '',
      style: workspace.spec.output_config?.style_preference || 'apple_keynote',
      humanOnCamera: Boolean(workspace.spec.output_config?.human_on_camera),
    });
  }, [workspace?.spec]);

  const sortedShots = useMemo(
    () => [...(workspace?.shots ?? [])].sort((a, b) => a.shot_index - b.shot_index),
    [workspace?.shots]
  );

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
  const activeClip = workspace?.clips.find((clip) => clip.shot_id === activeShot?.id) ?? null;

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

  const handleAction = async (key: string, task: () => Promise<unknown>) => {
    setActionLoading(key);
    setError(null);
    try {
      await task();
      await loadWorkspace(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
    } finally {
      setActionLoading(null);
    }
  };

  const handleGeneratePlan = async () => {
    await handleAction('generate-brief', async () => {
      const version = await projectApi.createSpecVersion(projectId, {
        user_prompt: form.prompt,
        platform: form.platform,
        target_audience: form.audience,
        style_preference: form.style,
        human_on_camera: form.humanOnCamera,
        target_duration_sec: form.duration,
        aspect_ratio: form.platform === 'bilibili' || form.platform === 'youtube' ? '16:9' : '9:16',
      });
      await projectApi.activateSpec(projectId, version.id);
      await workflowApi.generateBrief(projectId);
    });
  };

  const handleGenerateScript = async () => {
    await handleAction('generate-script', async () => {
      await workflowApi.generateNarrative(projectId);
      await workflowApi.generateShotPlan(projectId);
    });
  };

  const handleStep3Primary = async () => {
    if (!workspace) return;
    if (!workspace.storyboardGrids.length) {
      await handleAction('generate-storyboard', () => workflowApi.generateStoryboard(projectId));
      return;
    }
    if (!workspace.clips.length) {
      await handleAction('generate-clips', () => workflowApi.generateClips(projectId));
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
      await handleAction('trigger-export', () => workflowApi.triggerExport(projectId, '1080p'));
      return;
    }
    const mediaUrl = workspace.latestExport?.storage_uri || workspace.timeline?.preview_uri;
    if (mediaUrl) {
      window.open(mediaUrl, '_blank', 'noopener,noreferrer');
    }
  };

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
    { label: '平台', value: form.platform },
  ];

  const previewMedia = workspace.latestExport?.storage_uri || workspace.timeline?.preview_uri || activeClip?.storage_uri || startCell?.asset_url || '';
  const primaryStep3Label = !workspace.storyboardGrids.length
    ? '生成关键帧'
    : !workspace.clips.length
      ? '生成视频'
      : '下一镜头';
  const primaryStep6Label = !workspace.timeline
    ? '开始拼接'
    : !workspace.latestExport
      ? '导出视频'
      : '下载视频';

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
                  <div className="w-8 h-8 rounded-full overflow-hidden shrink-0 border border-gray-200">
                    <img src="https://images.unsplash.com/photo-1544005313-94ddf0286df2?ixlib=rb-4.0.3&auto=format&fit=crop&w=150&q=60" alt="User" />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <input
                    value={form.platform}
                    onChange={(e) => setForm((prev) => ({ ...prev, platform: e.target.value }))}
                    className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 outline-none"
                    placeholder="平台"
                  />
                  <input
                    type="number"
                    value={form.duration}
                    onChange={(e) => setForm((prev) => ({ ...prev, duration: Number(e.target.value || 30) }))}
                    className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 outline-none"
                    placeholder="时长"
                  />
                  <input
                    value={form.audience}
                    onChange={(e) => setForm((prev) => ({ ...prev, audience: e.target.value }))}
                    className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 outline-none"
                    placeholder="目标受众"
                  />
                  <input
                    value={form.style}
                    onChange={(e) => setForm((prev) => ({ ...prev, style: e.target.value }))}
                    className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 outline-none"
                    placeholder="视觉风格"
                  />
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
                disabled={actionLoading === 'generate-brief' || !form.prompt.trim()}
                className="w-full shrink-0 bg-violet-600 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60 text-white rounded-xl py-2.5 text-sm font-medium transition-colors shadow-lg shadow-violet-200 flex items-center justify-center gap-2 mb-3"
              >
                {actionLoading === 'generate-brief' ? '生成中...' : '生成视频方案'} <ArrowRight className="w-4 h-4" />
              </button>

              <div className="flex items-start gap-2 text-[10px] text-gray-400 shrink-0">
                <Lightbulb className="w-4 h-4 text-violet-500 shrink-0 mt-0.5" />
                <p>小贴士：描述越详细，生成效果越符合你的预期哦~</p>
              </div>
            </Card>
          </div>

          <div className="col-span-4 w-full h-full min-h-0">
            <Card className="w-full h-full overflow-hidden">
              <StepBadge step="2" title="生成分镜脚本" />
              <p className="text-gray-500 text-xs mb-3 shrink-0">AI 根据你的需求，生成视频分镜脚本</p>

              <div className="flex items-center gap-3 text-xs text-gray-600 mb-3 bg-gray-50 p-2.5 rounded-lg border border-gray-100 shrink-0 overflow-x-auto">
                <div><span className="text-gray-400">视频主题:</span> <span className="font-medium text-gray-900">{safeText(workspace.brief?.title, '待生成')}</span></div>
                <div><span className="text-gray-400">时长:</span> <span className="font-medium text-gray-900">{form.duration}秒</span></div>
                <div><span className="text-gray-400">风格:</span> <span className="font-medium text-gray-900">{safeText(workspace.brief?.style_direction, form.style)}</span></div>
                <div><span className="text-gray-400">平台:</span> <span className="font-medium text-gray-900">{form.platform}</span></div>
              </div>

              <div className="flex-1 overflow-y-auto rounded-xl border border-gray-100 text-sm min-h-0">
                <div className="grid grid-cols-[40px_60px_1fr_1fr] gap-2 p-3 border-b border-gray-100 font-medium text-gray-500 bg-gray-50 text-xs">
                  <div>镜头</div>
                  <div>时间</div>
                  <div>画面内容</div>
                  <div>旁白/字幕</div>
                </div>
                {sortedShots.length ? (
                  sortedShots.map((shot) => (
                    <div key={shot.id} className="grid grid-cols-[40px_60px_1fr_1fr] gap-2 p-3 border-b border-gray-50 items-center">
                      <div className="text-gray-400">{shot.shot_index + 1}</div>
                      <div className="text-gray-500 text-xs">{formatTimeRange(shot)}</div>
                      <div className="text-xs text-gray-800 line-clamp-3">{safeText(shot.subject || shot.location)}</div>
                      <div className="text-xs text-gray-600 line-clamp-3">{safeText(shot.dialogue || shot.lyric_text)}</div>
                    </div>
                  ))
                ) : (
                  <div className="p-6 text-sm text-gray-400 text-center">还没有分镜脚本，先在 Step 1 生成视频方案。</div>
                )}
              </div>

              <div className="flex items-center gap-2 mt-4 shrink-0">
                <button
                  onClick={() => void handleGenerateScript()}
                  disabled={actionLoading === 'generate-script' || !workspace.spec}
                  className="flex-1 border border-gray-200 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 text-gray-700 rounded-xl py-2.5 text-sm font-medium transition-colors flex items-center justify-center gap-2"
                >
                  <RefreshCw className={`w-4 h-4 ${actionLoading === 'generate-script' ? 'animate-spin' : ''}`} /> 重新生成
                </button>
                <button
                  onClick={() => void handleGenerateScript()}
                  disabled={actionLoading === 'generate-script' || !workspace.spec}
                  className="flex-1 bg-violet-600 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60 text-white rounded-xl py-2.5 text-sm font-medium transition-colors shadow-lg shadow-violet-200 flex items-center justify-center gap-2"
                >
                  {actionLoading === 'generate-script' ? '生成中...' : '下一步：生成关键帧'} <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </Card>
          </div>

          <div className="col-span-5 w-full h-full min-h-0">
            <Card className="w-full h-full overflow-hidden">
              <StepBadge step="3" title="生成关键帧画面" />
              <p className="text-gray-500 text-xs mb-3 shrink-0">AI 为每个镜头生成起始 / 中间 / 结尾三张关键帧，后续将按多图融合模式生成视频</p>

              <div className="flex items-center justify-between mb-3 shrink-0 gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-sm text-gray-600 shrink-0">镜头选择：</span>
                  <div className="flex gap-2 overflow-x-auto">
                    {sortedShots.map((shot, index) => (
                      <button
                        key={shot.id}
                        onClick={() => setSelectedShotIndex(index)}
                        className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors shrink-0 ${index === selectedShotIndex ? 'bg-violet-600 text-white shadow-md shadow-violet-200' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}
                      >
                        {shot.shot_index + 1}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="text-xs text-gray-500 shrink-0">当前步骤：{currentStep}/6</div>
              </div>

              <div className="flex-1 border border-violet-100 bg-violet-50/30 rounded-2xl p-3 mb-3 flex flex-col min-h-0">
                <div className="flex items-center gap-2 text-violet-600 font-medium text-xs mb-2 shrink-0">
                  <span className="w-1 h-3 border-l-2 border-violet-600 rounded"></span>
                  镜头 {activeShot ? activeShot.shot_index + 1 : '--'}：{activeShot ? formatTimeRange(activeShot) : '--'}
                  <span className="text-gray-400 font-normal ml-2">| {safeText(startCell?.scene_description || activeShot?.subject)}</span>
                </div>

                <div className="grid grid-cols-3 gap-3 mb-3 flex-1 min-h-0">
                  {[
                    { label: '起始帧', cell: startCell, active: true },
                    { label: '中间帧', cell: middleCell, active: false },
                    { label: '结束帧', cell: endCell, active: false },
                  ].map((frame, index) => (
                    <div key={index} className="relative group rounded-xl overflow-hidden h-full bg-gray-100">
                      {frame.cell?.asset_url ? (
                        <img src={frame.cell.asset_url} className="w-full h-full object-cover" alt={frame.label} />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-xs text-gray-400">待生成</div>
                      )}
                      <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent"></div>
                      <div className="absolute top-2 left-2 flex items-center gap-1.5">
                        <div className={`w-2.5 h-2.5 rounded-full border-2 border-white ${frame.active ? 'bg-violet-500' : 'bg-white/40'}`}></div>
                        <span className="text-white text-[10px] font-medium drop-shadow">{frame.label}</span>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="text-center text-xs font-medium text-gray-700 bg-white/70 py-1.5 rounded-lg backdrop-blur-sm border border-white shrink-0">
                  {safeText(activeShot?.dialogue || activeShot?.lyric_text, '当前镜头暂无文案')}
                </div>
              </div>

              <div className="flex items-center justify-between shrink-0">
                <button
                  onClick={() => setSelectedShotIndex((prev) => Math.max(0, prev - 1))}
                  className="flex items-center gap-1.5 text-gray-500 hover:text-gray-900 px-3 py-1.5 bg-gray-50 rounded-xl transition-colors font-medium text-xs"
                >
                  <ArrowLeft className="w-3 h-3" /> 上一镜头
                </button>
                <div className="flex gap-2">
                  <button
                    onClick={() => void handleAction('refresh-storyboard', () => workflowApi.generateStoryboard(projectId))}
                    disabled={actionLoading === 'refresh-storyboard'}
                    className="flex items-center gap-1.5 text-gray-600 hover:text-gray-900 px-3 py-1.5 bg-white border border-gray-200 rounded-xl transition-colors font-medium text-xs disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <RefreshCw className={`w-3 h-3 ${actionLoading === 'refresh-storyboard' ? 'animate-spin' : ''}`} /> 重新生成
                  </button>
                  <button className="flex items-center gap-1.5 text-gray-600 px-3 py-1.5 bg-white border border-gray-200 rounded-xl font-medium text-xs opacity-60 cursor-not-allowed">
                    <PenSquare className="w-3 h-3" /> 修改提示词
                  </button>
                </div>
                <button
                  onClick={() => void handleStep3Primary()}
                  disabled={Boolean(actionLoading)}
                  className="flex items-center gap-1.5 bg-violet-600 hover:bg-violet-700 text-white px-4 py-1.5 rounded-xl transition-all shadow-md shadow-violet-200 font-medium text-xs disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {actionLoading && ['generate-storyboard', 'generate-clips'].includes(actionLoading) ? '处理中...' : primaryStep3Label} <ArrowRight className="w-3 h-3" />
                </button>
              </div>

              <div className="mt-3 flex gap-2 overflow-x-auto items-center justify-between border-t border-gray-100 pt-3 shrink-0">
                {sortedShots.length ? (
                  sortedShots.map((shot, idx) => {
                    const cells = shotCellsByShotId.get(shot.id) ?? [];
                    const thumb = cells[0]?.asset_url;
                    return (
                    <button
                      key={`${shot.id}-${idx}`}
                      onClick={() => setSelectedShotIndex(idx)}
                      className={`w-16 aspect-video rounded-lg overflow-hidden shrink-0 border-2 ${idx === selectedShotIndex ? 'border-violet-500 shadow-sm' : 'border-transparent opacity-70 hover:opacity-100'} transition-all cursor-pointer`}
                    >
                      {thumb ? <img src={thumb} className="w-full h-full object-cover" alt="" /> : null}
                    </button>
                    );
                  })
                ) : (
                  <div className="text-xs text-gray-400">关键帧尚未生成</div>
                )}
              </div>
            </Card>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-2 flex-1 min-h-0 items-stretch">
          <div className="col-span-5 w-full h-full min-h-0">
            <Card className="w-full h-full overflow-hidden">
              <StepBadge step="5" title="视频生成中" />
              <p className="text-gray-500 text-xs mb-4 shrink-0">AI 根据每个镜头的三张关键帧做多图融合生成视频片段，并准备拼接时间线</p>

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

              <div className="flex-1 overflow-y-auto space-y-3 mb-4 relative pr-2 min-h-0">
                <div className="absolute left-5 top-5 bottom-5 w-[1.5px] bg-gray-100 z-0"></div>

                {sortedShots.length ? (
                  sortedShots.map((shot) => {
                    const clip = workspace.clips.find((item) => item.shot_id === shot.id);
                    const shotCells = shotCellsByShotId.get(shot.id) ?? [];
                    const thumb = shotCells[0]?.asset_url;
                    return (
                      <div key={shot.id} className="relative z-10 flex items-center justify-between bg-white border border-gray-100 rounded-xl p-2 shadow-sm">
                        <div className="flex items-center gap-2.5">
                          <div className="w-10 h-10 rounded-lg overflow-hidden bg-gray-100 shrink-0 border border-gray-200">
                            {thumb ? <img src={thumb} className={`w-full h-full object-cover ${clip ? '' : 'grayscale opacity-60'}`} alt="" /> : null}
                          </div>
                          <div>
                            <div className="text-xs font-medium text-gray-900">镜头 {shot.shot_index + 1}</div>
                            <div className="text-[10px] text-gray-400">{formatTimeRange(shot)} · 三图融合</div>
                          </div>
                        </div>
                        <div>
                          {clip ? (
                            <div className="flex items-center gap-1 text-emerald-600 text-xs font-medium mr-2">
                              <CheckCircle2 className="w-3 h-3" /> 已生成
                            </div>
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
                        ? '3 个镜头的视频片段已就绪，下一步可在 Step 6 触发拼接。'
                        : '先完成每个镜头的三图关键帧与融合生成，随后才能拼接导出。'}
                  </p>
                </div>
              </div>
            </Card>
          </div>

          <div className="col-span-7 w-full h-full min-h-0">
            <Card className="w-full h-full overflow-hidden">
              <StepBadge step="6" title="视频生成完成" />
              <p className="text-gray-500 text-xs mb-4 shrink-0">你的视频预览、拼接与导出都在这里收口</p>

              <div className="flex gap-4 flex-1 min-h-0">
                <div className="flex-1 h-full min-h-0">
                  <div className="relative h-full w-full bg-black rounded-xl overflow-hidden group shadow-md border border-gray-200 flex justify-center items-center">
                    {previewMedia ? (
                      previewMedia.endsWith('.mp4') ? (
                        <video src={previewMedia} className="absolute inset-0 w-full h-full object-cover" muted playsInline />
                      ) : (
                        <img src={previewMedia} className="absolute inset-0 w-full h-full object-cover" alt="Preview" />
                      )
                    ) : (
                      <div className="text-sm text-gray-300">等待拼接或导出结果</div>
                    )}
                    <div className="absolute inset-0 bg-black/20 group-hover:bg-black/40 transition-colors flex items-center justify-center cursor-pointer">
                      <div className="w-16 h-16 bg-white/20 backdrop-blur-md rounded-full flex items-center justify-center shadow-2xl border border-white/30">
                        <Play className="w-8 h-8 text-white ml-1 shadow-sm" />
                      </div>
                    </div>

                    <div className="absolute bottom-0 inset-x-0 p-3 bg-gradient-to-t from-black/80 to-transparent flex items-center gap-2 text-white text-[10px]">
                      <Play className="w-4 h-4 cursor-pointer" />
                      <div className="h-1 bg-white/30 flex-1 rounded-full overflow-hidden cursor-pointer">
                        <div className="h-full bg-violet-500 w-1/3"></div>
                      </div>
                      <span className="tabular-nums">00:00 / {Math.max(1, Math.round((workspace.timeline?.total_duration_ms || activeClip?.duration_ms || 30000) / 1000)).toString().padStart(2, '0')}</span>
                      <Maximize className="w-3 h-3 cursor-pointer ml-1" />
                    </div>
                  </div>
                </div>

                <div className="w-[180px] flex flex-col shrink-0 overflow-y-auto pr-1">
                  <h4 className="font-bold text-gray-900 mb-3 text-sm">视频信息</h4>
                  <div className="space-y-2 text-xs text-gray-600 mb-4 border-b border-gray-100 pb-4">
                    <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><Video className="w-3 h-3" /></div>时长：{formatDurationLabel(workspace.timeline?.total_duration_ms || activeClip?.duration_ms || 30000)}</div>
                    <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><CheckCircle2 className="w-3 h-3" /></div>分辨率：{ratioToResolution(workspace.spec?.output_config?.aspect_ratio, workspace.latestExport?.resolution)}</div>
                    <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><RefreshCw className="w-3 h-3" /></div>比例：{workspace.spec?.output_config?.aspect_ratio || '--'}</div>
                    <div className="flex items-center gap-1.5"><div className="w-4 flex justify-center"><Clock className="w-3 h-3" /></div>生成时间：{new Date(workspace.latestExport?.created_at || workspace.project.updated_at).toLocaleString()}</div>
                  </div>

                  <h4 className="font-bold text-gray-900 mb-3 text-sm">下一步</h4>
                  <div className="flex flex-col gap-2">
                    <button className="w-full bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 rounded-lg py-2 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 opacity-60 cursor-not-allowed">
                      <PenSquare className="w-3 h-3 text-gray-400" /> 编辑视频
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
                        const shareUrl = workspace.latestExport?.storage_uri || workspace.timeline?.preview_uri;
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
    </div>
  );
};

const Clock = ({ className }: { className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);
