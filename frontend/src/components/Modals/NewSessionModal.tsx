import React from 'react';
import { Plus, BookOpen } from 'lucide-react';

interface NewSessionModalProps {
  visible: boolean;
  sessionName: string;
  startChapterTitle: string | null;
  onNameChange: (name: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

export const NewSessionModal: React.FC<NewSessionModalProps> = ({
  visible,
  sessionName,
  startChapterTitle,
  onNameChange,
  onConfirm,
  onCancel,
}) => {
  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6 backdrop-blur-md bg-black/40">
      <div className="bg-slate-900 border border-white/10 rounded-3xl p-8 max-w-md w-full shadow-2xl animate-in zoom-in-95 duration-200">
        <h3 className="text-xl font-bold text-white mb-2 flex items-center gap-2">
          <Plus className="w-5 h-5 text-amber-500" />
          开启新的平行宇宙
        </h3>
        <div className="mb-6 p-3 bg-white/5 border border-white/5 rounded-xl">
          <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">起始背景</div>
          <div className="text-sm text-slate-300 flex items-center gap-2">
            <BookOpen className="w-3.5 h-3.5 text-sky-400" />
            {startChapterTitle ? `从章节: ${startChapterTitle}` : "从小说开篇/全局背景开始"}
          </div>
        </div>
        <p className="text-slate-400 text-sm mb-6 leading-relaxed">
          为这个全新的命运分支命名。它将作为一个独立的存档点，承载你与 AI 共同编撰的新故事。
        </p>
        <div className="space-y-4">
          <input
            type="text"
            value={sessionName}
            onChange={(e) => onNameChange(e.target.value)}
            placeholder="例如：被改变的抉择 / 隐藏的真相..."
            className="w-full bg-black/30 border border-white/10 rounded-xl px-5 py-4 text-white focus:outline-none focus:border-amber-500 transition-all font-medium"
            autoFocus
          />
          <div className="flex gap-3">
            <button
              onClick={onCancel}
              className="flex-1 px-4 py-3.5 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 font-medium transition-all"
            >
              放弃
            </button>
            <button
              onClick={onConfirm}
              disabled={!sessionName.trim()}
              className="flex-1 px-4 py-3.5 rounded-xl bg-amber-500 hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold transition-all shadow-lg shadow-amber-500/20"
            >
              确认开启
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
