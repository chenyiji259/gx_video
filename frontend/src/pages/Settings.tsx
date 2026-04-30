import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { User, CreditCard, Settings as SettingsIcon, Shield, Zap, Check, Monitor } from 'lucide-react';
import { motion } from 'motion/react';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { useAuthStore } from '@/stores/authStore';

export const Settings = () => {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState('billing');
  const { user } = useAuthStore();

  const handleSave = () => {
    toast.success(t('settings.account.savedToast'));
  };

  return (
    <div className="p-6 md:p-10 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-black font-['Space_Grotesk'] tracking-tighter text-white">{t('settings.title')}</h1>
        <p className="text-[#a5aac2] font-['Space_Grotesk'] text-sm mt-1 uppercase tracking-widest">{t('settings.subtitle')}</p>
      </div>

      <div className="flex flex-col md:flex-row gap-8">
        {/* Sidebar */}
        <div className="w-full md:w-64 space-y-2">
          {[
            { id: 'account', icon: User, label: t('settings.tabs.account') },
            { id: 'billing', icon: CreditCard, label: t('settings.tabs.billing') },
            { id: 'preferences', icon: SettingsIcon, label: t('settings.tabs.preferences') },
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "w-full flex items-center gap-3 px-4 py-3 rounded-xl font-['Space_Grotesk'] text-sm font-bold uppercase tracking-widest transition-all",
                activeTab === tab.id 
                  ? "bg-[#ba9eff]/10 text-[#ba9eff] border border-[#ba9eff]/30" 
                  : "text-[#6f758b] hover:bg-[#171f36] hover:text-[#dfe4fe] border border-transparent"
              )}
            >
              <tab.icon size={18} />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 bg-[#11192e] border border-[#41475b]/30 rounded-3xl p-8">
          
          {/* Account Tab */}
          {activeTab === 'account' && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
              <h2 className="text-xl font-bold text-white font-['Space_Grotesk']">{t('settings.account.title')}</h2>
              
              <div className="flex items-center gap-6">
                <div className="w-24 h-24 rounded-full bg-gradient-to-br from-[#ba9eff] to-[#8455ef] flex items-center justify-center text-3xl font-black text-black">
                  {user?.username?.charAt(0).toUpperCase() || 'U'}
                </div>
                <button className="px-4 py-2 bg-[#171f36] border border-[#41475b] rounded-lg text-sm text-white hover:border-[#ba9eff] transition-colors">
                  {t('settings.account.changeAvatar')}
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-xs text-[#6f758b] uppercase tracking-widest">{t('settings.account.username')}</label>
                  <input type="text" defaultValue={user?.username || ''} className="w-full bg-[#0c1326] border border-[#41475b] rounded-xl px-4 py-3 text-[#6f758b] outline-none" disabled />
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-[#6f758b] uppercase tracking-widest">{t('settings.account.planType')}</label>
                  <input type="text" defaultValue={user?.plan_type || 'free'} className="w-full bg-[#0c1326] border border-[#41475b] rounded-xl px-4 py-3 text-[#6f758b] outline-none capitalize" disabled />
                </div>
              </div>

              <div className="pt-6 border-t border-[#41475b]/30">
                <h3 className="text-lg font-bold text-white font-['Space_Grotesk'] mb-4">{t('settings.account.security')}</h3>
                <button className="px-4 py-2 bg-[#171f36] border border-[#41475b] rounded-lg text-sm text-white hover:border-[#ba9eff] transition-colors flex items-center gap-2">
                  <Shield size={16} /> {t('settings.account.changePassword')}
                </button>
              </div>

              <div className="flex justify-end pt-4">
                <button onClick={handleSave} className="px-6 py-3 bg-[#ba9eff] text-black font-bold rounded-xl hover:shadow-[0_0_20px_rgba(186,158,255,0.4)] transition-all">
                  {t('settings.account.saveChanges')}
                </button>
              </div>
            </motion.div>
          )}

          {/* Billing Tab */}
          {activeTab === 'billing' && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
              <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-[#171f36] p-6 rounded-2xl border border-[#ba9eff]/30">
              <div>
                <h2 className="text-xl font-bold text-white font-['Space_Grotesk'] flex items-center gap-2">
                    <Zap className="text-[#ba9eff]" /> {t('settings.billing.availableCredits')}
                  </h2>
                  <p className="text-[#a5aac2] text-sm mt-1">{t('settings.billing.creditsDesc')}</p>
                </div>
                <div className="text-4xl font-black text-[#ba9eff] font-['Space_Grotesk']">
                  {user?.credits.toLocaleString() || 0} <span className="text-sm text-[#6f758b] font-normal">CR</span>
                </div>
              </div>

              <div>
                <h3 className="text-lg font-bold text-white font-['Space_Grotesk'] mb-6">{t('settings.billing.upgradePlan')}</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Pro Plan */}
                  <div className="bg-[#0c1326] border border-[#41475b] rounded-2xl p-6 relative overflow-hidden group hover:border-[#ba9eff] transition-all">
                    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                      <Zap size={100} className="text-[#ba9eff]" />
                    </div>
                    <h4 className="text-2xl font-bold text-white font-['Space_Grotesk']">Pro</h4>
                    <div className="mt-2 mb-6">
                      <span className="text-3xl font-black text-white">$29</span>
                      <span className="text-[#6f758b]">{t('settings.billing.month')}</span>
                    </div>
                    <ul className="space-y-3 mb-8">
                      {['5,000 Credits/month', '1080p Export Resolution', 'Standard Render Queue', 'Community Access'].map((feature, i) => (
                        <li key={i} className="flex items-center gap-2 text-sm text-[#a5aac2]">
                          <Check size={16} className="text-[#ba9eff]" /> {feature}
                        </li>
                      ))}
                    </ul>
                    <button className="w-full py-3 bg-[#171f36] text-white font-bold rounded-xl border border-[#41475b] hover:border-[#ba9eff] transition-all">
                      {t('settings.billing.currentPlan')}
                    </button>
                  </div>

                  {/* Studio Plan */}
                  <div className="bg-gradient-to-b from-[#171f36] to-[#0c1326] border border-[#00cffc]/50 rounded-2xl p-6 relative overflow-hidden shadow-[0_0_30px_rgba(0,207,252,0.1)]">
                    <div className="absolute top-0 right-0 p-4 opacity-10">
                      <Monitor size={100} className="text-[#00cffc]" />
                    </div>
                    <div className="absolute top-4 right-4 px-3 py-1 bg-[#00cffc]/20 text-[#00cffc] text-[10px] font-bold uppercase tracking-widest rounded-full border border-[#00cffc]/30">
                      {t('settings.billing.recommended')}
                    </div>
                    <h4 className="text-2xl font-bold text-white font-['Space_Grotesk']">Studio</h4>
                    <div className="mt-2 mb-6">
                      <span className="text-3xl font-black text-white">$99</span>
                      <span className="text-[#6f758b]">{t('settings.billing.month')}</span>
                    </div>
                    <ul className="space-y-3 mb-8">
                      {['25,000 Credits/month', '4K Export Resolution', 'Priority Render Queue', 'Custom Watermark', 'API Access'].map((feature, i) => (
                        <li key={i} className="flex items-center gap-2 text-sm text-[#dfe4fe]">
                          <Check size={16} className="text-[#00cffc]" /> {feature}
                        </li>
                      ))}
                    </ul>
                    <button className="w-full py-3 bg-gradient-to-r from-[#00cffc] to-[#0088ff] text-black font-bold rounded-xl hover:shadow-[0_0_20px_rgba(0,207,252,0.4)] transition-all">
                      {t('settings.billing.upgradeToStudio')}
                    </button>
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {/* Preferences Tab */}
          {activeTab === 'preferences' && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
              <h2 className="text-xl font-bold text-white font-['Space_Grotesk']">{t('settings.preferences.title')}</h2>
              
              <div className="space-y-6">
                <div className="flex items-center justify-between p-4 bg-[#0c1326] rounded-xl border border-[#41475b]/50">
                  <div>
                    <h4 className="text-white font-medium">{t('settings.preferences.exportRes')}</h4>
                    <p className="text-sm text-[#6f758b]">{t('settings.preferences.exportResDesc')}</p>
                  </div>
                  <select className="bg-[#171f36] border border-[#41475b] text-white rounded-lg px-4 py-2 outline-none focus:border-[#ba9eff]">
                    <option value="720p">720p (Fast)</option>
                    <option value="1080p">1080p (Standard)</option>
                    <option value="4k">4K (Studio Plan)</option>
                  </select>
                </div>

                <div className="flex items-center justify-between p-4 bg-[#0c1326] rounded-xl border border-[#41475b]/50">
                  <div>
                    <h4 className="text-white font-medium">{t('settings.preferences.emailNotif')}</h4>
                    <p className="text-sm text-[#6f758b]">{t('settings.preferences.emailNotifDesc')}</p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" defaultChecked className="sr-only peer" />
                    <div className="w-11 h-6 bg-[#171f36] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#ba9eff]"></div>
                  </label>
                </div>

                <div className="flex items-center justify-between p-4 bg-[#0c1326] rounded-xl border border-[#41475b]/50">
                  <div>
                    <h4 className="text-white font-medium">{t('settings.preferences.theme')}</h4>
                    <p className="text-sm text-[#6f758b]">{t('settings.preferences.themeDesc')}</p>
                  </div>
                  <div className="px-3 py-1 bg-[#171f36] text-[#6f758b] rounded text-sm border border-[#41475b]">
                    {t('settings.preferences.darkOnly')}
                  </div>
                </div>
              </div>

              <div className="flex justify-end pt-4">
                <button onClick={handleSave} className="px-6 py-3 bg-[#ba9eff] text-black font-bold rounded-xl hover:shadow-[0_0_20px_rgba(186,158,255,0.4)] transition-all">
                  {t('settings.preferences.savePreferences')}
                </button>
              </div>
            </motion.div>
          )}

        </div>
      </div>
    </div>
  );
};
