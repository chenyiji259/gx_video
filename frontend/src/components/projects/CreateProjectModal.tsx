import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useTranslation } from 'react-i18next';
import { X, Clapperboard, Sparkles, ArrowRight, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface CreateProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (name: string) => Promise<void>;
  mode?: 'create' | 'rename';
  initialName?: string;
}

export const CreateProjectModal: React.FC<CreateProjectModalProps> = ({ isOpen, onClose, onSubmit, mode = 'create', initialName = '' }) => {
  const { t } = useTranslation();
  const isRename = mode === 'rename';
  const [name, setName] = useState(initialName);
  const [loading, setLoading] = useState(false);

  // Sync name when initialName changes (e.g. for edit mode)
  React.useEffect(() => {
    if (isOpen) setName(initialName);
  }, [isOpen, initialName]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || loading) return;

    setLoading(true);
    try {
      await onSubmit(name);
      setName('');
      onClose();
    } catch (error) {
      console.error('Failed to create project:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          />
          
          <motion.div 
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            className="w-full max-w-lg bg-[#0c1326] border border-[#ba9eff]/20 rounded-3xl overflow-hidden shadow-[0_0_50px_rgba(186,158,255,0.15)] relative z-10"
          >
            {/* Header / Decoration */}
            <div className="h-32 bg-gradient-to-br from-[#ba9eff]/20 to-[#00cffc]/20 relative flex items-center justify-center overflow-hidden">
              <div className="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/carbon-fibre.png')] opacity-20"></div>
              <motion.div 
                animate={{ rotate: 360 }}
                transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
                className="absolute w-64 h-64 border border-[#ba9eff]/10 rounded-full"
              ></motion.div>
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[#ba9eff] to-[#8455ef] flex items-center justify-center shadow-2xl relative z-10">
                <Clapperboard size={32} className="text-black" />
              </div>
              <button 
                onClick={onClose}
                className="absolute top-4 right-4 p-2 rounded-full bg-black/20 hover:bg-black/40 text-[#6f758b] hover:text-white transition-all"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-8 space-y-6">
              <div className="text-center space-y-2">
                <h2 className="text-2xl font-black font-['Space_Grotesk'] tracking-tighter text-white uppercase italic">
                  {isRename ? t('createProjectModal.renameTitle1') : t('createProjectModal.createTitle1')}{' '}
                  <span className="text-[#ba9eff]">
                    {isRename ? t('createProjectModal.renameTitle2') : t('createProjectModal.createTitle2')}
                  </span>
                </h2>
                <p className="text-[#a5aac2] text-xs font-['Space_Grotesk'] uppercase tracking-[0.2em] opacity-60">
                  {isRename ? t('createProjectModal.renameSubtitle') : t('createProjectModal.createSubtitle')}
                </p>
              </div>

              <div className="space-y-2">
                <label className="text-[10px] font-['Space_Grotesk'] text-[#6f758b] uppercase tracking-[0.2em] ml-1">{t('createProjectModal.label')}</label>
                <div className="relative group">
                  <input 
                    autoFocus
                    type="text" 
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t('createProjectModal.placeholder')}
                    className="w-full bg-[#171f36]/40 border border-[#41475b] rounded-xl py-4 pl-5 pr-12 text-[#dfe4fe] focus:border-[#ba9eff] focus:ring-1 focus:ring-[#ba9eff] transition-all outline-none font-['Space_Grotesk'] font-bold tracking-tight"
                  />
                  <div className="absolute right-4 top-1/2 -translate-y-1/2 text-[#ba9eff]">
                    <Sparkles size={18} className={cn(name.length > 0 ? "opacity-100" : "opacity-0", "transition-opacity animate-pulse")} />
                  </div>
                </div>
              </div>

              <div className="flex gap-4 pt-2">
                <button 
                  type="button"
                  onClick={onClose}
                  className="flex-1 py-4 rounded-xl border border-[#41475b] text-[#6f758b] font-bold font-['Space_Grotesk'] uppercase tracking-widest text-[10px] hover:bg-[#171f36] hover:text-white transition-all"
                >
                  {t('createProjectModal.abort')}
                </button>
                <button 
                  disabled={!name.trim() || loading}
                  type="submit"
                  className="flex-[2] py-4 rounded-xl bg-gradient-to-r from-[#ba9eff] to-[#8455ef] text-black font-black font-['Space_Grotesk'] uppercase tracking-widest text-[10px] shadow-lg shadow-[#ba9eff]/20 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-30 disabled:hover:scale-100 transition-all flex items-center justify-center gap-2"
                >
                  {loading ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <>{isRename ? t('createProjectModal.rename') : t('createProjectModal.initialize')} <ArrowRight size={14} /></>
                  )}
                </button>
              </div>
            </form>

            {/* Footer Tip */}
            <div className="px-8 py-4 bg-[#171f36]/30 border-t border-[#41475b]/20 flex items-center gap-3">
              <div className="w-6 h-6 rounded-md bg-[#ba9eff]/10 flex items-center justify-center shrink-0">
                <Sparkles size={12} className="text-[#ba9eff]" />
              </div>
              <p className="text-[9px] text-[#6f758b] leading-tight">
                <strong className="text-[#ba9eff]">DIRECTOR'S NOTE:</strong> {t('createProjectModal.directorNote')}
              </p>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};
