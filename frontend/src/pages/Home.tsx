import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Play, Heart, Eye, Share2, LayoutGrid, List, Clock, ChevronRight, Rocket, User } from 'lucide-react';
import { motion } from 'motion/react';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/stores/authStore';
import { dashboardService } from '@/services/api';
import { Link } from 'react-router-dom';

const CommunityCard = ({ title, author, prompt, bpm, tag, views, likes, image }: any) => {
  const { t } = useTranslation();
  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      className="bg-[#0c1326]/80 backdrop-blur-md rounded-2xl overflow-hidden border border-[#41475b]/30 group hover:border-[#00cffc]/50 hover:shadow-[0_0_30px_rgba(0,207,252,0.15)] transition-all duration-500"
    >
      <div className="relative h-56 overflow-hidden">
        <img 
          src={image} 
          alt={title} 
          className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
          referrerPolicy="no-referrer"
        />
        <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
          <button className="w-16 h-16 rounded-full bg-[#00cffc] flex items-center justify-center shadow-[0_0_30px_rgba(0,207,252,0.6)] transform scale-90 group-hover:scale-100 transition-transform">
            <Play size={32} className="text-black fill-current" />
          </button>
        </div>
        <div className="absolute bottom-3 left-3 flex gap-2">
          <span className="bg-black/60 backdrop-blur-md px-2 py-0.5 rounded text-[10px] font-['Space_Grotesk'] font-bold text-[#00cffc] border border-[#00cffc]/20 uppercase">{bpm} BPM</span>
          <span className="bg-black/60 backdrop-blur-md px-2 py-0.5 rounded text-[10px] font-['Space_Grotesk'] font-bold text-[#ff59e3] border border-[#ff59e3]/20 uppercase">{tag}</span>
        </div>
      </div>
      <div className="p-5 space-y-4">
        <div className="flex justify-between items-start">
          <div>
            <h4 className="font-['Space_Grotesk'] font-bold text-lg">{title}</h4>
            <p className="text-xs text-[#a5aac2] line-clamp-1 mt-1">{t('community.promptLabel')}: "{prompt}"</p>
          </div>
          <Heart size={20} className="text-[#a5aac2]/40 hover:text-[#00cffc] cursor-pointer" />
        </div>
        <div className="flex items-center justify-between pt-2 border-t border-[#41475b]/10">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-[#1c253e] border border-[#00cffc]/30 overflow-hidden">
              <img src={`https://picsum.photos/seed/${author}/50/50`} alt={author} referrerPolicy="no-referrer" />
            </div>
            <span className="text-[10px] font-['Space_Grotesk'] font-bold uppercase tracking-widest text-[#a5aac2]">@{author}</span>
          </div>
          <div className="flex gap-4">
            <span className="flex items-center gap-1 text-[10px] text-[#a5aac2] font-['Space_Grotesk']"><Eye size={12} /> {views}</span>
            <span className="flex items-center gap-1 text-[10px] text-[#a5aac2] font-['Space_Grotesk']"><Share2 size={12} /> {likes}</span>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

const StatCard = ({ label, value, color }: { label: string, value: string, color: string }) => (
  <div className={cn("bg-[#0c1326]/80 border border-[#41475b]/30 p-6 rounded-2xl relative overflow-hidden backdrop-blur-sm", color)}>
    <div className="absolute left-0 top-0 bottom-0 w-1 bg-current opacity-50" />
    <p className="font-['Space_Grotesk'] text-[10px] uppercase tracking-[0.2em] text-[#a5aac2] font-bold">{label}</p>
    <p className="text-3xl font-bold font-['Space_Grotesk'] mt-2 tracking-tight">{value}</p>
  </div>
);

export const Home = () => {
  const { t } = useTranslation();
  const { user, token } = useAuthStore();
  const [dashboardData, setDashboardData] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (token) {
      setIsLoading(true);
      dashboardService.getOverview()
        .then(res => {
          if (res.success) {
            setDashboardData(res.data);
          }
        })
        .finally(() => setIsLoading(false));
    }
  }, [token]);

  return (
    <div className="p-8 space-y-12">
      {/* Hero Section */}
      <section className="relative h-[480px] rounded-2xl overflow-hidden flex items-center px-12 group">
        <div className="absolute inset-0 z-0">
          <img 
            src="https://picsum.photos/seed/vidmuse-hero/1920/1080" 
            className="w-full h-full object-cover opacity-60 transition-transform duration-700 group-hover:scale-105"
            alt="Hero"
            referrerPolicy="no-referrer"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-[#070d1f] via-[#070d1f]/40 to-transparent"></div>
          <div className="absolute inset-0 bg-gradient-to-t from-[#070d1f] to-transparent"></div>
        </div>
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="relative z-10 max-w-3xl space-y-8"
        >
          <div className="space-y-4">
            <motion.div 
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              className="inline-flex items-center gap-2 bg-[#00cffc]/10 border border-[#00cffc]/20 px-3 py-1 rounded-full mb-2"
            >
              <span className="w-2 h-2 rounded-full bg-[#00cffc] animate-pulse"></span>
            <span className="font-['Space_Grotesk'] text-[10px] uppercase tracking-widest text-[#00cffc] font-bold">{t('home.engineBadge')}</span>
            </motion.div>
            <h2 className="text-5xl md:text-7xl font-black font-['Space_Grotesk'] tracking-tight leading-[1.2] text-transparent bg-clip-text bg-gradient-to-br from-white via-[#dfe4fe] to-[#a5aac2] py-2 drop-shadow-[0_0_15px_rgba(255,255,255,0.2)]">
              {t('home.heroTitleLine1', 'CREATE CINEMATIC')}<br />
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#00cffc] via-[#0088ff] to-[#ba9eff] animate-gradient-x leading-normal drop-shadow-[0_0_15px_rgba(0,207,252,0.4)]">{t('home.heroTitleLine2', 'VIDEO CONTENT')}</span>
            </h2>
            <p className="text-[#a5aac2] font-['Space_Grotesk'] text-sm md:text-lg max-w-xl uppercase tracking-[0.2em] font-medium opacity-80">
              {t('home.heroSubtitle', 'AI-DRIVEN VIDEO CREATION FOR INDEPENDENT CREATORS')}
            </p>
          </div>

          <div className="flex flex-col sm:flex-row gap-4 pt-6">
            {token ? (
              <Link 
                to="/projects"
                className="px-10 py-4 bg-gradient-to-r from-[#00cffc] to-[#0088ff] text-black font-black rounded-full hover:shadow-[0_0_30px_rgba(0,207,252,0.6)] transition-all hover:scale-105 uppercase tracking-tighter flex items-center justify-center gap-2"
              >
                <Rocket size={20} /> {t('home.startDirecting', 'Start Creating')}
              </Link>
            ) : (
              <Link 
                to="/auth"
                className="px-10 py-4 bg-[#00cffc] text-black font-black rounded-full hover:shadow-[0_0_30px_rgba(0,207,252,0.6)] transition-all hover:scale-105 uppercase tracking-tighter flex items-center justify-center gap-2"
              >
                <User size={20} /> {t('home.becomeDirector', 'Become a Creator')}
              </Link>
            )}
            <button className="px-10 py-4 border-2 border-[#41475b] text-[#dfe4fe] font-bold rounded-full hover:bg-[#171f36] transition-all uppercase tracking-tighter flex items-center justify-center gap-2">
              <Play size={18} fill="currentColor" /> {t('home.watchShowreel', 'Watch Showreel')}
            </button>
          </div>
        </motion.div>
      </section>

      {/* Recent Projects (Conditional) */}
      {token && dashboardData?.recent_projects?.length > 0 && (
        <section className="space-y-6">
          <div className="flex justify-between items-end">
            <div>
              <h3 className="text-2xl font-bold font-['Space_Grotesk'] tracking-tight flex items-center gap-2 text-transparent bg-clip-text bg-gradient-to-r from-[#dfe4fe] to-[#a5aac2]">
                <Clock className="text-[#00cffc]" size={24} />
                {t('home.continueDirecting')}
              </h3>
              <p className="text-[#6f758b] font-['Space_Grotesk'] text-xs uppercase tracking-[0.2em] mt-1 font-medium">{t('home.jumpBack')}</p>
            </div>
            <Link to="/projects" className="text-[#00cffc]/80 hover:text-[#00cffc] transition-all flex items-center gap-1 text-sm font-bold font-['Space_Grotesk'] tracking-wider">
              {t('home.viewAll')} <ChevronRight size={16} />
            </Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {dashboardData.recent_projects.map((project: any) => (
              <Link 
                key={project.id} 
                to={`/projects/${project.id}`}
                className="bg-[#0c1326]/80 border border-[#41475b]/30 rounded-2xl p-6 hover:border-[#00cffc] hover:shadow-[0_0_30px_rgba(0,207,252,0.1)] transition-all group backdrop-blur-sm"
              >
                <div className="flex items-center justify-between mb-4">
                  <div className="w-10 h-10 rounded-xl bg-[#00cffc]/10 flex items-center justify-center text-[#00cffc]">
                    <Play size={18} fill="currentColor" />
                  </div>
                  <span className="text-[10px] font-bold font-['Space_Grotesk'] text-[#a5aac2] uppercase tracking-widest">{project.current_stage.replace('_', ' ')}</span>
                </div>
                <h4 className="font-['Space_Grotesk'] font-bold text-white group-hover:text-[#00cffc] transition-colors line-clamp-1 text-lg">{project.name}</h4>
                <div className="mt-6 flex items-center justify-between">
                  <div className="flex-1 h-1.5 bg-[#1c253e] rounded-full overflow-hidden mr-4">
                    <div 
                      className="h-full bg-gradient-to-r from-[#00cffc] to-[#0088ff]" 
                      style={{ width: `${project.progress_percentage}%` }}
                    ></div>
                  </div>
                  <span className="text-[10px] font-bold text-[#00cffc] font-['Space_Grotesk']">{project.progress_percentage}%</span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Community Grid - 已隐藏（保留代码便于回滚） - 2026-04-30
      <section className="space-y-8">
        <div className="flex justify-between items-end">
          <div>
            <h3 className="text-3xl font-bold font-['Space_Grotesk'] tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-white to-[#a5aac2]">{t('home.communityMasterpieces')}</h3>
            <p className="text-[#6f758b] font-['Space_Grotesk'] text-sm mt-1 uppercase tracking-[0.2em] font-medium">{t('home.globalCreativeDynamics')}</p>
          </div>
          <div className="flex gap-2">
            <button className="p-2 rounded-lg bg-[#0c1326] border border-[#41475b]/30 hover:border-[#00cffc] transition-all text-[#00cffc] shadow-[0_0_15px_rgba(0,207,252,0.1)]"><LayoutGrid size={20} /></button>
            <button className="p-2 rounded-lg bg-[#0c1326] border border-[#41475b]/30 hover:border-[#00cffc] transition-all text-[#6f758b] hover:text-[#00cffc]"><List size={20} /></button>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <CommunityCard 
            title="Cyber Dream" 
            author="Hyper_Void" 
            prompt="Anxious neon glitch city pulsing with sub-bass..." 
            bpm={128} 
            tag="Melodic" 
            views="2.4k" 
            likes="142" 
            image="https://picsum.photos/seed/cyber1/800/600" 
          />
          <CommunityCard 
            title="Solar Storm" 
            author="Lumina_VFX" 
            prompt="Slow golden plasma flowing through the void..." 
            bpm={95} 
            tag="Ambient" 
            views="1.8k" 
            likes="89" 
            image="https://picsum.photos/seed/solar1/800/600" 
          />
          <CommunityCard 
            title="Fractal Chaos" 
            author="Neuro_Flow" 
            prompt="Aggressive ink drops colliding in liquid nitrogen..." 
            bpm={174} 
            tag="Neurostep" 
            views="4.1k" 
            likes="312" 
            image="https://picsum.photos/seed/fractal1/800/600" 
          />
        </div>
      </section>
      */}

      <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <StatCard label={t('home.activeTasks')} value={token ? (dashboardData?.stats?.total_projects?.toString() || "0") : "1,248"} color="text-[#00cffc]" />
        <StatCard label={t('home.computeLoad')} value={token ? "Ready" : "42.8%"} color="text-[#00cffc]" />
      </section>
    </div>
  );
};
