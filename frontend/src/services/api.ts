import { Project, Asset, AudioAnalysis, Decision } from '@/types';
import { buildChatCompletionPayload, CHAT_COMPLETIONS_PATH } from '@/services/chatCompletions';
import { apiClient as api, openAIClient } from '@/services/http';

export const authService = {
  login: async (credentials: any) => {
    const response = await api.post('/auth/login', credentials);
    return response.data;
  },
  register: async (credentials: any) => {
    const response = await api.post('/auth/register', credentials);
    return response.data;
  },
};

export const projectService = {
  getProjects: async (params?: { limit?: number; after?: string; include_archived?: boolean }) => {
    const response = await api.get('/projects', { params });
    return response.data;
  },

  createProject: async (name: string) => {
    const response = await api.post('/projects', { name });
    return response.data;
  },

  getProject: async (id: string) => {
    const response = await api.get(`/projects/${id}`);
    return response.data;
  },

  updateProject: async (projectId: string, data: { name?: string; archived?: boolean }) => {
    const response = await api.patch(`/projects/${projectId}`, data);
    return response.data;
  },

  deleteProject: async (projectId: string) => {
    const response = await api.delete(`/projects/${projectId}`);
    return response.data;
  },

  getProjectAssets: async (id: string, params?: { asset_type?: string; limit?: number }) => {
    const response = await api.get(`/projects/${id}/assets`, { params });
    return response.data;
  },

  getAudioAnalysis: async (id: string) => {
    const response = await api.get(`/projects/${id}/audio-analysis/active`);
    return response.data;
  },

  getBrief: async (id: string) => {
    const response = await api.get(`/projects/${id}/brief/active`);
    return response.data;
  },

  getStyle: async (id: string) => {
    const response = await api.get(`/projects/${id}/style/active`);
    return response.data;
  },

  getNarrative: async (id: string) => {
    const response = await api.get(`/projects/${id}/narrative/active`);
    return response.data;
  },

  getVisualBible: async (id: string) => {
    const response = await api.get(`/projects/${id}/visual-bible/active`);
    return response.data;
  },

  generateCharacterRef: async (projectId: string, characterId: string) => {
    const response = await api.post(`/projects/${projectId}/visual-bible/generate-character-ref`, {
      character_id: characterId,
    });
    return response.data;
  },

  generateSceneRef: async (projectId: string, sceneId: string) => {
    const response = await api.post(`/projects/${projectId}/visual-bible/generate-scene-ref`, {
      scene_id: sceneId,
    });
    return response.data;
  },

  getDecisions: async (id: string) => {
    const response = await api.get(`/projects/${id}/decisions`);
    return response.data;
  },

  makeDecision: async (projectId: string, decisionId: string, optionId: string) => {
    const response = await api.post(`/projects/${projectId}/decisions/${decisionId}/select`, {
      selected_option_id: optionId,
    });
    return response.data;
  },

  getShots: async (projectId: string) => {
    const response = await api.get(`/projects/${projectId}/shots`);
    return response.data;
  },

  getStoryboard: async (projectId: string) => {
    const response = await api.get(`/projects/${projectId}/storyboard/active`);
    return response.data;
  },

  getStoryboardFrames: async (projectId: string) => {
    const response = await api.get(`/projects/${projectId}/storyboard-frames`);
    return response.data;
  },

  // doc 21 §6.3：九宫格架构新接口
  // 返回所有九宫格大图 + 9×N 切分图 URL，前端按 grid_index 增量渲染
  getStoryboardGrids: async (projectId: string) => {
    const response = await api.get(`/projects/${projectId}/storyboard/grids`);
    return response.data;
  },

  getClips: async (projectId: string) => {
    const response = await api.get(`/projects/${projectId}/clips`);
    return response.data;
  },

  getTimeline: async (projectId: string) => {
    const response = await api.get(`/projects/${projectId}/timeline/active`);
    return response.data;
  },

  getTimelineSegments: async (projectId: string) => {
    const response = await api.get(`/projects/${projectId}/timeline/segments`);
    return response.data;
  },
};

export const chatService = {
  getSessions: async (projectId: string) => {
    const response = await api.get(`/projects/${projectId}/sessions`);
    return response.data;
  },

  sendMessage: async (projectId: string, message: string, sessionId?: string) => {
    const response = await openAIClient.post(
      CHAT_COMPLETIONS_PATH,
      buildChatCompletionPayload(projectId, message, false, sessionId)
    );
    return response.data;
  },
  
  getSessionMessages: async (projectId: string, sessionId: string) => {
    const response = await api.get(`/projects/${projectId}/sessions/${sessionId}/messages`);
    return response.data;
  }
};

export const assetService = {
  getGlobalAssets: async (params?: { asset_type?: string; limit?: number }) => {
    const response = await api.get('/assets', { params });
    return response.data;
  },

  initUpload: async (projectId: string, data: { filename: string; content_type: string; asset_type?: string }) => {
    const response = await api.post(`/projects/${projectId}/assets/upload-init`, data);
    return response.data;
  },
  
  uploadToMinio: async (uploadUrl: string, file: File) => {
    const response = await fetch(uploadUrl, {
      method: 'PUT',
      body: file,
      headers: {
        'Content-Type': file.type,
      },
    });
    if (!response.ok) {
      throw new Error(`Failed to upload to MinIO: ${response.statusText}`);
    }
    return true;
  },

  completeUpload: async (projectId: string, data: any) => {
    const response = await api.post(`/projects/${projectId}/assets/complete`, data);
    return response.data;
  },

  uploadAsset: async (projectId: string, file: File, assetType?: string) => {
    const initRes = await assetService.initUpload(projectId, {
      filename: file.name,
      content_type: file.type,
      asset_type: assetType,
    });

    if (!initRes.success) throw new Error('Failed to init upload');
    const { asset_id, object_key, bucket_name, upload_url } = initRes.data;

    await assetService.uploadToMinio(upload_url, file);

    const completeRes = await assetService.completeUpload(projectId, {
      asset_id,
      object_key,
      bucket_name,
      filename: file.name,
      content_type: file.type,
      asset_type: assetType,
    });

    return completeRes;
  }
};

export const dashboardService = {
  getOverview: async () => {
    const response = await api.get('/dashboard/overview');
    return response.data;
  },
};

export const workflowService = {
  // 旧流程（音乐MV模式）：已停用
  // analyzeAudio: (projectId: string) => api.post(`/projects/${projectId}/workflow/analyze-audio`),
  generateBrief: async (projectId: string) => {
    const response = await api.post(`/projects/${projectId}/workflow/generate-brief`);
    return response.data;
  },
  generateNarrative: async (projectId: string) => {
    const response = await api.post(`/projects/${projectId}/workflow/generate-narrative`);
    return response.data;
  },
  generateShotPlan: async (projectId: string) => {
    const response = await api.post(`/projects/${projectId}/workflow/generate-shot-plan`);
    return response.data;
  },
  generateStoryboard: async (projectId: string) => {
    const response = await api.post(`/projects/${projectId}/workflow/generate-storyboard`);
    return response.data;
  },
  generateClips: async (projectId: string) => {
    const response = await api.post(`/projects/${projectId}/workflow/generate-clips`);
    return response.data;
  },
  // /timeline/compose 为异步 dispatch ToolJob 路由（正确）
  // /workflow/generate-timeline 为同步阻塞路由（错误）
  composeTimeline: async (projectId: string) => {
    const response = await api.post(`/projects/${projectId}/timeline/compose`);
    return response.data;
  }
};

export const projectSpecService = {
  recommendDuration: async (projectId: string, data: {
    user_prompt?: string;
    platform?: string;
    target_audience?: string;
    style_preference?: string;
    human_on_camera?: boolean;
  }) => {
    const response = await api.post(`/projects/${projectId}/spec/recommend-duration`, data);
    return response.data;
  },
  createVersion: async (projectId: string, data: {
    audio_asset_id?: string;
    user_prompt?: string;
    audio_start_sec?: number;
    audio_end_sec?: number;
    reference_image_asset_ids?: string[];
    // 新流程：视频需求字段
    platform?: string;
    target_audience?: string;
    style_preference?: string;
    human_on_camera?: boolean;
    target_duration_sec?: number;
    aspect_ratio?: string;
  }) => {
    const response = await api.post(`/projects/${projectId}/spec/versions`, data);
    return response.data;
  },
  activate: async (projectId: string, versionId: string) => {
    const response = await api.post(`/projects/${projectId}/spec/activate`, { version_id: versionId });
    return response.data;
  },
  getActive: async (projectId: string) => {
    const response = await api.get(`/projects/${projectId}/spec/active`);
    return response.data;
  },
};

export const shotService = {
  regenerate: async (projectId: string, shotId: string) => {
    const response = await api.post(`/projects/${projectId}/shots/${shotId}/regenerate`);
    return response.data;
  },
};

export const exportService = {
  triggerExport: async (projectId: string, resolution: '720p' | '1080p' | '2K' | '4K') => {
    const response = await api.post(`/projects/${projectId}/exports`, { resolution });
    return response.data;
  },
  getLatestExport: async (projectId: string) => {
    const response = await api.get(`/projects/${projectId}/exports/latest`);
    return response.data;
  },
};

export default api;
