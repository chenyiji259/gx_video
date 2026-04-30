import React, { useEffect } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/stores/authStore';

export const ProtectedRoute: React.FC = () => {
  const { user, token, isLoading, fetchMe } = useAuthStore();
  const location = useLocation();

  useEffect(() => {
    if (token && !user) {
      fetchMe();
    }
  }, [token, user, fetchMe]);

  if (isLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#E2FE50] border-t-transparent"></div>
      </div>
    );
  }

  if (!token) {
    return <Navigate to="/auth" state={{ from: location }} replace />;
  }

  return <Outlet />;
};
