import React from 'react';
import { Workspace } from './components/Workspace';
import ProjectBoard from './components/ProjectBoard';
import Login from './components/Login';
import { ViewState } from './types';
import { useEffect, useState } from 'react';
import { authApi, clearToken } from './api';

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
        clearToken();
        localStorage.removeItem(LAST_VIEW_KEY);
        localStorage.removeItem(LAST_PROJECT_ID_KEY);
        setSelectedProjectId(null);
        setCurrentView('login');
      }
    };

    void bootstrap();
  }, []);

  const navigate = (view: ViewState) => {
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
      {currentView === 'login' && <Login onNavigate={navigate} />}
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
