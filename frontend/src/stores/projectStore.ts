import { create } from 'zustand';
import { Project, Decision, ProjectStage } from '@/types';

interface ProjectState {
  project: Project | null;
  currentStage: string;
  productionViewStage: 'idle' | 'clips_generating';
  shotRunStates: Record<string, 'waiting' | 'submitted' | 'running' | 'completed' | 'failed'>;
  failedStageAction: string | null;
  failedStageMessage: string | null;
  pendingDecisions: Decision[];
  setProject: (project: Project | null) => void;
  setCurrentStage: (stage: string) => void;
  setProductionViewStage: (stage: 'idle' | 'clips_generating') => void;
  hydrateProductionViewStage: (projectId?: string) => void;
  setShotRunState: (shotId: string, state: 'waiting' | 'submitted' | 'running' | 'completed' | 'failed') => void;
  resetShotRunStates: () => void;
  setFailedStageInfo: (action: string | null, message?: string | null) => void;
  setPendingDecisions: (decisions: Decision[] | ((current: Decision[]) => Decision[])) => void;
  refreshFlag: number;
  triggerRefresh: () => void;
  clipRefreshFlag: number;
  triggerClipRefresh: () => void;
  isGenerating: boolean;
  setIsGenerating: (isGenerating: boolean) => void;
  generatingMessage: string | null;
  setGeneratingMessage: (msg: string | null) => void;
  generationProgress: number;
  setGenerationProgress: (progress: number) => void;
  latestDirectorMessage: any | null;
  setLatestDirectorMessage: (msg: any | null) => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  project: null,
  currentStage: 'created',
  productionViewStage: 'idle',
  shotRunStates: {},
  failedStageAction: null,
  failedStageMessage: null,
  pendingDecisions: [],
  setProject: (project) => set((state) => ({
    project,
    currentStage: project ? project.current_stage : 'created',
    productionViewStage:
      !project ||
      project.current_stage === 'created' ||
      project.current_stage === 'input_ready' ||
      project.current_stage === 'brief_ready' ||
      project.current_stage === 'narrative_ready' ||
      project.current_stage === 'visual_bible_ready' ||
      project.current_stage === 'shot_plan_ready' ||
      project?.current_stage === 'clips_ready' ||
      project?.current_stage === 'timeline_ready' ||
      project?.current_stage === 'export_ready' ||
      project?.current_stage === 'completed'
        ? 'idle'
        : state.productionViewStage,
  })),
  setCurrentStage: (stage) => set((state) => ({
    currentStage: stage,
    project: state.project ? { ...state.project, current_stage: stage as ProjectStage } : null,
  })),
  setProductionViewStage: (productionViewStage) => {
    if (typeof window !== 'undefined') {
      window.sessionStorage.setItem('vidmuse_production_view_stage', productionViewStage);
    }
    set({ productionViewStage });
  },
  hydrateProductionViewStage: (projectId) => set((state) => {
    if (!projectId || state.project?.id !== projectId) {
      return { productionViewStage: 'idle' };
    }
    const stored =
      typeof window !== 'undefined'
        ? (window.sessionStorage.getItem('vidmuse_production_view_stage') as 'idle' | 'clips_generating' | null)
        : null;
    return { productionViewStage: stored || 'idle' };
  }),
  setShotRunState: (shotId, shotState) =>
    set((state) => ({
      shotRunStates: {
        ...state.shotRunStates,
        [shotId]: shotState,
      },
    })),
  resetShotRunStates: () => set({ shotRunStates: {} }),
  setFailedStageInfo: (failedStageAction, failedStageMessage = null) =>
    set({ failedStageAction, failedStageMessage }),
  setPendingDecisions: (decisions) =>
    set((state) => ({
      pendingDecisions: typeof decisions === 'function' ? decisions(state.pendingDecisions) : decisions,
    })),
  refreshFlag: 0,
  triggerRefresh: () => set((state) => ({ refreshFlag: state.refreshFlag + 1 })),
  clipRefreshFlag: 0,
  triggerClipRefresh: () => set((state) => ({ clipRefreshFlag: state.clipRefreshFlag + 1 })),
  isGenerating: false,
  setIsGenerating: (isGenerating) => set({ isGenerating }),
  generatingMessage: null,
  setGeneratingMessage: (generatingMessage) => set({ generatingMessage }),
  generationProgress: 0,
  setGenerationProgress: (generationProgress) => set({ generationProgress }),
  latestDirectorMessage: null,
  setLatestDirectorMessage: (latestDirectorMessage) => set({ latestDirectorMessage }),
}));
