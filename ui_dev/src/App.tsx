import React from 'react';
import { Workspace } from './components/Workspace';
import ProjectBoard from './components/ProjectBoard';
import Login from './components/Login';
import { ViewState } from './types';
import { useEffect, useState } from 'react';
import { AUTH_EXPIRED_EVENT, authApi, clearToken } from './api';

const AUTH_TOKEN_KEY = 'guangxi_token';
const LEGACY_AUTH_TOKEN_KEY = 'vidmuse_token';
const LAST_VIEW_KEY = 'guangxi_last_view';
const LAST_PROJECT_ID_KEY = 'guangxi_last_project_id';

const hasAuthToken = () =>
  Boolean(localStorage.getItem(AUTH_TOKEN_KEY) || localStorage.getItem(LEGACY_AUTH_TOKEN_KEY));

const readInitialView = (): ViewState => {
  if (!hasAuthToken()) return 'login';

  const lastView = localStorage.getItem(LAST_VIEW_KEY);
  const lastProjectId = localStorage.getItem(LAST_PROJECT_ID_KEY);
  return lastView === 'workspace' && lastProjectId ? 'workspace' : 'projects';
};

export default function App() {
  const [currentView, setCurrentView] = useState<ViewState>(readInitialView);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    () => localStorage.getItem(LAST_PROJECT_ID_KEY)
  );
  const [loginNotice, setLoginNotice] = useState<string | null>(null);

  const resetToLogin = (notice?: string) => {
    clearToken();
    localStorage.removeItem(LAST_VIEW_KEY);
    localStorage.removeItem(LAST_PROJECT_ID_KEY);
    setSelectedProjectId(null);
    setLoginNotice(notice ?? null);
    setCurrentView('login');
  };

  useEffect(() => {
    const bootstrap = async () => {
      if (!hasAuthToken()) {
        setCurrentView('login');
        setSelectedProjectId(null);
        return;
      }
      try {
        await authApi.getMe();
        const lastView = localStorage.getItem(LAST_VIEW_KEY);
        const lastProjectId = localStorage.getItem(LAST_PROJECT_ID_KEY);
        setSelectedProjectId(lastProjectId);
        setCurrentView(lastView === 'workspace' && lastProjectId ? 'workspace' : 'projects');
      } catch {
        resetToLogin('登录状态已过期，请重新登录。');
      }
    };

    void bootstrap();
  }, []);

  useEffect(() => {
    const handleAuthExpired = () => {
      resetToLogin('登录状态已过期，请重新登录。');
    };

    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    return () => {
      window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    };
  }, []);

  const navigate = (view: ViewState) => {
    if (view !== 'login') {
      setLoginNotice(null);
    }
    setCurrentView(view);
    localStorage.setItem(LAST_VIEW_KEY, view);

    if (view !== 'workspace') {
      setSelectedProjectId(null);
      localStorage.removeItem(LAST_PROJECT_ID_KEY);
    }
  };

  const openWorkspace = (projectId: string) => {
    setSelectedProjectId(projectId);
    localStorage.setItem(LAST_PROJECT_ID_KEY, projectId);
    localStorage.setItem(LAST_VIEW_KEY, 'workspace');
    setCurrentView('workspace');
  };

  return (
    <>
      {currentView === 'login' && <Login onNavigate={navigate} notice={loginNotice} />}
      {currentView === 'projects' && (
        <ProjectBoard
          onNavigate={navigate}
          onOpenProject={openWorkspace}
        />
      )}
      {currentView === 'workspace' && selectedProjectId && (
        <Workspace
          projectId={selectedProjectId}
          onNavigate={navigate}
        />
      )}
    </>
  );
}
