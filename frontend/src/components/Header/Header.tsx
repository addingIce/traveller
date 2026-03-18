import React from 'react';
import { Brain, Settings } from 'lucide-react';

interface HeaderProps {
  onOpenConfig: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onOpenConfig }) => {
  return (
    <header className="border-b border-white/10 px-8 py-4 flex justify-between items-center backdrop-blur-md sticky top-0 z-50">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 bg-gradient-to-br from-sky-400 to-indigo-500 rounded-xl flex items-center justify-center shadow-lg shadow-sky-500/20">
          <Brain className="text-white w-6 h-6" />
        </div>
        <span className="text-xl font-bold tracking-tight bg-gradient-to-r from-sky-400 to-white bg-clip-text text-transparent">
          TRAVELLER ENGINE
        </span>
      </div>
      <div className="flex items-center gap-6 text-sm text-slate-400">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
          ZEP Connected
        </div>
        <button
          onClick={onOpenConfig}
          className="p-2 rounded-lg bg-white/5 hover:bg-white/10 hover:text-white text-slate-400 transition-all"
          title="系统配置"
        >
          <Settings className="w-5 h-5" />
        </button>
      </div>
    </header>
  );
};
