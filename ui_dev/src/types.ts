export type ViewState = 'login' | 'projects' | 'workspace';

export interface User {
  id: string;
  username: string;
  status: string;
  credits: number;
  plan_type: string;
  created_at: string;
}

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
  current_stage: string;
  progress_percentage: number;
  cover_url: string | null;
  active_versions: ProjectActiveVersions;
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProjectSpec {
  id: string;
  user_prompt: string;
  output_config?: {
    platform?: string;
    aspect_ratio?: string;
    target_audience?: string;
    style_preference?: string;
    human_on_camera?: boolean;
    target_duration_sec?: number;
  } | null;
}

export interface CreativeBrief {
  id: string;
  title: string;
  summary: string;
  style_direction?: string | null;
  mood_tags?: string[] | null;
  raw_payload?: Record<string, unknown> | null;
}

export interface StyleBible {
  id: string;
  palette?: Record<string, unknown> | null;
  lighting_style?: string | null;
  camera_style?: string | null;
  film_texture?: string | null;
  reference_notes?: string | null;
}

export interface NarrativeShot {
  shot_index?: number;
  start_ms?: number;
  end_ms?: number;
  duration_sec?: number;
  duration_ms?: number;
  subject?: string | null;
  location?: string | null;
  dialogue?: string | null;
  lyric_text?: string | null;
  scene_description?: string | null;
  visual_description?: string | null;
  action_description?: string | null;
  start_frame_description?: string | null;
  middle_frame_description?: string | null;
  end_frame_description?: string | null;
  camera_language?: string | null;
}

export interface NarrativeScript {
  id: string;
  version_no: number;
  story_arc?: string | null;
  characters?: Record<string, unknown>[] | null;
  scenes?: Record<string, unknown>[] | null;
  section_mapping?: Record<string, unknown>[] | null;
  raw_payload?: {
    shots?: NarrativeShot[];
    story_arc?: string;
    [key: string]: unknown;
  } | null;
}

export interface Shot {
  id: string;
  shot_index: number;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  subject?: string | null;
  location?: string | null;
  dialogue?: string | null;
  lyric_text?: string | null;
  camera_language?: string | null;
  status?: string | null;
  last_failure?: {
    code?: string | null;
    message?: string | null;
    provider?: string | null;
    event_id?: string | null;
    created_at?: string | null;
  } | null;
}

export interface StoryboardCell {
  cell_position: number;
  asset_id: string;
  asset_url?: string | null;
  shot_id?: string | null;
  shot_index?: number | null;
  frame_description?: string;
  scene_description?: string;
  is_reused_from_prev_grid?: boolean;
}

export interface StoryboardGrid {
  grid_index: number;
  parent_asset_id?: string | null;
  parent_asset_url?: string | null;
  bundle_id?: string | null;
  cells: StoryboardCell[];
}

export interface Clip {
  id: string;
  shot_id: string;
  version_no: number;
  asset_id: string;
  storage_uri: string;
  duration_ms?: number | null;
  status: string;
  created_at?: string | null;
}

export interface TimelineSegment {
  id: string;
  shot_id: string;
  clip_version_id: string;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
}

export interface Timeline {
  version_id: string;
  version_no: number;
  render_status: string;
  total_duration_ms?: number | null;
  segment_count?: number | null;
  preview_uri?: string | null;
}

export interface ExportRecord {
  export_version_id: string;
  timeline_version_id?: string | null;
  asset_id: string;
  storage_uri: string;
  resolution: string;
  status: string;
  created_at?: string | null;
}

export interface PendingDecisionOption {
  id: string;
  title?: string;
  label?: string;
  summary?: string;
}

export interface PendingDecision {
  id: string;
  decision_type: string;
  target_entity_type?: string | null;
  target_entity_id?: string | null;
  options_payload?: PendingDecisionOption[] | null;
  default_option_id?: string | null;
  selected_option_id?: string | null;
  status: string;
  created_at?: string | null;
}

export interface WorkspaceData {
  project: Project;
  spec: ProjectSpec | null;
  brief: CreativeBrief | null;
  style: StyleBible | null;
  narrative: NarrativeScript | null;
  shots: Shot[];
  storyboardGrids: StoryboardGrid[];
  clips: Clip[];
  timeline: Timeline | null;
  timelineSegments: TimelineSegment[];
  latestExport: ExportRecord | null;
  decisions: PendingDecision[];
}
