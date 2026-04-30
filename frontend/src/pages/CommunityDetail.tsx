import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Play, Heart, Share2, Copy, Music, UserCircle, ArrowLeft } from 'lucide-react';
import { motion } from 'motion/react';

export const CommunityDetail = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [isPlaying, setIsPlaying] = useState(false);
  const [liked, setLiked] = useState(false);

  // Mock data for the masterpiece
  const masterpiece = {
    id,
    title: "Neon Genesis Symphony",
    creator: "CyberDirector_99",
    views: "12.4k",
    likes: "3.2k",
    prompt: "A cyberpunk cityscape at night, neon lights reflecting in puddles. A lone figure walking through the rain, transitioning into a high-speed hovercar chase. Cinematic lighting, anamorphic lens flare, moody atmosphere. Synchronized to a heavy synthwave beat.",
    audioTrack: "Midnight Run - Synthwave Mix",
    tags: ["Cyberpunk", "Synthwave", "Cinematic", "Action"],
    videoUrl: "https://www.w3schools.com/html/mov_bbb.mp4", // Placeholder video
    posterUrl: `https://picsum.photos/seed/${id}/1920/1080`
  };

  return (
    <div className="min-h-[calc(100vh-64px)] bg-[#070d1f] text-white p-6 md:p-10">
      <button 
        onClick={() => navigate('/community')}
        className="flex items-center gap-2 text-[#6f758b] hover:text-[#dfe4fe] transition-colors mb-6 font-['Space_Grotesk'] text-sm uppercase tracking-widest"
      >
        <ArrowLeft size={16} /> {t('community.backToCommunity')}
      </button>

      <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Left Column: Video Player & Main Info */}
        <div className="lg:col-span-2 space-y-6">
          {/* Video Player */}
          <div className="aspect-video bg-black rounded-2xl overflow-hidden border border-[#41475b]/50 relative group shadow-[0_0_50px_rgba(0,0,0,0.5)]">
            <video 
              src={masterpiece.videoUrl} 
              poster={masterpiece.posterUrl}
              controls={isPlaying}
              className="w-full h-full object-cover"
              onPlay={() => setIsPlaying(true)}
              onPause={() => setIsPlaying(false)}
            />
            {!isPlaying && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/40 group-hover:bg-black/20 transition-all">
                <button 
                  onClick={() => setIsPlaying(true)}
                  className="w-20 h-20 bg-[#ba9eff]/20 backdrop-blur-md rounded-full flex items-center justify-center text-[#ba9eff] border border-[#ba9eff]/50 hover:scale-110 hover:bg-[#ba9eff] hover:text-black transition-all shadow-[0_0_30px_rgba(186,158,255,0.3)]"
                >
                  <Play size={32} className="fill-current ml-2" />
                </button>
              </div>
            )}
          </div>

          {/* Title & Actions */}
          <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
            <div>
              <h1 className="text-3xl font-['Space_Grotesk'] font-bold text-white mb-2">{masterpiece.title}</h1>
              <div className="flex items-center gap-4 text-[#6f758b] text-sm">
                <span className="flex items-center gap-1"><Play size={14} /> {masterpiece.views} {t('community.views')}</span>
                <span className="flex items-center gap-1"><Heart size={14} /> {masterpiece.likes} {t('community.likes')}</span>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button 
                onClick={() => setLiked(!liked)}
                className={`p-3 rounded-xl border transition-all ${liked ? 'bg-[#ff59e3]/20 border-[#ff59e3] text-[#ff59e3]' : 'bg-[#171f36] border-[#41475b] text-[#dfe4fe] hover:border-[#ba9eff]'}`}
              >
                <Heart size={20} className={liked ? "fill-current" : ""} />
              </button>
              <button className="p-3 bg-[#171f36] border border-[#41475b] rounded-xl text-[#dfe4fe] hover:border-[#ba9eff] transition-all">
                <Share2 size={20} />
              </button>
              <button className="px-6 py-3 bg-gradient-to-r from-[#ba9eff] to-[#8455ef] text-black font-bold rounded-xl hover:shadow-[0_0_20px_rgba(186,158,255,0.4)] transition-all uppercase tracking-tight flex items-center gap-2">
                <Copy size={18} /> {t('community.remixProject')}
              </button>
            </div>
          </div>
        </div>

        {/* Right Column: Metadata & Details */}
        <div className="space-y-6">
          {/* Creator Info */}
          <div className="bg-[#11192e] border border-[#41475b]/30 rounded-2xl p-6 flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-[#00cffc] to-[#ba9eff] p-[2px]">
              <div className="w-full h-full bg-[#0c1326] rounded-full flex items-center justify-center">
                <UserCircle size={32} className="text-[#a5aac2]" />
              </div>
            </div>
            <div>
              <div className="text-xs text-[#6f758b] font-['Space_Grotesk'] uppercase tracking-widest mb-1">{t('community.directedBy')}</div>
              <div className="font-bold text-lg text-[#dfe4fe]">{masterpiece.creator}</div>
            </div>
            <button className="ml-auto px-4 py-1.5 bg-[#171f36] border border-[#41475b] rounded-full text-xs font-bold text-[#ba9eff] hover:bg-[#ba9eff] hover:text-black transition-colors">
              {t('community.follow')}
            </button>
          </div>

          {/* Audio Track */}
          <div className="bg-[#11192e] border border-[#41475b]/30 rounded-2xl p-6">
            <h3 className="text-xs font-['Space_Grotesk'] text-[#6f758b] uppercase tracking-widest mb-4">{t('community.originalAudio')}</h3>
            <div className="flex items-center gap-3 p-3 bg-[#0c1326] rounded-xl border border-[#41475b]/50">
              <div className="w-10 h-10 rounded bg-[#ba9eff]/20 flex items-center justify-center text-[#ba9eff]">
                <Music size={20} />
              </div>
              <div className="flex-1 overflow-hidden">
                <div className="font-medium text-sm text-[#dfe4fe] truncate">{masterpiece.audioTrack}</div>
                <div className="text-xs text-[#6f758b]">03:42</div>
              </div>
              <button className="p-2 text-[#00cffc] hover:bg-[#00cffc]/10 rounded-full transition-colors">
                <Play size={16} className="fill-current" />
              </button>
            </div>
          </div>

          {/* Prompt Used */}
          <div className="bg-[#11192e] border border-[#41475b]/30 rounded-2xl p-6">
            <h3 className="text-xs font-['Space_Grotesk'] text-[#6f758b] uppercase tracking-widest mb-4">{t('community.directorPrompt')}</h3>
            <p className="text-sm text-[#a5aac2] leading-relaxed italic border-l-2 border-[#ba9eff] pl-4">
              "{masterpiece.prompt}"
            </p>
          </div>

          {/* Tags */}
          <div className="bg-[#11192e] border border-[#41475b]/30 rounded-2xl p-6">
            <h3 className="text-xs font-['Space_Grotesk'] text-[#6f758b] uppercase tracking-widest mb-4">{t('community.tags')}</h3>
            <div className="flex flex-wrap gap-2">
              {masterpiece.tags.map(tag => (
                <span key={tag} className="px-3 py-1 bg-[#171f36] border border-[#41475b] rounded-full text-xs text-[#dfe4fe] hover:border-[#ba9eff] transition-colors cursor-pointer">
                  #{tag}
                </span>
              ))}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};
