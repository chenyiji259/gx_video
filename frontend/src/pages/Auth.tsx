import React, { useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { motion } from 'motion/react';
import { Play, Mail, Lock, ArrowRight } from 'lucide-react';
import { toast } from 'sonner';
import { useAuthStore } from '@/stores/authStore';

export const Auth = () => {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const { t } = useTranslation();
  const { token, user, performLogin, performRegister } = useAuthStore();
  const location = useLocation();

  const from = location.state?.from?.pathname || '/projects';

  // 已登录时直接重定向，避免 useEffect + navigate 双重触发闪烁
  if (token && user) {
    return <Navigate to={from} replace />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    
    // Using email field as username for our backend
    const credentials = { username: email, password };
    
    let success = false;
    if (isLogin) {
      success = await performLogin(credentials);
    } else {
      success = await performRegister(credentials);
    }

    setIsLoading(false);
    if (success) {
      toast.success(isLogin ? t('auth.loginSuccess') : t('auth.registerSuccess'));
      // 登录成功后 state 更新，组件顶部的 Navigate 会自动接管跳转，无需手动 navigate
    } else {
      toast.error(isLogin ? t('auth.loginFail') : t('auth.registerFail'));
    }
  };

  return (
    <div className="min-h-screen bg-[#070d1f] flex items-center justify-center relative overflow-hidden">
      {/* Background Elements */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-[#ba9eff]/10 blur-[120px] rounded-full pointer-events-none"></div>
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-[#00cffc]/10 blur-[120px] rounded-full pointer-events-none"></div>

      <div className="w-full max-w-5xl grid grid-cols-1 md:grid-cols-2 gap-8 p-8 relative z-10">
        
        {/* Left Side: Branding & Visual */}
        <div className="hidden md:flex flex-col justify-center space-y-8 pr-12">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#ba9eff] to-[#00cffc] flex items-center justify-center shadow-[0_0_20px_rgba(186,158,255,0.4)]">
              <Play size={20} className="text-black ml-1" fill="currentColor" />
            </div>
            <span className="text-2xl font-['Space_Grotesk'] font-bold tracking-tighter text-white">
              光<span className="text-[#ba9eff]">希</span>
            </span>
          </div>
          
          <h1 className="text-5xl font-['Space_Grotesk'] font-bold text-white leading-tight">
            {t('auth.visualizeYour')} <br/>
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#ba9eff] to-[#00cffc]">{t('auth.sonicSignature')}</span>
          </h1>
          
          <p className="text-[#6f758b] text-lg">
            {t('auth.brandDesc')}
          </p>

          <div className="flex items-center gap-4 mt-8">
            <div className="flex -space-x-4">
              {[1, 2, 3, 4].map(i => (
                <img key={i} src={`https://picsum.photos/seed/user${i}/100/100`} className="w-10 h-10 rounded-full border-2 border-[#070d1f]" alt="User" />
              ))}
            </div>
            <div className="text-sm text-[#a5aac2]">
              <strong className="text-white">10,000+</strong> {t('auth.creatorsJoined')}
            </div>
          </div>
        </div>

        {/* Right Side: Auth Form */}
        <motion.div 
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          className="bg-[#11192e]/80 backdrop-blur-xl border border-[#41475b]/50 rounded-3xl p-10 shadow-2xl"
        >
          <div className="mb-8">
            <h2 className="text-3xl font-['Space_Grotesk'] font-bold text-white mb-2">
              {isLogin ? t('auth.welcomeBack') : t('auth.createAccount')}
            </h2>
            <p className="text-[#6f758b]">
              {isLogin ? t('auth.signInDesc') : t('auth.signUpDesc')}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <label className="text-xs font-['Space_Grotesk'] text-[#a5aac2] uppercase tracking-widest">{t('auth.usernameLabel')}</label>
              <div className="relative">
                <input 
                  type="text" 
                  required 
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-[#0c1326] border border-[#41475b] rounded-xl pl-10 pr-4 py-3 text-white focus:border-[#ba9eff] focus:ring-1 focus:ring-[#ba9eff] transition-all outline-none" 
                  placeholder={t('auth.usernamePlaceholder')}
                />
                <Mail size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6f758b]" />
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <label className="text-xs font-['Space_Grotesk'] text-[#a5aac2] uppercase tracking-widest">{t('auth.passwordLabel')}</label>
                {isLogin && <a href="#" className="text-xs text-[#ba9eff] hover:underline">{t('auth.forgotPassword')}</a>}
              </div>
              <div className="relative">
                <input 
                  type="password" 
                  required 
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-[#0c1326] border border-[#41475b] rounded-xl pl-10 pr-4 py-3 text-white focus:border-[#ba9eff] focus:ring-1 focus:ring-[#ba9eff] transition-all outline-none" 
                  placeholder="••••••••" 
                />
                <Lock size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6f758b]" />
              </div>
            </div>

            <button disabled={isLoading} type="submit" className="w-full bg-gradient-to-r from-[#ba9eff] to-[#8455ef] text-black font-bold py-3 rounded-xl hover:shadow-[0_0_20px_rgba(186,158,255,0.4)] disabled:opacity-50 transition-all flex items-center justify-center gap-2 mt-4">
              {isLoading ? t('auth.processing') : (isLogin ? t('auth.signIn') : t('auth.signUp'))} {!isLoading && <ArrowRight size={18} />}
            </button>
          </form>

          <p className="mt-8 text-center text-sm text-[#6f758b]">
            {isLogin ? t('auth.noAccount') : t('auth.hasAccount')}{' '}
            <button onClick={() => setIsLogin(!isLogin)} className="text-[#ba9eff] hover:underline font-medium">
              {isLogin ? t('auth.signUpLink') : t('auth.signInLink')}
            </button>
          </p>
        </motion.div>
      </div>
    </div>
  );
};
