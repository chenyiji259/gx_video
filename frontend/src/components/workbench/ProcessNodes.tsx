import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Settings,
  Lightbulb,
  ScrollText,
  Grid3x3,
  Video,
  Clapperboard,
  Download,
  CheckCircle2
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface ProcessNodesProps {
  project: any;
  viewStage?: string;
  onViewStageChange?: (stage: string) => void;
  minimal?: boolean;
}

const STAGES = [
  { id: 'setup', backendStages: ['created', 'input_ready'], label: '项目设置', icon: Settings },
  { id: 'brief', backendStages: ['brief_ready'], label: '创意设计', icon: Lightbulb },
  { id: 'narrative', backendStages: ['narrative_ready', 'visual_bible_ready'], label: '叙事剧本', icon: ScrollText },
  { id: 'storyboard', backendStages: ['shot_plan_ready', 'storyboard_ready'], label: '九宫格分镜', icon: Grid3x3 },
  { id: 'clips_generating', backendStages: ['clips_generating', 'clips_ready'], label: '视频生成', icon: Video },
  { id: 'composition', backendStages: ['video_composition', 'timeline_ready'], label: '视频合成', icon: Clapperboard },
  { id: 'export', backendStages: ['export_ready', 'completed'], label: '视频导出', icon: Download }
];

export const ProcessNodes: React.FC<ProcessNodesProps> = ({ project, viewStage, onViewStageChange, minimal = false }) => {
  const { t } = useTranslation();
  const currentBackendStage = project?.current_stage || 'created';
  const activeBackendStage = viewStage || currentBackendStage;
  const normalizedCurrentStage = currentBackendStage === 'timeline_ready' ? 'video_composition' : currentBackendStage;
  const normalizedViewStage = activeBackendStage === 'timeline_ready' ? 'video_composition' : activeBackendStage;
  
  // Find indices based on backend stages
  const rawCurrentIndex = STAGES.findIndex(s => s.backendStages.includes(normalizedCurrentStage));
  // 'failed' 等未映射阶段：所有已有步骤可点击（不锁定），不标记任何步骤为活跃
  const currentIndex = rawCurrentIndex >= 0 ? rawCurrentIndex : STAGES.length;
  const viewIndex = STAGES.findIndex(s => s.backendStages.includes(normalizedViewStage));
  
  return (
    <div className="flex flex-col gap-2">
      {STAGES.map((stage, index) => {
        const isActive = index === viewIndex;
        const isLocked = index > currentIndex + 1;
        const isCompleted = index < currentIndex;
        const Icon = stage.icon;

        return (
          <div key={stage.id} className="relative w-full">
            <button
              disabled={isLocked}
              title={minimal ? stage.label : undefined}
              onClick={() => {
                if (onViewStageChange && !isLocked) {
                  const targetStage =
                    stage.id === 'composition'
                      ? 'video_composition'
                      : index === currentIndex
                      ? currentBackendStage
                      : stage.backendStages[stage.backendStages.length - 1];
                  onViewStageChange(targetStage);
                }
              }}
              className={cn(
                "w-full flex items-center transition-all duration-300 relative text-sm",
                minimal ? "justify-center px-0 py-4" : "px-6 py-3 gap-4",
                isActive ? "bg-cyan-500/10 text-cyan-400" : "text-slate-400 hover:bg-white/5 hover:text-slate-200",
                isLocked ? "opacity-30 cursor-not-allowed" : "cursor-pointer"
              )}
            >
              {/* Active Left Border */}
              {isActive && (
                <div className="absolute left-0 top-0 h-full w-1 bg-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.4)]" />
              )}

              <div className={cn(
                "flex items-center justify-center transition-all duration-300",
                isCompleted ? "text-emerald-400" : isActive ? "text-cyan-400 scale-110" : "text-slate-500"
              )}>
                {isCompleted ? <CheckCircle2 size={18} strokeWidth={2} /> : <Icon size={18} strokeWidth={2} />}
              </div>

              {!minimal && (
                <div className="flex-1 text-left min-w-0">
                  <span className={cn(
                    "font-bold tracking-tight transition-colors duration-300 truncate block",
                    isCompleted ? "text-emerald-400/80" : isActive ? "text-white" : "text-slate-400"
                  )}>
                    {stage.label}
                  </span>
                  {isActive && currentBackendStage === 'shot_plan_ready' && stage.id === 'storyboard' && (
                    <div className="mt-0.5 text-[8px] font-bold uppercase tracking-[0.1em] text-slate-500 animate-pulse">
                      生成中...
                    </div>
                  )}
                </div>
              )}
            </button>
          </div>
        );
      })}
    </div>
  );
};
