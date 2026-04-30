import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { 
  Music, 
  Image as ImageIcon, 
  Video, 
  Search, 
  Download, 
  Trash2, 
  Filter,
  FileAudio,
  FileImage,
  FileVideo,
  MoreVertical
} from 'lucide-react';
import { motion } from 'motion/react';
import { assetService } from '@/services/api';
import { Asset } from '@/types';
import { cn } from '@/lib/utils';

export const Library = () => {
  const { t } = useTranslation();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    fetchAssets();
  }, []);

  const fetchAssets = async () => {
    try {
      const res = await assetService.getGlobalAssets({ limit: 100 });
      if (res.success) {
        setAssets(res.data.items);
      }
    } catch (error) {
      console.error('Failed to fetch assets:', error);
    } finally {
      setLoading(false);
    }
  };

  const filteredAssets = assets.filter(asset => {
    if (filter === 'all') return true;
    if (filter === 'audio') return asset.asset_type.includes('audio');
    if (filter === 'image') return asset.asset_type.includes('image') || asset.asset_type.includes('frame');
    if (filter === 'video') return asset.asset_type.includes('video') || asset.asset_type.includes('clip');
    return true;
  });

  const getAssetIcon = (type: string) => {
    if (type.includes('audio')) return <FileAudio size={24} className="text-[#00cffc]" />;
    if (type.includes('image') || type.includes('frame')) return <FileImage size={24} className="text-[#ba9eff]" />;
    if (type.includes('video') || type.includes('clip')) return <FileVideo size={24} className="text-[#ff59e3]" />;
    return <Video size={24} />;
  };

  return (
    <div className="p-4 md:p-8 space-y-8">
      <div>
        <h1 className="text-3xl md:text-4xl font-black font-['Space_Grotesk'] tracking-tighter">
          {t('nav.library')}
        </h1>
        <p className="text-[#a5aac2] font-['Space_Grotesk'] text-xs md:text-sm mt-1 uppercase tracking-widest">
          {t('library.subtitle')}
        </p>
      </div>

      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center bg-[#171f36]/40 p-2 rounded-xl border border-[#41475b]/20 gap-4">
        <div className="flex flex-wrap gap-2 w-full sm:w-auto">
          {([['all', t('library.filterAll')], ['audio', t('library.filterAudio')], ['image', t('library.filterImage')], ['video', t('library.filterVideo')]] as [string, string][]).map(([key, label]) => (
            <button 
              key={key}
              onClick={() => setFilter(key)}
              className={cn(
                "px-4 md:px-6 py-2 rounded-lg text-[10px] md:text-xs font-bold font-['Space_Grotesk'] uppercase tracking-widest transition-all flex-1 sm:flex-none text-center",
                filter === key ? "bg-[#ba9eff] text-black shadow-[0_0_15px_rgba(186,158,255,0.3)]" : "text-[#6f758b] hover:text-[#dfe4fe] bg-[#0c1326] sm:bg-transparent"
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex gap-4 px-4 w-full sm:w-auto justify-end">
          <Search size={18} className="text-[#6f758b]" />
          <Filter size={18} className="text-[#6f758b]" />
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map(i => (
            <div key={i} className="aspect-square bg-[#171f36]/40 rounded-xl border border-[#41475b]/20 relative overflow-hidden">
              <div className="absolute inset-0 -translate-x-full animate-[shimmer_1.5s_infinite] bg-gradient-to-r from-transparent via-white/5 to-transparent"></div>
              <div className="absolute bottom-4 left-4 right-4 h-3 bg-[#41475b]/20 rounded"></div>
            </div>
          ))}
        </div>
      ) : filteredAssets.length > 0 ? (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {filteredAssets.map((asset) => (
            <motion.div 
              key={asset.id}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="group relative aspect-square bg-[#171f36]/70 rounded-xl border border-[#41475b]/20 overflow-hidden hover:border-[#ba9eff] transition-all"
            >
              {asset.asset_type.includes('image') || asset.asset_type.includes('frame') ? (
                <img 
                  src={asset.storage_uri} 
                  alt={asset.filename} 
                  className="w-full h-full object-cover opacity-60 group-hover:opacity-100 transition-opacity"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center p-4">
                  {getAssetIcon(asset.asset_type)}
                  <p className="text-[10px] text-[#6f758b] mt-2 text-center truncate w-full">{asset.filename}</p>
                </div>
              )}
              
              <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-3">
                <button className="p-2 rounded-full bg-[#171f36] text-[#ba9eff] hover:scale-110 transition-transform"><Download size={16} /></button>
                <button className="p-2 rounded-full bg-[#171f36] text-[#ff59e3] hover:scale-110 transition-transform"><Trash2 size={16} /></button>
              </div>
              
              <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button className="text-[#dfe4fe]"><MoreVertical size={16} /></button>
              </div>
            </motion.div>
          ))}
        </div>
      ) : (
        <motion.div 
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-center py-32 bg-gradient-to-b from-[#171f36]/40 to-transparent rounded-3xl border-2 border-dashed border-[#41475b]/30 relative overflow-hidden group"
        >
          <div className="absolute inset-0 bg-[#ba9eff]/5 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"></div>
          <div className="w-24 h-24 bg-[#0c1326] rounded-full flex items-center justify-center mx-auto mb-6 border border-[#41475b]/50 shadow-[0_0_30px_rgba(0,0,0,0.5)] relative z-10">
            <ImageIcon size={40} className="text-[#6f758b] group-hover:text-[#ba9eff] transition-colors duration-500" />
          </div>
          <h3 className="text-2xl font-black font-['Space_Grotesk'] mb-2 text-white relative z-10">{t('library.empty')}</h3>
          <p className="text-[#a5aac2] max-w-md mx-auto relative z-10">{t('library.emptyDesc')}</p>
        </motion.div>
      )}
    </div>
  );
};
