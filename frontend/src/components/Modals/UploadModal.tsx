import React from 'react';
import { BookOpen } from 'lucide-react';

interface UploadModalProps {
  visible: boolean;
  uploadTitle: string;
  selectedFileName: string | null;
  onTitleChange: (title: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

export const UploadModal: React.FC<UploadModalProps> = ({
  visible,
  uploadTitle,
  selectedFileName,
  onTitleChange,
  onConfirm,
  onCancel,
}) => {
  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in">
      <div className="bg-slate-800 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl animate-in zoom-in duration-200">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-sky-400" />
          上传小说
        </h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-slate-400 mb-2">小说标题</label>
            <input
              type="text"
              value={uploadTitle}
              onChange={(e) => onTitleChange(e.target.value)}
              placeholder="请输入小说标题"
              className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-sky-500 transition-all"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  onConfirm();
                }
              }}
            />
          </div>
          <div className="text-xs text-slate-500">
            已选择文件: {selectedFileName}
          </div>
          <div className="flex gap-3 pt-2">
            <button
              onClick={onCancel}
              className="flex-1 px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 text-sm transition-all"
            >
              取消
            </button>
            <button
              onClick={onConfirm}
              className="flex-1 px-4 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-600 text-white text-sm transition-all"
            >
              开始上传
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
