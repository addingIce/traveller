import React from 'react';
import { Save } from 'lucide-react';

interface BookmarkModalProps {
  visible: boolean;
  bookmarkName: string;
  onNameChange: (name: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

export const BookmarkModal: React.FC<BookmarkModalProps> = ({
  visible,
  bookmarkName,
  onNameChange,
  onConfirm,
  onCancel,
}) => {
  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in">
      <div className="bg-slate-800 border border-white/10 rounded-2xl p-6 w-full max-w-sm shadow-2xl animate-in zoom-in duration-200">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-amber-400">
          <Save className="w-5 h-5" />
          创建书签
        </h3>
        <p className="text-xs text-slate-400 mb-4">保存当前故事节点以便稍后分支到"平行宇宙"</p>
        <input
          type="text"
          value={bookmarkName}
          onChange={(e) => onNameChange(e.target.value)}
          className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-2.5 text-sm mb-4 focus:outline-none focus:border-amber-500"
          placeholder="书签名称"
          autoFocus
        />
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 text-sm"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-600 text-white text-sm"
          >
            确定
          </button>
        </div>
      </div>
    </div>
  );
};
