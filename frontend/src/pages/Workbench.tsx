import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { 
  Bot, 
  Loader2, 
  ArrowLeft,
  Layout,
  Menu,
  ChevronRight,
  Activity,
  AlertTriangle,
  ChevronLeft,
  CheckCircle2,
  RotateCcw,
  Zap
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '@/lib/utils';
import { projectService, chatService, workflowService, projectSpecService } from '@/services/api';
import { useProjectStore } from '@/stores/projectStore';
import { useProjectEvents } from '@/lib/sse';
import { streamMessage } from '@/services/chatStream';

// Stage components
import { ProcessNodes } from '@/components/workbench/ProcessNodes';
import { SetupView } from '@/components/workbench/SetupView';
import { AIDirectorPanel } from '@/components/workbench/AIDirectorPanel';
import { BriefView } from '@/components/workbench/BriefView';
import { NarrativeView } from '@/components/workbench/NarrativeView';
import { StoryboardReviewer } from '@/components/workbench/StoryboardReviewer';
import { VideoGenerationWorkspace } from '@/components/workbench/VideoGenerationWorkspace';
import { VideoCompositionWorkspace } from '@/components/workbench/VideoCompositionWorkspace';
import { VideoExportWorkspace } from '@/components/workbench/VideoExportWorkspace';

const STAGE_LABELS: Record<string, string> = {
  created: '项目设置',
  input_ready: '需求输入',
  brief_ready: '创意设计',
  narrative_ready: '叙事剧本',
  visual_bible_ready: '叙事剧本',
  shot_plan_ready: '九宫格准备',
  storyboard_ready: '九宫格图',
  clips_generating: '视频生成',
  clips_ready: '视频生成',
  video_composition: '视频合成',
  timeline_ready: '视频合成',
  export_ready: '导出',
  completed: '已完成',
  failed: '处理失败',
};

const StageTransitionOverlay = ({
  visible,
  message,
  progress,
  stage,
}: {
  visible: boolean;
  message: string | null;
  progress: number;
  stage: string;
}) => {
  if (!visible) return null;
  const steps = ['需求', '创意', '剧本', '九宫格', '视频', '导出'];
  const activeIndex = Math.max(0, Math.min(steps.length - 1, Math.floor((progress || 0) / 18)));
  return (
    <motion.div
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      className="pointer-events-none sticky top-4 z-40 mb-4 glass-panel px-6 py-4 shadow-2xl rounded-3xl mx-4"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-4">
          <div className="relative flex h-12 w-12 items-center justify-center rounded-2xl bg-cyan-500/10 border border-cyan-500/20">
            <Zap size={22} className="text-cyan-400 animate-pulse" />
            <span className="absolute inset-[-5px] border border-cyan-400/10 animate-ping rounded-2xl" />
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-slate-400 font-space">
              {STAGE_LABELS[stage] || stage}
            </p>
            <h2 className="mt-0.5 text-lg font-bold text-white">
              {message || '正在推进到下一阶段...'}
            </h2>
          </div>
        </div>
        <div className="min-w-0 flex-1 lg:max-w-xl">
          <div className="grid grid-cols-6 gap-3">
            {steps.map((step, idx) => (
              <div key={step} className="min-w-0">
                <div className={cn('h-1.5 overflow-hidden rounded-full bg-slate-800', idx <= activeIndex && 'bg-slate-700')}>
                  <div className={cn("h-full w-full origin-left bg-gradient-to-r from-cyan-400 to-violet-500 transition-transform duration-1000", idx < activeIndex ? "scale-x-100" : idx === activeIndex ? "scale-x-50 animate-pulse" : "scale-x-0")} />
                </div>
                <p className={cn("mt-2 truncate text-center text-[10px] font-bold tracking-wider transition-colors", idx <= activeIndex ? "text-cyan-400" : "text-slate-500")}>{step}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  );
};

const DECISION_STAGE_MAP: Record<string, string[]> = {
  input_ready: ['select_style_direction'],
  brief_ready: ['confirm_brief'],
  narrative_ready: ['confirm_narrative'],
  shot_plan_ready: ['confirm_shot_plan'],
  storyboard_ready: ['confirm_storyboard', 'confirm_cost_clips'],
};

const DECISION_NEXT_LABEL: Record<string, string> = {
  select_style_direction: '确认并生成创意方案',
  confirm_brief: '确认并生成叙事剧本',
  confirm_narrative: '确认并生成九宫格分镜',
  confirm_shot_plan: '确认并生成九宫格分镜',
  confirm_storyboard: '确认并生成视频片段',
  confirm_cost_clips: '确认并生成视频片段',
};

const StageDecisionBar = ({
  decision,
  isGenerating,
  onDecision,
}: {
  decision: any | null;
  isGenerating: boolean;
  onDecision: (decisionId: string, optionId: string) => void;
}) => {
  if (!decision) return null;

  const options = Array.isArray(decision.options_payload) ? decision.options_payload : [];

  return (
    <div className="absolute left-1/2 bottom-6 z-50 w-[min(960px,calc(100%-48px))] -translate-x-1/2">
      <div className="glass-panel border border-cyan-400/20 rounded-3xl px-5 py-4 shadow-[0_24px_80px_rgba(0,0,0,0.55)]">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <p className="text-[10px] font-bold font-space text-cyan-400 tracking-[0.28em] uppercase">
              阶段确认
            </p>
            <h3 className="mt-1 text-base font-bold text-white">
              {DECISION_NEXT_LABEL[decision.decision_type] || '确认当前阶段'}
            </h3>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {options.length > 0 ? (
              options.map((opt: any) => (
                <button
                  key={opt.id}
                  disabled={isGenerating}
                  onClick={() => onDecision(decision.id, opt.id)}
                  className="inline-flex items-center gap-2 rounded-full bg-cyan-500 px-5 py-2.5 text-xs font-black text-black transition-all hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <CheckCircle2 size={16} />
                  {opt.title || '确认'}
                </button>
              ))
            ) : (
              <button
                disabled={isGenerating}
                onClick={() => onDecision(decision.id, 'confirm')}
                className="inline-flex items-center gap-2 rounded-full bg-cyan-500 px-5 py-2.5 text-xs font-black text-black transition-all hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <CheckCircle2 size={16} />
                确认并继续
              </button>
            )}
            <button
              disabled={isGenerating}
              onClick={() => onDecision(decision.id, 'regenerate')}
              className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-5 py-2.5 text-xs font-bold text-slate-200 transition-all hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RotateCcw size={16} />
              重新生成
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export const Workbench = () => {
  const { t } = useTranslation();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const {
    project,
    setProject,
    pendingDecisions,
    setPendingDecisions,
    refreshFlag,
    isGenerating,
    setIsGenerating,
    setGeneratingMessage,
    generatingMessage,
    generationProgress,
    setGenerationProgress,
    productionViewStage,
    setProductionViewStage,
    hydrateProductionViewStage,
    setShotRunState,
    resetShotRunStates,
    failedStageAction,
    failedStageMessage,
    setFailedStageInfo,
  } = useProjectStore();
  useProjectEvents(projectId);
  const latestDirectorMessage = useProjectStore((s) => s.latestDirectorMessage);

  // Layout State
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isChatOpen, setIsChatOpen] = useState(false);

  // Workflow State
  const [prompt, setPrompt] = useState('');
  const [messages, setMessages] = useState<any[]>([]);
  const [inputText, setInputText] = useState('');
  const [loading, setLoading] = useState(true);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [sending, setSending] = useState(false);
  const [viewStage, setViewStage] = useState<string | null>(null);
  const [isViewPinned, setIsViewPinned] = useState(false);
  
  // Setup state
  const [isCreating, setIsCreating] = useState(false);
  const [selectedPlatform, setSelectedPlatform] = useState<string>('tiktok');
  const [selectedDuration, setSelectedDuration] = useState<number>(60);
  const [durationInput, setDurationInput] = useState<string>('60');
  const [targetAudience, setTargetAudience] = useState<string>('');
  const [selectedStyle, setSelectedStyle] = useState<string>('animated_tech');
  const [humanOnCamera, setHumanOnCamera] = useState<boolean | null>(null);
  const refreshTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const canShowProductionProgress =
    project?.current_stage === 'clips_generating' ||
    project?.current_stage === 'storyboard_ready';
  
  const activeStage =
    isViewPinned && viewStage
      ? viewStage
      : canShowProductionProgress && productionViewStage === 'clips_generating'
      ? 'clips_generating'
      : (viewStage || project?.current_stage || 'created');

  const decisionTypesForVisibleStage = [
    ...(DECISION_STAGE_MAP[activeStage] || []),
    ...(DECISION_STAGE_MAP[project?.current_stage || ''] || []),
  ];
  const activeDecision = pendingDecisions.find((decision: any) =>
    decisionTypesForVisibleStage.includes(decision.decision_type)
  ) || null;

  const resetGeneratingState = () => {
    setIsGenerating(false);
    setGeneratingMessage(null);
    setGenerationProgress(0);
    setProductionViewStage('idle');
    resetShotRunStates();
  };

  useEffect(() => {
    hydrateProductionViewStage(projectId);
    if (!projectId) return;
    if (isInitialLoad) {
      fetchProjectData(true);
    } else {
      if (refreshTimeoutRef.current) clearTimeout(refreshTimeoutRef.current);
      refreshTimeoutRef.current = setTimeout(() => fetchProjectData(true), 300);
    }
    return () => {
      if (refreshTimeoutRef.current) clearTimeout(refreshTimeoutRef.current);
    };
  }, [projectId, refreshFlag]);

  useEffect(() => {
    if (!project?.current_stage) return;
    if (!isViewPinned || !viewStage) {
      if (project.current_stage === 'timeline_ready') {
        setViewStage('video_composition');
      } else {
        setViewStage(project.current_stage);
      }
    }
  }, [project?.current_stage, isViewPinned, viewStage]);

  useEffect(() => {
    if (latestDirectorMessage) {
      setMessages(prev => [...prev, latestDirectorMessage]);
      useProjectStore.getState().setLatestDirectorMessage(null);
    }
  }, [latestDirectorMessage]);

  useEffect(() => {
    if (!projectId) return;
    const shouldPoll = project?.current_stage === 'input_ready' || isGenerating;
    if (!shouldPoll) return;
    const intervalId = window.setInterval(() => {
      void fetchProjectData(true);
    }, 8000);
    return () => window.clearInterval(intervalId);
  }, [projectId, project?.current_stage, isGenerating]);

  const fetchProjectData = async (isRefresh = false) => {
    if (!projectId) return;
    try {
      if (!isRefresh || isInitialLoad) setLoading(true);
      const [projRes, decRes] = await Promise.all([
        projectService.getProject(projectId),
        projectService.getDecisions(projectId)
      ]);

      if (projRes.success) {
        const stageChanged = !!project?.current_stage && project.current_stage !== projRes.data.current_stage;
        const versionsChanged =
          JSON.stringify(project?.active_versions || {}) !== JSON.stringify(projRes.data.active_versions || {});
        setProject(projRes.data);
        
        const STAGE_ORDER = [
          'created', 'input_ready', 'brief_ready',
          'narrative_ready', 'visual_bible_ready', 'shot_plan_ready',
          'storyboard_ready', 'clips_generating', 'clips_ready', 'video_composition', 'timeline_ready', 'export_ready', 'completed', 'failed',
        ];
        const viewIdx = STAGE_ORDER.indexOf(viewStage || '');
        const currentIdx = STAGE_ORDER.indexOf(projRes.data.current_stage);
        const viewStageAheadOfCurrent = viewIdx > currentIdx && currentIdx >= 0;
        if (!viewStage || !isViewPinned || viewStageAheadOfCurrent) {
          setViewStage(projRes.data.current_stage);
        }
        if (isGenerating && (stageChanged || versionsChanged)) {
          resetGeneratingState();
        }
      }
      if (decRes.success) {
        const openDecisions = (decRes.data.items || []).filter((d: any) => d.status === 'open');
        setPendingDecisions(openDecisions);
        if (openDecisions.length > 0 && isGenerating) {
           resetGeneratingState();
        }
      }
      
      const sessRes = await chatService.getSessions(projectId);
      if (sessRes.success && sessRes.data?.items?.length) {
        const msgRes = await chatService.getSessionMessages(projectId, sessRes.data.items[0].id);
        if (msgRes.success) {
           const dbMsgs = (msgRes.data?.items ?? []).map((m: any) => ({
             role: m.role, content: m.content_text, created_at: m.created_at
           }));
           if (dbMsgs.length > 0) setMessages(dbMsgs);
           else setMessages([{ role: 'assistant', content: t('workbench.aiDirectorWelcome') }]);
        }
      }
    } catch (error) {
    } finally {
      setLoading(false);
      setIsInitialLoad(false);
    }
  };

  const handleSendMessage = async () => {
    if (!projectId || !inputText.trim() || sending) return;
    const userMsg = { role: 'user', content: inputText, created_at: new Date().toISOString() };
    setMessages(prev => [...prev, userMsg]);
    const currentInput = inputText;
    setInputText('');
    setSending(true);

    const tempId = Date.now();
    setMessages(prev => [...prev, { _id: tempId, role: 'assistant', content: '', created_at: new Date().toISOString() }]);

    await streamMessage(projectId, currentInput, (chunk) => {
        setMessages(prev => prev.map(msg => msg._id === tempId ? { ...msg, content: (msg.content || '') + chunk } : msg));
      },
      (vidmuseData) => {
        setSending(false);
        if (vidmuseData?.requires_confirmation) fetchProjectData(true);
      },
      () => setSending(false)
    );
  };

  const handleDecision = async (decisionId: string, optionId: string) => {
    if (!projectId) return;
    try {
      const dec = pendingDecisions.find(d => d.id === decisionId);
      if (!dec) return;

      const res = await projectService.makeDecision(projectId, decisionId, optionId);
      if (res.success) {
        setPendingDecisions(prev => prev.filter(d => d.id !== decisionId));
        if (optionId === 'regenerate') {
            setIsGenerating(true);
            setGeneratingMessage('正在重新生成...');
            switch (dec.decision_type) {
              case 'confirm_brief':
                await workflowService.generateBrief(projectId);
                break;
              case 'confirm_narrative':
                await workflowService.generateNarrative(projectId);
                break;
              case 'confirm_shot_plan':
                await workflowService.generateStoryboard(projectId);
                break;
              case 'confirm_storyboard':
                await workflowService.generateStoryboard(projectId);
                break;
            }
        } else if (optionId !== 'cancel') {
            switch (dec.decision_type) {
              case 'select_style_direction':
                setIsGenerating(true);
                setGeneratingMessage('正在生成创意方案...');
                await workflowService.generateBrief(projectId);
                break;
              case 'confirm_brief':
                setIsGenerating(true);
                setGeneratingMessage('正在生成叙事剧本...');
                await workflowService.generateNarrative(projectId);
                break;
              case 'confirm_narrative':
                setIsGenerating(true);
                setGeneratingMessage('正在生成九宫格分镜...');
                await workflowService.generateStoryboard(projectId);
                break;
              case 'confirm_shot_plan':
                setIsGenerating(true);
                setGeneratingMessage('正在生成九宫格分镜...');
                await workflowService.generateStoryboard(projectId);
                break;
              case 'confirm_storyboard':
                setIsGenerating(true);
                setGeneratingMessage('正在生成视频片段...');
                await workflowService.generateClips(projectId);
                break;
              case 'confirm_cost_clips':
                setIsGenerating(true);
                setGeneratingMessage('正在生成视频片段...');
                await workflowService.generateClips(projectId);
                break;
            }
        }
        await fetchProjectData(true);
      }
    } catch (error) {
      console.error('Failed to handle decision:', error);
      resetGeneratingState();
      await fetchProjectData(true);
    }
  };

  const handleRetrigger = async (action: string) => {
    if (!projectId || isGenerating) return;
    setIsGenerating(true);
    try {
      if (action === 'generate_shot_plan') {
        setGeneratingMessage('正在生成九宫格分镜...');
        await workflowService.generateStoryboard(projectId);
      } else if (action === 'generate_storyboard') {
        setGeneratingMessage('正在生成九宫格分镜...');
        await workflowService.generateStoryboard(projectId);
      } else if (action === 'generate_clips') {
        setGeneratingMessage('正在生成视频片段...');
        setFailedStageInfo(null, null);
        setProductionViewStage('clips_generating');
        setViewStage('clips_generating');
        setIsViewPinned(false);
        const currentShots = await projectService.getShots(projectId).catch(() => null);
        const shotItems = currentShots?.success ? currentShots.data?.items ?? [] : [];
        resetShotRunStates();
        for (const shot of shotItems) {
          setShotRunState(shot.id, 'submitted');
        }
        await workflowService.generateClips(projectId);
      }
      await fetchProjectData(true);
    } catch (e) {
      console.error('Retrigger failed:', e);
      resetGeneratingState();
    }
  };

  const handleStartCreation = async () => {
    if (!projectId || isCreating || !prompt.trim() || humanOnCamera === null) return;
    setIsCreating(true);
    try {
      const specRes = await projectSpecService.createVersion(projectId, {
        user_prompt: prompt,
        platform: selectedPlatform,
        target_duration_sec: selectedDuration,
        aspect_ratio: platformAspectRatio(selectedPlatform),
        target_audience: targetAudience,
        style_preference: selectedStyle,
        human_on_camera: humanOnCamera,
      });

      if (specRes.success) {
        await projectSpecService.activate(projectId, specRes.data.id);
        setIsGenerating(true);
        setGeneratingMessage('AI 正在生成创意方案...');
        setGenerationProgress(0);
        await workflowService.generateBrief(projectId);
        await fetchProjectData(true);
      }
    } catch (e) {
      console.error('Failed to start creation:', e);
    } finally {
      setIsCreating(false);
    }
  };

  const platformAspectRatio = (platform: string): string => {
    const vertical = ['tiktok', 'youtube_shorts', 'xiaohongshu', '小红书'];
    return vertical.includes(platform?.toLowerCase()) ? '9:16' : '16:9';
  };

  const renderContent = () => {
    const stage = activeStage;
    const stagesWithOwnUI = ['brief_ready', 'narrative_ready', 'visual_bible_ready', 'shot_plan_ready', 'storyboard_ready', 'clips_generating', 'clips_ready', 'video_composition', 'timeline_ready', 'export_ready', 'completed'];
    
    if ((stage === 'input_ready' && isGenerating) || (isGenerating && !stagesWithOwnUI.includes(stage))) {
      return (
        <div className="flex flex-col items-center justify-center min-h-[500px] gap-8">
           <div className="relative">
             <div className="absolute inset-0 bg-violet-500/20 blur-2xl rounded-full" />
             <Activity size={64} className="text-violet-400 animate-pulse relative z-10" />
           </div>
           <div className="text-center space-y-4">
              <h2 className="text-3xl font-bold font-space text-white tracking-tight">{generatingMessage || 'AI 正在处理...'}</h2>
              {(generationProgress ?? 0) > 0 && (
                <div className="w-[400px] max-w-full mx-auto space-y-3">
                  <div className="h-2 rounded-full bg-slate-800 overflow-hidden shadow-inner">
                    <div
                      className="h-full bg-gradient-to-r from-cyan-400 to-violet-500 transition-all duration-300 shadow-[0_0_10px_rgba(34,211,238,0.5)]"
                      style={{ width: `${Math.max(0, Math.min(100, generationProgress))}%` }}
                    />
                  </div>
                  <p className="text-xs text-slate-400 font-space font-bold tracking-widest">{Math.round(generationProgress)}% COMPLETE</p>
                </div>
              )}
           </div>
        </div>
      );
    }

    if (stage === 'input_ready') {
      return (
        <div className="flex min-h-[560px] items-center justify-center">
          <div className="w-full max-w-2xl rounded-[32px] glass-panel p-12 text-center shadow-2xl">
            <div className="mx-auto mb-8 flex h-20 w-20 items-center justify-center rounded-3xl bg-cyan-500/10 border border-cyan-500/20">
              <Zap size={32} className="animate-pulse text-cyan-400" />
            </div>
            <h2 className="mb-4 text-4xl font-bold text-white font-space tracking-tight">AI 正在启动创作</h2>
            <p className="mx-auto max-w-xl text-base leading-relaxed text-slate-400">
              需求已经提交，系统正在整理创意目标、时长规划和角色设定。创意方案生成完成后，这里会自动切换到方案展示页。
            </p>
            <div className="mx-auto mt-10 max-w-md rounded-3xl bg-slate-900/50 border border-white/5 p-6 text-left">
              <div className="mb-4 flex items-center justify-between text-[10px] font-bold uppercase tracking-[0.3em] text-slate-500 font-space">
                <span>当前进度</span>
                <span className="text-cyan-400">ANALYZING INPUT</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                <div className="h-full w-1/3 rounded-full bg-gradient-to-r from-cyan-400 to-violet-500 animate-pulse" />
              </div>
              <div className="mt-6 space-y-3 text-sm text-slate-300">
                <div className="flex items-center gap-3"><div className="w-1.5 h-1.5 rounded-full bg-cyan-400" /> <span>提取核心需求与平台特征</span></div>
                <div className="flex items-center gap-3"><div className="w-1.5 h-1.5 rounded-full bg-slate-600" /> <span>构建创意简报 (Creative Brief)</span></div>
                <div className="flex items-center gap-3"><div className="w-1.5 h-1.5 rounded-full bg-slate-600" /> <span>定义视觉风格指南</span></div>
              </div>
            </div>
          </div>
        </div>
      );
    }

    if (stage === 'failed') return (
      <div className="flex flex-col items-center justify-center min-h-[500px] gap-8">
        <div className="h-20 w-20 rounded-3xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center">
          <AlertTriangle size={40} className="text-rose-400" />
        </div>
        <div className="text-center space-y-4">
          <h2 className="text-3xl font-bold text-white font-space">项目处理失败</h2>
          <p className="text-slate-400 text-lg max-w-md mx-auto leading-relaxed">
            {failedStageMessage || '别担心，这可能只是临时的网络、上游额度或模型账户问题。你可以重试当前失败阶段，或返回项目列表稍后继续。'}
          </p>
          <div className="flex items-center justify-center gap-4 pt-2">
            {failedStageAction === 'generate_clips' && (
              <button
                onClick={() => handleRetrigger('generate_clips')}
                disabled={isGenerating}
                className="px-10 py-3 bg-cyan-500 border border-cyan-400/20 text-black rounded-full text-sm hover:bg-cyan-300 transition-all font-black font-space tracking-widest shadow-xl disabled:opacity-50 disabled:cursor-not-allowed"
              >
                重试视频生成阶段
              </button>
            )}
            <button onClick={() => navigate('/projects')} className="px-10 py-3 bg-slate-800 border border-white/5 text-white rounded-full text-sm hover:bg-slate-700 transition-all font-bold font-space tracking-widest shadow-xl">
              返回项目列表
            </button>
          </div>
        </div>
      </div>
    );

    if (stage === 'created') return <SetupView
          prompt={prompt} setPrompt={setPrompt}
          selectedPlatform={selectedPlatform} setSelectedPlatform={setSelectedPlatform}
          selectedDuration={selectedDuration} setSelectedDuration={setSelectedDuration}
          durationInput={durationInput} setDurationInput={setDurationInput}
          targetAudience={targetAudience} setTargetAudience={setTargetAudience}
          selectedStyle={selectedStyle} setSelectedStyle={setSelectedStyle}
          humanOnCamera={humanOnCamera} setHumanOnCamera={setHumanOnCamera}
          onStartCreation={handleStartCreation} isCreating={isCreating}
        />;

    if (stage === 'brief_ready') return <BriefView projectId={projectId!} />;
    if (stage === 'narrative_ready' || stage === 'visual_bible_ready') return <NarrativeView projectId={projectId!} />;
    if (['shot_plan_ready', 'storyboard_ready'].includes(stage)) return <StoryboardReviewer projectId={projectId!} currentStage={stage} />;
    if (['clips_generating', 'clips_ready'].includes(stage)) return <VideoGenerationWorkspace projectId={projectId!} currentStage={stage} />;
    if (['video_composition', 'timeline_ready'].includes(stage)) return <VideoCompositionWorkspace projectId={projectId!} currentStage={stage} />;
    if (['export_ready', 'completed'].includes(stage)) return <VideoExportWorkspace projectId={projectId!} />;

    return null;
  };

  if (loading) return <div className="flex h-screen bg-[#020617] items-center justify-center"><Loader2 className="text-cyan-400 animate-spin" size={32} /></div>;

  return (
    <div className="flex h-screen overflow-hidden bg-[#020617] relative text-slate-100 font-sans">
      {/* Modern Collapsible Sidebar */}
      <aside 
        className={cn(
          "relative z-40 bg-slate-950/80 backdrop-blur-xl border-r border-white/5 transition-all duration-500 flex flex-col shrink-0",
          isSidebarOpen ? "w-64" : "w-16"
        )}
      >
        {/* Logo & Toggle */}
        <div className="h-16 flex items-center justify-between px-5 border-b border-white/5 bg-black/20">
           <div className={cn("flex items-center gap-3 transition-opacity duration-300", !isSidebarOpen && "opacity-0")}>
              <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-cyan-400 to-violet-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
                 <Bot size={18} className="text-white" />
              </div>
              <span className="text-sm font-bold font-space text-white tracking-widest uppercase">vidMuse</span>
           </div>
           <button 
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              className="w-8 h-8 rounded-lg hover:bg-white/5 flex items-center justify-center text-slate-500 hover:text-white transition-all"
           >
              <Menu size={18} />
           </button>
        </div>

        <div className="flex-1 py-6 overflow-y-auto custom-scrollbar">
           <ProcessNodes 
              project={project} 
              viewStage={activeStage}
              onViewStageChange={(s) => {
                 setViewStage(s);
                 setIsViewPinned(true);
              }}
              minimal={!isSidebarOpen}
           />
        </div>

        <div className="p-4 border-t border-white/5 bg-black/20">
           <div className={cn("flex items-center gap-3 p-3 rounded-2xl bg-white/5 transition-all", !isSidebarOpen && "justify-center")}>
              <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center shrink-0">
                 <Activity size={14} className="text-cyan-400" />
              </div>
              {isSidebarOpen && (
                 <div className="flex-1 min-w-0">
                    <p className="text-[10px] font-bold text-white truncate">用户工作台</p>
                    <p className="text-[8px] font-bold text-slate-500 uppercase tracking-widest">系统就绪</p>
                 </div>
              )}
           </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 h-full relative">
         {/* Modern Top Header */}
         <header className="h-16 shrink-0 bg-slate-950/40 backdrop-blur-md border-b border-white/5 flex items-center justify-between px-8 relative z-30">
            <div className="flex items-center gap-6">
               <button 
                  onClick={() => navigate('/')}
                  className="flex items-center gap-2 text-[10px] font-bold font-space text-slate-500 hover:text-white transition-colors uppercase tracking-widest"
               >
                  <ArrowLeft size={14} />
                  返回
               </button>
               <div className="h-4 w-px bg-white/10" />
               <div className="flex items-center gap-3">
                  <span className="text-xs font-bold text-slate-200">项目：</span>
                  <span className="text-xs font-bold font-space text-cyan-400 uppercase tracking-widest">{project?.name || '新创作'}</span>
               </div>
            </div>

            {/* Central Progress Pulse */}
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-md hidden lg:block">
               <div className="h-1 bg-white/5 rounded-full overflow-hidden relative">
                  <div 
                    className="absolute inset-y-0 left-0 bg-gradient-to-r from-cyan-400 via-violet-500 to-cyan-400 transition-all duration-1000"
                    style={{ width: `${project?.progress_percentage || 0}%` }}
                  />
               </div>
            </div>

            <div className="flex items-center gap-6">
               <div className="hidden sm:flex flex-col items-end">
                  <span className="text-[9px] font-bold font-space text-slate-600 uppercase tracking-widest">当前阶段</span>
                  <div className="flex items-center gap-2">
                     <div className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" />
                     <span className="text-xs font-bold text-white uppercase tracking-wider">{STAGE_LABELS[project?.current_stage || 'created'] || '处理中'}</span>
                  </div>
               </div>
               <button 
                  onClick={() => setIsChatOpen(!isChatOpen)}
                  className={cn(
                     "px-4 py-2 rounded-xl flex items-center gap-3 transition-all",
                     isChatOpen ? "bg-cyan-500 text-white shadow-lg shadow-cyan-500/20" : "bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white"
                  )}
               >
                  <Bot size={18} />
                  <span className="text-xs font-bold font-space uppercase tracking-widest">AI 导演</span>
               </button>
            </div>
         </header>

         {/* Stage Transition Overlay */}
         <StageTransitionOverlay 
            visible={isGenerating} 
            message={generatingMessage} 
            progress={generationProgress}
            stage={project?.current_stage || 'created'}
         />

         {/* Workspace Switcher */}
         <div className="flex-1 min-h-0 relative">
            {loading ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#020617] z-50">
                 <Loader2 size={48} className="text-cyan-400 animate-spin" />
                 <p className="mt-8 text-xs font-bold font-space text-slate-500 tracking-[0.4em] uppercase animate-pulse">正在进入创作空间...</p>
              </div>
            ) : (
              <div className="h-full w-full overflow-hidden">
                 <AnimatePresence mode="wait">
                    <motion.div
                      key={activeStage}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                      transition={{ duration: 0.4, ease: "easeOut" }}
                      className="h-full w-full"
                    >
                       {renderContent()}
                    </motion.div>
                 </AnimatePresence>
              </div>
            )}
            <StageDecisionBar
              decision={activeDecision}
              isGenerating={isGenerating}
              onDecision={handleDecision}
            />
         </div>

         {/* AI Director Panel - Floating Overlay */}
         <AnimatePresence>
            {isChatOpen && (
              <motion.div 
                initial={{ x: 400, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                exit={{ x: 400, opacity: 0 }}
                className="absolute right-6 top-20 bottom-6 w-[400px] z-[60] shadow-2xl"
              >
                <div className="h-full rounded-3xl overflow-hidden glass-panel border border-white/5 shadow-[0_32px_64px_rgba(0,0,0,0.5)]">
                   <AIDirectorPanel 
                     project={project} messages={messages} inputText={inputText} setInputText={setInputText}
                     sending={sending} onSendMessage={handleSendMessage} isChatOpen={isChatOpen}
                     setIsChatOpen={setIsChatOpen} pendingDecisions={pendingDecisions} onDecision={handleDecision}
                   />
                </div>
              </motion.div>
            )}
         </AnimatePresence>
      </main>
    </div>
  );
};
