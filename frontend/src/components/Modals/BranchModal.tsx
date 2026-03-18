import React from 'react';
import { Save } from 'lucide-react';

interface BranchModalProps {
  visible: boolean;
  branchBookmarkName: string | null;
  branchSessionName: string;
  onNameChange: (name: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

export const BranchModal: React.FC<BranchModalProps> = ({
  visible,
  branchBookmarkName,
  branchSessionName,
  onNameChange,
  onConfirm,
  onCancel,
}) => {
  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in">
      <div className="bg-slate-800 border border-white/10 rounded-2xl p-6 w-full max-w-sm shadow-2xl animate-in zoom-in duration-200">
        <h3 className="text-lg font-semibold mb-2 flex items-center gap-2 text-amber-400">
          <Save className="w-5 h-5" />
          从书签开启分支
        </h3>
        <p className="text-xs text-slate-400 mb-4">
          {branchBookmarkName ? `基于书签「${branchBookmarkName}」创建新的平行宇宙` : "基于书签创建新的平行宇宙"}
        </p>
        <input
          type="text"
          value={branchSessionName}
          onChange={(e) => onNameChange(e.target.value)}
          className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-2.5 text-sm mb-4 focus:outline-none focus:border-amber-500"
          placeholder="分支名称"
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
            disabled={!branchSessionName.trim()}
            className="flex-1 px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-600 text-white text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
};
