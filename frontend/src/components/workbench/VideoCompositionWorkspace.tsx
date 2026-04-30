import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Clapperboard,
  Film,
  Layers,
  Loader2,
  Maximize2,
  MonitorUp,
  Music,
  Pause,
  Play,
  Sparkles,
  Zap,
  Clock,
  ChevronRight,
  Settings,
  Scissors
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

import { workflowService } from '@/services/api';
import { useProjectStore } from '@/stores/projectStore';
import { cn } from '@/lib/utils';
import { safeText, useVideoStageData } from './useVideoStageData';

type EditorClip = {
  id: string;
  shotId: string;
  shotIndex: number;
  label: string;
  title: string;
  storageUri: string | null;
  startMs: number;
  durationMs: number;
  endMs: number;
  location?: string | null;
  cameraLanguage?: string | null;
  statusLabel?: string;
};

const formatTime = (timeInSeconds: number) => {
  const totalSeconds = Math.max(0, Math.floor(timeInSeconds));
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
  const s = Math.floor(totalSeconds % 60).toString().padStart(2, '0');
  const ms = Math.floor((timeInSeconds % 1) * 100).toString().padStart(2, '0');
  return `${m}:${s}.${ms}`;
};

export const VideoCompositionWorkspace = ({
  projectId,
}: {
  projectId: string;
  currentStage: string;
}) => {
  const [activeTab, setActiveTab] = useState<'sequence' | 'timeline'>('sequence');
  const [isPlaying, setIsPlaying] = useState(false);
  const [composing, setComposing] = useState(false);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [activePreviewIndex, setActivePreviewIndex] = useState(0);
  const [videoDuration, setVideoDuration] = useState(0);
  const [videoCurrentTime, setVideoCurrentTime] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const timelineScrollRef = useRef<HTMLDivElement>(null);
  
  const { setIsGenerating, setGeneratingMessage } = useProjectStore();
  const {
    loading,
    clips,
    queueShots,
    timeline,
    timelineSegments,
    totalDurationMs,
  } = useVideoStageData(projectId);

  const isTimelineReady = !!timeline?.preview_uri;

  const editorClips = useMemo<EditorClip[]>(() => {
    const shotMap = new Map(queueShots.map((shot) => [shot.id, shot]));
    const clipMap = new Map(clips.map((clip) => [clip.id, clip]));

    if (timelineSegments.length > 0) {
      return timelineSegments
        .map((segment, index) => {
          const clip = clipMap.get(segment.clip_version_id);
          const shot = shotMap.get(segment.shot_id);
          return {
            id: clip?.id || segment.clip_version_id,
            shotId: segment.shot_id,
            shotIndex: shot?.shot_index ?? index,
            label: `镜头 ${String((shot?.shot_index ?? index) + 1).padStart(2, '0')}`,
            title: safeText(shot?.subject, '暂无主体描述'),
            storageUri: clip?.storage_uri || null,
            startMs: segment.start_ms,
            durationMs: segment.duration_ms || Math.max(segment.end_ms - segment.start_ms, 1000),
            endMs: segment.end_ms,
            location: shot?.location,
            cameraLanguage: shot?.camera_language,
            statusLabel: shot?.statusLabel,
          };
        })
        .sort((a, b) => a.shotIndex - b.shotIndex || a.startMs - b.startMs);
    }

    let cursorMs = 0;
    return queueShots
      .filter((shot) => shot.clip)
      .map((shot, index) => {
        const durationMs = shot.clip?.duration_ms || shot.duration_ms || 5000;
        const item = {
          id: shot.clip!.id,
          shotId: shot.id,
          shotIndex: shot.shot_index ?? index,
          label: `镜头 ${String((shot.shot_index ?? index) + 1).padStart(2, '0')}`,
          title: safeText(shot.subject, '暂无主体描述'),
          storageUri: shot.clip?.storage_uri || null,
          startMs: cursorMs,
          durationMs,
          endMs: cursorMs + durationMs,
          location: shot.location,
          cameraLanguage: shot.camera_language,
          statusLabel: shot.statusLabel,
        };
        cursorMs += durationMs;
        return item;
      })
      .sort((a, b) => a.shotIndex - b.shotIndex || a.startMs - b.startMs);
  }, [clips, queueShots, timelineSegments]);

  const playableClips = useMemo(
    () => editorClips.filter((clip) => !!clip.storageUri),
    [editorClips],
  );

  const previewMode = activeTab === 'timeline' && timeline?.preview_uri ? 'timeline' : playableClips.length > 0 ? 'sequence' : 'empty';
  
  const activeSequenceClip =
    previewMode === 'sequence'
      ? playableClips[Math.min(activePreviewIndex, Math.max(playableClips.length - 1, 0))] || null
      : null;

  const selectedClip =
    (selectedClipId ? editorClips.find((clip) => clip.id === selectedClipId) : null) ||
    activeSequenceClip ||
    editorClips[0] ||
    null;
      
  const previewSrc = previewMode === 'timeline' ? timeline?.preview_uri || null : activeSequenceClip?.storageUri || null;

  const effectiveDurationMs = Math.max(
    totalDurationMs || 0,
    editorClips.reduce((max, clip) => Math.max(max, clip.endMs), 0),
    1000,
  );

  const pixelsPerSecond = 80;
  const trackWidth = (effectiveDurationMs / 1000) * pixelsPerSecond;

  useEffect(() => {
    if (previewMode !== 'sequence') {
      setActivePreviewIndex(0);
      return;
    }
    if (!selectedClipId) return;
    const nextIndex = playableClips.findIndex((clip) => clip.id === selectedClipId);
    if (nextIndex >= 0) {
      setActivePreviewIndex(nextIndex);
    }
  }, [playableClips, previewMode, selectedClipId]);

  useEffect(() => {
    if (!videoRef.current || !previewSrc) return;
    setVideoCurrentTime(0);
    setVideoDuration(0);
    videoRef.current.load();

    if (isPlaying) {
      const playPromise = videoRef.current.play();
      if (playPromise) {
        void playPromise
          .then(() => setIsPlaying(true))
          .catch(() => setIsPlaying(false));
      }
    }
  }, [activePreviewIndex, previewMode, previewSrc]);

  const handleCompose = async () => {
    setComposing(true);
    setIsGenerating(true);
    setGeneratingMessage('正在合成完整视频...');
    try {
      await workflowService.composeTimeline(projectId);
    } catch (error) {
      console.error('Failed to compose timeline:', error);
      setComposing(false);
      setIsGenerating(false);
      setGeneratingMessage(null);
    }
  };

  const handleVideoEnded = () => {
    if (previewMode === 'sequence') {
      if (activePreviewIndex < playableClips.length - 1) {
        const nextClip = playableClips[activePreviewIndex + 1];
        setActivePreviewIndex(activePreviewIndex + 1);
        if (selectedClipId) {
          setSelectedClipId(nextClip.id);
        }
      } else {
        setIsPlaying(false);
      }
    } else {
      setIsPlaying(false);
    }
  };

  const handlePlayInOrder = () => {
    setActiveTab('sequence');
    setSelectedClipId(null);
    if (activePreviewIndex >= playableClips.length - 1) {
      setActivePreviewIndex(0);
    }
    setIsPlaying(true);
  };

  const handleSelectClip = (clip: EditorClip) => {
    setSelectedClipId(clip.id);
    setActiveTab('sequence');
    const idx = playableClips.findIndex((item) => item.id === clip.id);
    if (idx >= 0) {
      setActivePreviewIndex(idx);
      setIsPlaying(true);
      window.requestAnimationFrame(() => {
        void videoRef.current?.play().catch(() => setIsPlaying(false));
      });
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-[#020617]">
        <div className="flex flex-col items-center gap-4">
          <Loader2 size={32} className="text-cyan-400 animate-spin" />
          <p className="text-slate-400 font-space font-bold tracking-widest text-xs uppercase">正在加载时间轴数据...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#020617] overflow-hidden">
      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-[1fr_400px] gap-px bg-white/5">
        
        <section className="flex flex-col min-h-0 bg-[#020617] overflow-hidden">
          <div className="flex-1 min-h-0 p-8 flex flex-col">
            <div className="flex items-center justify-between mb-6">
               <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center">
                     <MonitorUp size={16} className="text-cyan-400" />
                  </div>
                  <h3 className="text-xs font-bold font-space tracking-widest text-slate-400 uppercase">节目预览</h3>
               </div>

               <div className="flex bg-slate-900/50 p-1 rounded-xl border border-white/5">
                  <button 
                    onClick={() => setActiveTab('sequence')}
                    className={cn(
                      "px-4 py-1.5 rounded-lg text-[10px] font-bold font-space transition-all",
                      activeTab === 'sequence' ? "bg-cyan-500 text-white shadow-lg shadow-cyan-500/20" : "text-slate-500 hover:text-slate-300"
                    )}
                  >
                    合成前 (镜头衔接)
                  </button>
                  <button 
                    onClick={() => setActiveTab('timeline')}
                    disabled={!timeline?.preview_uri}
                    className={cn(
                      "px-4 py-1.5 rounded-lg text-[10px] font-bold font-space transition-all flex items-center gap-2",
                      activeTab === 'timeline' ? "bg-cyan-500 text-white shadow-lg shadow-cyan-500/20" : "text-slate-500 hover:text-slate-300",
                      !timeline?.preview_uri && "opacity-50 cursor-not-allowed"
                    )}
                  >
                    合成后 (完整导出)
                    {!timeline?.preview_uri && <div className="w-1 h-1 rounded-full bg-slate-600" />}
                  </button>
               </div>

               <div className="flex items-center gap-4">
                  <button
                    onClick={handlePlayInOrder}
                    disabled={playableClips.length === 0}
                    className={cn(
                      "flex items-center gap-2 px-4 py-1.5 rounded-full text-[10px] font-bold font-space transition-all border",
                      selectedClipId
                        ? "border-white/10 text-slate-300 hover:text-white hover:bg-white/5"
                        : "border-cyan-500/30 bg-cyan-500/10 text-cyan-300",
                      playableClips.length === 0 && "opacity-50 cursor-not-allowed"
                    )}
                  >
                    <Play size={12} />
                    顺序播放
                  </button>
                  <button 
                    onClick={handleCompose}
                    disabled={composing || clips.length === 0}
                    className="flex items-center gap-2 px-4 py-1.5 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 disabled:cursor-not-allowed rounded-full text-[10px] font-bold font-space text-white transition-all shadow-lg shadow-cyan-500/20"
                  >
                    {composing ? <Loader2 size={12} className="animate-spin" /> : <Clapperboard size={12} />}
                    开始视频合成
                  </button>
               </div>
            </div>

            <div className="flex-1 bg-black rounded-3xl overflow-hidden border border-white/5 shadow-2xl relative group">
              <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-black/60 opacity-0 group-hover:opacity-100 transition-opacity z-10" />
              
              {previewSrc ? (
                <video
                  ref={videoRef}
                  src={previewSrc}
                  className="w-full h-full object-contain"
                  onTimeUpdate={(e) => setVideoCurrentTime(e.currentTarget.currentTime)}
                  onDurationChange={(e) => setVideoDuration(e.currentTarget.duration)}
                  onEnded={handleVideoEnded}
                  playsInline
                />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center text-slate-800 space-y-4">
                   <Film size={64} strokeWidth={1} />
                   <p className="text-xs font-bold font-space tracking-[0.2em] uppercase">等待渲染素材...</p>
                </div>
              )}

              {/* Player Overlay Controls */}
              <div className="absolute bottom-0 left-0 right-0 p-8 flex flex-col gap-4 z-20 translate-y-4 opacity-0 group-hover:translate-y-0 group-hover:opacity-100 transition-all">
                <div className="flex items-center justify-between">
                   <div className="flex items-center gap-6">
                      <button 
                        onClick={() => {
                          if (videoRef.current?.paused) {
                            videoRef.current.play();
                            setIsPlaying(true);
                          } else {
                            videoRef.current?.pause();
                            setIsPlaying(false);
                          }
                        }}
                        className="w-12 h-12 rounded-full bg-white text-black flex items-center justify-center shadow-xl hover:scale-110 transition-transform"
                      >
                        {isPlaying ? <Pause size={20} fill="currentColor" /> : <Play size={20} className="ml-1" fill="currentColor" />}
                      </button>
                      <div className="space-y-1">
                         <div className="text-2xl font-bold font-space text-white tabular-nums">
                            {formatTime(videoCurrentTime)}
                         </div>
                         <div className="text-[10px] font-bold font-space text-slate-400 uppercase tracking-widest">
                            {previewMode === 'sequence'
                              ? `${selectedClipId ? '选中播放' : '顺序播放'} · 镜头 ${activePreviewIndex + 1} / ${playableClips.length}`
                              : `总时长 ${formatTime(videoDuration)}`}
                         </div>
                      </div>
                   </div>
                   <button className="w-10 h-10 rounded-xl bg-white/10 backdrop-blur-md border border-white/10 flex items-center justify-center text-white hover:bg-white/20 transition-all">
                      <Maximize2 size={18} />
                   </button>
                </div>
                
                <div className="h-1.5 w-full bg-white/10 rounded-full overflow-hidden cursor-pointer relative group/progress">
                   <div 
                     className="absolute top-0 left-0 h-full bg-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.6)]"
                     style={{ width: `${(videoCurrentTime / (videoDuration || 1)) * 100}%` }}
                   />
                </div>
              </div>
            </div>
          </div>

          {/* Timeline Section */}
          <div className="h-64 bg-slate-950 border-t border-white/5 flex flex-col">
            <div className="h-10 px-8 flex items-center justify-between border-b border-white/5 shrink-0 bg-black/20">
               <div className="flex items-center gap-3">
                  <Scissors size={14} className="text-cyan-400" />
                  <span className="text-[10px] font-bold font-space text-slate-500 uppercase tracking-widest">时间轴 Timeline</span>
               </div>
               <div className="flex items-center gap-4 text-[10px] font-bold font-space text-slate-600 tabular-nums">
                  <span className="text-cyan-400">{formatTime(videoCurrentTime)}</span>
                  <span>/</span>
                  <span>{formatTime(effectiveDurationMs / 1000)}</span>
               </div>
            </div>
            <div ref={timelineScrollRef} className="flex-1 overflow-x-auto overflow-y-hidden p-8 relative custom-scrollbar">
              <div className="relative min-w-full" style={{ width: `${Math.max(trackWidth, 960)}px` }}>
                {editorClips.map((clip) => (
                  <div 
                    key={clip.id}
                    onClick={() => handleSelectClip(clip)}
                    className={cn(
                      "absolute top-0 h-16 rounded-md border transition-all cursor-pointer group/clip overflow-hidden",
                      selectedClipId === clip.id ? "bg-cyan-500/20 border-cyan-400 z-10" : "bg-slate-800 border-white/10 hover:bg-slate-700",
                      !clip.storageUri && "opacity-40 grayscale"
                    )}
                    style={{ 
                      left: (clip.startMs / 1000) * pixelsPerSecond,
                      width: (clip.durationMs / 1000) * pixelsPerSecond
                    }}
                  >
                    <div className="absolute inset-0 px-3 py-1">
                       <p className="text-[8px] font-bold text-white truncate uppercase tracking-tighter mb-0.5">{clip.label}</p>
                       <p className="text-[8px] text-slate-400 truncate line-clamp-1 opacity-60">{clip.title}</p>
                    </div>
                    {selectedClipId === clip.id && <div className="absolute inset-y-0 left-0 w-0.5 bg-cyan-400" />}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <aside className="bg-slate-950 border-l border-white/5 flex flex-col min-h-0">
          <div className="h-10 flex items-center justify-between px-6 border-b border-white/5 shrink-0">
             <div className="flex items-center gap-3">
                <Settings size={14} className="text-violet-400" />
                <h2 className="text-xs font-bold font-space tracking-widest text-slate-400 uppercase">属性查看器</h2>
             </div>
          </div>

          <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-8">
            <AnimatePresence mode="wait">
              {selectedClip ? (
                <motion.div 
                  key={selectedClip.id}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  className="space-y-8"
                >
                  <div className="aspect-video rounded-2xl bg-black border border-white/5 overflow-hidden relative shadow-2xl">
                     {selectedClip.storageUri ? (
                        <video src={selectedClip.storageUri} className="w-full h-full object-cover" />
                     ) : (
                        <div className="w-full h-full flex flex-col items-center justify-center text-slate-800">
                           <Loader2 size={32} className="animate-spin mb-2" />
                           <span className="text-[8px] font-bold uppercase tracking-widest">渲染中...</span>
                        </div>
                     )}
                     <div className="absolute top-4 left-4 px-2 py-1 bg-violet-500/20 border border-violet-500/40 backdrop-blur-md rounded text-[9px] font-bold text-violet-200 uppercase">
                        {selectedClip.label}
                     </div>
                  </div>

                  <div className="space-y-4">
                     <h4 className="text-[9px] font-bold font-space text-slate-500 tracking-[0.3em] uppercase">镜头描述</h4>
                     <p className="text-sm text-slate-200 leading-relaxed font-medium">
                        {selectedClip.title}
                     </p>
                  </div>

                  <div className="space-y-4">
                     <div className="flex items-center gap-4 p-4 rounded-xl bg-white/[0.02] border border-white/5">
                        <Zap size={14} className="text-cyan-400" />
                        <div className="flex-1">
                           <p className="text-[8px] font-bold text-slate-500 uppercase mb-0.5">运镜方式</p>
                           <p className="text-xs text-slate-300">{selectedClip.cameraLanguage || '标准镜头'}</p>
                        </div>
                     </div>
                     <div className="flex items-center gap-4 p-4 rounded-xl bg-white/[0.02] border border-white/5">
                        <Layers size={14} className="text-emerald-400" />
                        <div className="flex-1">
                           <p className="text-[8px] font-bold text-slate-500 uppercase mb-0.5">场景位置</p>
                           <p className="text-xs text-slate-300">{selectedClip.location || '工作室'}</p>
                        </div>
                     </div>
                  </div>
                </motion.div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-slate-800 text-center space-y-4">
                   <Sparkles size={48} strokeWidth={1} />
                   <p className="text-xs font-bold font-space uppercase tracking-widest">选中片段查看详情</p>
                </div>
              )}
            </AnimatePresence>
          </div>
        </aside>
      </div>
    </div>
  );
};
