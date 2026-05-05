import React, { useState } from 'react';
import { Plus, Trash2, Video, LogOut, X } from 'lucide-react';
import { ViewState, Project } from '../types';
import { clearToken, projectApi } from '../api';

interface ProjectBoardProps {
  onNavigate: (view: ViewState) => void;
  onOpenProject: (projectId: string) => void;
}

export default function ProjectBoard({ onNavigate, onOpenProject }: ProjectBoardProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    const loadProjects = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await projectApi.listProjects();
        setProjects(result.items ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载项目失败');
      } finally {
        setLoading(false);
      }
    };

    void loadProjects();
  }, []);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!confirm('确定删除这个项目吗？')) return;
    try {
      await projectApi.deleteProject(id);
      setProjects(projects.filter((p) => p.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除项目失败');
    }
  };

  const openCreateDialog = () => {
    setProjectName('');
    setError(null);
    setShowCreateDialog(true);
  };

  const handleCreate = async () => {
    const name = projectName.trim();
    if (!name) {
      setError('请输入项目名称');
      return;
    }

    setCreating(true);
    setError(null);
    try {
      const newProject = await projectApi.createProject(name);
      setProjects([newProject, ...projects]);
      setShowCreateDialog(false);
      setProjectName('');
      onOpenProject(newProject.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建项目失败');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top Navbar */}
      <nav className="bg-white border-b border-gray-100 px-6 py-4 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-violet-500 to-indigo-600 rounded-xl flex items-center justify-center">
            <Video className="w-5 h-5 text-white" />
          </div>
          <span className="font-bold text-xl text-gray-900 tracking-tight">工作台</span>
        </div>
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-full bg-gray-100 overflow-hidden border border-gray-200">
            <img src="https://images.unsplash.com/photo-1534528741775-53994a69daeb?ixlib=rb-4.0.3&auto=format&fit=crop&w=150&q=60" alt="Avatar" className="w-full h-full object-cover" />
          </div>
          <button
            onClick={() => {
              clearToken();
              onNavigate('login');
            }}
            className="text-gray-500 hover:text-gray-800 transition-colors"
          >
            <LogOut className="w-5 h-5" />
          </button>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">我的项目</h1>
            <p className="text-gray-500 text-sm mt-1">管理你的所有 AI 生成视频项目</p>
          </div>
          <button 
            onClick={openCreateDialog}
            disabled={creating}
            className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60 text-white px-5 py-2.5 rounded-xl transition-all shadow-lg shadow-violet-200 font-medium"
          >
            <Plus className="w-5 h-5" />
            {creating ? '创建中...' : '新建项目'}
          </button>
        </div>

        {error ? (
          <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="text-center py-20 bg-white rounded-3xl border border-gray-100 shadow-sm">
            <h3 className="text-lg font-medium text-gray-900 mb-1">正在加载项目...</h3>
          </div>
        ) : projects.length === 0 ? (
          <div className="text-center py-20 bg-white rounded-3xl border border-gray-100 shadow-sm">
            <Video className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-1">还没有项目</h3>
            <p className="text-gray-500 text-sm mb-6">点击右上角"新建项目"开始你的第一个视频创作</p>
            <button 
              onClick={openCreateDialog}
              className="bg-violet-50 text-violet-600 hover:bg-violet-100 px-5 py-2 rounded-lg font-medium transition-colors"
            >
              立刻创建
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {projects.map((project) => (
              <div 
                key={project.id} 
                className="group bg-white rounded-2xl overflow-hidden border border-gray-100 shadow-sm hover:shadow-xl hover:shadow-violet-100/50 transition-all cursor-pointer flex flex-col"
                onClick={() => onOpenProject(project.id)}
              >
                <div className="relative aspect-video bg-gray-100 overflow-hidden">
                  <img
                    src={project.cover_url || 'https://images.unsplash.com/photo-1544161515-4ab6ce6db874?ixlib=rb-4.0.3&auto=format&fit=crop&w=500&q=60'}
                    alt={project.name}
                    className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                  />
                  {/* Enter Overlay */}
                  <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                    <span className="bg-white/90 text-gray-900 px-4 py-2 rounded-full font-medium text-sm shadow-lg backdrop-blur-sm">
                      进入工作台
                    </span>
                  </div>
                </div>
                <div className="p-4 flex flex-col flex-1">
                  <div className="flex justify-between items-start mb-2">
                    <h3 className="font-semibold text-gray-900 line-clamp-1 flex-1">{project.name}</h3>
                    <button 
                      onClick={(e) => handleDelete(e, project.id)}
                      className="text-gray-400 hover:text-red-500 p-1 opacity-0 group-hover:opacity-100 transition-all ml-2"
                      title="删除项目"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="text-xs text-gray-400 mt-auto">
                    {new Date(project.updated_at).toLocaleString()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {showCreateDialog ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/35 px-4">
          <div className="w-full max-w-md rounded-2xl bg-white border border-gray-100 shadow-2xl shadow-gray-900/20 p-5">
            <div className="flex items-start justify-between gap-4 mb-5">
              <div>
                <h2 className="text-lg font-bold text-gray-900">新建项目</h2>
                <p className="text-sm text-gray-500 mt-1">先给项目命名，后续工作台会围绕这个项目继续创作。</p>
              </div>
              <button
                onClick={() => setShowCreateDialog(false)}
                className="text-gray-400 hover:text-gray-700 transition-colors p-1"
                aria-label="关闭"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <label className="block text-xs font-medium text-gray-600 mb-2">项目名称</label>
            <input
              autoFocus
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleCreate();
              }}
              className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-800 outline-none focus:border-violet-400 focus:ring-4 focus:ring-violet-100"
              placeholder="例如：麦角硫因 15 秒种草广告"
              maxLength={80}
            />
            <div className="text-right text-[11px] text-gray-400 mt-1">{projectName.trim().length}/80</div>

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowCreateDialog(false)}
                className="px-4 py-2 rounded-xl border border-gray-200 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => void handleCreate()}
                disabled={creating || !projectName.trim()}
                className="px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60 text-sm text-white font-medium transition-colors"
              >
                {creating ? '创建中...' : '创建并进入'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
