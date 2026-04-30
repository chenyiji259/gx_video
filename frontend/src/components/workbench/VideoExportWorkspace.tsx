import React, { useState } from 'react';
import { Download, Loader2, Settings, MonitorPlay, CheckCircle2, ChevronRight, Zap, Film } from 'lucide-react';
import { exportService } from '@/services/api';
import { useVideoStageData } from './useVideoStageData';
import { cn } from '@/lib/utils';

type ExportResolution = '720p' | '1080p' | '2K' | '4K';

const EXPORT_RESOLUTION_OPTIONS: Array<{
  value: ExportResolution;
  title: string;
  description: string;
}> = [
  { value: '720p', title: '720p', description: '标准清晰度 / 快速交付' },
  { value: '1080p', title: '1080p', description: '高清 / 常规成片' },
  { value: '2K', title: '2K', description: '2560x1440 / 高规格发布' },
  { value: '4K', title: '4K', description: '3840x2160 / 大屏母版' },
];

export const VideoExportWorkspace = ({
  projectId,
}: {
  projectId: string;
}) => {
  const [exporting, setExporting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [selectedResolution, setSelectedResolution] = useState<ExportResolution>('1080p');
  const { loading, latestExport, timeline, refreshAll } = useVideoStageData(projectId);

  const handleExport = async (resolution: ExportResolution) => {
    setExporting(true);
    try {
      await exportService.triggerExport(projectId, resolution);
      await refreshAll();
    } catch (error) {
      console.error('Export failed:', error);
    } finally {
      setExporting(false);
    }
  };

  const buildDownloadFilename = () => {
    const resolution = latestExport?.resolution || selectedResolution;
    const version = latestExport?.export_version_id?.slice(-8) || 'final';
    return `vidmuse-${projectId}-${resolution}-${version}.mp4`;
  };

  const downloadFromUrl = (url: string, filename: string, blob?: Blob) => {
    const href = blob ? URL.createObjectURL(blob) : url;
    const link = document.createElement('a');
    link.href = href;
    link.download = filename;
    link.rel = 'noopener noreferrer';
    document.body.appendChild(link);
    link.click();
    link.remove();
    if (blob) {
      window.setTimeout(() => URL.revokeObjectURL(href), 1000);
    }
  };

  const handleDownload = async () => {
    if (!latestExport?.storage_uri || downloading) return;
    setDownloading(true);
    const filename = buildDownloadFilename();
    try {
      const response = await fetch(latestExport.storage_uri);
      if (!response.ok) throw new Error(`download failed: ${response.status}`);
      const blob = await response.blob();
      downloadFromUrl(latestExport.storage_uri, filename, blob);
    } catch (error) {
      console.warn('Blob download failed, falling back to direct download link:', error);
      downloadFromUrl(latestExport.storage_uri, filename);
    } finally {
      setDownloading(false);
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-[#020617]">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="animate-spin text-cyan-400" size={32} />
          <p className="text-xs font-space font-bold tracking-widest text-slate-500 uppercase">加载导出数据...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#020617] overflow-y-auto custom-scrollbar p-8 2xl:p-12">
      <div className="max-w-6xl mx-auto w-full space-y-12">
        
        {/* Header */}
        <header className="space-y-6">
           <div className="flex items-center gap-3">
              <span className="px-3 py-1 bg-cyan-500/10 border border-cyan-500/20 rounded-full text-[10px] font-bold font-space text-cyan-400 tracking-widest uppercase">
                 阶段 07 / 交付导出
              </span>
           </div>
           <div className="space-y-4 max-w-2xl">
              <h1 className="text-5xl font-bold font-space text-white tracking-tight">导出与交付</h1>
              <p className="text-slate-400 text-sm leading-relaxed">您的创作已完成。选择您偏好的分辨率并生成最终的高质量导出母版以供交付。</p>
           </div>
        </header>

        {/* Cinema Monitor */}
        <div className="glass-panel p-4 rounded-[32px] border-white/10 shadow-2xl bg-black/40 overflow-hidden group">
           <div className="aspect-video relative rounded-[24px] overflow-hidden bg-black">
              {latestExport?.storage_uri || timeline?.preview_uri ? (
                <video
                  src={latestExport?.storage_uri || timeline?.preview_uri || undefined}
                  className="w-full h-full object-contain"
                  controls
                  playsInline
                />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center text-center p-12 space-y-6">
                   <div className="w-20 h-20 rounded-full bg-white/5 border border-white/5 flex items-center justify-center">
                      <MonitorPlay size={40} className="text-slate-700" />
                   </div>
                   <div className="space-y-2">
                      <h4 className="text-lg font-bold text-slate-400">等待主合成完成</h4>
                      <p className="text-xs text-slate-600 max-w-xs leading-relaxed uppercase font-bold font-space tracking-widest">请先完成视频合成阶段，以生成主预览。</p>
                   </div>
                </div>
              )}
              
              <div className="absolute top-6 left-6 flex gap-3 pointer-events-none">
                 <div className="px-3 py-1 bg-black/60 backdrop-blur-md rounded-full text-[10px] font-bold font-space text-white uppercase tracking-widest flex items-center gap-2">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    主母版预览
                 </div>
              </div>
           </div>
        </div>

        {/* Controls Grid */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-8">
           
           {/* Resolution Select */}
           <div className="space-y-6">
              <h3 className="text-sm font-bold font-space tracking-widest text-slate-400 uppercase flex items-center gap-3">
                 <Settings size={16} className="text-cyan-400" />
                 分辨率设置
              </h3>
              <div className="grid grid-cols-1 gap-4">
                 {EXPORT_RESOLUTION_OPTIONS.map((option) => (
                   <button
                     key={option.value}
                     onClick={() => setSelectedResolution(option.value)}
                     className={cn(
                       "w-full p-6 rounded-2xl border text-left flex items-center justify-between transition-all group",
                       selectedResolution === option.value
                         ? "bg-cyan-500/10 border-cyan-500/30 text-white shadow-lg"
                         : "bg-white/5 border-white/5 text-slate-400 hover:bg-white/10"
                     )}
                   >
                     <div className="space-y-1">
                        <span className="text-lg font-bold block">{option.title}</span>
                        <span className="text-[10px] font-bold font-space uppercase tracking-widest text-slate-500">
                           {option.description}
                        </span>
                     </div>
                     <div className={cn("w-6 h-6 rounded-full border-2 flex items-center justify-center transition-all", 
                       selectedResolution === option.value ? "border-cyan-400 bg-cyan-400/20" : "border-slate-800")}>
                        {selectedResolution === option.value && <CheckCircle2 size={12} className="text-cyan-400" />}
                     </div>
                   </button>
                 ))}
              </div>
           </div>

           {/* Export Action */}
           <div className="space-y-6">
              <div className="space-y-6">
                 <div className="space-y-2">
                    <h3 className="text-xl font-bold font-space text-white">成品导出确认</h3>
                    <p className="text-sm text-slate-400 leading-relaxed">
                       导出会重新编码并生成指定分辨率的母版文件；2K/4K 会进行上采样编码，耗时与文件体积会明显增加。
                    </p>
                 </div>

                 <div className="flex gap-3 pt-6">
                    <button
                      onClick={() => handleExport(selectedResolution)}
                      disabled={exporting || !timeline?.preview_uri}
                      className="flex-1 h-14 bg-violet-500 hover:bg-violet-400 disabled:bg-slate-800 disabled:text-slate-500 text-slate-950 font-black font-space rounded-2xl flex items-center justify-center gap-2 transition-all uppercase tracking-widest text-xs"
                    >
                      {exporting ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
                      {latestExport ? '重新编码导出' : '开始编码导出'}
                    </button>
                    
                    <button
                      onClick={handleDownload}
                      disabled={!latestExport?.storage_uri || downloading}
                      className="h-14 px-8 bg-white/5 border border-white/10 text-white hover:bg-white/10 disabled:opacity-30 rounded-2xl flex items-center justify-center transition-all"
                      title="下载成品到本地"
                    >
                      {downloading ? <Loader2 size={18} className="animate-spin" /> : <Download size={18} />}
                    </button>
                 </div>
              </div>
           </div>
        </section>

        {/* Footer Next Steps */}
        <footer className="pt-12 border-t border-white/5 flex items-center justify-between">
           <div className="space-y-1">
              <p className="text-[10px] font-bold font-space text-slate-500 tracking-widest uppercase">最终状态</p>
              <h4 className="text-xl font-bold font-space text-white">{latestExport ? '已准备好分发' : '等待最终导出'}</h4>
           </div>
           <div className="flex items-center gap-4 text-xs font-bold font-space text-cyan-400 group cursor-pointer">
              <span>返回控制台首页</span>
              <ChevronRight size={16} className="group-hover:translate-x-1 transition-transform" />
           </div>
        </footer>
      </div>
    </div>
  );
};
