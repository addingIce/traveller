import React, { useState } from 'react';
import { Network, History, Brain, ChevronRight, PenTool } from 'lucide-react';

const App: React.FC = () => {
    const [activeTab, setActiveTab] = useState<'graph' | 'plot'>('graph');

    return (
        <div className="min-h-screen bg-[#0f172a] text-[#f1f5f9] font-sans selection:bg-sky-500/30">
            {/* Header */}
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
                    <button className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg transition-all">
                        Settings
                    </button>
                </div>
            </header>

            <main className="max-w-[1600px] mx-auto p-8 grid grid-cols-[380px_1fr] gap-8">
                {/* Sidebar */}
                <aside className="space-y-6">
                    <div className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 backdrop-blur-sm">
                        <h2 className="text-sky-400 font-semibold mb-4 flex items-center gap-2">
                            <History className="w-4 h-4" /> 作品档案库
                        </h2>
                        <div className="space-y-2">
                            {['test_novel', '哈利波特与魔法石'].map((novel, i) => (
                                <div
                                    key={novel}
                                    className={`p-3 rounded-xl cursor-pointer transition-all border ${i === 0 ? 'bg-sky-500/10 border-sky-500/50' : 'bg-transparent border-transparent hover:bg-white/5'
                                        }`}
                                >
                                    <div className="font-medium">{novel}</div>
                                    <div className="text-xs text-slate-500 mt-1">
                                        {i === 0 ? '昨天录入 · 1.2k 片段' : '2小时前 · 0.8k 片段'}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 backdrop-blur-sm">
                        <h2 className="text-sky-400 font-semibold mb-4">当前世界统计</h2>
                        <div className="grid grid-cols-2 gap-4 text-center">
                            <div className="bg-white/5 p-4 rounded-xl border border-white/5">
                                <div className="text-2xl font-bold">42</div>
                                <div className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">实体角色</div>
                            </div>
                            <div className="bg-white/5 p-4 rounded-xl border border-white/5">
                                <div className="text-2xl font-bold">158</div>
                                <div className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">物理关系</div>
                            </div>
                        </div>
                    </div>
                </aside>

                {/* Content Area */}
                <section className="space-y-8">
                    {/* Main Visualizer */}
                    <div className="bg-slate-800/50 border border-white/10 rounded-3xl overflow-hidden backdrop-blur-sm shadow-2xl">
                        <div className="px-6 py-4 border-b border-white/10 flex justify-between items-center bg-white/5">
                            <div className="flex gap-1 p-1 bg-black/20 rounded-lg">
                                <button
                                    onClick={() => setActiveTab('graph')}
                                    className={`px-4 py-1.5 rounded-md text-sm transition-all ${activeTab === 'graph' ? 'bg-sky-500 text-white shadow-lg shadow-sky-500/20' : 'text-slate-400 hover:text-white'}`}
                                >
                                    关系图谱
                                </button>
                                <button
                                    onClick={() => setActiveTab('plot')}
                                    className={`px-4 py-1.5 rounded-md text-sm transition-all ${activeTab === 'plot' ? 'bg-sky-500 text-white shadow-lg shadow-sky-500/20' : 'text-slate-400 hover:text-white'}`}
                                >
                                    剧情时间线
                                </button>
                            </div>
                            <span className="text-xs font-mono text-sky-400/70">SYNCING WITH ZEP ENGINE...</span>
                        </div>

                        <div className="h-[600px] relative bg-black/20">
                            {activeTab === 'graph' ? (
                                <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500">
                                    <Network className="w-12 h-12 mb-4 opacity-20 animate-pulse" />
                                    <p className="text-sm">正在加载 Zep 知识图谱节点...</p>
                                </div>
                            ) : (
                                <div className="p-8 space-y-4">
                                    {[
                                        { type: '旁白', content: '月光透过破损的窗棂，洒在林平之惨白的脸上。', color: 'text-sky-400' },
                                        { type: '动作', content: '他颤抖着手，从怀中摸出一卷残破的绸缎。', color: 'text-amber-400' },
                                        { type: '心理', content: '辟邪剑谱……终究还是落到了我的手里。', color: 'text-indigo-400' }
                                    ].map((log, i) => (
                                        <div key={i} className="flex gap-4 p-4 bg-white/5 rounded-xl border border-white/5 animate-in slide-in-from-left duration-500" style={{ animationDelay: `${i * 150}ms` }}>
                                            <span className={`font-bold min-w-[60px] ${log.color}`}>[{log.type}]</span>
                                            <span className="text-slate-300">{log.content}</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-8">
                        <div className="bg-gradient-to-br from-sky-500/10 to-transparent border border-sky-500/20 p-6 rounded-2xl group hover:border-sky-500/40 transition-all cursor-pointer">
                            <div className="flex justify-between items-start mb-4">
                                <PenTool className="text-sky-400 w-8 h-8" />
                                <ChevronRight className="text-slate-600 group-hover:text-white" />
                            </div>
                            <h3 className="text-lg font-bold mb-2">进入第一视角扮演</h3>
                            <p className="text-sm text-slate-500">
                                以书中角色或原创穿越者身份进入故事，与所有 NPC 进行实时解构式对话推演。
                            </p>
                        </div>
                        <div className="bg-gradient-to-br from-indigo-500/10 to-transparent border border-indigo-500/20 p-6 rounded-2xl group hover:border-indigo-500/40 transition-all cursor-pointer">
                            <div className="flex justify-between items-start mb-4">
                                <History className="text-indigo-400 w-8 h-8" />
                                <ChevronRight className="text-slate-600 group-hover:text-white" />
                            </div>
                            <h3 className="text-lg font-bold mb-2">上帝视角改写器</h3>
                            <p className="text-sm text-slate-500">
                                直接干涉剧情节点大纲，引导未来走向，让 AI 引擎为您自动续写分支篇章。
                            </p>
                        </div>
                    </div>
                </section>
            </main>
        </div>
    );
};

export default App;
