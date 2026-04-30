import React from 'react';
import { Workspace } from './components/Workspace';
import ProjectBoard from './components/ProjectBoard';
import Login from './components/Login';
import { ViewState } from './types';
import { useEffect, useState } from 'react';
import { authApi, clearToken } from './api';

export default function App() {
  const [currentView, setCurrentView] = useState<ViewState>(
    localStorage.getItem('vidmuse_token') ? 'projects' : 'login'
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  useEffect(() => {
    const bootstrap = async () => {
      const token = localStorage.getItem('vidmuse_token');
      if (!token) {
        setCurrentView('login');
        return;
      }
      try {
        await authApi.getMe();
        setCurrentView('projects');
      } catch {
        clearToken();
        setCurrentView('login');
      }
    };

    void bootstrap();
  }, []);

  const openWorkspace = (projectId: string) => {
    setSelectedProjectId(projectId);
    setCurrentView('workspace');
  };

  return (
    <>
      {currentView === 'login' && <Login onNavigate={setCurrentView} />}
      {currentView === 'projects' && (
        <ProjectBoard
          onNavigate={setCurrentView}
          onOpenProject={openWorkspace}
        />
      )}
      {currentView === 'workspace' && selectedProjectId && (
        <Workspace
          projectId={selectedProjectId}
          onNavigate={setCurrentView}
        />
      )}
    </>
  );
}
