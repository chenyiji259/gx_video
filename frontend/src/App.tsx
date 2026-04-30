import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import { Layout } from './components/Layout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { Home } from './pages/Home';
import { Workbench } from './pages/Workbench';
import { Projects } from './pages/Projects';
import { Library } from './pages/Library';
// 社区功能已隐藏（保留代码便于回滚） - 2026-04-30
// import { Community } from './pages/Community';
// import { CommunityDetail } from './pages/CommunityDetail';
import { Auth } from './pages/Auth';
import { Settings } from './pages/Settings';
import { Help } from './pages/Help';
import './i18n';

export default function App() {
  return (
    <Router>
      <Toaster theme="dark" position="top-right" toastOptions={{ style: { background: '#171f36', border: '1px solid #41475b', color: '#dfe4fe' } }} />
      <Routes>
        <Route path="/auth" element={<Auth />} />
        <Route path="/" element={<Layout />}>
          {/* Public Routes */}
          <Route index element={<Home />} />
          {/* 社区路由已隐藏（保留代码便于回滚） - 2026-04-30
          <Route path="community" element={<Community />} />
          <Route path="community/:id" element={<CommunityDetail />} />
          */}
          <Route path="help" element={<Help />} />

          {/* Protected Routes */}
          <Route element={<ProtectedRoute />}>
            <Route path="projects" element={<Projects />} />
            <Route path="projects/:projectId" element={<Workbench />} />
            <Route path="library" element={<Library />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  );
}

