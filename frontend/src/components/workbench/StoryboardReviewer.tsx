import React, { useEffect, useMemo, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Clapperboard,
  Grid3x3,
  Image as ImageIcon,
  Loader2,
  Sparkles,
  X,
  ArrowRight,
  ScanLine,
  Zap,
  Maximize2,
  ChevronRight,
  ChevronLeft,
  Aperture
} from 'lucide-react';

import { projectService } from '@/services/api';
import { useProjectStore } from '@/stores/projectStore';
import { cn } from '@/lib/utils';

type ShotItem = {
  id: string;
  shot_index: number;
  duration_ms?: number;
  emotion?: string | null;
  emotion_intensity?: string | null;
  subject?: string | null;
  location?: string | null;
  dialogue?: string | null;
  camera_language?: string | null;
  lyric_text?: string | null;
  status?: string | null;
};

type StoryboardFrameItem = {
  id: string;
  shot_id?: string | null;
  asset_id: string;
  storage_uri?: string | null;
  parent_asset_id?: string | null;
  prompt_bundle_id?: string | null;
  frame_index?: number | null;
  cell_position?: number | null;
  grid_index?: number | null;
  metadata?: Record<string, unknown>;
};

type GridCell = {
  cell_position: number;
  asset_id: string;
  asset_url?: string | null;
  shot_id?: string | null;
  shot_index?: number | null;
  frame_description?: string;
  scene_description?: string;
  is_reused_from_prev_grid?: boolean;
};

type GridPrompt = {
  bundle_id: string;
  provider: string;
  positive_prompt: string;
  negative_prompt?: string | null;
  params?: Record<string, unknown>;
};

type GridItem = {
  grid_index: number;
  parent_asset_id?: string | null;
  parent_asset_url?: string | null;
  bundle_id?: string | null;
  prompt_preview?: string | null;
  prompt_bundle?: GridPrompt | null;
  cells: GridCell[];
};

const safeText = (value: unknown, fallback = '暂无信息') => {
  if (value == null) return fallback;
  if (typeof value === 'string') return value.trim() || fallback;
  return String(value);
};

const shotLabel = (index: number | null | undefined) =>
  `镜头 ${String((index ?? 0) + 1).padStart(2, '0')}`;

export const StoryboardReviewer = ({
  projectId,
  currentStage,
}: {
  projectId: string;
  currentStage: string;
}) => {
  const [shots, setShots] = useState<ShotItem[]>([]);
  const [frames, setFrames] = useState<StoryboardFrameItem[]>([]);
  const [grids, setGrids] = useState<GridItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [selectedShotIndex, setSelectedShotIndex] = useState(0);
  
  const ribbonRef = useRef<HTMLDivElement>(null);
  const refreshFlag = useProjectStore((state) => state.refreshFlag);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [shotsRes, framesRes, gridsRes] = await Promise.all([
          projectService.getShots(projectId).catch(() => ({ success: false, data: { items: [] } })),
          projectService.getStoryboardFrames(projectId).catch(() => ({ success: false, data: { frames: [] } })),
          projectService.getStoryboardGrids(projectId).catch(() => ({ success: false, data: { grids: [] } })),
        ]);

        setShots(shotsRes.success ? shotsRes.data.items ?? [] : []);
        setFrames(framesRes.success ? framesRes.data.frames ?? [] : []);
        setGrids(
          gridsRes.success
            ? [...(gridsRes.data.grids ?? [])].sort((a: GridItem, b: GridItem) => a.grid_index - b.grid_index)
            : []
        );
      } catch (error) {
        console.error('Failed to fetch storyboard data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [projectId, refreshFlag]);

  const sortedShots = useMemo(() => [...shots].sort((a, b) => (a?.shot_index ?? 0) - (b?.shot_index ?? 0)), [shots]);

  const frameBoundaryMap = useMemo(() => {
    const cellFrameMap = new Map<string, StoryboardFrameItem[]>();
    for (const frame of frames) {
      if (frame.shot_id && frame.cell_position) {
        const current = cellFrameMap.get(frame.shot_id) ?? [];
        current.push(frame);
        cellFrameMap.set(frame.shot_id, current);
      }
    }
    const result = new Map<string, { firstFrameUrl?: string | null; lastFrameUrl?: string | null; gridIndex?: number | null }>();
    for (const [shotId, shotFrames] of cellFrameMap.entries()) {
      const ordered = [...shotFrames].sort((a, b) => (a.cell_position ?? 0) - (b.cell_position ?? 0));
      const first = ordered[0];
      const last = ordered[ordered.length - 1];
      result.set(shotId, {
        firstFrameUrl: first?.storage_uri,
        lastFrameUrl: last?.storage_uri,
        gridIndex: first?.grid_index,
      });
    }
    return result;
  }, [frames]);

  const shotCards = useMemo(() => {
    const cellsByShotId = new Map<string, GridCell>();
    for (const grid of grids) {
      for (const cell of grid.cells ?? []) {
        if (cell.shot_id && !cellsByShotId.has(cell.shot_id)) {
          cellsByShotId.set(cell.shot_id, cell);
        }
      }
    }
    return sortedShots.map((shot) => {
      const matchedCell = cellsByShotId.get(shot.id);
      const boundary = frameBoundaryMap.get(shot.id);
      const nextCell = grids.flatMap((grid) => grid.cells ?? []).find((cell) => cell.shot_index === (shot.shot_index ?? 0) + 1);
      return {
        ...shot,
        firstFrameUrl: matchedCell?.asset_url || boundary?.firstFrameUrl || null,
        lastFrameUrl: nextCell?.asset_url || boundary?.lastFrameUrl || null,
        firstFrameDescription: matchedCell?.frame_description || '',
        lastFrameDescription: nextCell?.frame_description || '',
        sceneDescription: matchedCell?.scene_description || shot.location || '',
        sourceGridIndex: matchedCell?.shot_index != null ? Math.floor((matchedCell.shot_index as number) / 8) + 1 : boundary?.gridIndex,
      };
    });
  }, [sortedShots, grids, frameBoundaryMap]);

  const activeShot = shotCards[selectedShotIndex] || null;

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-[#020617]">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="animate-spin text-cyan-400" size={32} />
          <p className="text-xs font-space font-bold tracking-widest text-slate-500 uppercase">加载分镜数据...</p>
        </div>
      </div>
    );
  }

  if (sortedShots.length === 0) {
    return (
      <div className="h-full flex items-center justify-center p-12 bg-[#020617]">
        <div className="w-full max-w-2xl glass-panel p-12 rounded-[32px] text-center border-white/5">
          <Aperture className="mx-auto mb-6 text-cyan-400 animate-pulse" size={32} />
          <h2 className="mb-4 text-3xl font-bold text-white font-space">分镜设计中...</h2>
          <p className="text-sm leading-relaxed text-slate-400">
            AI 导演正在处理镜头规划与九宫格边界。完成后，此工作区将转变为交互式审核看板。
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#020617] overflow-hidden">
      <section className="h-48 shrink-0 bg-slate-900/40 border-b border-white/5 relative z-10 flex flex-col">
         <div className="h-10 flex items-center justify-between px-8 shrink-0 border-b border-white/5 bg-black/20">
            <div className="flex items-center gap-3">
               <Grid3x3 size={14} className="text-cyan-400" />
               <span className="text-[10px] font-bold font-space tracking-widest text-slate-500 uppercase">导演镜头轨道</span>
            </div>
            <div className="flex items-center gap-4 text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase">
               <span>共 {shotCards.length} 个镜头</span>
               <div className="h-3 w-px bg-white/10" />
               <span className="text-cyan-400">{grids.length} 组九宫格</span>
            </div>
         </div>
         
         <div 
           ref={ribbonRef}
           className="flex-1 overflow-x-auto flex items-center px-8 gap-4 custom-scrollbar"
         >
            {shotCards.map((shot, idx) => (
              <button 
                key={shot.id}
                onClick={() => setSelectedShotIndex(idx)}
                className={cn(
                  "h-28 aspect-video rounded-xl border-2 transition-all shrink-0 relative group overflow-hidden",
                  selectedShotIndex === idx ? "border-cyan-400 scale-105 shadow-[0_0_20px_rgba(34,211,238,0.3)]" : "border-white/5 hover:border-white/20"
                )}
              >
                {shot.firstFrameUrl ? (
                   <img src={shot.firstFrameUrl} className="w-full h-full object-cover" alt="" />
                ) : (
                   <div className="w-full h-full bg-slate-800 flex items-center justify-center">
                      <ImageIcon size={20} className="text-slate-600" />
                   </div>
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent" />
                <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between">
                   <span className="text-[9px] font-bold font-space text-white">{shotLabel(shot.shot_index)}</span>
                   <div className={cn("w-1.5 h-1.5 rounded-full", shot.firstFrameUrl ? "bg-emerald-400" : "bg-slate-500")} />
                </div>
              </button>
            ))}
         </div>
      </section>

      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-[1fr_420px] gap-px bg-white/5">
        <section className="flex flex-col min-h-0 bg-[#020617] overflow-y-auto custom-scrollbar p-8 2xl:p-12">
          <AnimatePresence mode="wait">
            {activeShot && (
              <motion.div 
                key={activeShot.id}
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}
                className="max-w-5xl mx-auto w-full space-y-12"
              >
                <div className="space-y-6">
                   <div className="flex items-center justify-between">
                      <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                         <ScanLine size={16} className="text-cyan-400" />
                         视觉连贯性
                      </h3>
                      <div className="px-4 py-1.5 bg-cyan-500/10 border border-cyan-500/20 rounded-full text-xs font-bold font-space text-cyan-400">
                         {shotLabel(activeShot.shot_index)}
                      </div>
                   </div>

                   <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] items-center gap-6">
                      <div className="space-y-3">
                         <div className="aspect-video rounded-2xl overflow-hidden glass-panel border-white/10 shadow-2xl relative group">
                            {activeShot.firstFrameUrl ? (
                               <img src={activeShot.firstFrameUrl} className="w-full h-full object-cover cursor-pointer transition-transform duration-500 group-hover:scale-110" alt="" onClick={() => setPreviewImage(activeShot.firstFrameUrl!)} />
                            ) : (
                               <div className="w-full h-full flex items-center justify-center bg-slate-900 text-slate-700 text-[10px] font-bold uppercase font-space">等待生成</div>
                            )}
                            <div className="absolute top-4 left-4 px-2 py-1 bg-black/60 backdrop-blur-md rounded text-[9px] font-bold text-white uppercase tracking-wider">开场帧</div>
                         </div>
                         <p className="text-[10px] text-slate-500 font-medium leading-relaxed italic">{activeShot.firstFrameDescription || "等待生成..."}</p>
                      </div>

                      <div className="flex flex-col items-center gap-2">
                         <ArrowRight size={24} className="text-cyan-500" />
                      </div>

                      <div className="space-y-3">
                         <div className="aspect-video rounded-2xl overflow-hidden glass-panel border-white/10 shadow-2xl relative group">
                            {activeShot.lastFrameUrl ? (
                               <img src={activeShot.lastFrameUrl} className="w-full h-full object-cover cursor-pointer transition-transform duration-500 group-hover:scale-110" alt="" onClick={() => setPreviewImage(activeShot.lastFrameUrl!)} />
                            ) : (
                               <div className="w-full h-full flex items-center justify-center bg-slate-900 text-slate-700 text-[10px] font-bold uppercase font-space">等待生成</div>
                            )}
                            <div className="absolute top-4 left-4 px-2 py-1 bg-black/60 backdrop-blur-md rounded text-[9px] font-bold text-white uppercase tracking-wider">结束帧</div>
                         </div>
                         <p className="text-[10px] text-slate-500 font-medium leading-relaxed italic">{activeShot.lastFrameDescription || "等待生成..."}</p>
                      </div>
                   </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-8 pt-8 border-t border-white/5">
                   <div className="space-y-6">
                      <div className="space-y-2">
                         <label className="text-[10px] font-bold font-space text-slate-500 tracking-[0.2em] uppercase">核心叙事</label>
                         <div className="glass-card p-6 rounded-2xl border-white/10 shadow-xl">
                            <p className="text-base text-slate-100 leading-relaxed font-medium">{activeShot.subject}</p>
                         </div>
                      </div>
                      
                      {activeShot.dialogue && (
                        <div className="space-y-2">
                           <label className="text-[10px] font-bold font-space text-violet-400 tracking-[0.2em] uppercase">对白 / 配音</label>
                           <div className="bg-violet-500/5 border border-violet-500/10 p-4 rounded-xl">
                              <p className="text-sm text-violet-200 font-medium italic">"{activeShot.dialogue}"</p>
                           </div>
                        </div>
                      )}
                   </div>

                   <div className="space-y-6">
                      <div className="grid grid-cols-1 gap-4">
                        <div className="glass-card p-5 rounded-2xl flex items-center gap-4">
                           <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center shrink-0">
                              <Zap size={18} className="text-cyan-400" />
                           </div>
                           <div>
                              <p className="text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase mb-1">运镜语言</p>
                              <p className="text-sm text-slate-200 font-medium">{safeText(activeShot.camera_language)}</p>
                           </div>
                        </div>

                        <div className="glass-card p-5 rounded-2xl flex items-center gap-4">
                           <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center shrink-0">
                              <Clapperboard size={18} className="text-emerald-400" />
                           </div>
                           <div>
                              <p className="text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase mb-1">场景定位</p>
                              <p className="text-sm text-slate-200 font-medium">{safeText(activeShot.location)}</p>
                           </div>
                        </div>

                        <div className="glass-card p-5 rounded-2xl flex items-center gap-4">
                           <div className="w-10 h-10 rounded-xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center shrink-0">
                              <Sparkles size={18} className="text-violet-400" />
                           </div>
                           <div>
                              <p className="text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase mb-1">情绪 / 色调</p>
                              <p className="text-sm text-slate-200 font-medium">{safeText(activeShot.emotion)} ({activeShot.emotion_intensity || '中等'})</p>
                           </div>
                        </div>
                      </div>
                   </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </section>

        <aside className="bg-slate-950 border-l border-white/5 flex flex-col min-h-0">
           <div className="h-12 flex items-center justify-between px-6 border-b border-white/5 shrink-0">
              <div className="flex items-center gap-3">
                 <Grid3x3 size={16} className="text-violet-400" />
                 <h2 className="text-xs font-bold font-space tracking-widest text-slate-400 uppercase">九宫格画廊</h2>
              </div>
           </div>

           <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-8">
              {grids.map((grid) => (
                <div key={grid.grid_index} className="space-y-4">
                   <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase">Grid #{grid.grid_index}</span>
                      <span className="text-[9px] font-bold font-space text-cyan-400/60 uppercase tracking-tighter">1024 x 1024 母版</span>
                   </div>
                   <div className="aspect-square rounded-2xl overflow-hidden glass-panel border-white/10 shadow-xl group cursor-pointer" onClick={() => setPreviewImage(grid.parent_asset_url!)}>
                      {grid.parent_asset_url ? (
                        <img src={grid.parent_asset_url} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700" alt="" />
                      ) : (
                        <div className="w-full h-full bg-slate-900 flex flex-col items-center justify-center gap-3">
                           <Loader2 size={24} className="text-slate-700 animate-spin" />
                           <span className="text-[9px] font-bold font-space text-slate-700 uppercase">生成中...</span>
                        </div>
                      )}
                   </div>
                   {grid.prompt_preview && (
                     <div className="p-4 bg-white/[0.02] border border-white/5 rounded-xl">
                        <p className="text-[10px] text-slate-500 leading-relaxed line-clamp-3 italic">"{grid.prompt_preview}"</p>
                     </div>
                   )}
                </div>
              ))}
              
              {grids.length === 0 && (
                <div className="h-40 border border-dashed border-white/5 rounded-2xl flex flex-col items-center justify-center gap-3 text-slate-700">
                   <Grid3x3 size={32} className="opacity-20" />
                   <span className="text-[10px] font-bold font-space uppercase tracking-widest">暂无九宫格数据</span>
                </div>
              )}
           </div>
        </aside>
      </div>

      {/* Fullscreen Preview Modal */}
      <AnimatePresence>
        {previewImage && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-[100] flex items-center justify-center bg-black/95 p-12 backdrop-blur-xl"
            onClick={() => setPreviewImage(null)}
          >
            <button className="absolute right-12 top-12 text-white/40 hover:text-white transition-colors">
              <X size={32} />
            </button>
            <motion.img
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              src={previewImage}
              alt="Preview"
              className="max-h-full max-w-full rounded-2xl shadow-2xl object-contain"
              onClick={(e) => e.stopPropagation()}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
