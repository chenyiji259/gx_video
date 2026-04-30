import React from 'react';
import {
  Sparkles,
  Loader2,
  Clock,
  Users,
  Palette,
  FileText,
  Monitor,
  Settings
} from 'lucide-react';
import { cn } from '@/lib/utils';

const PLATFORMS = [
  { id: 'tiktok', label: '抖音 / TikTok', ratio: '9:16' },
  { id: 'bilibili', label: '哔哩哔哩 / Bilibili', ratio: '16:9' },
  { id: 'youtube', label: 'YouTube', ratio: '16:9' },
  { id: 'youtube_shorts', label: 'YouTube Shorts', ratio: '9:16' },
  { id: 'xiaohongshu', label: '小红书', ratio: '9:16' },
];

const DURATIONS = [
  { value: 30, label: '30秒' },
  { value: 60, label: '60秒' },
  { value: 120, label: '2分钟' },
  { value: 180, label: '3分钟' },
];

const STYLES = [
  { id: 'animated_tech', label: '科技动画', description: '蓝色科技线条、数据流、全息界面。' },
  { id: 'live_action', label: '实拍风格', description: '写实的电影级质量，强调人物表现。' },
  { id: 'minimal', label: '极简主义', description: '干净的元素，大量留白，高端质感。' },
  { id: 'cinematic', label: '电影质感', description: '戏剧化的光影，深邃的纹理，强烈的情感氛围。' },
  { id: 'cyberpunk', label: '赛博朋克', description: '霓虹灯光，高对比度色彩，未来城市感。' },
  { id: 'apple_keynote', label: '发布会风格', description: '精准、专业且极具现代感。' },
  { id: 'documentary', label: '纪实影像', description: '真实观察感、自然光线与克制镜头语言。' },
  { id: 'luxury_editorial', label: '轻奢广告', description: '高级材质、柔和高光与品牌级陈列构图。' },
  { id: 'retro_film', label: '复古胶片', description: '颗粒、漏光、偏暖色调与怀旧电影氛围。' },
  { id: 'motion_graphics', label: '动态图形', description: '强节奏排版、图形转场和信息可视化表达。' },
  { id: 'fantasy_epic', label: '奇幻史诗', description: '宏大场景、戏剧化色彩与高张力视觉想象。' },
  { id: 'new_chinese', label: '新中式美学', description: '东方留白、器物质感与雅致氛围并重。' },
];

interface SetupViewProps {
  prompt: string;
  setPrompt: (v: string) => void;
  selectedPlatform: string;
  setSelectedPlatform: (v: string) => void;
  selectedDuration: number;
  setSelectedDuration: (v: number) => void;
  durationInput: string;
  setDurationInput: (v: string) => void;
  targetAudience: string;
  setTargetAudience: (v: string) => void;
  selectedStyle: string;
  setSelectedStyle: (v: string) => void;
  humanOnCamera: boolean | null;
  setHumanOnCamera: (v: boolean) => void;
  onStartCreation: () => void;
  isCreating: boolean;
}

export const SetupView: React.FC<SetupViewProps> = ({
  prompt, setPrompt,
  selectedPlatform, setSelectedPlatform,
  selectedDuration, setSelectedDuration,
  durationInput, setDurationInput,
  targetAudience, setTargetAudience,
  selectedStyle, setSelectedStyle,
  humanOnCamera, setHumanOnCamera,
  onStartCreation, isCreating,
}) => {
  const parsedDuration = Number(durationInput);
  const durationIsValid = Number.isFinite(parsedDuration) && parsedDuration >= 5 && parsedDuration <= 600;
  const canStart = prompt.trim().length > 0 && humanOnCamera !== null && durationIsValid && !isCreating;
  const selectedStyleMeta = STYLES.find((style) => style.id === selectedStyle) ?? STYLES[0];

  return (
    <div className="h-full flex flex-col bg-[#020617] overflow-y-auto custom-scrollbar p-8 2xl:p-12">
      <div className="mx-auto w-full max-w-[1360px] space-y-12">
        
        {/* Header */}
        <header className="space-y-6">
           <div className="flex items-center gap-3">
              <span className="px-3 py-1 bg-cyan-500/10 border border-cyan-500/20 rounded-full text-[10px] font-bold font-space text-cyan-400 tracking-widest uppercase">
                 项目初始化 v1.0
              </span>
           </div>
           <h1 className="text-5xl font-bold font-space text-white leading-tight tracking-tight uppercase">
              开启您的创意之旅
           </h1>
           <p className="text-lg text-slate-400 leading-relaxed max-w-2xl">
              定义您的愿景，让我们的 AI 导演为您打造专业的视频体验。
           </p>
        </header>

        <main className="space-y-12">
           {/* Project Identity */}
           <section className="space-y-6">
              <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                 <Settings size={16} className="text-cyan-400" />
                 项目身份
              </h3>
              <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_1.1fr_1.3fr] gap-6">
                 <div className="glass-panel p-8 rounded-[32px] border-white/5 space-y-4 group transition-all hover:border-white/10 min-h-[220px]">
                    <label className="text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase block">目标受众</label>
                    <input 
                      type="text"
                      value={targetAudience}
                      onChange={(e) => setTargetAudience(e.target.value)}
                      placeholder="例如：科技爱好者、Z世代..."
                      className="w-full bg-transparent border-none text-2xl font-bold text-white placeholder:text-slate-800 focus:ring-0 p-0"
                    />
                 </div>
                 <div className="glass-panel p-8 rounded-[32px] border-white/5 space-y-4 group transition-all hover:border-white/10 min-h-[220px]">
                    <label className="text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase block">当前视觉方向</label>
                    <div className="space-y-3">
                      <p className="text-2xl font-bold text-white">{selectedStyleMeta.label}</p>
                      <p className="text-sm leading-relaxed text-slate-400">{selectedStyleMeta.description}</p>
                    </div>
                 </div>
                 <div className="glass-panel p-8 rounded-[32px] border-white/5 space-y-4 group transition-all hover:border-white/10 min-h-[220px]">
                    <label className="text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase block">真人入镜门禁</label>
                    <div className="grid grid-cols-2 gap-3">
                      <button
                        type="button"
                        onClick={() => setHumanOnCamera(true)}
                        className={cn(
                          "rounded-2xl border px-4 py-4 text-left transition-all",
                          humanOnCamera === true
                            ? "bg-cyan-500/10 border-cyan-500/30 text-white shadow-lg"
                            : "bg-white/5 border-white/5 text-slate-400 hover:bg-white/10"
                        )}
                      >
                        <span className="block text-sm font-bold">需要真人</span>
                        <span className="mt-1 block text-[11px] leading-relaxed text-slate-500">后续镜头会优先保留真人主体与人物连续性。</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setHumanOnCamera(false)}
                        className={cn(
                          "rounded-2xl border px-4 py-4 text-left transition-all",
                          humanOnCamera === false
                            ? "bg-amber-500/10 border-amber-500/30 text-white shadow-lg"
                            : "bg-white/5 border-white/5 text-slate-400 hover:bg-white/10"
                        )}
                      >
                        <span className="block text-sm font-bold">不要真人</span>
                        <span className="mt-1 block text-[11px] leading-relaxed text-slate-500">后续画面会避开真人脸和真人主体，偏产品、场景或图形表达。</span>
                      </button>
                    </div>
                    <div className="rounded-2xl border border-cyan-500/10 bg-cyan-500/5 p-4">
                      <div className="flex items-center gap-3 text-[10px] font-bold font-space tracking-widest text-slate-400 uppercase">
                        <Users size={14} className="text-cyan-400" />
                        主体策略
                      </div>
                      <p className="mt-3 text-base font-bold text-white">
                        {humanOnCamera === true
                          ? '当前要求：真人主体必须进入关键画面'
                          : humanOnCamera === false
                            ? '当前要求：后续画面不要出现真人主体'
                            : '请先选择是否需要真人入镜'}
                      </p>
                      <p className="mt-2 text-sm leading-relaxed text-slate-400">
                        这个门禁会一路传到 creative brief、叙事剧本、九宫格生图和后续视频 prompt，不再单独悬在页面底部。
                      </p>
                    </div>
                 </div>
              </div>
           </section>

           {/* Core Brief */}
           <section className="space-y-6">
              <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                 <FileText size={16} className="text-amber-400" />
                 核心需求
              </h3>
              <div className="glass-panel p-8 rounded-[32px] border-white/5 space-y-4 group transition-all hover:border-white/10">
                 <label className="text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase block">创作目标</label>
                 <textarea 
                    rows={4}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="描述您的视频内容、主要卖点和核心讯息..."
                    className="w-full bg-transparent border-none text-lg text-slate-200 leading-relaxed placeholder:text-slate-800 focus:ring-0 p-0 resize-none"
                 />
              </div>
           </section>

           {/* Secondary Configs */}
           <section className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)] gap-8 items-start">
              {/* Platform & Duration */}
              <div className="space-y-8">
                 <div className="space-y-6">
                    <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                       <Monitor size={16} className="text-violet-400" />
                       格式与平台
                    </h3>
                    <div className="grid grid-cols-1 2xl:grid-cols-2 gap-3">
                       {PLATFORMS.map(p => (
                         <button
                           key={p.id}
                           onClick={() => setSelectedPlatform(p.id)}
                           className={cn(
                             "p-6 rounded-2xl border text-left flex items-center justify-between transition-all group",
                             selectedPlatform === p.id 
                               ? "bg-violet-500/10 border-violet-500/30 text-white shadow-lg" 
                               : "bg-white/5 border-white/5 text-slate-400 hover:bg-white/10"
                           )}
                         >
                           <div className="space-y-1">
                              <span className="text-base font-bold block">{p.label}</span>
                              <span className="text-[10px] font-bold font-space uppercase tracking-widest text-slate-500">{p.ratio} 比例</span>
                           </div>
                           <div className={cn("w-2 h-2 rounded-full", selectedPlatform === p.id ? "bg-violet-400 animate-pulse" : "bg-slate-800")} />
                         </button>
                       ))}
                    </div>
                 </div>

                 <div className="space-y-6">
                    <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                       <Clock size={16} className="text-emerald-400" />
                       预计时长
                    </h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                       {DURATIONS.map(d => (
                         <button
                           key={d.value}
                           onClick={() => {
                             setSelectedDuration(d.value);
                             setDurationInput(String(d.value));
                           }}
                           className={cn(
                             "py-4 rounded-xl border text-center transition-all",
                             selectedDuration === d.value 
                               ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400 shadow-lg" 
                               : "bg-white/5 border-white/5 text-slate-500 hover:bg-white/10"
                           )}
                         >
                           <span className="text-sm font-bold font-space">{d.label}</span>
                         </button>
                       ))}
                    </div>
                    <div className="grid grid-cols-1 gap-4 rounded-3xl border border-white/5 bg-white/5 p-6">
                      <div className="flex flex-col gap-4">
                        <div className="space-y-2">
                          <label className="block text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase">自定义时长（秒）</label>
                          <input
                            type="number"
                            min={5}
                            max={600}
                            step={1}
                            value={durationInput}
                            onChange={(e) => {
                              const nextValue = e.target.value;
                              setDurationInput(nextValue);
                              const parsed = Number(nextValue);
                              if (Number.isFinite(parsed) && parsed >= 5 && parsed <= 600) {
                                setSelectedDuration(parsed);
                              }
                            }}
                            className="w-full rounded-2xl border border-white/10 bg-slate-950/60 px-4 py-3 text-lg font-bold text-white outline-none transition-all focus:border-emerald-400/40"
                            placeholder="输入 5-600 秒"
                          />
                        </div>
                      </div>
                      <div className="space-y-2">
                        <p className="text-sm font-bold text-white">
                          当前将按 <span className="text-emerald-400">{selectedDuration} 秒</span> 规划视频总时长
                        </p>
                        <p className="text-sm leading-relaxed text-slate-500">
                          时长直接由你控制，系统会按当前秒数规划 brief、镜头密度和后续生成节奏。
                        </p>
                      </div>
                    </div>
                 </div>
              </div>

              {/* Style Detail */}
              <div className="space-y-6">
                 <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                    <Palette size={16} className="text-pink-400" />
                    风格矩阵
                 </h3>
                 <div className="glass-panel rounded-[32px] border-white/5 p-6">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {STYLES.map((style) => (
                        <button
                          key={style.id}
                          type="button"
                          onClick={() => setSelectedStyle(style.id)}
                          className={cn(
                            "rounded-[24px] border p-5 text-left transition-all",
                            selectedStyle === style.id
                              ? "border-pink-400/40 bg-pink-500/10 shadow-[0_0_30px_rgba(236,72,153,0.14)]"
                              : "border-white/5 bg-white/[0.03] hover:border-white/10 hover:bg-white/[0.05]"
                          )}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <h4 className="text-base font-bold text-white">{style.label}</h4>
                              <p className="mt-2 text-sm leading-relaxed text-slate-400">{style.description}</p>
                            </div>
                            <div
                              className={cn(
                                "mt-1 h-2.5 w-2.5 shrink-0 rounded-full",
                                selectedStyle === style.id ? "bg-pink-400 shadow-[0_0_12px_rgba(244,114,182,0.85)]" : "bg-slate-700"
                              )}
                            />
                          </div>
                        </button>
                      ))}
                    </div>
                 </div>
              </div>
           </section>
        </main>

        {/* Action Bar */}
        <footer className="pt-12 border-t border-white/5">
           <button 
             onClick={onStartCreation}
             disabled={!canStart}
             className={cn(
               "w-full h-20 rounded-[24px] font-black font-space text-xl tracking-[0.2em] uppercase flex items-center justify-center gap-4 transition-all",
               canStart 
                 ? "bg-gradient-to-r from-cyan-400 to-violet-600 text-white shadow-2xl shadow-cyan-500/40 hover:scale-[1.02] active:scale-[0.98]" 
                 : "bg-slate-900 text-slate-700 cursor-not-allowed opacity-50"
             )}
           >
              {isCreating ? (
                <>
                  <Loader2 className="animate-spin" />
                  项目启动中...
                </>
              ) : (
                <>
                  <Sparkles size={24} />
                  开始创作
                </>
              )}
           </button>
        </footer>
      </div>
    </div>
  );
};
