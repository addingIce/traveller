import React from 'react';
import { BookOpen, X, GitBranch } from 'lucide-react';
import { ChapterInfo } from '../../api';

interface ChapterModalProps {
  visible: boolean;
  chapter: ChapterInfo | null;
  onClose: () => void;
  onCreateBranch: (chapter: ChapterInfo) => void;
}

export const ChapterModal: React.FC<ChapterModalProps> = ({
  visible,
  chapter,
  onClose,
  onCreateBranch,
}) => {
  if (!visible || !chapter) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in">
      <div className="bg-slate-800 border border-white/10 rounded-2xl w-full max-w-2xl max-h-[80vh] shadow-2xl flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-white/10 flex justify-between items-center shrink-0">
          <h3 className="text-lg font-semibold text-sky-400 flex items-center gap-2">
            <BookOpen className="w-5 h-5" />
            {chapter.title}
          </h3>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-all"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">
            {chapter.content || chapter.content_preview}
          </p>
        </div>
        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/10 flex justify-end gap-3 shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 text-sm transition-all"
          >
            关闭
          </button>
          <button
            onClick={() => onCreateBranch(chapter)}
            className="px-4 py-2 rounded-xl bg-sky-500 hover:bg-sky-600 text-white text-sm transition-all flex items-center gap-2"
          >
            <GitBranch className="w-4 h-4" />
            从本章开启平行宇宙
          </button>
        </div>
      </div>
    </div>
  );
};
