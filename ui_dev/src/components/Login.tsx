import React, { useState } from 'react';
import { ViewState } from '../types';
import { authApi, setToken } from '../api';

interface LoginProps {
  onNavigate: (view: ViewState) => void;
}

export default function Login({ onNavigate }: LoginProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await authApi.login(username, password);
      setToken(result.access_token);
      onNavigate('projects');
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
      <div className="w-full max-w-md bg-white rounded-3xl shadow-xl shadow-gray-200/50 p-8">
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-gradient-to-br from-violet-500 to-indigo-600 rounded-2xl mx-auto mb-4 flex items-center justify-center shadow-lg shadow-violet-200">
            <svg
              className="w-8 h-8 text-white"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
              />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">光希内容创作平台</h1>
          <p className="text-gray-500 mt-2 text-sm">登录后继续管理项目和视频创作流程</p>
        </div>

        <form onSubmit={handleLogin} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              用户名
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent transition-all"
              placeholder="请输入用户名"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              密码
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-3 rounded-xl border border-gray-200 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent transition-all"
              placeholder="请输入密码"
              required
            />
          </div>

          <div className="flex items-center justify-between text-sm">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" className="rounded text-violet-600 focus:ring-violet-500" />
              <span className="text-gray-600">记住我</span>
            </label>
            <a href="#" className="text-violet-600 hover:text-violet-700 font-medium">忘记密码？</a>
          </div>

          {error ? (
            <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600">
              {error}
            </div>
          ) : null}

          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-violet-600 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60 text-white font-medium py-3 rounded-xl transition-colors shadow-lg shadow-violet-200"
          >
            {submitting ? '登录中...' : '登录'}
          </button>
        </form>

        <div className="mt-8 text-center text-sm text-gray-500">
          还没有账号？{' '}
          <a href="#" className="text-violet-600 hover:text-violet-700 font-medium">
            立即注册
          </a>
        </div>
      </div>
    </div>
  );
}
