import React, { useMemo, useState } from 'react';
import { 
  ArrowRight, 
  Clapperboard, 
  Film, 
  Loader2, 
  RefreshCw, 
  Sparkles, 
  Clock, 
  Zap, 
  MonitorPlay,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';

import { shotService } from '@/services/api';
import { cn } from '@/lib/utils';
import { safeText, useVideoStageData } from './useVideoStageData';
import { useProjectStore } from '@/stores/projectStore';

const StatCard = ({
  label,
  value,
  icon: Icon,
  accent,
  bg
}: {
  label: string;
  value: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  accent: string;
  bg: string;
}) => (
  <div className={cn("p-6 rounded-[24px] border border-white/5 flex flex-col items-center text-center group transition-all shadow-lg", bg)}>
    <Icon size={20} className={cn("mb-4", accent)} />
    <span className="text-[9px] font-bold font-space text-slate-500 tracking-widest uppercase mb-2">{label}</span>
    <span className={cn("text-2xl font-bold font-space tracking-tight", accent)}>{value}</span>
  </div>
);

const FrameSourceCard = ({ title, url }: { title: string; url?: string | null }) => (
  <div className="glass-card p-3 rounded-2xl border-white/5 flex flex-col gap-2">
    <p className="text-[9px] font-bold font-space text-slate-500 tracking-widest uppercase">{title}</p>
    {url ? (
      <div className="aspect-square rounded-xl overflow-hidden border border-white/10 relative group">
        <img src={url} alt={title} className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110" referrerPolicy="no-referrer" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
    ) : (
      <div className="aspect-square flex items-center justify-center rounded-xl border border-dashed border-white/5 bg-white/[0.02] text-[9px] font-bold font-space text-slate-700 uppercase">
        Awaiting
      </div>
    )}
  </div>
);

export const VideoGenerationWorkspace = ({
  projectId,
  currentStage,
}: {
  projectId: string;
  currentStage: string;
}) => {
  const [regeneratingShots, setRegeneratingShots] = useState<Set<string>>(new Set());
  const failedStageAction = useProjectStore((state) => state.failedStageAction);
  const failedStageMessage = useProjectStore((state) => state.failedStageMessage);
  const {
    loading,
    queueShots,
    completedClips,
    currentGeneratingShot,
    generatedCount,
    shots,
    refreshAll,
  } = useVideoStageData(projectId);

  const isGeneratingStage = currentStage === 'clips_generating';
  const estimatedDurationSec = useMemo(
    () => shots.reduce((sum, shot) => sum + (shot.duration_ms ?? 0), 0) / 1000,
    [shots],
  );

  const handleRegenerateShot = async (shotId: string) => {
    if (regeneratingShots.has(shotId)) return;
    setRegeneratingShots((prev) => new Set(prev).add(shotId));
    try {
      await shotService.regenerate(projectId, shotId);
      await refreshAll();
    } catch (error) {
      console.error('Failed to regenerate shot:', error);
    } finally {
      setRegeneratingShots((prev) => {
        const next = new Set(prev);
        next.delete(shotId);
        return next;
      });
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="animate-spin text-cyan-400" size={32} />
          <p className="text-xs font-space font-bold tracking-widest text-slate-500 uppercase">Loading Generation Workspace...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#020617] overflow-y-auto custom-scrollbar p-8 2xl:p-12">
      <div className="max-w-7xl mx-auto w-full space-y-12">
        
        {/* Header & Stats */}
        <header className="space-y-8">
           <div className="flex items-center justify-between gap-6 flex-wrap">
              <div className="space-y-3">
                 <div className="flex items-center gap-3">
                    <span className="px-3 py-1 bg-cyan-500/10 border border-cyan-500/20 rounded-full text-[10px] font-bold font-space text-cyan-400 tracking-widest uppercase">
                       {isGeneratingStage ? '渲染引擎运行中' : '视频生成模块'}
                    </span>
                 </div>
                 <h1 className="text-4xl font-bold font-space text-white tracking-tight">生产流水线</h1>
              </div>
              <div className="flex gap-4">
                 <StatCard label="完成进度" value={`${generatedCount} / ${queueShots.length}`} icon={Zap} accent="text-cyan-400" bg="bg-cyan-500/5" />
                 <StatCard label="预计总时长" value={`${estimatedDurationSec.toFixed(1)}秒`} icon={Clock} accent="text-violet-400" bg="bg-violet-500/5" />
              </div>
           </div>
           
           <div className="glass-panel p-6 rounded-[24px] border-white/5 flex items-center gap-6">
              <div className="w-12 h-12 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center shrink-0">
                 <MonitorPlay size={24} className="text-slate-400" />
              </div>
              <div className="space-y-1">
                 <p className="text-sm text-slate-200 font-medium">增量渲染已开启</p>
                 <p className="text-xs text-slate-500 leading-relaxed">镜头并行处理中。完成后，它们会自动出现在下方列表中并同步到时间轴。</p>
              </div>
           </div>

           {failedStageAction === 'generate_clips' && (
             <div className="rounded-[24px] border border-rose-500/20 bg-rose-500/5 p-5 flex items-center justify-between gap-6">
               <div className="flex items-start gap-4">
                 <AlertCircle size={20} className="text-rose-400 shrink-0 mt-0.5" />
                 <div className="space-y-1">
                   <p className="text-sm font-bold text-white">视频生成阶段失败</p>
                   <p className="text-xs leading-relaxed text-slate-400">
                     {failedStageMessage || '部分镜头生成失败，请处理上游模型账户或配额问题后重试整个视频生成阶段。'}
                   </p>
                 </div>
               </div>
               <div className="px-3 py-1.5 rounded-xl border border-rose-500/20 bg-black/20 text-[10px] font-bold font-space tracking-widest uppercase text-rose-300">
                 整阶段重试请在失败页执行
               </div>
             </div>
           )}
        </header>

        {/* Combined Production List */}
        <section className="space-y-6 flex-1 min-h-0 flex flex-col">
           <div className="flex items-center justify-between shrink-0">
              <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                 <Film size={16} className="text-cyan-400" />
                 制作列表
              </h3>
              <span className="text-[10px] font-bold font-space text-slate-600 uppercase tracking-widest">共 {queueShots.length} 个镜头</span>
           </div>

           <div className="flex-1 overflow-y-auto custom-scrollbar space-y-4 pr-2">
              {queueShots.map((shot, idx) => {
                const clip = completedClips.find(c => c.id === shot.id);
                const isGenerating = currentGeneratingShot?.id === shot.id;

                return (
                  <div key={shot.id} className={cn(
                    "glass-panel rounded-[24px] border-white/5 overflow-hidden transition-all duration-500",
                    isGenerating ? "bg-cyan-500/5 border-cyan-500/20 shadow-[0_0_20px_rgba(34,211,238,0.1)]" : "bg-white/[0.02]"
                  )}>
                    <div className="grid grid-cols-1 md:grid-cols-[1fr_400px] gap-6 p-6">
                       {/* Left Side: Info */}
                       <div className="space-y-4">
                          <div className="flex items-center gap-4">
                             <div className="w-10 h-10 rounded-xl bg-black/40 flex items-center justify-center shrink-0 text-[11px] font-bold font-space text-slate-500 border border-white/5">
                                {String(idx + 1).padStart(2, '0')}
                             </div>
                             <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-3 mb-1">
                                   <span className={cn(
                                     "px-2 py-0.5 rounded-full text-[9px] font-bold font-space uppercase tracking-wider",
                                     shot.statusLabel === '已完成' ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" :
                                     shot.statusLabel === '生成中' ? "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20" :
                                     "bg-slate-800 text-slate-500 border border-white/5"
                                   )}>
                                      {shot.statusLabel === '已完成' ? '制作完成' : 
                                       shot.statusLabel === '生成中' ? '正在渲染' : 
                                       shot.statusLabel === '失败' ? '制作失败' : '排队中'}
                                   </span>
                                   {isGenerating && <Loader2 size={12} className="text-cyan-400 animate-spin" />}
                                </div>
                                <h4 className="text-base font-bold text-white truncate">{shot.subject}</h4>
                             </div>
                          </div>
                          
                          <div className="grid grid-cols-2 gap-3">
                             <div className="p-3 bg-black/20 rounded-xl border border-white/5">
                                <span className="text-[8px] font-bold font-space text-slate-500 uppercase tracking-widest block mb-1">场景环境</span>
                                <p className="text-[10px] text-slate-400 line-clamp-1">{safeText(shot.location)}</p>
                             </div>
                             <div className="p-3 bg-black/20 rounded-xl border border-white/5">
                                <span className="text-[8px] font-bold font-space text-slate-500 uppercase tracking-widest block mb-1">运镜指令</span>
                                <p className="text-[10px] text-slate-400 line-clamp-1">{safeText(shot.camera_language)}</p>
                             </div>
                          </div>

                          {shot.statusLabel === '已完成' && (
                            <button 
                              onClick={() => handleRegenerateShot(shot.id)}
                              disabled={regeneratingShots.has(shot.id)}
                              className="flex items-center gap-2 px-3 py-1.5 bg-white/5 hover:bg-white/10 rounded-xl text-[9px] font-bold font-space text-slate-400 hover:text-white transition-all border border-white/5 w-fit"
                            >
                               {regeneratingShots.has(shot.id) ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
                               重新生成
                            </button>
                          )}
                       </div>

                       {/* Right Side: Video/Status */}
                       <div className="relative aspect-video bg-black/40 rounded-2xl overflow-hidden border border-white/10">
                          {clip?.clip?.storage_uri ? (
                            <video src={clip.clip.storage_uri} className="w-full h-full object-cover" controls playsInline />
                          ) : isGenerating ? (
                            <div className="w-full h-full flex flex-col items-center justify-center gap-4">
                               <div className="flex gap-2">
                                  <FrameSourceCard title="参考 A" url={shot.firstFrame} />
                                  <FrameSourceCard title="参考 B" url={shot.lastFrame} />
                               </div>
                               <div className="flex items-center gap-2 text-cyan-400">
                                  <Loader2 size={14} className="animate-spin" />
                                  <span className="text-[10px] font-bold font-space uppercase tracking-widest">渲染中...</span>
                               </div>
                            </div>
                          ) : (
                            <div className="w-full h-full flex flex-col items-center justify-center text-slate-700 space-y-2">
                               <MonitorPlay size={32} strokeWidth={1} />
                               <span className="text-[10px] font-bold font-space uppercase tracking-widest">排队等候</span>
                            </div>
                          )}
                       </div>
                    </div>
                  </div>
                );
              })}
           </div>
        </section>
      </div>
    </div>
  );
};
