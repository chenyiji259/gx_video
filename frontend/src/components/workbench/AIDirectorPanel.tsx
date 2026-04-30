import React, { useState, useEffect, useRef } from 'react';
import { 
  Bot, 
  Send, 
  ChevronRight, 
  MessageSquare, 
  Sparkles, 
  Package,
  Clock
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import ReactMarkdown from 'react-markdown';
import { cn } from '@/lib/utils';

import { useProjectStore } from '@/stores/projectStore';

interface AIDirectorPanelProps {
  project: any;
  messages: any[];
  inputText: string;
  setInputText: (text: string) => void;
  sending: boolean;
  onSendMessage: () => void;
  isChatOpen: boolean;
  setIsChatOpen: (open: boolean) => void;
  pendingDecisions: any[];
  onDecision: (decisionId: string, optionId: string) => void;
}

export const AIDirectorPanel: React.FC<AIDirectorPanelProps> = ({
  project,
  messages,
  inputText,
  setInputText,
  sending,
  onSendMessage,
  isChatOpen,
  setIsChatOpen,
  pendingDecisions,
  onDecision
}) => {
  const [activeTab, setActiveTab] = useState<'chat' | 'prompts' | 'assets'>('chat');
  const { isGenerating, generatingMessage, productionViewStage } = useProjectStore();
  const chatContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: 'smooth'
      });
    }
  }, [messages, pendingDecisions, isGenerating]);

  const tabs = [
    { id: 'chat', label: '对话', icon: MessageSquare },
    { id: 'prompts', label: '提示词', icon: Sparkles },
    { id: 'assets', label: '资产', icon: Package }
  ];

  const workflowStage = project?.current_stage || 'created';

  // 视频制作阶段：对话面板转为只读汇总模式
  const isProductionStage = ['clips_ready', 'timeline_ready', 'export_ready'].includes(workflowStage);

  // based on document, disable input if stage is 'input_ready' or some other background processing.
  // Actually, `input_ready` goes to `audio_analyzed` via background task.
  const isInputDisabled = sending || isGenerating || isProductionStage || workflowStage === 'input_ready' || workflowStage === 'created';

  const renderChatInterface = () => (
    <div className="flex-1 overflow-hidden relative flex flex-col">
      {/* Messages List */}
      <div 
        ref={chatContainerRef}
        className="flex-1 overflow-y-auto p-5 space-y-5 custom-scrollbar scroll-smooth"
      >
        {messages.map((msg, i) => (
          <div key={i} className={cn(
            "flex flex-col gap-1.5 max-w-[92%]",
            msg.role === 'user' ? "ml-auto items-end" : "mr-auto items-start"
          )}>
            {msg.role !== 'user' && (
              <div className="flex items-center gap-2 mb-1">
                <div className="w-6 h-6 rounded-full bg-[#1c253e]/50 flex items-center justify-center shadow-[inset_0_0_5px_rgba(0,207,252,0.3)]">
                  <Bot size={14} className="text-[#00cffc]" />
                </div>
                <span className="text-[11px] font-bold text-[#a5aac2] font-['Space_Grotesk'] tracking-wider">AI 导演助手</span>
              </div>
            )}
            <div className={cn(
              "px-4 py-3 rounded-2xl text-[13px] leading-relaxed font-['Space_Grotesk']",
              msg.role === 'user' ? "bg-gradient-to-r from-[#ba9eff] to-[#8455ef] text-black font-bold rounded-tr-sm" : "bg-[#1c253e]/30 text-[#dfe4fe] border border-[#41475b]/30 rounded-tl-sm relative backdrop-blur-sm"
            )}>
              {msg.role !== 'user' && (
                <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-gradient-to-b from-[#ba9eff] to-[#00cffc] rounded-l-2xl" />
              )}
              <div className={cn(msg.role !== 'user' && "pl-2")}>
                {msg.role === 'user' ? (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                ) : (
                  <div className="prose prose-invert prose-sm max-w-none prose-p:leading-relaxed prose-pre:bg-[#0c1326] prose-pre:border prose-pre:border-[#41475b]/30">
                    <ReactMarkdown>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}

        {/* Pending Decisions — 视频制作阶段不显示确认按钮 */}
        {!isProductionStage && (
        <AnimatePresence>
          {pendingDecisions.map((dec) => (
            <motion.div 
              key={dec.id}
              initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
              className="mt-6 border border-[#41475b]/30 rounded-xl bg-[#0c1326]/50 overflow-hidden shadow-[0_0_20px_rgba(0,0,0,0.5)] relative backdrop-blur-sm"
            >
              <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-[#ba9eff] to-[#ff59e3]" />
              
              <div className="p-5 pl-6 space-y-5">
                 <div className="flex items-center gap-3">
                    <h4 className="font-bold text-[#dfe4fe] text-sm font-['Space_Grotesk']">请选择或确认</h4>
                 </div>
                 
                 <div className="space-y-3 pt-2">
                    {dec.options_payload?.map((opt: any) => (
                      <button 
                        key={opt.id}
                        onClick={() => onDecision(dec.id, opt.id)}
                        className="w-full text-left p-3 bg-[#1c253e]/50 text-[#dfe4fe] rounded-lg text-sm font-bold hover:bg-[#1c253e] hover:border-[#ba9eff] border border-transparent transition-all font-['Space_Grotesk'] tracking-wide"
                      >
                         <div className="font-bold">{opt.title}</div>
                         {opt.summary && <div className="text-xs text-[#a5aac2] mt-1 font-normal tracking-normal">{opt.summary}</div>}
                      </button>
                    ))}
                    {(!dec.options_payload || dec.options_payload.length === 0) && (
                      <>
                        <button 
                          onClick={() => onDecision(dec.id, 'confirm')}
                          className="w-full py-2.5 bg-gradient-to-r from-[#ba9eff] to-[#8455ef] text-black rounded-lg text-sm font-bold hover:opacity-90 transition-all flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(186,158,255,0.3)] font-['Space_Grotesk'] tracking-widest"
                        >
                           确认并继续
                        </button>
                        <button 
                          onClick={() => onDecision(dec.id, 'regenerate')}
                          className="w-full py-2.5 bg-[#1c253e]/50 text-[#dfe4fe] rounded-lg text-sm font-bold hover:bg-[#1c253e] transition-all font-['Space_Grotesk'] tracking-widest border border-transparent hover:border-[#41475b]/50"
                        >
                           重新生成
                        </button>
                      </>
                    )}
                 </div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        )}

        {/* 视频制作阶段只读提示 */}
        {isProductionStage && productionViewStage === 'clips_generating' && (
          <div className="mx-5 my-4 p-4 bg-[#0c1326]/60 border border-[#00cffc]/20 rounded-xl space-y-2">
            <p className="text-xs font-bold text-[#00cffc] font-['Space_Grotesk'] tracking-wide">视频制作进行中</p>
            <p className="text-[11px] text-[#a5aac2] leading-relaxed">
              以上为完整的创意对话和决策记录。九宫格与视频制作阶段的主要操作已移动到中间工作台，右侧面板保留流程说明与历史沟通，不再承载主操作按钮。
            </p>
          </div>
        )}
        {isProductionStage && productionViewStage !== 'clips_generating' && workflowStage === 'clips_ready' && (
          <div className="mx-5 my-4 p-4 bg-[#0c1326]/60 border border-[#00cffc]/20 rounded-xl space-y-2">
            <p className="text-xs font-bold text-[#00cffc] font-['Space_Grotesk'] tracking-wide">视频片段已完成</p>
            <p className="text-[11px] text-[#a5aac2] leading-relaxed">
              当前所有视频片段已生成完成。你可以在中间工作台预览 clip、单独重生成某个镜头，或继续进入时间线合成。
            </p>
          </div>
        )}
        {isProductionStage && productionViewStage !== 'clips_generating' && workflowStage === 'timeline_ready' && (
          <div className="mx-5 my-4 p-4 bg-[#0c1326]/60 border border-[#00cffc]/20 rounded-xl space-y-2">
            <p className="text-xs font-bold text-[#00cffc] font-['Space_Grotesk'] tracking-wide">视频合成已就绪</p>
            <p className="text-[11px] text-[#a5aac2] leading-relaxed">
              当前视频片段生成已结束，项目已进入视频合成阶段。中间工作台会展示连续播放预览、时间线轨道和完整合成入口。
            </p>
          </div>
        )}
        {isProductionStage && productionViewStage !== 'clips_generating' && workflowStage === 'export_ready' && (
          <div className="mx-5 my-4 p-4 bg-[#0c1326]/60 border border-[#00cffc]/20 rounded-xl space-y-2">
            <p className="text-xs font-bold text-[#00cffc] font-['Space_Grotesk'] tracking-wide">视频导出阶段</p>
            <p className="text-[11px] text-[#a5aac2] leading-relaxed">
              当前项目已进入导出阶段。中间工作台会展示导出分辨率选择、导出记录与最终下载入口。
            </p>
          </div>
        )}
        {!isProductionStage && workflowStage === 'shot_plan_ready' && (
          <div className="mx-5 my-4 p-4 bg-[#0c1326]/60 border border-[#ba9eff]/20 rounded-xl space-y-2">
            <p className="text-xs font-bold text-[#ba9eff] font-['Space_Grotesk'] tracking-wide">九宫格制作阶段</p>
            <p className="text-[11px] text-[#a5aac2] leading-relaxed">
              当前仍处于九宫格与首尾帧准备阶段。只有九宫格全部生成并切分完成，项目进入 storyboard_ready 后，才能开始真正的视频片段生成。
            </p>
          </div>
        )}
        {!isProductionStage && workflowStage === 'storyboard_ready' && (
          <div className="mx-5 my-4 p-4 bg-[#0c1326]/60 border border-[#00cffc]/20 rounded-xl space-y-2">
            <p className="text-xs font-bold text-[#00cffc] font-['Space_Grotesk'] tracking-wide">九宫格已完成</p>
            <p className="text-[11px] text-[#a5aac2] leading-relaxed">
              当前九宫格与首尾帧已准备完成，项目已进入 storyboard_ready。现在可以开始真正的视频片段生成。
            </p>
          </div>
        )}
      </div>

      {/* Input Box — 视频制作阶段隐藏 */}
      {!isProductionStage && (
      <div className="p-4 bg-[#0c1326]/80 border-t border-[#41475b]/30 backdrop-blur-md">
         <div className="relative group">
            <textarea 
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), onSendMessage())}
              placeholder={isInputDisabled ? (generatingMessage || "处理中，请稍候...") : "向 AI 导演提问或输入指令..."}
              disabled={isInputDisabled}
              className="w-full h-12 bg-[#1c253e]/50 border border-[#41475b]/50 rounded-full pl-5 pr-12 py-3.5 text-xs text-[#dfe4fe] placeholder-[#a5aac2] focus:outline-none focus:border-[#ba9eff] focus:shadow-[0_0_15px_rgba(186,158,255,0.2)] transition-all resize-none overflow-hidden disabled:opacity-50 font-['Space_Grotesk']"
            />
            <button 
              onClick={onSendMessage}
              disabled={isInputDisabled || !inputText.trim()}
              className="absolute right-2 top-1.5 bottom-1.5 w-9 bg-gradient-to-r from-[#ba9eff] to-[#8455ef] text-black rounded-full flex items-center justify-center hover:shadow-[0_0_10px_rgba(186,158,255,0.5)] transition-all disabled:opacity-50 disabled:hover:shadow-none"
            >
              <Send size={14} />
            </button>
         </div>
      </div>
      )}
    </div>
  );

  const renderSetupStage = () => (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="p-5 flex items-center justify-between border-b border-[#41475b]/30 bg-[#0c1326]/50 backdrop-blur-md">
         <div className="flex items-center gap-3">
            <h3 className="text-[15px] font-bold text-[#dfe4fe] tracking-wide font-['Space_Grotesk']">创作向导</h3>
         </div>
         <button onClick={() => setIsChatOpen(false)} className="text-[#a5aac2] hover:text-[#ba9eff] transition-colors md:hidden"><ChevronRight size={18} /></button>
      </div>
      <div className="p-5 flex flex-col gap-4 overflow-y-auto flex-1">
        <div className="border border-[#41475b]/30 rounded-xl bg-[#1c253e]/30 overflow-hidden backdrop-blur-sm">
          <div className="p-4 space-y-3 text-sm text-[#dfe4fe] leading-relaxed font-['Space_Grotesk']">
            <p>欢迎来到 VidMuse，您的 AI 音乐视频创作平台。</p>
            <p>请在左侧上传音乐，填写创意描述，并点击“开始创作”。</p>
          </div>
        </div>
      </div>
    </div>
  );

  const renderDefaultChat = () => (
    <>
      <div className="p-5 flex items-center justify-between border-b border-[#41475b]/30 bg-[#0c1326]/50 backdrop-blur-md">
         <div className="flex items-center gap-3">
            <h3 className="text-[15px] font-bold text-[#dfe4fe] tracking-wide font-['Space_Grotesk']">AI Director</h3>
            <div className="flex items-center gap-1.5 px-2 py-0.5 bg-[#00cffc]/10 border border-[#00cffc]/20 rounded-full shadow-[0_0_10px_rgba(0,207,252,0.2)]">
               <div className="w-1.5 h-1.5 rounded-full bg-[#00cffc] animate-pulse" />
               <span className="text-[10px] font-bold text-[#00cffc] tracking-widest font-['Space_Grotesk']">在线</span>
            </div>
         </div>
         <button onClick={() => setIsChatOpen(false)} className="text-[#a5aac2] hover:text-[#00cffc] transition-colors md:hidden"><ChevronRight size={18} /></button>
      </div>

      {renderChatInterface()}
    </>
  );

  return (
    <>
      {isChatOpen && (
        <div 
          className="fixed inset-0 bg-black/50 z-30 md:hidden backdrop-blur-sm"
          onClick={() => setIsChatOpen(false)}
        />
      )}
      <aside className={cn(
        "bg-[#070d1f]/80 border-l border-[#41475b]/30 flex flex-col transition-all duration-300 z-40 shrink-0 absolute md:relative h-full right-0 backdrop-blur-md shadow-[-10px_0_30px_rgba(0,0,0,0.3)]",
        isChatOpen ? "translate-x-0 w-[340px]" : "translate-x-full w-[340px] md:w-0 md:translate-x-0 md:border-l-0 overflow-hidden"
      )}>
        {workflowStage === 'created' ? renderSetupStage() : renderDefaultChat()}
      </aside>
    </>
  );
};
