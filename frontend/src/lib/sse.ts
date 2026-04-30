import { useEffect } from 'react';
import { useProjectStore } from '@/stores/projectStore';

export const useProjectEvents = (projectId?: string) => {
  const triggerRefresh = useProjectStore((state) => state.triggerRefresh);
  const triggerClipRefresh = useProjectStore((state) => state.triggerClipRefresh);
  const setIsGenerating = useProjectStore((state) => state.setIsGenerating);
  const setGeneratingMessage = useProjectStore((state) => state.setGeneratingMessage);
  const setGenerationProgress = useProjectStore((state) => state.setGenerationProgress);
  const setLatestDirectorMessage = useProjectStore((state) => state.setLatestDirectorMessage);
  const setProductionViewStage = useProjectStore((state) => state.setProductionViewStage);
  const setShotRunState = useProjectStore((state) => state.setShotRunState);
  const resetShotRunStates = useProjectStore((state) => state.resetShotRunStates);
  const setFailedStageInfo = useProjectStore((state) => state.setFailedStageInfo);

  useEffect(() => {
    if (!projectId) return;

    const token = localStorage.getItem('vidmuse_token');
    // Append token as query parameter to bypass EventSource limitation on custom headers
    const url = `/api/v1/projects/${projectId}/events/stream${token ? `?token=${token}` : ''}`;
    
    const eventSource = new EventSource(url);

    eventSource.onopen = () => {
      console.log(`SSE connected for project: ${projectId}`);
    };

    // All backend events are sent as standard SSE data messages (not named events).
    // Backend format: data: {"event_type": "xxx", "_project_id": "...", ...}
    // We must parse event_type from JSON and route accordingly.
    const REFRESH_EVENTS = new Set([
      'project_clips_ready',
      'project_timeline_ready',
      'project_storyboard_ready',
      'project_shot_plan_ready',
      'project_brief_ready',
      'project_narrative_ready',
      'project_visual_bible_ready',  // doc 21 决策 D1：deprecated，保留兼容旧项目
      'project_audio_analyzed',
      'project_input_ready',
      'project_export_ready',
      'project_completed',
      // 业务特定别名
      'audio.analysis.completed',
      'narrative.completed',
      // Director 汇报完成后推 SSE，触发刷新让 Chat 侧边栏显示新消息
      'director.report',
      // 视觉圣经全部完成事件（doc 21 决策 D1：deprecated，保留兼容旧项目）
      'visual_bible.completed',
      // doc 21 §6.1 九宫格事件（增量推送）
      'storyboard.grid.generating',
      'storyboard.grid.generated',
      'storyboard.grid.split_done',
      'storyboard.all_grids_completed',
      'clips.all_completed',
      'clips.stage.failed',
    ]);

    eventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const eventType: string = payload.event_type ?? '';
        console.log('[SSE]', eventType, payload);

        if (eventType === 'sse_connected') {
          console.log(`[SSE] Connection confirmed for project: ${projectId}`);
          // 每次连接建立（含断线重连）都拉一次最新状态，
          // 避免断开期间完成的任务对前端不可见
          triggerRefresh();
          return;
        }

        if (eventType === 'audio.analysis.progress') {
          setIsGenerating(true);
          setGeneratingMessage(payload.message || '\u6b63\u5728\u5206\u6790\u97f3\u9891...');
          setGenerationProgress(payload.progress || 0);
        } else if (eventType === 'narrative.generating') {
          setIsGenerating(true);
          setGeneratingMessage(payload.message || '正在构思叙事剧本...');
        } else if (eventType === 'clip.shot.started') {
          setIsGenerating(true);
          setProductionViewStage('clips_generating');
          if (payload.shot_id) {
            setShotRunState(payload.shot_id, 'running');
          }
          setGeneratingMessage(`正在生成视频片段 #${(payload.shot_index ?? 0) + 1}...`);
        } else if (eventType === 'clip.shot.completed') {
          setIsGenerating(true);
          setProductionViewStage('clips_generating');
          if (payload.shot_id) {
            setShotRunState(payload.shot_id, 'completed');
          }
          setGeneratingMessage(`视频片段 #${(payload.shot_index ?? 0) + 1} 已完成`);
          triggerClipRefresh();
        } else if (eventType === 'clip.shot.failed') {
          // 单个 shot 失败不停止整体 generating 状态
          if (payload.shot_id) {
            setShotRunState(payload.shot_id, 'failed');
          }
          setGeneratingMessage(`视频片段 #${(payload.shot_index ?? 0) + 1} 生成失败，继续处理其余片段...`);
          triggerClipRefresh();
        } else if (eventType === 'clips.stage.failed') {
          setIsGenerating(false);
          setGeneratingMessage(payload.message || '视频生成阶段失败，可重试整个阶段。');
          setGenerationProgress(0);
          setProductionViewStage('idle');
          setFailedStageInfo(payload.retry_action || 'generate_clips', payload.message || '视频生成阶段失败，可重试整个阶段。');
          triggerRefresh();
          triggerClipRefresh();
        } else if (eventType === 'clip_regenerated') {
          // 单 shot 重新生成完成，只刷新视频生成组件数据
          triggerClipRefresh();
        } else if (eventType === 'clips.all_completed') {
          setIsGenerating(false);
          if ((payload.failed ?? 0) <= 0) {
            setGeneratingMessage(null);
            setFailedStageInfo(null, null);
          }
          setGenerationProgress(0);
          setProductionViewStage('idle');
          triggerClipRefresh();
        } else if (eventType === 'brief.generating') {
          setIsGenerating(true);
          setGeneratingMessage(payload.message || '正在生成创意方案...');
        } else if (eventType === 'shot_plan.generating') {
          setIsGenerating(true);
          setGeneratingMessage(payload.message || '正在生成镜头计划...');
        } else if (eventType === 'storyboard.generating') {
          setIsGenerating(true);
          setGeneratingMessage(payload.message || '正在生成分镜图...');
        } else if (eventType === 'storyboard.grid.generating') {
          // doc 21 §6.1：第 N 张九宫格开始生成
          setIsGenerating(true);
          const idx = payload.grid_index ?? 0;
          const total = payload.total_grids ?? 1;
          setGeneratingMessage(payload.message || `第 ${idx}/${total} 张九宫格生成中…`);
          if (total > 0 && idx > 0) {
            setGenerationProgress(Math.min(78, Math.round((idx / total) * 72)));
          }
        } else if (eventType === 'storyboard.grid.generated') {
          // 大图生成完成，触发拉数据展示
          setIsGenerating(true);
          setGeneratingMessage(`第 ${payload.grid_index} 张九宫格大图已完成，正在切分…`);
          const idx = payload.grid_index ?? 0;
          const total = payload.total_grids ?? 1;
          if (total > 0 && idx > 0) {
            setGenerationProgress(Math.min(86, Math.round((((idx - 1) + 0.55) / total) * 88)));
          }
        } else if (eventType === 'storyboard.grid.split_done') {
          // 切分 9 帧完成
          const cnt = payload.frames?.length ?? 9;
          setGeneratingMessage(`第 ${payload.grid_index} 张切分完成（${cnt} 帧），正在准备下一张…`);
          const gridIndex = payload.grid_index ?? 0;
          const totalGrids = payload.total_grids ?? 0;
          if (totalGrids > 0 && gridIndex > 0) {
            setGenerationProgress(Math.min(92, Math.round((gridIndex / totalGrids) * 88)));
          }
        } else if (eventType === 'storyboard.all_grids_completed') {
          // 所有九宫格完成
          setIsGenerating(false);
          setGeneratingMessage(null);
          setGenerationProgress(0);
          resetShotRunStates();
          setFailedStageInfo(null, null);
        } else if (eventType === 'visual_bible.initializing') {
          setIsGenerating(true);
          setGeneratingMessage(payload.message || '正在初始化视觉圣经...');
        } else if (eventType === 'visual_bible.completed') {
          console.log('[SSE] 视觉圣经全部完成，准备获取数据');
          setIsGenerating(false);
          setGeneratingMessage(null);
          setGenerationProgress(0);
        }

        // Director 汇报消息直接存入 store，前端立即追加到 Chat
        if (eventType === 'director.report' && payload.message) {
          setLatestDirectorMessage({
            role: 'assistant',
            content: payload.message,
            created_at: new Date().toISOString(),
          });
        }

        // 阶段推进事件：不立即更新 currentStage，等 fetchProjectData 拿到完整数据后再切换。
        // 这样前端不会在数据到达前就跳转到新阶段页面（空壳占位）。
        // setCurrentStage 由 fetchProjectData → setProject 自然完成。

        if (REFRESH_EVENTS.has(eventType)) {
          // 不在这里清除 isGenerating，让 fetchProjectData 检测到 stageChanged 后再清除。
          // 这保证 loading 动画持续到数据真正到达。
          triggerRefresh();
        }
      } catch {
        // non-JSON heartbeat or unknown message, ignore
      }
    };

    eventSource.onerror = (error) => {
      console.error('SSE Error:', error);
      // EventSource automatically attempts to reconnect on error
    };

    return () => {
      eventSource.close();
      console.log(`SSE disconnected for project: ${projectId}`);
    };
  }, [projectId, triggerRefresh, triggerClipRefresh]);
};
