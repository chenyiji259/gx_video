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
  AssetRecord,
} from './types';

const API_BASE_URL = '/api/v1';
const AUTH_TOKEN_KEY = 'guangxi_token';
const REFRESH_TOKEN_KEY = 'guangxi_refresh_token';
const LEGACY_AUTH_TOKEN_KEY = 'vidmuse_token';
export const AUTH_EXPIRED_EVENT = 'guangxi_auth_expired';
export const AUTH_TOKEN_REFRESHED_EVENT = 'guangxi_auth_token_refreshed';

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

const getRefreshToken = () => localStorage.getItem(REFRESH_TOKEN_KEY);

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

export const setToken = (token: string, refreshToken?: string) => {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
  if (refreshToken) {
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  }
  localStorage.removeItem(LEGACY_AUTH_TOKEN_KEY);
};

export const clearToken = () => {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(LEGACY_AUTH_TOKEN_KEY);
};

const notifyAuthExpired = () => {
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
};

const notifyTokenRefreshed = () => {
  window.dispatchEvent(new CustomEvent(AUTH_TOKEN_REFRESHED_EVENT));
};

const isAuthRequest = (path: string) => path === '/auth/login' || path === '/auth/refresh';

let refreshPromise: Promise<string | null> | null = null;

const refreshAccessToken = async (): Promise<string | null> => {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;

  if (!refreshPromise) {
    refreshPromise = (async () => {
      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      const payload = await parseJsonResponse(response);

      if (!response.ok || !payload || !('success' in payload) || !payload.success) {
        return null;
      }

      const data = payload.data as { access_token?: string };
      if (!data.access_token) return null;

      setToken(data.access_token);
      notifyTokenRefreshed();
      return data.access_token;
    })().finally(() => {
      refreshPromise = null;
    });
  }

  return refreshPromise;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers = new Headers(init?.headers ?? {});

  if (!headers.has('Content-Type') && init?.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (response.status === 401 && !isAuthRequest(path)) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      headers.set('Authorization', `Bearer ${newToken}`);
      response = await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers,
      });
    } else {
      clearToken();
      notifyAuthExpired();
    }
  }

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

async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  const token = getToken();
  const headers = new Headers(init?.headers ?? {});

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (response.status === 401 && !isAuthRequest(path)) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      headers.set('Authorization', `Bearer ${newToken}`);
      response = await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers,
      });
    } else {
      clearToken();
      notifyAuthExpired();
    }
  }

  if (!response.ok) {
    const payload = await parseJsonResponse(response);
    const detail = extractDetail(payload?.detail);
    const envelopeError = payload && 'error' in payload ? payload.error : undefined;
    const message = detail?.message || envelopeError?.message || `Request failed: ${response.status}`;
    const code = detail?.code || envelopeError?.code;
    throw new ApiError(message, response.status, code);
  }

  return response.blob();
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
      product_reference_asset_ids?: string[];
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

  downloadLatestExport(projectId: string): Promise<Blob> {
    return requestBlob(`/projects/${projectId}/exports/latest/download`);
  },

  listDecisions(projectId: string): Promise<{ items: PendingDecision[]; total: number }> {
    return request(`/projects/${projectId}/decisions`);
  },

  selectDecision(
    projectId: string,
    decisionId: string,
    selectedOptionId: string,
    feedbackText?: string
  ): Promise<PendingDecision> {
    return request(`/projects/${projectId}/decisions/${decisionId}/select`, {
      method: 'POST',
      body: JSON.stringify({
        selected_option_id: selectedOptionId,
        feedback_text: feedbackText,
      }),
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

export const assetApi = {
  initUpload(
    projectId: string,
    payload: { filename: string; content_type: string; asset_type?: string }
  ): Promise<{
    asset_id: string;
    upload_url: string;
    object_key: string;
    bucket_name: string;
    expires_in: number;
  }> {
    return request(`/projects/${projectId}/assets/upload-init`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  completeUpload(
    projectId: string,
    payload: {
      asset_id: string;
      object_key: string;
      bucket_name: string;
      filename: string;
      content_type: string;
      asset_type: string;
      width?: number;
      height?: number;
    }
  ): Promise<AssetRecord> {
    return request(`/projects/${projectId}/assets/complete`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  uploadFile(
    projectId: string,
    payload: { file: File; asset_type?: string; width?: number; height?: number }
  ): Promise<AssetRecord> {
    const formData = new FormData();
    formData.set('file', payload.file);
    if (payload.asset_type) formData.set('asset_type', payload.asset_type);
    if (payload.width) formData.set('width', String(payload.width));
    if (payload.height) formData.set('height', String(payload.height));
    return request(`/projects/${projectId}/assets/upload-file`, {
      method: 'POST',
      body: formData,
    });
  },

  listAssets(
    projectId: string,
    params: { asset_type?: string; limit?: number } = {}
  ): Promise<{ items: AssetRecord[]; count: number }> {
    const query = new URLSearchParams();
    if (params.asset_type) query.set('asset_type', params.asset_type);
    if (params.limit) query.set('limit', String(params.limit));
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return request(`/projects/${projectId}/assets${suffix}`);
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
