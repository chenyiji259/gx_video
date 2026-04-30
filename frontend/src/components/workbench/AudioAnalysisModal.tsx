import React from 'react';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'motion/react';
import { X, Activity, BarChart2, Music } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Cell } from 'recharts';

interface AudioAnalysisModalProps {
  isOpen: boolean;
  onClose: () => void;
  bpmData?: Array<{ time: string; bpm?: number; energy?: number }>;
  structureData?: Array<{ name: string; duration: number; fill?: string }>;
}

export const AudioAnalysisModal = ({ isOpen, onClose, bpmData = [], structureData = [] }: AudioAnalysisModalProps) => {
  const { t } = useTranslation();
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div 
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
        >
          <motion.div 
            initial={{ scale: 0.95, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: 20 }}
            onClick={(e) => e.stopPropagation()}
            className="bg-[#0c1326] border border-[#41475b] rounded-3xl p-8 max-w-4xl w-full shadow-[0_0_50px_rgba(0,0,0,0.5)] relative overflow-hidden max-h-[90vh] overflow-y-auto custom-scrollbar"
          >
            <button onClick={onClose} className="absolute top-6 right-6 text-[#6f758b] hover:text-white transition-colors z-20">
              <X size={24} />
            </button>

            <div className="flex items-center gap-3 mb-8">
              <div className="w-12 h-12 rounded-xl bg-[#00cffc]/20 flex items-center justify-center">
                <Activity size={24} className="text-[#00cffc]" />
              </div>
              <div>
                <h2 className="text-2xl font-bold text-white font-['Space_Grotesk']">{t('audioAnalysis.title')}</h2>
                <p className="text-sm text-[#a5aac2] uppercase tracking-widest">{t('audioAnalysis.subtitle')}</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              {/* Energy & BPM Chart */}
              <div className="bg-[#11192e] border border-[#41475b]/30 rounded-2xl p-6">
                <h3 className="text-sm font-bold text-white font-['Space_Grotesk'] mb-6 flex items-center gap-2">
                  <BarChart2 size={16} className="text-[#ba9eff]" /> {t('audioAnalysis.energyBpmTitle')}
                </h3>
                <div className="h-64">
                  {bpmData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={bpmData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <defs>
                          <linearGradient id="colorEnergy" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#ba9eff" stopOpacity={0.8}/>
                            <stop offset="95%" stopColor="#ba9eff" stopOpacity={0}/>
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#41475b" vertical={false} />
                        <XAxis dataKey="time" stroke="#6f758b" fontSize={10} tickLine={false} axisLine={false} />
                        <YAxis stroke="#6f758b" fontSize={10} tickLine={false} axisLine={false} />
                        <Tooltip 
                          contentStyle={{ backgroundColor: '#171f36', borderColor: '#41475b', borderRadius: '8px', color: '#fff' }}
                          itemStyle={{ color: '#ba9eff' }}
                        />
                        <Area type="monotone" dataKey="energy" stroke="#ba9eff" fillOpacity={1} fill="url(#colorEnergy)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-full flex items-center justify-center text-xs text-[#6f758b]">暂无能量曲线数据</div>
                  )}
                </div>
              </div>

              {/* Song Structure */}
              <div className="bg-[#11192e] border border-[#41475b]/30 rounded-2xl p-6">
                <h3 className="text-sm font-bold text-white font-['Space_Grotesk'] mb-6 flex items-center gap-2">
                  <Music size={16} className="text-[#00cffc]" /> {t('audioAnalysis.songStructureTitle')}
                </h3>
                <div className="h-64">
                  {structureData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={structureData} layout="vertical" margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#41475b" horizontal={false} />
                        <XAxis type="number" stroke="#6f758b" fontSize={10} tickLine={false} axisLine={false} />
                        <YAxis dataKey="name" type="category" stroke="#dfe4fe" fontSize={12} tickLine={false} axisLine={false} width={60} />
                        <Tooltip 
                          cursor={{fill: '#171f36'}}
                          contentStyle={{ backgroundColor: '#171f36', borderColor: '#41475b', borderRadius: '8px', color: '#fff' }}
                        />
                        <Bar dataKey="duration" radius={[0, 4, 4, 0]}>
                          {structureData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.fill || '#41475b'} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-full flex items-center justify-center text-xs text-[#6f758b]">暂无结构分析数据</div>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-8 bg-[#171f36] border border-[#ba9eff]/30 rounded-xl p-6">
              <h4 className="text-sm font-bold text-[#ba9eff] mb-2">{t('audioAnalysis.directorSummaryTitle')}</h4>
              <p className="text-sm text-[#a5aac2] leading-relaxed">{t('audioAnalysis.directorSummaryText')}</p>
            </div>

          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
