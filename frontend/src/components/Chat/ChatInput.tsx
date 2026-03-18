import React from 'react';
import { Send } from 'lucide-react';

type InputMode = 'free' | 'act' | 'say' | 'think';

interface ChatInputProps {
  value: string;
  mode: InputMode;
  isChatting: boolean;
  isNovelReady: boolean;
  isCurrentSessionRoot: boolean;
  onChange: (value: string) => void;
  onModeChange: (mode: InputMode) => void;
  onSubmit: () => void;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  value,
  mode,
  isChatting,
  isNovelReady,
  isCurrentSessionRoot,
  onChange,
  onModeChange,
  onSubmit,
}) => {
  const getPlaceholder = () => {
    if (isCurrentSessionRoot) {
      return "原始剧情线不可编辑，请创建平行宇宙进行剧情推演...";
    }
    if (!isNovelReady) {
      return "作品尚未就绪，无法进行剧情推演...";
    }
    switch (mode) {
      case 'act': return "执行动作...";
      case 'say': return "说出对白...";
      case 'think': return "心中暗想...";
      default: return "执行动作 / 说出对白 / 心中暗想...";
    }
  };

  const getModeLabel = () => {
    switch (mode) {
      case 'act': return '动作输入模式';
      case 'say': return '对白输入模式';
      case 'think': return '心理输入模式';
      default: return '自由输入';
    }
  };

  const disabled = isChatting || !isNovelReady || isCurrentSessionRoot;

  return (
    <div className="p-4 bg-slate-800/80 border-t border-white/10 backdrop-blur-lg z-20">
      <div className="max-w-4xl mx-auto mb-2 flex items-center justify-between">
        <div className="flex gap-2 text-[10px] font-bold uppercase tracking-widest">
          <button
            onClick={() => onModeChange('free')}
            className={`px-3 py-1 rounded-full border transition-all ${
              mode === 'free' ? 'bg-white/10 border-slate-400 text-slate-200' : 'border-white/10 text-slate-500 hover:text-white'
            }`}
          >
            自由
          </button>
          <button
            onClick={() => onModeChange('act')}
            className={`px-3 py-1 rounded-full border transition-all ${
              mode === 'act' ? 'bg-amber-500/20 border-amber-400 text-amber-200' : 'border-white/10 text-slate-500 hover:text-white'
            }`}
          >
            动作
          </button>
          <button
            onClick={() => onModeChange('say')}
            className={`px-3 py-1 rounded-full border transition-all ${
              mode === 'say' ? 'bg-sky-500/20 border-sky-400 text-sky-200' : 'border-white/10 text-slate-500 hover:text-white'
            }`}
          >
            对白
          </button>
          <button
            onClick={() => onModeChange('think')}
            className={`px-3 py-1 rounded-full border transition-all ${
              mode === 'think' ? 'bg-indigo-500/20 border-indigo-400 text-indigo-200' : 'border-white/10 text-slate-500 hover:text-white'
            }`}
          >
            心理
          </button>
        </div>
        <div className="text-[10px] text-slate-500">
          {getModeLabel()}
        </div>
      </div>
      <form
        onSubmit={(e) => { e.preventDefault(); onSubmit(); }}
        className="flex gap-3 max-w-4xl mx-auto items-center relative"
      >
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          placeholder={getPlaceholder()}
          className={`flex-1 border rounded-full px-6 py-4 text-white focus:outline-none transition-colors shadow-inner ${
            isNovelReady && !isCurrentSessionRoot
              ? 'bg-black/40 border-white/10 focus:border-sky-500 focus:ring-1 focus:ring-sky-500'
              : 'bg-slate-800 border-slate-700 text-slate-500 cursor-not-allowed'
          }`}
        />
        <button
          disabled={isChatting || !value.trim() || !isNovelReady || isCurrentSessionRoot}
          type="submit"
          className="absolute right-2 px-4 py-2 bg-sky-500 hover:bg-sky-400 text-white rounded-full transition-all flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-sky-500/20 font-bold"
        >
          推进 <Send className="w-4 h-4 ml-1" />
        </button>
      </form>
    </div>
  );
};