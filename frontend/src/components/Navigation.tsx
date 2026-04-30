import React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { 
  Home, 
  Clapperboard, 
  Users, 
  Library, 
  Settings, 
  HelpCircle,
  Bell,
  Zap,
  Search,
  LogOut,
  Menu,
  X,
  Aperture
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/stores/authStore';

// Custom icons to match Material Symbols if needed, but Lucide is fine
const NavItem = ({ to, icon: Icon, label, active, collapsed, onClick }: { to: string, icon: any, label: string, active?: boolean, collapsed?: boolean, onClick?: () => void }) => (
  <Link 
    to={to} 
    onClick={onClick}
    className={cn(
      "flex items-center gap-2 px-3 py-2 rounded-lg transition-all duration-300",
      active 
        ? "text-[#00cffc] font-bold bg-gradient-to-b from-[#00cffc]/10 to-transparent scale-[0.98]" 
        : "text-[#dfe4fe]/60 hover:text-[#dfe4fe] hover:bg-[#171f36]"
    )}
  >
    <Icon size={16} className={cn(active && "fill-current")} />
    <span className="font-['Space_Grotesk'] text-xs uppercase tracking-wider">{label}</span>
  </Link>
);

export const Sidebar = ({ collapsed, isMobileMenuOpen, setIsMobileMenuOpen }: { collapsed?: boolean, isMobileMenuOpen?: boolean, setIsMobileMenuOpen?: (v: boolean) => void }) => {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();

  const handleLogout = () => {
    logout();
    navigate('/auth');
  };

  const toggleLanguage = () => {
    const nextLang = i18n.language === 'zh' ? 'en' : 'zh';
    i18n.changeLanguage(nextLang);
  };

  return (
    <>
      {/* Mobile Overlay */}
      {isMobileMenuOpen && (
        <div 
          className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 md:hidden"
          onClick={() => setIsMobileMenuOpen?.(false)}
        />
      )}
      
      <aside className={cn(
        "h-screen fixed left-0 top-0 border-r border-transparent bg-[#0c1326] shadow-[4px_0px_24px_rgba(0,0,0,0.5)] flex flex-col py-8 px-4 z-50 transition-all duration-300",
        collapsed ? "w-20" : "w-64",
        isMobileMenuOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
      )}>
        <div className="mb-10 px-2 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#00cffc] to-[#0088ff] flex items-center justify-center shadow-[0_0_20px_rgba(0,207,252,0.4)] shrink-0">
              <Aperture size={24} className="text-black" />
            </div>
            {!collapsed && (
              <div>
                <h1 className="text-xl font-bold tracking-tighter text-transparent bg-clip-text bg-gradient-to-r from-[#00cffc] to-[#0088ff] drop-shadow-[0_0_15px_rgba(0,207,252,0.5)] font-['Space_Grotesk'] animate-gradient-x">光希</h1>
                <p className="font-['Space_Grotesk'] text-[10px] tracking-wider text-[#a5aac2]/60">视频内容创作平台</p>
              </div>
            )}
          </div>
          <button className="md:hidden text-[#6f758b]" onClick={() => setIsMobileMenuOpen?.(false)}>
            <X size={24} />
          </button>
        </div>

        <nav className="flex-1 space-y-2">
          <NavItem to="/" icon={Home} label={t('nav.home')} active={location.pathname === '/'} collapsed={collapsed} onClick={() => setIsMobileMenuOpen?.(false)} />
          <NavItem to="/projects" icon={Clapperboard} label={t('nav.projects')} active={location.pathname.startsWith('/projects')} collapsed={collapsed} onClick={() => setIsMobileMenuOpen?.(false)} />
          {/* 社区入口已隐藏（保留代码便于回滚） - 2026-04-30
          <NavItem to="/community" icon={Users} label={t('nav.community')} active={location.pathname === '/community'} collapsed={collapsed} onClick={() => setIsMobileMenuOpen?.(false)} />
          */}
          <NavItem to="/library" icon={Library} label={t('nav.library')} active={location.pathname === '/library'} collapsed={collapsed} onClick={() => setIsMobileMenuOpen?.(false)} />
        </nav>

        <div className="mt-auto pt-6 border-t border-[#41475b]/20 space-y-1">
          <NavItem to="/settings" icon={Settings} label={t('nav.settings')} active={location.pathname === '/settings'} collapsed={collapsed} onClick={() => setIsMobileMenuOpen?.(false)} />
          <NavItem to="/help" icon={HelpCircle} label={t('nav.help')} active={location.pathname === '/help'} collapsed={collapsed} onClick={() => setIsMobileMenuOpen?.(false)} />
          
          {user && (
            collapsed ? (
              // 收缩状态：只显示退出图标
              <button
                onClick={handleLogout}
                className="flex items-center justify-center w-full py-3 mt-2 text-[#6f758b] hover:text-[#ff59e3] transition-colors rounded-lg hover:bg-[#171f36]"
                title="Logout"
              >
                <LogOut size={20} />
              </button>
            ) : (
              // 展开状态：完整用户卡片
              <div className="flex items-center gap-3 px-4 py-4 mt-4 bg-[#171f36]/40 rounded-xl">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#00cffc] to-[#0088ff] flex items-center justify-center shrink-0">
                  <span className="text-black text-xs font-bold uppercase">
                    {user.username?.charAt(0) || 'U'}
                  </span>
                </div>
                <div className="overflow-hidden flex-1">
                  <p className="text-xs font-bold truncate">{user.username}</p>
                  <p className="text-[9px] text-[#00c0ea] font-['Space_Grotesk'] uppercase">{user.plan_type || 'free'}</p>
                </div>
                <button onClick={handleLogout} className="text-[#6f758b] hover:text-[#ff59e3] transition-colors shrink-0" title="Logout">
                  <LogOut size={14} />
                </button>
              </div>
            )
          )}
        </div>
      </aside>
    </>
  );
};

export const TopBar = ({ collapsed, setIsMobileMenuOpen }: { collapsed?: boolean, setIsMobileMenuOpen?: (v: boolean) => void }) => {
  const { t, i18n } = useTranslation();
  const { token, user, logout } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = () => {
    logout();
    navigate('/auth');
  };

  const toggleLanguage = () => {
    const nextLang = i18n.language === 'zh' ? 'en' : 'zh';
    i18n.changeLanguage(nextLang);
  };

  return (
    <header className="fixed top-0 left-0 right-0 h-16 z-50 bg-[#0c1326]/90 backdrop-blur-xl border-b border-[#41475b]/30 flex justify-between items-center px-4 md:px-8 transition-all duration-300">
      <div className="flex items-center gap-8">
        <Link to="/" className="flex items-center gap-3 group">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#00cffc] to-[#0088ff] flex items-center justify-center shadow-lg shadow-[#00cffc]/20 shrink-0 group-hover:scale-105 transition-transform">
            <Clapperboard size={18} className="text-black" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tighter text-transparent bg-clip-text bg-gradient-to-r from-[#00cffc] to-[#0088ff] drop-shadow-[0_0_8px_rgba(0,207,252,0.3)] font-['Space_Grotesk']">光希</h1>
          </div>
        </Link>
        
        <nav className="hidden md:flex items-center gap-1">
          <NavItem to="/" icon={Home} label={t('nav.home')} active={location.pathname === '/'} />
          <NavItem to="/projects" icon={Clapperboard} label={t('nav.projects')} active={location.pathname.startsWith('/projects')} />
          {/* 社区入口已隐藏（保留代码便于回滚） - 2026-04-30
          <NavItem to="/community" icon={Users} label={t('nav.community')} active={location.pathname === '/community'} />
          */}
          <NavItem to="/library" icon={Library} label={t('nav.library')} active={location.pathname === '/library'} />
        </nav>
      </div>

      <div className="flex items-center gap-4 md:gap-6">
        <button
          onClick={toggleLanguage}
          className="px-3 py-1.5 rounded-lg bg-[#171f36] border border-[#41475b]/50 hover:border-[#00cffc] text-[#a5aac2] hover:text-[#00cffc] transition-all font-['Space_Grotesk'] text-[10px] font-bold uppercase tracking-widest"
        >
          {t('common.switchLang')}
        </button>
        {token ? (
          <div className="flex items-center gap-4">
            <Link to="/settings" className="text-[#dfe4fe]/70 hover:text-[#00cffc] transition-colors"><Settings size={18} /></Link>
            <button onClick={handleLogout} className="text-[#dfe4fe]/70 hover:text-[#ff59e3] transition-colors" title="Logout"><LogOut size={18} /></button>
            <div className="hidden sm:flex items-center gap-2 pl-4 border-l border-[#41475b]/30">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#00cffc] to-[#0088ff] flex items-center justify-center shrink-0">
                <span className="text-black text-xs font-bold uppercase">
                  {user?.username?.charAt(0) || 'U'}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <Link 
            to="/auth"
            className="bg-[#00cffc] px-6 py-2 rounded-lg text-black font-black font-['Space_Grotesk'] text-xs uppercase tracking-tighter shadow-lg shadow-[#00cffc]/30 hover:shadow-[#00cffc]/50 transition-all hover:scale-105"
          >
            {t('common.signIn')}
          </Link>
        )}
        <button className="md:hidden text-[#dfe4fe]" onClick={() => setIsMobileMenuOpen?.(true)}>
          <Menu size={24} />
        </button>
      </div>
    </header>
  );
};

