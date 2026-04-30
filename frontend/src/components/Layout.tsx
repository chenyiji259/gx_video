import React, { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { TopBar } from './Navigation';

export const Layout = () => {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const location = useLocation();
  const isWorkbench = location.pathname.includes('/projects/');

  return (
    <div className="min-h-screen bg-[#070d1f] text-[#dfe4fe] flex flex-col overflow-x-hidden">
      {!isWorkbench && <TopBar setIsMobileMenuOpen={setIsMobileMenuOpen} />}
      <main className={`${isWorkbench ? '' : 'pt-16'} flex-1 relative`}>
        <Outlet />
        
        {/* Background Decorative Elements */}
        {!isWorkbench && (
          <>
            <div className="fixed top-1/4 -right-24 w-96 h-96 bg-[#00cffc]/5 blur-[120px] rounded-full -z-10 pointer-events-none"></div>
            <div className="fixed bottom-1/4 -left-24 w-[500px] h-[500px] bg-[#ba9eff]/5 blur-[150px] rounded-full -z-10 pointer-events-none"></div>
          </>
        )}
      </main>
    </div>
  );
};
