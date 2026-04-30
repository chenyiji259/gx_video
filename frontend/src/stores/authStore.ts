import { create } from 'zustand';
import api from '@/services/api';

interface User {
  id: string;
  username: string;
  status: string;
  credits: number;
  plan_type: string;
  created_at: string;
}

interface AuthState {
  token: string | null;
  user: User | null;
  isLoading: boolean;
  login: (token: string, user: User) => void;
  logout: () => void;
  fetchMe: () => Promise<void>;
  performLogin: (credentials: any) => Promise<boolean>;
  performRegister: (credentials: any) => Promise<boolean>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem('vidmuse_token'),
  user: null,
  isLoading: !!localStorage.getItem('vidmuse_token'),

  login: (token, user) => {
    localStorage.setItem('vidmuse_token', token);
    set({ token, user, isLoading: false });
  },

  logout: () => {
    localStorage.removeItem('vidmuse_token');
    set({ token: null, user: null, isLoading: false });
  },

  fetchMe: async () => {
    const { token } = get();
    if (!token) {
      set({ isLoading: false });
      return;
    }
    try {
      // Base URL already includes /api/v1
      const res = await api.get('/users/me');
      if (res.data.success) {
        set({ user: res.data.data, isLoading: false });
      } else {
        get().logout();
      }
    } catch (err) {
      console.error('Failed to fetch user me', err);
      get().logout();
    }
  },

  performLogin: async (credentials: any) => {
    try {
      const res = await api.post('/auth/login', credentials);
      if (res.data.success) {
        get().login(res.data.data.access_token, res.data.data.user);
        return true;
      }
      return false;
    } catch (err) {
      return false;
    }
  },

  performRegister: async (credentials: any) => {
    try {
      const res = await api.post('/auth/register', credentials);
      if (res.data.success) {
        get().login(res.data.data.access_token, res.data.data.user);
        return true;
      }
      return false;
    } catch (err) {
      return false;
    }
  },
}));
