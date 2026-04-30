import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { 
  Plus, 
  Search, 
  MoreVertical, 
  Clock, 
  CheckCircle2, 
  AlertCircle,
  Clapperboard,
  Trash2,
  Archive,
  Edit2,
  Sparkles,
  Activity,
  ChevronRight
} from 'lucide-react';
import { motion } from 'motion/react';
import { projectService } from '@/services/api';
import { Project } from '@/types';
import { useNavigate } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { CreateProjectModal } from '@/components/projects/CreateProjectModal';

export const Projects = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<Project | null>(null);

  useEffect(() => {
    fetchProjects();
  }, []);

  const fetchProjects = async () => {
    try {
      const response = await projectService.getProjects();
      if (response.success) {
        setProjects(response.data.items);
      }
    } catch (error) {
      console.error('Failed to fetch projects:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateProject = async (name: string) => {
    try {
      if (editingProject) {
        // Handle Rename
        const response = await projectService.updateProject(editingProject.id, { name });
        if (response.success) {
          setEditingProject(null);
          fetchProjects();
        }
      } else {
        // Handle Create
        const response = await projectService.createProject(name);
        if (response.success) {
          navigate(`/projects/${response.data.id}`);
        }
      }
    } catch (error) {
      console.error('Project action failed:', error);
      throw error;
    }
  };

  const handleDeleteProject = async (prjId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(t('projects.deleteConfirm'))) return;
    try {
      const response = await projectService.deleteProject(prjId);
      if (response.success) {
        fetchProjects();
      }
    } catch (error) {
      console.error('Failed to delete project:', error);
    }
  };

  const startRename = (prj: Project, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingProject(prj);
    setIsModalOpen(true);
  };

  const filteredProjects = projects.filter(p => 
    p.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const getStageColor = (stage: string) => {
    switch (stage) {
      case 'export_ready': return 'text-[#00cffc] bg-[#00cffc]/10 border-[#00cffc]/20';
      case 'created': return 'text-[#a5aac2] bg-[#a5aac2]/10 border-[#a5aac2]/20';
      default: return 'text-[#ba9eff] bg-[#ba9eff]/10 border-[#ba9eff]/20';
    }
  };

  return (
    <div className="relative min-h-full p-4 md:p-8 overflow-hidden">
      {/* Cyberpunk Grid Background */}
      <div className="absolute inset-0 pointer-events-none bg-[linear-gradient(rgba(0,207,252,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(0,207,252,0.03)_1px,transparent_1px)] bg-[size:40px_40px] [mask-image:radial-gradient(ellipse_80%_50%_at_50%_0%,#000_70%,transparent_100%)] z-0" />
      
      {/* Subtle Ambient Glow */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-[#ba9eff]/10 blur-[120px] rounded-full pointer-events-none z-0" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-[#00cffc]/10 blur-[120px] rounded-full pointer-events-none z-0" />

      <div className="relative z-10 space-y-8">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4">
        <div>
          <h1 className="text-3xl md:text-4xl font-black font-['Space_Grotesk'] tracking-tighter">
            {t('nav.projects')}
          </h1>
          <p className="text-[#a5aac2] font-['Space_Grotesk'] text-xs md:text-sm mt-1 uppercase tracking-widest">
            {t('projects.subtitle')}
          </p>
        </div>
        <button 
          onClick={() => setIsModalOpen(true)}
          className="w-full sm:w-auto justify-center bg-gradient-to-br from-[#ba9eff] to-[#8455ef] text-black px-6 py-3 rounded-lg font-bold font-['Space_Grotesk'] tracking-tight flex items-center gap-2 shadow-[0_0_20px_rgba(186,158,255,0.3)] hover:scale-105 transition-all"
        >
          <Plus size={20} />
          {t('projects.newProject')}
        </button>
      </div>

      <CreateProjectModal 
        isOpen={isModalOpen} 
        onClose={() => { setIsModalOpen(false); setEditingProject(null); }} 
        onSubmit={handleCreateProject}
        mode={editingProject ? 'rename' : 'create'}
        initialName={editingProject?.name || ''}
      />

      <div className="relative max-w-md">
        <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-[#dfe4fe]/40" />
        <input 
          type="text" 
          placeholder={t('projects.searchPlaceholder')}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full bg-[#171f36]/40 border border-[#41475b]/30 rounded-xl py-3 pl-12 pr-4 text-sm focus:border-[#ba9eff] focus:ring-0 transition-all"
        />
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3, 4, 5, 6].map(i => (
            <div key={i} className="bg-[#0c1326]/60 backdrop-blur-xl rounded-2xl p-6 border border-[#41475b]/40 relative overflow-hidden">
              <div className="absolute inset-0 -translate-x-full animate-[shimmer_1.5s_infinite] bg-gradient-to-r from-transparent via-white/5 to-transparent z-10"></div>
              <div className="relative z-0 flex justify-between items-start mb-4">
                <div className="w-12 h-12 rounded-xl bg-[#41475b]/20 border border-[#41475b]/30"></div>
                <div className="flex gap-2">
                  <div className="w-8 h-8 rounded-lg bg-[#41475b]/20"></div>
                  <div className="w-8 h-8 rounded-lg bg-[#41475b]/20"></div>
                </div>
              </div>
              <div className="w-3/4 h-7 bg-[#41475b]/20 rounded mb-4 relative z-0"></div>
              <div className="w-1/4 h-5 bg-[#41475b]/20 rounded mb-8 relative z-0"></div>
              <div className="w-full h-1.5 bg-[#41475b]/20 rounded-full mb-6 relative z-0"></div>
              <div className="flex items-center justify-between pt-4 border-t border-[#41475b]/20 relative z-0">
                <div className="w-1/3 h-3 bg-[#41475b]/20 rounded"></div>
                <div className="w-1/4 h-3 bg-[#41475b]/20 rounded"></div>
              </div>
            </div>
          ))}
        </div>
      ) : filteredProjects.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredProjects.map((project) => (
            <motion.div 
              key={project.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              onClick={() => navigate(`/projects/${project.id}`)}
              className="relative bg-[#0c1326]/60 backdrop-blur-xl rounded-2xl p-6 border border-[#41475b]/40 hover:border-[#ba9eff]/50 hover:shadow-[0_0_30px_rgba(186,158,255,0.15)] transition-all cursor-pointer group overflow-hidden"
            >
              {/* Card Decorative Background SVG */}
              <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-[#ba9eff]/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-bl-full pointer-events-none" />
              <div className="absolute -bottom-4 -right-4 text-[#41475b]/20 group-hover:text-[#ba9eff]/10 transition-colors duration-500 pointer-events-none rotate-12">
                <Sparkles size={120} strokeWidth={1} />
              </div>

              <div className="relative z-10">
                <div className="flex justify-between items-start mb-4">
                  <div className="w-12 h-12 rounded-xl bg-[#171f36] flex items-center justify-center text-[#00cffc] group-hover:scale-110 group-hover:shadow-[0_0_15px_rgba(0,207,252,0.3)] transition-all overflow-hidden border border-[#41475b]/30">
                    {project.cover_url ? (
                      <img src={project.cover_url} alt="cover" className="w-full h-full object-cover" />
                    ) : (
                      <Clapperboard size={24} />
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button 
                      className="p-2 text-[#6f758b] hover:text-[#00cffc] hover:bg-[#00cffc]/10 rounded-lg transition-colors" 
                      onClick={(e) => startRename(project, e)}
                      title="重命名项目"
                    >
                      <Edit2 size={16} />
                    </button>
                    <button 
                      className="p-2 text-[#6f758b] hover:text-[#ff59e3] hover:bg-[#ff59e3]/10 rounded-lg transition-colors" 
                      onClick={(e) => handleDeleteProject(project.id, e)}
                      title="删除项目"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
                
                <h3 className="text-xl font-bold font-['Space_Grotesk'] mb-2 truncate group-hover:text-transparent group-hover:bg-clip-text group-hover:bg-gradient-to-r group-hover:from-[#ba9eff] group-hover:to-[#00cffc] transition-all">{project.name}</h3>
                
                <div className="flex flex-wrap gap-2 mb-4">
                  <span className={cn("px-2 py-0.5 rounded text-[10px] font-['Space_Grotesk'] font-bold border uppercase tracking-wider flex items-center gap-1", getStageColor(project.current_stage))}>
                    <Activity size={10} />
                    {project.current_stage.replace(/_/g, ' ')}
                  </span>
                </div>

                {/* Progress Bar */}
                <div className="mb-6">
                  <div className="flex justify-between items-center mb-1.5">
                    <span className="text-[10px] font-bold text-[#a5aac2] uppercase tracking-wider">{t('projects.completion')}</span>
                    <span className="text-[10px] font-bold text-[#00cffc] drop-shadow-[0_0_2px_rgba(0,207,252,0.8)]">{project?.progress_percentage ?? 0}%</span>
                  </div>
                  <div className="h-1.5 w-full bg-[#171f36] rounded-full overflow-hidden shadow-inner border border-[#41475b]/30">
                    <motion.div 
                      initial={{ width: 0 }}
                      animate={{ width: `${project?.progress_percentage ?? 0}%` }}
                      className="h-full bg-gradient-to-r from-[#ba9eff] to-[#00cffc] shadow-[0_0_8px_rgba(0,207,252,0.5)]"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between pt-4 border-t border-[#41475b]/20 text-[10px] text-[#6f758b] font-['Space_Grotesk'] uppercase tracking-widest">
                  <span className="flex items-center gap-1.5"><Clock size={12} /> {new Date(project.updated_at).toLocaleDateString()}</span>
                  <span className="text-[#00cffc] group-hover:translate-x-1 transition-transform flex items-center gap-1 group-hover:drop-shadow-[0_0_5px_rgba(0,207,252,0.5)]">{t('projects.openWorkbench')} <ChevronRight size={12} /></span>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      ) : (
        <motion.div 
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-center py-24 bg-[#0c1326]/60 backdrop-blur-md rounded-3xl border border-[#41475b]/40 relative overflow-hidden group hover:border-[#00cffc]/30 hover:shadow-[0_0_30px_rgba(0,207,252,0.1)] transition-all"
        >
          <div className="absolute inset-0 bg-gradient-to-b from-[#00cffc]/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"></div>
          <div className="w-24 h-24 bg-[#171f36] rounded-full flex items-center justify-center mx-auto mb-6 border border-[#41475b]/50 shadow-[0_0_30px_rgba(0,0,0,0.5)] relative z-10 group-hover:scale-110 transition-transform duration-500">
            <Clapperboard size={40} className="text-[#6f758b] group-hover:text-[#00cffc] group-hover:drop-shadow-[0_0_8px_rgba(0,207,252,0.5)] transition-all duration-500" />
          </div>
          <h3 className="text-2xl font-black font-['Space_Grotesk'] mb-2 text-white relative z-10">{t('projects.noProjects')}</h3>
          <p className="text-[#a5aac2] mb-8 max-w-md mx-auto relative z-10">{t('projects.noProjectsDesc')}</p>
          <button 
            onClick={() => setIsModalOpen(true)}
            className="px-8 py-4 bg-gradient-to-r from-[#ba9eff] to-[#8455ef] text-black font-bold rounded-xl hover:shadow-[0_0_30px_rgba(186,158,255,0.4)] transition-all relative z-10 uppercase tracking-tight flex items-center gap-2 mx-auto hover:scale-105"
          >
            <Plus size={18} /> {t('projects.createFirst')}
          </button>
        </motion.div>
      )}
      </div>
    </div>
  );
};
