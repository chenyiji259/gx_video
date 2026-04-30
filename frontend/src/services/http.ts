import axios, { AxiosError, AxiosInstance } from 'axios';

const JSON_CONTENT_TYPE = 'application/json';
const AUTH_TOKEN_KEY = 'vidmuse_token';

export const API_BASE_URL = '/api/v1';
export const OPENAI_COMPAT_BASE_URL = '/v1';

export const getAuthToken = () => localStorage.getItem(AUTH_TOKEN_KEY);

export const clearAuthToken = () => {
  localStorage.removeItem(AUTH_TOKEN_KEY);
};

export const handleUnauthorized = () => {
  clearAuthToken();
  if (window.location.pathname !== '/auth') {
    window.location.href = '/auth';
  }
};

const attachInterceptors = (client: AxiosInstance) => {
  client.interceptors.request.use((config) => {
    const token = getAuthToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  client.interceptors.response.use(
    (response) => response,
    (error: AxiosError) => {
      if (error.response?.status === 401) {
        handleUnauthorized();
      }
      return Promise.reject(error);
    }
  );

  return client;
};

const createHttpClient = (baseURL: string) =>
  attachInterceptors(
    axios.create({
      baseURL,
      headers: {
        'Content-Type': JSON_CONTENT_TYPE,
      },
    })
  );

export const buildAuthHeaders = (headers: Record<string, string> = {}) => {
  const token = getAuthToken();

  return {
    'Content-Type': JSON_CONTENT_TYPE,
    ...headers,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
};

export const apiClient = createHttpClient(API_BASE_URL);
export const openAIClient = createHttpClient(OPENAI_COMPAT_BASE_URL);
