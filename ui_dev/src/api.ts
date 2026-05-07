import type {
  Clip,
  CreativeBrief,
  ExportRecord,
  NarrativeScript,
  Project,
  ProjectSpec,
  PendingDecision,
  Shot,
  StoryboardGrid,
  StyleBible,
  Timeline,
  TimelineSegment,
  User,
} from './types';

const API_BASE_URL = '/api/v1';
const AUTH_TOKEN_KEY = 'guangxi_token';
const LEGACY_AUTH_TOKEN_KEY = 'vidmuse_token';

type ApiEnvelope<T> = {
  success: boolean;
  data: T;
  request_id?: string;
  error?: {
    code?: string;
    message?: string;
  };
};

type ApiErrorPayload = Partial<ApiEnvelope<unknown>> & {
  detail?: { code?: string; message?: string } | string | unknown;
};

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

const getToken = () => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) return token;

  const legacyToken = localStorage.getItem(LEGACY_AUTH_TOKEN_KEY);
  if (legacyToken) {
    localStorage.setItem(AUTH_TOKEN_KEY, legacyToken);
    localStorage.removeItem(LEGACY_AUTH_TOKEN_KEY);
  }
  return legacyToken;
};

const parseJsonResponse = async (response: Response): Promise<ApiErrorPayload | undefined> => {
  const rawBody = await response.text();
  if (!rawBody.trim()) {
    return undefined;
  }

  try {
    return JSON.parse(rawBody) as ApiErrorPayload;
  } catch {
    const message = response.ok
      ? '后端返回了无效的 JSON 响应'
      : `请求失败: ${response.status}`;
    throw new ApiError(message, response.status, 'invalid_json_response');
  }
};

const extractDetail = (detail: ApiErrorPayload['detail']) => {
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    return detail as { code?: string; message?: string };
  }
  if (typeof detail === 'string') {
    return { message: detail };
  }
  return undefined;
};

export const getProjectEventsStreamUrl = (projectId: string) => {
  const token = getToken();
  const query = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${API_BASE_URL}/projects/${encodeURIComponent(projectId)}/events/stream${query}`;
};

export const setToken = (token: string) => {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
  localStorage.removeItem(LEGACY_AUTH_TOKEN_KEY);
};

export const clearToken = () => {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(LEGACY_AUTH_TOKEN_KEY);
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(init?.headers ?? {});

  if (!headers.has('Content-Type') && init?.body) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  const payload = await parseJsonResponse(response);

  if (!response.ok) {
    const detail = extractDetail(payload?.detail);
    const envelopeError = payload && 'error' in payload ? payload.error : undefined;
    const message = detail?.message || envelopeError?.message || `Request failed: ${response.status}`;
    const code = detail?.code || envelopeError?.code;
    throw new ApiError(message, response.status, code);
  }

  if (!payload || !('success' in payload) || !payload.success) {
    const message = payload?.error?.message || '后端返回了空响应或不符合 API 契约';
    const code = payload?.error?.code || 'invalid_api_response';
    throw new ApiError(message, response.status, code);
  }

  return payload.data as T;
}

export const isNotFoundError = (error: unknown) =>
  error instanceof ApiError && error.status === 404;

export const authApi = {
  async login(username: string, password: string): Promise<{
    access_token: string;
    refresh_token: string;
    token_type: string;
    user: User;
  }> {
    return request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  },

  async getMe(): Promise<User> {
    return request('/users/me');
  },
};

export const projectApi = {
  listProjects(): Promise<{ items: Project[] }> {
    return request('/projects');
  },

  createProject(name: string): Promise<Project> {
    return request('/projects', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  },

  deleteProject(projectId: string): Promise<{ id: string }> {
    return request(`/projects/${projectId}`, {
      method: 'DELETE',
    });
  },

  getProject(projectId: string): Promise<Project> {
    return request(`/projects/${projectId}`);
  },

  getActiveSpec(projectId: string): Promise<ProjectSpec> {
    return request(`/projects/${projectId}/spec/active`);
  },

  createSpecVersion(
    projectId: string,
    payload: {
      user_prompt: string;
      platform?: string;
      target_audience?: string;
      style_preference?: string;
      human_on_camera?: boolean;
      target_duration_sec?: number;
      aspect_ratio?: string;
      video_resolution?: '480p' | '720p' | '1080p';
      image_resolution?: '2K';
      generation_profile?: string;
      storyboard_layout?: string;
      segment_duration_sec?: number;
      story_board_aspect_ratio?: string;
      style_preset_locked?: boolean;
      subtitles_enabled?: boolean;
    }
  ): Promise<{ id: string }> {
    return request(`/projects/${projectId}/spec/versions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  activateSpec(projectId: string, versionId: string): Promise<ProjectSpec> {
    return request(`/projects/${projectId}/spec/activate`, {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId }),
    });
  },

  getBrief(projectId: string): Promise<CreativeBrief> {
    return request(`/projects/${projectId}/brief/active`);
  },

  getStyle(projectId: string): Promise<StyleBible> {
    return request(`/projects/${projectId}/style/active`);
  },

  getNarrative(projectId: string): Promise<NarrativeScript> {
    return request(`/projects/${projectId}/narrative/active`);
  },

  getShots(projectId: string): Promise<{ items: Shot[] }> {
    return request(`/projects/${projectId}/shots`);
  },

  getStoryboardGrids(projectId: string): Promise<{ grids: StoryboardGrid[] }> {
    return request(`/projects/${projectId}/storyboard/grids`);
  },

  getClips(projectId: string): Promise<{ clips: Clip[]; count: number }> {
    return request(`/projects/${projectId}/clips`);
  },

  getTimeline(projectId: string): Promise<Timeline> {
    return request(`/projects/${projectId}/timeline/active`);
  },

  getTimelineSegments(projectId: string): Promise<{ segments: TimelineSegment[] }> {
    return request(`/projects/${projectId}/timeline/segments`);
  },

  getLatestExport(projectId: string): Promise<ExportRecord> {
    return request(`/projects/${projectId}/exports/latest`);
  },

  listDecisions(projectId: string): Promise<{ items: PendingDecision[]; total: number }> {
    return request(`/projects/${projectId}/decisions`);
  },

  selectDecision(
    projectId: string,
    decisionId: string,
    selectedOptionId: string
  ): Promise<PendingDecision> {
    return request(`/projects/${projectId}/decisions/${decisionId}/select`, {
      method: 'POST',
      body: JSON.stringify({ selected_option_id: selectedOptionId }),
    });
  },

  regenerateShot(projectId: string, shotId: string): Promise<Clip> {
    return request(`/projects/${projectId}/shots/${shotId}/regenerate`, {
      method: 'POST',
      headers: {
        'X-Idempotency-Key': `${projectId}-${shotId}-${Date.now()}`,
      },
    });
  },
};

export const workflowApi = {
  generateCreativePackage(projectId: string) {
    return request(`/projects/${projectId}/workflow/generate-creative-package`, { method: 'POST' });
  },

  generateBrief(projectId: string) {
    return request(`/projects/${projectId}/workflow/generate-brief`, { method: 'POST' });
  },

  generateNarrative(projectId: string) {
    return request(`/projects/${projectId}/workflow/generate-narrative`, { method: 'POST' });
  },

  generateShotPlan(projectId: string) {
    return request(`/projects/${projectId}/workflow/generate-shot-plan`, { method: 'POST' });
  },

  generateStoryboard(projectId: string) {
    return request(`/projects/${projectId}/workflow/generate-storyboard`, { method: 'POST' });
  },

  generateClips(projectId: string) {
    return request(`/projects/${projectId}/workflow/generate-clips`, { method: 'POST' });
  },

  composeTimeline(projectId: string) {
    return request(`/projects/${projectId}/timeline/compose`, { method: 'POST' });
  },

  triggerExport(
    projectId: string,
    resolution: '720p' | '1080p' | '2K' | '4K' = '1080p'
  ): Promise<ExportRecord & { message?: string }> {
    return request(`/projects/${projectId}/exports`, {
      method: 'POST',
      body: JSON.stringify({ resolution }),
    });
  },
};
