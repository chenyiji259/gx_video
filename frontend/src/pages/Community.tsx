import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { 
  Play, 
  Heart, 
  Eye, 
  Share2, 
  LayoutGrid, 
  List, 
  Search, 
  Filter,
  TrendingUp,
  Clock,
  Award
} from 'lucide-react';
import { motion } from 'motion/react';
import { cn } from '@/lib/utils';

const CommunityCard = ({ id, title, author, prompt, bpm, tag, views, likes, image }: any) => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  
  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      onClick={() => navigate(`/community/${id}`)}
      className="bg-[#171f36]/70 backdrop-blur-md rounded-xl overflow-hidden shadow-[inset_0_0_0_1px_rgba(65,71,91,0.2)] group hover:shadow-[0_0_20px_rgba(186,158,255,0.2)] transition-all duration-500 cursor-pointer"
    >
      <div className="relative h-56 overflow-hidden">
        <img 
          src={image} 
          alt={title} 
          className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
          referrerPolicy="no-referrer"
        />
        <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
          <button className="w-16 h-16 rounded-full bg-[#ba9eff] flex items-center justify-center shadow-[0_0_20px_rgba(186,158,255,0.6)] transform scale-90 group-hover:scale-100 transition-transform">
            <Play size={32} className="text-black fill-current" />
          </button>
        </div>
        <div className="absolute bottom-3 left-3 flex gap-2">
          <span className="bg-black/60 backdrop-blur-md px-2 py-0.5 rounded text-[10px] font-['Space_Grotesk'] font-bold text-[#00c0ea] border border-[#00cffc]/20 uppercase">{bpm} BPM</span>
          <span className="bg-black/60 backdrop-blur-md px-2 py-0.5 rounded text-[10px] font-['Space_Grotesk'] font-bold text-[#ff59e3] border border-[#ff59e3]/20 uppercase">{tag}</span>
        </div>
      </div>
      <div className="p-5 space-y-4">
        <div className="flex justify-between items-start">
          <div>
            <h4 className="font-['Space_Grotesk'] font-bold text-lg">{title}</h4>
            <p className="text-xs text-[#a5aac2] line-clamp-1 mt-1">{t('community.promptLabel')}: "{prompt}"</p>
          </div>
          <Heart size={20} className="text-[#a5aac2]/40 hover:text-[#ba9eff] cursor-pointer" />
        </div>
        <div className="flex items-center justify-between pt-2 border-t border-[#41475b]/10">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-[#1c253e] border border-[#ba9eff]/30 overflow-hidden">
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

export const Community = () => {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState('trending');

  const masterpieces = [
    { id: '1', title: "Cyber Dream", author: "Hyper_Void", prompt: "Anxious neon glitch city pulsing with sub-bass...", bpm: 128, tag: "Melodic", views: "2.4k", likes: "142", image: "https://picsum.photos/seed/cyber1/800/600" },
    { id: '2', title: "Solar Storm", author: "Lumina_VFX", prompt: "Slow golden plasma flowing through the void...", bpm: 95, tag: "Ambient", views: "1.8k", likes: "89", image: "https://picsum.photos/seed/solar1/800/600" },
    { id: '3', title: "Fractal Chaos", author: "Neuro_Flow", prompt: "Aggressive ink drops colliding in liquid nitrogen...", bpm: 174, tag: "Neurostep", views: "4.1k", likes: "312", image: "https://picsum.photos/seed/fractal1/800/600" },
    { id: '4', title: "Oceanic Pulse", author: "Deep_Blue", prompt: "Deep sea bioluminescence reacting to low frequencies...", bpm: 80, tag: "Deep House", views: "3.2k", likes: "210", image: "https://picsum.photos/seed/ocean1/800/600" },
    { id: '5', title: "Midnight Drive", author: "Retro_Wave", prompt: "80s synthwave sunset with palm trees and grid lines...", bpm: 110, tag: "Synthwave", views: "5.6k", likes: "450", image: "https://picsum.photos/seed/retro1/800/600" },
    { id: '6', title: "Mountain Echo", author: "Nature_Synth", prompt: "Snowy peaks dissolving into digital particles...", bpm: 105, tag: "Electronic", views: "1.2k", likes: "67", image: "https://picsum.photos/seed/mountain1/800/600" },
  ];

  return (
    <div className="p-4 md:p-8 space-y-8 md:space-y-12">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div>
          <h1 className="text-3xl md:text-4xl font-black font-['Space_Grotesk'] tracking-tighter">
            {t('nav.community')}
          </h1>
          <p className="text-[#a5aac2] font-['Space_Grotesk'] text-xs md:text-sm mt-1 uppercase tracking-widest">
            Discover and share visual sonic masterpieces
          </p>
        </div>
        <div className="flex gap-4 w-full md:w-auto">
          <div className="relative group flex-1 md:flex-none">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#dfe4fe]/40" />
            <input 
              type="text" 
              placeholder="Search masterpieces..."
              className="bg-[#171f36]/40 border border-[#41475b]/30 rounded-xl py-2 pl-9 pr-4 text-xs focus:border-[#ba9eff] focus:ring-0 w-full md:w-64 transition-all"
            />
          </div>
          <button className="p-2 rounded-xl bg-[#171f36]/40 border border-[#41475b]/30 text-[#dfe4fe]/60 hover:text-[#ba9eff] transition-all">
            <Filter size={18} />
          </button>
        </div>
      </div>

      <div className="flex gap-8 border-b border-[#41475b]/20">
        {[
          { id: 'trending', icon: TrendingUp, label: 'Trending' },
          { id: 'latest', icon: Clock, label: 'Latest' },
          { id: 'featured', icon: Award, label: 'Featured' }
        ].map((tab) => (
          <button 
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-2 pb-4 text-sm font-bold font-['Space_Grotesk'] uppercase tracking-widest transition-all relative",
              activeTab === tab.id ? "text-[#ba9eff]" : "text-[#6f758b] hover:text-[#dfe4fe]"
            )}
          >
            <tab.icon size={16} />
            {tab.label}
            {activeTab === tab.id && (
              <motion.div 
                layoutId="activeTab"
                className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#ba9eff] shadow-[0_0_10px_#ba9eff]"
              />
            )}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
        {masterpieces.map((item, idx) => (
          <CommunityCard key={idx} {...item} />
        ))}
      </div>

      <div className="flex justify-center pt-8">
        <button className="px-8 py-3 bg-[#171f36] border border-[#41475b]/40 rounded-xl text-[#ba9eff] font-bold font-['Space_Grotesk'] uppercase tracking-widest hover:border-[#ba9eff] transition-all">
          Load More Masterpieces
        </button>
      </div>
    </div>
  );
};
