export type ClipItem = {
  id: string;
  shot_id: string;
  storage_uri: string | null;
  duration_ms: number;
  start_ms: number;
  version_no?: number;
  status?: string;
};

export type ShotItem = {
  id: string;
  shot_index: number;
  start_ms?: number;
  end_ms?: number;
  duration_ms?: number;
  subject?: string | null;
  location?: string | null;
  emotion?: string | null;
  camera_language?: string | null;
  status?: string | null;
};

export type GridCell = {
  shot_id?: string | null;
  shot_index?: number | null;
  cell_position: number;
  asset_url?: string | null;
  frame_description?: string;
};

export type GridItem = {
  grid_index: number;
  parent_asset_url?: string | null;
  cells: GridCell[];
};

export type TimelineSegment = {
  id: string;
  shot_id: string;
  clip_version_id: string;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  transition_in?: string | null;
  transition_out?: string | null;
};

export type TimelineData = {
  version_id: string;
  version_no: number;
  project_id: string;
  render_status: string;
  total_duration_ms: number;
  segment_count: number;
  preview_uri: string | null;
  is_active: boolean;
  created_at?: string | null;
};

export type ExportData = {
  export_version_id: string;
  timeline_version_id?: string;
  asset_id?: string;
  storage_uri: string | null;
  resolution: '720p' | '1080p' | '2K' | '4K';
  status: string;
  created_at?: string | null;
};

export type QueueShot = ShotItem & {
  clip?: ClipItem;
  firstFrame?: string | null;
  lastFrame?: string | null;
  gridIndex?: number;
  statusLabel: string;
};
