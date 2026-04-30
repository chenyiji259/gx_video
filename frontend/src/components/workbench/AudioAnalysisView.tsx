import React, { useEffect, useMemo, useRef, useState } from 'react';
import { 
  Activity, 
  BarChart2, 
  Clock,
  Music, 
  Zap,
  Mic,
  Play,
  Pause
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { projectService } from '@/services/api';

interface AudioAnalysisViewProps {
  projectId: string;
}

export const AudioAnalysisView: React.FC<AudioAnalysisViewProps> = ({ projectId }) => {
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    const fetchAnalysis = async () => {
      try {
        const res = await projectService.getAudioAnalysis(projectId);
        if (res.success && res.data) {
          setAnalysis(res.data);
        }
      } catch (error) {
        console.error("Failed to fetch audio analysis:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchAnalysis();
  }, [projectId]);

  const togglePlay = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
      } else {
        audioRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const handleTimeUpdate = () => {
    if (audioRef.current) {
      setCurrentTime(audioRef.current.currentTime);
      setDuration(audioRef.current.duration || 0);
    }
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const segments = analysis?.section_map || [];
  const lyrics = analysis?.lyrics_alignment || [];
  const bpm = analysis?.bpm || 0;
  const key = analysis?.key_scale || '--';
  const genre = analysis?.genre || '';
  const sectionsCount = segments.length;
  const hasPlayableAudio = Boolean(analysis?.audio_url);
  const inferredDuration =
    duration ||
    analysis?.duration_sec ||
    (segments.length > 0 ? Math.max(...segments.map((s: any) => Number(s.end) || 0)) : 0);
  
  // Calculate progress percentage
  const progressPercent = inferredDuration > 0 ? (currentTime / inferredDuration) * 100 : 0;

  const waveformBars = useMemo(() => {
    const length = 60;
    const curve: number[] = Array.isArray(analysis?.energy_curve) ? analysis.energy_curve : [];
    if (curve.length > 0) {
      return Array.from({ length }, (_, i) => {
        const idx = Math.floor((i / Math.max(length - 1, 1)) * (curve.length - 1));
        const v = Number(curve[idx] ?? 0);
        const normalized = Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0;
        return 20 + normalized * 60;
      });
    }
    return Array.from({ length }, (_, i) => 30 + ((i * 17) % 40));
  }, [analysis?.energy_curve]);
  
  // Determine active lyric index
  let activeLyricIdx = -1;
  for (let i = 0; i < lyrics.length; i++) {
    if (currentTime >= (lyrics[i].start ?? lyrics[i].time)) {
      activeLyricIdx = i;
    } else {
      break;
    }
  }

  // Auto scroll lyrics
  useEffect(() => {
    if (activeLyricIdx >= 0) {
      const container = document.getElementById('lyrics-container');
      const activeEl = document.getElementById(`lyric-${activeLyricIdx}`);
      if (container && activeEl) {
        const containerHeight = container.clientHeight;
        const offsetTop = activeEl.offsetTop;
        const elementHeight = activeEl.clientHeight;
        
        container.scrollTo({
          top: offsetTop - containerHeight / 2 + elementHeight / 2,
          behavior: 'smooth'
        });
      }
    }
  }, [activeLyricIdx]);

  if (loading) {
    return <div className="animate-pulse p-8 text-[#a5aac2] font-['Space_Grotesk']">Loading analysis...</div>;
  }

  if (!analysis) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-[#a5aac2] font-['Space_Grotesk']">暂无音频分析结果</div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6 pb-20">
      {/* Hidden Audio Player */}
      <audio 
        ref={audioRef} 
        src={analysis?.audio_url} 
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleTimeUpdate}
        onEnded={() => setIsPlaying(false)}
      />

      {/* Metrics Bar */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        {[
          { label: 'BPM', value: bpm.toString(), icon: Activity, color: '#ba9eff' },
          { label: '段落', value: sectionsCount.toString(), icon: BarChart2, color: '#00cffc' },
          { label: '时长', value: formatTime(analysis?.duration_sec || duration), icon: Clock, color: '#dfe4fe' },
          { label: '调性 / 流派', value: `${key}${genre ? ' · ' + genre : ''}`, icon: Music, color: '#ff59e3' },
        ].map((item, i) => (
          <div key={i} className="bg-[#0c1326]/50 border border-[#41475b]/30 rounded-2xl p-6 flex items-center justify-between group hover:border-[#ba9eff]/50 hover:shadow-[0_0_20px_rgba(186,158,255,0.1)] transition-all backdrop-blur-sm">
             <div className="space-y-1">
                <p className="text-xs font-bold text-[#a5aac2] tracking-widest uppercase font-['Space_Grotesk']">{item.label}</p>
                <p className="text-[32px] font-bold text-[#dfe4fe] tracking-tight leading-none font-['Space_Grotesk']">{item.value}</p>
             </div>
             <div className="w-12 h-12 rounded-full bg-[#1c253e]/50 flex items-center justify-center transition-colors shadow-[inset_0_0_10px_rgba(0,0,0,0.5)]">
                <item.icon size={24} style={{ color: item.color }} />
             </div>
          </div>
        ))}
      </div>

      {/* Content Layout: Top (Player + Waveform) & Bottom (Lyrics + Summary) */}
      <div className="flex flex-col gap-6">
        
        {/* Top Column: Player & Waveform Combined */}
        <section className="bg-[#0c1326]/50 border border-[#41475b]/30 rounded-2xl p-8 relative overflow-hidden backdrop-blur-sm shrink-0 flex flex-col min-h-[240px]">
          <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-[#ba9eff] to-[#00cffc]" />
          
          <div className="flex items-center justify-between mb-8">
             <div className="flex items-center gap-3">
                <Music size={20} className="text-[#ba9eff]" />
                <h3 className="text-lg font-bold text-[#dfe4fe] tracking-wider font-['Space_Grotesk']">音乐频谱与段落</h3>
             </div>
             
             {/* Player Controls Inline */}
             <div className="flex items-center gap-6">
                <span className="text-xs font-bold text-[#a5aac2] font-['Space_Grotesk'] tracking-widest w-12 text-right">{formatTime(currentTime)}</span>
                <div className="flex items-center justify-center gap-4">
                  <button 
                    onClick={() => {
                      if (audioRef.current) audioRef.current.currentTime = Math.max(0, currentTime - 5);
                    }}
                    disabled={!hasPlayableAudio}
                    className="w-8 h-8 rounded-full bg-[#1c253e] flex items-center justify-center text-[#a5aac2] hover:text-[#dfe4fe] transition-colors disabled:opacity-50"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 17l-5-5 5-5M18 17l-5-5 5-5"/></svg>
                  </button>
                  
                  <button 
                    onClick={togglePlay}
                    disabled={!hasPlayableAudio}
                    className="w-12 h-12 rounded-full bg-gradient-to-r from-[#00cffc] to-[#ba9eff] flex items-center justify-center text-black hover:shadow-[0_0_20px_rgba(186,158,255,0.6)] transition-all disabled:opacity-50 disabled:hover:shadow-none"
                  >
                    {isPlaying ? <Pause size={20} className="fill-current" /> : <Play size={20} className="fill-current ml-1" />}
                  </button>

                  <button 
                    onClick={() => {
                      if (audioRef.current) audioRef.current.currentTime = Math.min(inferredDuration, currentTime + 5);
                    }}
                    disabled={!hasPlayableAudio}
                    className="w-8 h-8 rounded-full bg-[#1c253e] flex items-center justify-center text-[#a5aac2] hover:text-[#dfe4fe] transition-colors disabled:opacity-50"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M13 17l5-5-5-5M6 17l5-5-5-5"/></svg>
                  </button>
                </div>
                <span className="text-xs font-bold text-[#a5aac2] font-['Space_Grotesk'] tracking-widest w-12 text-left">{formatTime(inferredDuration || 0)}</span>
             </div>
          </div>

          <div className="flex-1 flex flex-col justify-end">
            <div className="bg-[#070d1f]/50 h-[160px] rounded-xl relative overflow-hidden border border-[#41475b]/30 shadow-[inset_0_0_20px_rgba(0,0,0,0.5)] cursor-pointer group"
              onClick={(e) => {
                if (!audioRef.current || !hasPlayableAudio) return;
                const rect = e.currentTarget.getBoundingClientRect();
                const clickX = e.clientX - rect.left;
                const percent = clickX / rect.width;
                audioRef.current.currentTime = percent * inferredDuration;
              }}
            >
               {/* Waveform Bars */}
               <div className="absolute inset-0 flex items-end justify-center gap-1 px-8 pb-8 pt-8 pointer-events-none">
                  {waveformBars.map((barHeight, i) => {
                    const barPercent = (i / 60) * 100;
                    const isPlayed = barPercent <= progressPercent;
                    const isCurrent = Math.abs(barPercent - progressPercent) < 1.5;
                    return (
                      <div 
                        key={i} 
                        className={cn(
                          "w-1.5 rounded-full transition-all duration-300",
                          isPlayed ? "bg-gradient-to-t from-[#ba9eff] to-[#00cffc]" : "bg-[#1c253e]",
                          isCurrent && "bg-white shadow-[0_0_15px_white] h-full"
                        )} 
                        style={{ height: isCurrent ? '100%' : `${barHeight}%` }}
                      />
                    );
                  })}
               </div>

               {/* Time Cursor */}
               <div 
                 className="absolute inset-y-0 w-[2px] bg-white shadow-[0_0_15px_white] z-10 transition-all duration-300 pointer-events-none"
                 style={{ left: `calc(32px + (100% - 64px) * ${Math.max(0, Math.min(1, progressPercent / 100))})` }}
               />
            </div>
            
            {/* Segment Markers placed below the waveform */}
            <div className="h-10 mt-2 flex px-8 relative pointer-events-none">
               {segments.map((s: any, idx: number) => {
                 const segWidth = inferredDuration > 0 ? (((s.end - s.start) / inferredDuration) * 100) : 0;
                 const colors = ['#ba9eff', '#00cffc', '#ff59e3', '#a5aac2', '#dfe4fe'];
                 const color = s.color || colors[idx % colors.length];
                 return (
                   <div 
                     key={idx} 
                     className="h-full flex flex-col justify-start overflow-hidden transition-colors border-l-2 pl-2 pt-1"
                     style={{ width: `${segWidth}%`, borderLeftColor: color }}
                   >
                      <p className="text-[10px] font-bold tracking-widest uppercase font-['Space_Grotesk'] truncate" style={{ color: color }}>{s.label}</p>
                   </div>
                 );
               })}
            </div>
          </div>
        </section>

        {/* Bottom Row: Lyrics & Summary */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 h-[400px]">
          {/* Lyric Synchronization */}
          <section className="bg-[#0c1326]/50 border border-[#41475b]/30 rounded-2xl p-8 relative overflow-hidden backdrop-blur-sm flex flex-col h-full">
            <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-[#ba9eff] to-[#ff59e3]" />
            
            <div className="flex items-center justify-between mb-6 shrink-0">
               <div className="flex items-center gap-3">
                  <Mic size={20} className="text-[#ba9eff]" />
                  <h3 className="text-lg font-bold text-[#dfe4fe] tracking-wider font-['Space_Grotesk']">歌词同步视图</h3>
               </div>
            </div>

            <div className="space-y-6 px-4 overflow-y-auto custom-scrollbar flex-1 relative scroll-smooth" id="lyrics-container">
               {lyrics.map((line: any, i: number) => {
                 const isActive = i === activeLyricIdx;
                 const lineTime = line.start ?? line.time ?? 0;
                 const lineText = line.word ?? line.text ?? '';
                 return (
                   <div key={i} id={`lyric-${i}`} className={cn(
                     "flex items-center gap-6 transition-all duration-300 cursor-pointer hover:opacity-80 py-1",
                     isActive ? "opacity-100" : "opacity-40"
                   )} onClick={() => {
                     if (audioRef.current) {
                       audioRef.current.currentTime = lineTime;
                     }
                   }}>
                      <span className={cn(
                        "text-xs font-['Space_Grotesk'] w-12 text-right tracking-widest",
                        isActive ? "text-[#00cffc] font-bold" : "text-[#a5aac2]"
                      )}>{formatTime(lineTime)}</span>
                      <div className={cn(
                        "text-base transition-all flex items-center gap-3 font-bold",
                        isActive ? "text-[#dfe4fe] text-xl" : "text-[#a5aac2]"
                      )}>
                        {isActive && <div className="w-1 h-6 bg-[#00cffc] rounded-full shadow-[0_0_10px_#00cffc]" />}
                        {typeof lineText === 'object' && lineText !== null ? JSON.stringify(lineText).replace(/["{}]/g, ' ') : lineText}
                      </div>
                   </div>
                 );
               })}
               {lyrics.length === 0 && (
                  <div className="text-sm text-[#a5aac2] font-['Space_Grotesk'] absolute inset-0 flex items-center justify-center">暂无歌词数据</div>
               )}
            </div>
          </section>

          {/* AI Music Summary */}
          <section className="bg-[#0c1326]/50 border border-[#41475b]/30 rounded-2xl p-8 relative overflow-hidden backdrop-blur-sm flex flex-col h-full">
            <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-[#ba9eff] to-[#ff59e3]" />
            <div className="flex items-center gap-3 mb-6 shrink-0">
              <BarChart2 size={20} className="text-[#ba9eff]" />
              <h3 className="text-lg font-bold text-[#dfe4fe] tracking-wider font-['Space_Grotesk']">AI 分析摘要</h3>
            </div>
            <div className="overflow-y-auto custom-scrollbar flex-1 pr-4 space-y-6">
              {analysis?.quality_summary ? (
                typeof analysis.quality_summary === 'string' ? (
                  <p className="text-[#a5aac2] text-sm leading-relaxed whitespace-pre-wrap">
                    {analysis.quality_summary}
                  </p>
                ) : (
                  <>
                    {analysis.quality_summary.music_summary && (
                      <div className="space-y-2">
                        <h4 className="text-sm font-bold text-[#dfe4fe] flex items-center gap-2">
                          <span className="w-1 h-3 bg-[#ba9eff] rounded-full"></span>
                          音乐总体摘要
                        </h4>
                        <p className="text-[#a5aac2] text-xs leading-relaxed">
                          {analysis.quality_summary.music_summary}
                        </p>
                      </div>
                    )}
                    {analysis.quality_summary.visual_suggestion && (
                      <div className="space-y-2">
                        <h4 className="text-sm font-bold text-[#dfe4fe] flex items-center gap-2">
                          <span className="w-1 h-3 bg-[#00cffc] rounded-full"></span>
                          视觉建议
                        </h4>
                        <p className="text-[#a5aac2] text-xs leading-relaxed">
                          {analysis.quality_summary.visual_suggestion}
                        </p>
                      </div>
                    )}
                    {analysis.quality_summary.music_structure_summary?.sections && (
                      <div className="space-y-3">
                        <h4 className="text-sm font-bold text-[#dfe4fe] flex items-center gap-2">
                          <span className="w-1 h-3 bg-[#ff59e3] rounded-full"></span>
                          段落分析
                        </h4>
                        <div className="space-y-3">
                          {analysis.quality_summary.music_structure_summary.sections.map((sec: any, idx: number) => (
                            <div key={idx} className="bg-[#1c253e]/30 border border-[#41475b]/30 p-3 rounded-xl hover:border-[#ba9eff]/50 transition-colors">
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-xs font-bold text-[#ba9eff] uppercase tracking-widest font-['Space_Grotesk']">{sec.label}</span>
                                <span className="text-[10px] text-[#a5aac2] font-['Space_Grotesk']">{formatTime(sec.start)} - {formatTime(sec.end)}</span>
                              </div>
                              <p className="text-xs text-[#dfe4fe] leading-relaxed mb-1">{sec.description}</p>
                              {sec.lyrics_summary && (
                                <p className="text-[10px] text-[#a5aac2] leading-relaxed italic border-l-2 border-[#41475b]/50 pl-2">
                                  {sec.lyrics_summary}
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {analysis.quality_summary.emotion_arc?.overall && (
                      <div className="space-y-2">
                        <h4 className="text-sm font-bold text-[#dfe4fe] flex items-center gap-2">
                          <span className="w-1 h-3 bg-[#00cffc] rounded-full"></span>
                          情绪弧线
                        </h4>
                        <p className="text-[#a5aac2] text-xs leading-relaxed">
                          {analysis.quality_summary.emotion_arc.overall}
                        </p>
                      </div>
                    )}
                    {analysis.quality_summary.editing_guidance?.per_section && (
                      <div className="space-y-3">
                        <h4 className="text-sm font-bold text-[#dfe4fe] flex items-center gap-2">
                          <span className="w-1 h-3 bg-[#ba9eff] rounded-full"></span>
                          剪辑指导
                        </h4>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          {analysis.quality_summary.editing_guidance.per_section.map((guide: any, idx: number) => (
                            <div key={idx} className="bg-[#1c253e]/30 border border-[#41475b]/30 p-2 rounded-lg flex flex-col gap-1">
                               <div className="flex justify-between items-center">
                                 <span className="text-[10px] font-bold text-[#dfe4fe] font-['Space_Grotesk'] uppercase">{guide.section}</span>
                                 <span className="text-[10px] text-[#00cffc]">{guide.motion}</span>
                               </div>
                               <div className="flex justify-between items-center text-[9px] text-[#a5aac2]">
                                 <span>剪辑密度: {guide.cut_density}</span>
                                 <span>镜头时长: {guide.shot_duration_range?.join('-')}s</span>
                               </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )
              ) : (
                <div className="h-full flex items-center justify-center">
                  <p className="text-sm text-[#a5aac2] font-['Space_Grotesk']">暂无摘要数据</p>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};
