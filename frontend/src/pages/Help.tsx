import React, { useState } from 'react';
import { BookOpen, Keyboard, PlayCircle, FileVideo, Music, ChevronRight } from 'lucide-react';
import { motion } from 'motion/react';
import { cn } from '@/lib/utils';

export const Help = () => {
  const [activeTab, setActiveTab] = useState('onboarding');

  const shortcuts = [
    { key: 'Space', action: 'Play / Pause Timeline' },
    { key: 'S', action: 'Split Clip at Playhead' },
    { key: 'Delete / Backspace', action: 'Delete Selected Clip' },
    { key: 'Ctrl + Z', action: 'Undo Last Action' },
    { key: 'Ctrl + Shift + Z', action: 'Redo Action' },
    { key: 'Left Arrow', action: 'Move Playhead Back 1 Frame' },
    { key: 'Right Arrow', action: 'Move Playhead Forward 1 Frame' },
    { key: 'Shift + Scroll', action: 'Horizontal Scroll Timeline' },
    { key: 'Ctrl + Scroll', action: 'Zoom Timeline In/Out' },
  ];

  const workflowSteps = [
    { icon: Music, title: '1. Audio Analysis', desc: 'Upload your track. Our AI analyzes BPM, mood, and structure to create a sonic map.' },
    { icon: FileVideo, title: '2. Director\'s Brief', desc: 'Review the AI-generated narrative and visual style. Tweak prompts to match your vision.' },
    { icon: PlayCircle, title: '3. Storyboard & Shot Plan', desc: 'Approve the shot-by-shot breakdown. Regenerate specific frames until perfect.' },
    { icon: Keyboard, title: '4. Timeline & Export', desc: 'Fine-tune clips in the timeline editor. Render the final 4K masterpiece.' },
  ];

  return (
    <div className="p-6 md:p-10 max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-black font-['Space_Grotesk'] tracking-tighter text-white">Help & Documentation</h1>
        <p className="text-[#a5aac2] font-['Space_Grotesk'] text-sm mt-1 uppercase tracking-widest">Master the AI Director Workflow</p>
      </div>

      <div className="flex flex-col md:flex-row gap-8">
        {/* Sidebar */}
        <div className="w-full md:w-64 space-y-2">
          {[
            { id: 'onboarding', icon: BookOpen, label: 'Getting Started' },
            { id: 'shortcuts', icon: Keyboard, label: 'Keyboard Shortcuts' },
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "w-full flex items-center gap-3 px-4 py-3 rounded-xl font-['Space_Grotesk'] text-sm font-bold uppercase tracking-widest transition-all",
                activeTab === tab.id 
                  ? "bg-[#00cffc]/10 text-[#00cffc] border border-[#00cffc]/30" 
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
          
          {/* Onboarding Tab */}
          {activeTab === 'onboarding' && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
              <h2 className="text-xl font-bold text-white font-['Space_Grotesk']">The VidMuse Workflow</h2>
              <p className="text-[#a5aac2]">Learn how to transform your audio into a cinematic music video in four simple steps.</p>
              
              <div className="space-y-6 mt-8">
                {workflowSteps.map((step, idx) => (
                  <div key={idx} className="flex gap-6 bg-[#0c1326] p-6 rounded-2xl border border-[#41475b]/50 hover:border-[#ba9eff]/50 transition-colors">
                    <div className="w-12 h-12 rounded-full bg-[#171f36] flex items-center justify-center shrink-0 border border-[#41475b]">
                      <step.icon size={24} className="text-[#ba9eff]" />
                    </div>
                    <div>
                      <h3 className="text-lg font-bold text-white mb-2">{step.title}</h3>
                      <p className="text-[#6f758b] text-sm leading-relaxed">{step.desc}</p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-8 p-6 bg-gradient-to-r from-[#ba9eff]/10 to-transparent border border-[#ba9eff]/30 rounded-2xl flex items-center justify-between">
                <div>
                  <h4 className="text-white font-bold mb-1">Ready to create?</h4>
                  <p className="text-sm text-[#a5aac2]">Start your first project in the Workbench.</p>
                </div>
                <button className="px-6 py-2 bg-[#ba9eff] text-black font-bold rounded-xl hover:shadow-[0_0_20px_rgba(186,158,255,0.4)] transition-all flex items-center gap-2">
                  Go to Projects <ChevronRight size={16} />
                </button>
              </div>
            </motion.div>
          )}

          {/* Shortcuts Tab */}
          {activeTab === 'shortcuts' && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
              <h2 className="text-xl font-bold text-white font-['Space_Grotesk']">Keyboard Shortcuts</h2>
              <p className="text-[#a5aac2]">Speed up your editing process in the Timeline Editor with these hotkeys.</p>
              
              <div className="bg-[#0c1326] rounded-2xl border border-[#41475b]/50 overflow-hidden">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-[#171f36] border-b border-[#41475b]/50">
                      <th className="p-4 text-xs font-['Space_Grotesk'] text-[#6f758b] uppercase tracking-widest">Shortcut</th>
                      <th className="p-4 text-xs font-['Space_Grotesk'] text-[#6f758b] uppercase tracking-widest">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shortcuts.map((shortcut, idx) => (
                      <tr key={idx} className="border-b border-[#41475b]/20 last:border-0 hover:bg-[#171f36]/50 transition-colors">
                        <td className="p-4">
                          <span className="px-2 py-1 bg-[#1c253e] border border-[#41475b] rounded text-xs text-[#dfe4fe] font-mono">
                            {shortcut.key}
                          </span>
                        </td>
                        <td className="p-4 text-sm text-[#a5aac2]">{shortcut.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </motion.div>
          )}

        </div>
      </div>
    </div>
  );
};
