import React from 'react';
import { LocateFixed, ZoomIn, ZoomOut } from 'lucide-react';

interface GraphToolbarProps {
  graphTypeFilters: Set<string>;
  onFilterChange: (filters: Set<string>) => void;
  onFitView: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onResetZoom: () => void;
}

export const GraphToolbar: React.FC<GraphToolbarProps> = ({
  graphTypeFilters,
  onFilterChange,
  onFitView,
  onZoomIn,
  onZoomOut,
  onResetZoom,
}) => {
  const filterTypes = [
    { key: 'all', label: '全部' },
    { key: 'person', label: '人物' },
    { key: 'place', label: '地点' },
    { key: 'org', label: '组织' },
    { key: 'item', label: '物品' },
    { key: 'concept', label: '概念' },
  ] as const;

  const allTypes = ['person', 'place', 'org', 'item', 'concept'];

  const handleFilterClick = (key: string) => {
    const isAll = key === 'all';
    const newFilters = new Set(graphTypeFilters);

    if (isAll) {
      // 点击"全部"：切换选中/取消所有
      if (allTypes.every(type => newFilters.has(type))) {
        onFilterChange(new Set()); // 取消所有
      } else {
        onFilterChange(new Set(allTypes)); // 选中所有
      }
    } else {
      // 其他按钮：toggle 逻辑
      if (newFilters.has(key)) {
        newFilters.delete(key);
      } else {
        newFilters.add(key);
      }
      onFilterChange(newFilters);
    }
  };

  const isFilterActive = (key: string) => {
    if (key === 'all') {
      return allTypes.every(type => graphTypeFilters.has(type));
    }
    return graphTypeFilters.has(key);
  };

  return (
    <>
      {/* Left: Filter buttons */}
      <div className="absolute top-4 left-4 z-20 flex items-center gap-2 bg-slate-900/80 border border-white/10 rounded-xl p-2 backdrop-blur-sm text-[10px] uppercase tracking-widest text-slate-300">
        {filterTypes.map((t) => (
          <button
            key={t.key}
            onClick={() => handleFilterClick(t.key)}
            className={`px-2 py-1 rounded-lg border transition-all ${
              isFilterActive(t.key)
                ? 'bg-sky-500/20 border-sky-400 text-sky-200'
                : 'border-white/10 text-slate-500 hover:text-white'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Right: Zoom controls */}
      <div className="absolute top-4 right-4 z-20 flex items-center gap-2 bg-slate-900/80 border border-white/10 rounded-xl p-2 backdrop-blur-sm">
        <button
          onClick={onFitView}
          className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-200 transition-colors"
          title="图谱居中（最优尺寸）"
        >
          <LocateFixed className="w-4 h-4" />
        </button>
        <button
          onClick={onZoomIn}
          className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-200 transition-colors"
          title="放大"
        >
          <ZoomIn className="w-4 h-4" />
        </button>
        <button
          onClick={onZoomOut}
          className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-200 transition-colors"
          title="缩小"
        >
          <ZoomOut className="w-4 h-4" />
        </button>
        <button
          onClick={onResetZoom}
          className="px-2 py-1 text-xs rounded-lg bg-white/5 hover:bg-white/10 text-slate-200 transition-colors"
          title="1:1"
        >
          1:1
        </button>
      </div>
    </>
  );
};
