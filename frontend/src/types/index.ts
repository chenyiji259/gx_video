export type ProjectStage = 
  | 'created'
  | 'input_ready'
  | 'audio_analyzed'
  | 'brief_ready'
  | 'narrative_ready'
  | 'visual_bible_ready'
  | 'shot_plan_ready'
  | 'storyboard_ready'
  | 'clips_generating'
  | 'clips_ready'
  | 'video_composition'
  | 'timeline_ready'
  | 'export_ready'
  | 'completed'
  | 'failed';

export interface ProjectActiveVersions {
  project_spec: string | null;
  audio_analysis: string | null;
  creative_brief: string | null;
  style_bible: string | null;
  character_set: string | null;
  narrative_script: string | null;
  scene_plan: string | null;
  shot_plan: string | null;
  storyboard: string | null;
  timeline: string | null;
  latest_export: string | null;
}

export interface Project {
  id: string;
  name: string;
  status: 'active' | 'archived';
  current_stage: ProjectStage;
  progress_percentage: number;
  cover_url: string | null;
  active_versions: ProjectActiveVersions;
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface Asset {
  id: string;
  project_id: string;
  asset_type: string;
  filename: string;
  content_type: string;
  storage_uri: string;
  duration_ms?: number;
  width?: number;
  height?: number;
  created_at: string;
}

export interface AudioAnalysis {
  id: string;
  bpm: number;
  beat_map: number[];
  section_map: { start: number; end: number; label: string }[];
  energy_curve: number[];
  chord_progression?: { section: string; chords: string[] }[];
  instrumentation?: string[];
  five_second_analysis?: {
    start: number;
    end: number;
    energy: number;
    mood: string;
    instruments: string[];
  }[];
  quality_summary: {
    music_summary: string;
    visual_suggestion: string;
    music_structure_summary?: any;
    emotion_arc?: any;
    editing_guidance?: any;
  };
  lyrics_alignment: { time: number; text: string }[];
  key_scale?: string;
  genre?: string;
  audio_url?: string;
}

export interface Decision {
  id: string;
  decision_type: string;
  options_payload: { id: string; title: string; summary?: string }[]; 
  selected_option_id: string | null;
  status: 'open' | 'selected' | 'expired' | 'cancelled';
}
