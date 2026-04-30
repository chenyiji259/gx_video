import React, { useEffect, useMemo, useState } from 'react';
import {
  BookOpen,
  Clapperboard,
  Camera,
  Droplets,
  Film,
  Loader2,
  MapPin,
  Palette,
  SwatchBook,
  Sparkles,
  Users,
  ScrollText,
} from 'lucide-react';

import { projectService } from '@/services/api';
import { useProjectStore } from '@/stores/projectStore';
import { cn } from '@/lib/utils';

interface NarrativeViewProps {
  projectId: string;
}

const text = (value: unknown, fallback = '暂无信息') => {
  if (value == null) return fallback;
  if (typeof value === 'string') return value.trim() || fallback;
  if (Array.isArray(value)) return value.length ? value.join(' / ') : fallback;
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
};

export const NarrativeView: React.FC<NarrativeViewProps> = ({ projectId }) => {
  const [narrative, setNarrative] = useState<any>(null);
  const [style, setStyle] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const refreshFlag = useProjectStore((state) => state.refreshFlag);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [narrativeRes, styleRes] = await Promise.all([
          projectService.getNarrative(projectId),
          projectService.getStyle(projectId).catch(() => null),
        ]);
        if (narrativeRes?.success) setNarrative(narrativeRes.data);
        if (styleRes?.success) setStyle(styleRes.data);
      } catch (error) {
        console.error('Failed to fetch narrative data', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [projectId, refreshFlag]);

  const shots = useMemo(() => narrative?.raw_payload?.shots || [], [narrative]);
  const briefCharacters =
    narrative?.raw_payload?.brief_extension?.character_list ||
    narrative?.raw_payload?.creative_brief?.extension?.character_list ||
    [];
  const characters = (narrative?.characters?.length ? narrative.characters : briefCharacters) || [];
  const scenes = narrative?.scenes || [];
  const stylePayload = style?.raw_payload?.style_bible || style?.raw_payload || {};
  const palette = stylePayload?.palette || {};
  const styleCards = useMemo(
    () => [
      {
        icon: Sparkles,
        title: '光影',
        value: text(style?.lighting_style || stylePayload?.lighting_style || stylePayload?.lighting),
        accent: 'text-emerald-300',
      },
      {
        icon: Camera,
        title: '镜头',
        value: text(style?.camera_style || stylePayload?.camera_style || stylePayload?.camera_language),
        accent: 'text-cyan-300',
      },
      {
        icon: Droplets,
        title: '质感',
        value: text(style?.film_texture || stylePayload?.film_texture || stylePayload?.grain),
        accent: 'text-violet-300',
      },
      {
        icon: SwatchBook,
        title: '参考',
        value: text(style?.reference_notes || stylePayload?.reference_notes),
        accent: 'text-amber-300',
      },
    ],
    [style, stylePayload],
  );

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="animate-spin text-cyan-400" size={32} />
          <p className="text-xs font-space font-bold tracking-widest text-slate-500 uppercase">加载剧本中...</p>
        </div>
      </div>
    );
  }

  if (!narrative) {
    return (
      <div className="h-full flex items-center justify-center p-12">
        <div className="w-full max-w-2xl glass-panel p-12 rounded-[32px] text-center border-white/5">
          <BookOpen className="mx-auto mb-6 text-cyan-400 animate-pulse" size={32} />
          <h2 className="mb-4 text-3xl font-bold text-white font-space">剧本编写中...</h2>
          <p className="text-sm leading-relaxed text-slate-400">
            AI 导演正在将您的创意提案扩展为逐镜头的叙事剧本。这将成为您制作的核心。
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#020617] overflow-y-auto custom-scrollbar p-8 2xl:p-12">
      <div className="max-w-6xl mx-auto w-full space-y-12">
        
        {/* Header Section */}
        <header className="space-y-8">
           <div className="flex items-center gap-3">
              <span className="px-3 py-1 bg-violet-500/10 border border-violet-500/20 rounded-full text-[10px] font-bold font-space text-violet-400 tracking-widest uppercase">
                 剧本 v{narrative.version_no || 1}
              </span>
           </div>
           <div className="flex items-end justify-between gap-6 flex-wrap">
              <div className="space-y-4 max-w-2xl">
                 <h1 className="text-5xl font-bold font-space text-white tracking-tight">叙事剧本 Narrative Script</h1>
                 <p className="text-slate-400 text-sm leading-relaxed">基于创意提案的场景、镜头和角色交互的详细拆解。</p>
              </div>
              <div className="flex gap-4">
                 <div className="p-4 rounded-2xl border border-white/5 bg-white/5 flex flex-col items-center text-center min-w-[120px]">
                    <Film size={18} className="text-cyan-400 mb-2" />
                    <span className="text-[9px] font-bold font-space text-slate-500 uppercase tracking-widest mb-1">镜头数</span>
                    <span className="text-xl font-bold font-space text-white">{shots.length}</span>
                 </div>
                 <div className="p-4 rounded-2xl border border-white/5 bg-white/5 flex flex-col items-center text-center min-w-[120px]">
                    <Users size={18} className="text-violet-400 mb-2" />
                    <span className="text-[9px] font-bold font-space text-slate-500 uppercase tracking-widest mb-1">角色数</span>
                    <span className="text-xl font-bold font-space text-white">{characters.length}</span>
                 </div>
                 <div className="p-4 rounded-2xl border border-white/5 bg-white/5 flex flex-col items-center text-center min-w-[120px]">
                    <Palette size={18} className="text-emerald-400 mb-2" />
                    <span className="text-[9px] font-bold font-space text-slate-500 uppercase tracking-widest mb-1">风格</span>
                    <span className="text-xl font-bold font-space text-white">{style ? '已绑定' : '待同步'}</span>
                 </div>
              </div>
           </div>
        </header>

        {/* Story Arc */}
        <section className="glass-panel p-8 rounded-[32px] border-white/10 shadow-2xl relative overflow-hidden group">
           <div className="absolute inset-0 bg-gradient-to-br from-violet-500/5 via-transparent to-cyan-500/5 opacity-0 group-hover:opacity-100 transition-opacity" />
           <div className="flex items-center gap-3 mb-6">
              <ScrollText size={16} className="text-cyan-400" />
              <span className="text-[10px] font-bold font-space text-slate-500 tracking-[0.3em] uppercase">故事弧线与流程</span>
           </div>
           <p className="text-lg text-slate-200 leading-relaxed font-medium whitespace-pre-wrap relative z-10">
              {text(narrative.story_arc)}
           </p>
        </section>

        <section className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-12">
           {/* Left: Shot Breakdown */}
           <div className="space-y-8">
              <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                 <Clapperboard size={16} className="text-cyan-400" />
                 镜头拆解
              </h3>
              
              <div className="space-y-6">
                 {shots.map((shot: any, idx: number) => (
                   <div key={idx} className="glass-card rounded-[24px] border-white/5 overflow-hidden flex flex-col group hover:border-white/10 transition-colors">
                      <div className="h-10 px-6 flex items-center justify-between bg-white/5 border-b border-white/5">
                         <div className="flex items-center gap-3">
                            <span className="text-[10px] font-bold font-space text-cyan-400">镜头 {String(idx + 1).padStart(2, '0')}</span>
                            <div className="w-1 h-1 rounded-full bg-slate-700" />
                            <span className="text-[10px] font-bold font-space text-slate-500 uppercase tracking-wider">{text(shot.emotion, '标准')}</span>
                         </div>
                         <div className="flex items-center gap-2">
                            {shot.characters_in_shot?.map((c: string, i: number) => (
                              <span key={i} className="text-[9px] font-bold text-slate-500">{c}</span>
                            ))}
                         </div>
                      </div>
                      
                      <div className="p-6 space-y-6">
                         <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="p-4 bg-white/[0.02] rounded-xl border border-white/5">
                               <label className="text-[9px] font-bold font-space text-slate-500 tracking-widest uppercase mb-2 block">开场帧</label>
                               <p className="text-xs text-slate-300 leading-relaxed italic">{text(shot.start_frame_description)}</p>
                            </div>
                            <div className="p-4 bg-white/[0.02] rounded-xl border border-white/5">
                               <label className="text-[9px] font-bold font-space text-slate-500 tracking-widest uppercase mb-2 block">结束帧</label>
                               <p className="text-xs text-slate-300 leading-relaxed italic">{text(shot.end_frame_description)}</p>
                            </div>
                         </div>

                         <div className="space-y-4">
                            <div className="space-y-2">
                               <label className="text-[9px] font-bold font-space text-slate-500 tracking-widest uppercase block">动作 / 主体</label>
                               <p className="text-sm text-slate-100 font-medium leading-relaxed">{text(shot.action_description)}</p>
                            </div>
                            <div className="space-y-2 p-4 bg-cyan-500/5 rounded-xl border border-cyan-500/10">
                               <label className="text-[9px] font-bold font-space text-cyan-400 tracking-widest uppercase block">旁白与音频</label>
                               <p className="text-sm text-cyan-100 font-bold">"{text(shot.dialogue, '无对话')}"</p>
                            </div>
                         </div>
                      </div>
                   </div>
                 ))}
              </div>
           </div>

           {/* Right: Cast & Sets */}
           <aside className="space-y-12">
              <div className="space-y-6">
                 <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                    <Palette size={16} className="text-emerald-400" />
                    视觉风格约束
                 </h3>
                 <div className="glass-card p-5 rounded-2xl border-white/5 space-y-5">
                    <div className="grid grid-cols-[76px_1fr] gap-4 items-center">
                       <div className="flex gap-2">
                         <div
                           className="h-14 flex-1 rounded-xl border border-white/10"
                           style={{ backgroundColor: palette.primary || '#C41E3A' }}
                         />
                         <div
                           className="h-14 flex-1 rounded-xl border border-white/10"
                           style={{ backgroundColor: palette.secondary || '#020617' }}
                         />
                       </div>
                       <p className="text-xs text-slate-300 leading-relaxed line-clamp-4">
                         {text(palette.description, '当前剧本将沿用已生成的视觉风格约束。')}
                       </p>
                    </div>
                    <div className="space-y-3">
                       {styleCards.map((card) => (
                         <div key={card.title} className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
                            <div className="mb-2 flex items-center gap-2">
                              <card.icon size={14} className={card.accent} />
                              <span className="text-[9px] font-bold font-space text-slate-500 tracking-widest uppercase">
                                {card.title}
                              </span>
                            </div>
                            <p className="text-xs leading-5 text-slate-300">{card.value}</p>
                         </div>
                       ))}
                    </div>
                 </div>
              </div>

              <div className="space-y-6">
                 <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                    <Users size={16} className="text-violet-400" />
                    角色列表
                 </h3>
                 <div className="space-y-4">
                    {characters.map((char: any, i: number) => (
                      <div key={i} className="glass-card p-5 rounded-2xl border-white/5 space-y-2">
                         <div className="flex items-center justify-between">
                            <h4 className="text-sm font-bold text-white">{text(char.name)}</h4>
                            <span className="text-[9px] font-bold font-space text-slate-600 uppercase">{text(char.role || '主角')}</span>
                         </div>
                         <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">{text(char.description || char.appearance)}</p>
                      </div>
                    ))}
                 </div>
              </div>

              <div className="space-y-6">
                 <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                    <MapPin size={16} className="text-emerald-400" />
                    环境场景
                 </h3>
                 <div className="space-y-4">
                    {scenes.map((scene: any, i: number) => (
                      <div key={i} className="glass-card p-5 rounded-2xl border-white/5 space-y-2">
                         <h4 className="text-sm font-bold text-white">{text(scene.name)}</h4>
                         <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">{text(scene.description)}</p>
                      </div>
                    ))}
                 </div>
              </div>
           </aside>
        </section>

      </div>
    </div>
  );
};
