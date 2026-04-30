import React, { useEffect, useMemo, useState } from 'react';
import {
  Clock3,
  Grid3x3,
  Lightbulb,
  Loader2,
  MonitorPlay,
  Target,
  Users,
  Video,
  Zap,
  Palette
} from 'lucide-react';

import { projectService } from '@/services/api';
import { useProjectStore } from '@/stores/projectStore';
import { cn } from '@/lib/utils';

interface BriefViewProps {
  projectId: string;
}

const safeText = (value: unknown, fallback = '暂无信息') => {
  if (value == null) return fallback;
  if (typeof value === 'string') return value.trim() || fallback;
  if (Array.isArray(value)) return value.length ? value.join(' / ') : fallback;
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
};

const ratioLabel = (ratio?: string) => {
  if (!ratio) return 'Not Specified';
  if (ratio === '9:16') return '9:16 Vertical';
  if (ratio === '16:9') return '16:9 Cinema';
  if (ratio === '1:1') return '1:1 Square';
  return ratio;
};

export const BriefView: React.FC<BriefViewProps> = ({ projectId }) => {
  const [brief, setBrief] = useState<any>(null);
  const [style, setStyle] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const refreshFlag = useProjectStore((state) => state.refreshFlag);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [briefRes, styleRes] = await Promise.all([
          projectService.getBrief(projectId).catch(() => null),
          projectService.getStyle(projectId).catch(() => null),
        ]);
        if (briefRes?.success) setBrief(briefRes.data);
        if (styleRes?.success) setStyle(styleRes.data);
      } catch (error) {
        console.error('Failed to fetch brief data', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [projectId, refreshFlag]);

  const briefPayload = brief?.raw_payload?.creative_brief || brief?.raw_payload || {};
  const stylePayload = style?.raw_payload?.style_bible || style?.raw_payload || {};
  const extension = briefPayload?.extension || {};
  const characters = extension.character_list || [];

  const planningCards = useMemo(
    () => [
      {
        icon: Clock3,
        label: '预计时长',
        value: extension.target_duration_sec ? `${extension.target_duration_sec}秒` : '60秒',
        accent: 'text-cyan-400',
        bg: 'bg-cyan-500/5'
      },
      {
        icon: Video,
        label: '镜头数量',
        value: extension.shot_count ? `${extension.shot_count}` : '8-12',
        accent: 'text-violet-400',
        bg: 'bg-violet-500/5'
      },
      {
        icon: Grid3x3,
        label: '九宫格数',
        value: extension.grid_count ? `${extension.grid_count}` : '2',
        accent: 'text-emerald-400',
        bg: 'bg-emerald-500/5'
      },
      {
        icon: MonitorPlay,
        label: '画面比例',
        value: ratioLabel(extension.aspect_ratio),
        accent: 'text-amber-400',
        bg: 'bg-amber-500/5'
      },
    ],
    [extension]
  );

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="animate-spin text-cyan-400" size={32} />
          <p className="text-xs font-space font-bold tracking-widest text-slate-500 uppercase">加载创意提案中...</p>
        </div>
      </div>
    );
  }

  if (!brief) {
    return (
      <div className="h-full flex items-center justify-center p-12">
        <div className="w-full max-w-2xl glass-panel p-12 rounded-[32px] text-center border-white/5">
          <Lightbulb className="mx-auto mb-6 text-cyan-400 animate-pulse" size={32} />
          <h2 className="mb-4 text-3xl font-bold text-white font-space">构思中...</h2>
          <p className="text-sm leading-relaxed text-slate-400">
            AI 导演正在分析您的输入并起草核心创意方向。提案很快就会出现。
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#020617] overflow-y-auto custom-scrollbar p-8 2xl:p-12">
      <div className="max-w-6xl mx-auto w-full space-y-12">
        
        {/* Hero Section */}
        <header className="space-y-6">
           <div className="flex items-center gap-3">
              <span className="px-3 py-1 bg-cyan-500/10 border border-cyan-500/20 rounded-full text-[10px] font-bold font-space text-cyan-400 tracking-widest uppercase">
                 创意提案 v{brief.version_no || 1}
              </span>
           </div>
           <h1 className="text-5xl font-bold font-space text-white leading-tight tracking-tight">
              {safeText(brief.title || briefPayload.title, 'AI 视频方案')}
           </h1>
           <div className="glass-panel p-8 rounded-[32px] border-white/10 shadow-2xl relative overflow-hidden group">
              <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/5 via-transparent to-violet-500/5 opacity-0 group-hover:opacity-100 transition-opacity" />
              <p className="text-[10px] font-bold font-space text-slate-500 tracking-[0.3em] uppercase mb-4 flex items-center gap-2">
                 <Zap size={12} className="text-cyan-400" />
                 核心摘要
              </p>
              <p className="text-lg text-slate-200 leading-relaxed font-medium relative z-10">
                 {safeText(brief.summary || briefPayload.summary)}
              </p>
           </div>
        </header>

        {/* Specs Grid */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-6">
           {planningCards.map((item) => (
             <div key={item.label} className={cn("p-6 rounded-[24px] border border-white/5 flex flex-col items-center text-center group hover:scale-105 transition-all shadow-lg", item.bg)}>
                <item.icon size={20} className={cn("mb-4", item.accent)} />
                <span className="text-[9px] font-bold font-space text-slate-500 tracking-widest uppercase mb-2">{item.label}</span>
                <span className={cn("text-2xl font-bold font-space tracking-tight", item.accent)}>{item.value}</span>
             </div>
           ))}
        </section>

        {/* Strategy & Style */}
        <section className="grid grid-cols-1 lg:grid-cols-[1.2fr_0.8fr] gap-8">
           <div className="space-y-8">
              <div className="space-y-4">
                 <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                    <Target size={16} className="text-cyan-400" />
                    投放策略
                 </h3>
                 <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="glass-card p-6 rounded-2xl">
                       <label className="text-[9px] font-bold font-space text-slate-500 tracking-widest uppercase mb-2 block">目标平台</label>
                       <p className="text-sm text-slate-200 font-bold">{safeText(extension.target_platform || extension.platform)}</p>
                    </div>
                    <div className="glass-card p-6 rounded-2xl">
                       <label className="text-[9px] font-bold font-space text-slate-500 tracking-widest uppercase mb-2 block">目标受众</label>
                       <p className="text-sm text-slate-200 font-bold">{safeText(extension.target_audience)}</p>
                    </div>
                 </div>
              </div>

              <div className="space-y-4">
                 <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                    <Users size={16} className="text-violet-400" />
                    角色设定
                 </h3>
                 {characters.length > 0 ? (
                   <div className="grid grid-cols-1 gap-4">
                      {characters.map((char: any, i: number) => (
                        <div key={i} className="glass-card p-6 rounded-2xl flex items-start gap-6 group">
                           <div className="w-12 h-12 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center shrink-0 font-space font-bold text-white group-hover:bg-violet-500/20 group-hover:border-violet-500/30 transition-all">
                              {char.name?.charAt(0) || 'C'}
                           </div>
                           <div className="space-y-2">
                              <h4 className="text-base font-bold text-white">{char.name}</h4>
                              <p className="text-xs text-slate-400 leading-relaxed">{char.appearance}</p>
                              {char.personality && (
                                <p className="text-[10px] text-violet-400 font-bold font-space uppercase tracking-widest">{char.personality}</p>
                              )}
                           </div>
                        </div>
                      ))}
                   </div>
                 ) : (
                   <div className="p-12 rounded-2xl border border-dashed border-white/10 text-center text-slate-600">
                      <span className="text-[10px] font-bold font-space uppercase tracking-widest">No detailed characters specified</span>
                   </div>
                 )}
              </div>
           </div>

           <div className="space-y-8">
              <div className="space-y-4">
                 <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                    <Palette size={16} className="text-emerald-400" />
                    视觉指南
                 </h3>
                 <div className="glass-panel p-8 rounded-[32px] space-y-8 border-white/10 shadow-xl">
                    <div className="space-y-4">
                       <div className="flex items-center gap-3">
                          <div className="w-2 h-8 bg-emerald-400 rounded-full" />
                          <span className="text-[10px] font-bold font-space text-slate-400 tracking-widest uppercase">光影与氛围</span>
                       </div>
                       <p className="text-sm text-slate-200 leading-relaxed">
                          {safeText(style?.lighting_style || stylePayload?.lighting_style || stylePayload?.lighting)}
                       </p>
                    </div>
                    <div className="space-y-4">
                       <div className="flex items-center gap-3">
                          <div className="w-2 h-8 bg-cyan-400 rounded-full" />
                          <span className="text-[10px] font-bold font-space text-slate-400 tracking-widest uppercase">镜头语言</span>
                       </div>
                       <p className="text-sm text-slate-200 leading-relaxed">
                          {safeText(style?.camera_style || stylePayload?.camera_style || stylePayload?.camera_language)}
                       </p>
                    </div>
                    <div className="space-y-4">
                       <div className="flex items-center gap-3">
                          <div className="w-2 h-8 bg-violet-400 rounded-full" />
                          <span className="text-[10px] font-bold font-space text-slate-400 tracking-widest uppercase">画面质感</span>
                       </div>
                       <p className="text-sm text-slate-200 leading-relaxed">
                          {safeText(style?.film_texture || stylePayload?.film_texture || stylePayload?.grain)}
                       </p>
                    </div>
                 </div>
              </div>
           </div>
        </section>

      </div>
    </div>
  );
};
