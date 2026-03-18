import React from 'react';
import { Zap, Target } from 'lucide-react';
import { DirectorMode } from '../../api';

interface ModeSelectorProps {
  mode: DirectorMode;
  onChange: (mode: DirectorMode) => void;
}

export const ModeSelector: React.FC<ModeSelectorProps> = ({ mode, onChange }) => {
  return (
    <div className="px-6 py-2 flex items-center justify-between border-t border-white/5 bg-slate-800/10 backdrop-blur-sm">
      <div className="flex gap-1 bg-black/40 p-1 rounded-xl border border-white/5">
        <button
          onClick={() => onChange(DirectorMode.SANDBOX)}
          className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-2 ${
            mode === DirectorMode.SANDBOX 
            ? 'bg-amber-500 text-white shadow-lg shadow-amber-500/20' 
            : 'text-slate-400 hover:text-white'
          }`}
        >
          <Zap className="w-3 h-3" /> 沙盒模式 A
        </button>
        <button
          onClick={() => onChange(DirectorMode.CONVERGENCE)}
          className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-2 ${
            mode === DirectorMode.CONVERGENCE 
            ? 'bg-indigo-500 text-white shadow-lg shadow-indigo-500/20' 
            : 'text-slate-400 hover:text-white'
          }`}
        >
          <Target className="w-3 h-3" /> 收束模式 B
        </button>
      </div>
      <div className="text-[10px] text-slate-500 font-medium">
        {mode === DirectorMode.SANDBOX 
          ? "当前状态：自由推演中" 
          : "当前状态：剧情引导中"}
      </div>
    </div>
  );
};
