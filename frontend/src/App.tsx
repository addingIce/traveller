import React, { useState, useEffect, useRef } from 'react';
import { Network, History, Brain, ChevronRight, PenTool, Send, Loader2 } from 'lucide-react';
import G6 from '@antv/g6';
import { fetchKnowledgeGraph, chatInteract, ChatResponse, searchGraph, fetchNodeDetail } from './api';
import { Search, Info, Target, MessageSquare } from 'lucide-react';

const SESSION_KEY = "traveller_session_id";

const getSessionId = () => {
    const params = new URLSearchParams(window.location.search);
    const sidFromUrl = params.get("sid");
    if (sidFromUrl) {
        localStorage.setItem(SESSION_KEY, sidFromUrl);
        return sidFromUrl;
    }
    const existing = localStorage.getItem(SESSION_KEY);
    if (existing) return existing;
    const newId = "session_" + Math.random().toString(36).substring(7);
    localStorage.setItem(SESSION_KEY, newId);
    return newId;
};

// Persisted session ID (supports cross-device resume via ?sid=xxx)
const sessionId = getSessionId();

const App: React.FC = () => {
    const [activeTab, setActiveTab] = useState<'graph' | 'plot'>('plot');
    const [graphData, setGraphData] = useState<any>(null);
    const [isGraphLoading, setIsGraphLoading] = useState(false);
    const [chatInput, setChatInput] = useState("");
    const [isChatting, setIsChatting] = useState(false);
    
    // Search & Selection State
    const [searchInput, setSearchInput] = useState("");
    const [isSearching, setIsSearching] = useState(false);
    const [searchResults, setSearchResults] = useState<{ nodes: any[], facts: string[] } | null>(null);
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
    const [nodeDetail, setNodeDetail] = useState<any | null>(null);

    // Custom type for generic message history inside the app UI
    const [history, setHistory] = useState<(ChatResponse & { type: 'ai' } | { type: 'user', content: string })[]>([]);

    const graphContainer = useRef<HTMLDivElement>(null);
    const graphRef = useRef<any>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Auto scroll to bottom
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [history]);

    // Handle Tab Switch & Graph Load
    useEffect(() => {
        if (activeTab === 'graph') {
            if (!graphData) {
                loadGraph();
            } else {
                renderGraph(graphData);
            }
        }
    }, [activeTab]);

    const loadGraph = async () => {
        setIsGraphLoading(true);
        try {
            const data = await fetchKnowledgeGraph('test_novel');
            setGraphData(data);
            if (activeTab === 'graph') renderGraph(data);
        } catch (e) {
            console.error("加载图谱失败", e);
        } finally {
            setIsGraphLoading(false);
        }
    };

    const renderGraph = (data: any) => {
        if (!graphContainer.current || data.nodes?.length === 0) return;

        // Cleanup old graph
        if (graphRef.current) {
            graphRef.current.destroy();
        }

        graphRef.current = new G6.Graph({
            container: graphContainer.current,
            width: graphContainer.current.scrollWidth,
            height: 600,
            fitView: true,
            layout: {
                type: 'force',
                preventOverlap: true,
                nodeSize: 30,
                linkDistance: 100,
            },
            defaultNode: {
                size: 30,
                style: {
                    fill: '#0f172a',
                    stroke: '#38bdf8',
                    lineWidth: 2,
                },
                labelCfg: {
                    style: { fill: '#f1f5f9', fontSize: 12 },
                    position: 'bottom',
                },
            },
            defaultEdge: {
                style: {
                    stroke: '#475569',
                    lineWidth: 1,
                    endArrow: { path: G6.Arrow.triangle(4, 5, 0), fill: '#475569' },
                },
                labelCfg: { autoRotate: true, style: { fill: '#94a3b8', fontSize: 10 } },
            },
            modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
            nodeStateStyles: {
                selected: {
                    stroke: '#f8fafc',
                    lineWidth: 4,
                    fill: '#0ea5e9',
                },
            },
        });

        graphRef.current.data(data);
        graphRef.current.render();

        // Add Listeners
        graphRef.current.on('node:click', (e: any) => {
            const id = e.item.getModel().id;
            handleNodeClick(id as string);
        });

        graphRef.current.on('canvas:click', () => {
            setSelectedNodeId(null);
            setNodeDetail(null);
        });
    };

    const handleSearch = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!searchInput.trim()) return;

        setIsSearching(true);
        try {
            const results = await searchGraph('test_novel', searchInput);
            setSearchResults(results);
            setNodeDetail(null); // 清除之前的节点详情，确保搜索结果列表能正常显示
            setSelectedNodeId(null); // 清除选中的节点
            setActiveTab('graph'); // 自动跳转到图谱页查看
        } catch (e) {
            console.error("搜索失败", e);
        } finally {
            setIsSearching(false);
        }
    };

    const handleNodeClick = async (id: string) => {
        setSelectedNodeId(id);
        const detail = await fetchNodeDetail(id);
        setNodeDetail(detail);

        // Update graph styles to highlight
        if (graphRef.current) {
            const node = graphRef.current.findById(id);
            if (node) {
                // Clear all selected states
                graphRef.current.getNodes().forEach((n: any) => {
                    graphRef.current.setItemState(n, 'selected', false);
                });
                graphRef.current.setItemState(node, 'selected', true);
            }
        }
    };

    const locateNode = (id: string) => {
        if (!graphRef.current) return;
        const node = graphRef.current.findById(id);
        if (node) {
            graphRef.current.focusItem(node, true, {
                easing: 'easeCubic',
                duration: 500,
            });
            handleNodeClick(id);
        }
    };

    const handleSendChat = async () => {
        if (!chatInput.trim() || isChatting) return;

        const userMessage = chatInput.trim();
        setHistory(prev => [...prev, { type: 'user', content: userMessage }]);
        setChatInput("");
        setIsChatting(true);

        try {
            const aiResponse = await chatInteract(sessionId, 'test_novel', userMessage);
            setHistory(prev => [...prev, { type: 'ai', ...aiResponse }]);

            // If the action caused a long-term change, refresh our graph quietly
            if (aiResponse.world_impact.world_state_changed) {
                loadGraph();
            }
        } catch (e) {
            console.error("互动失败", e);
            alert("剧情推演失败。请确保您已启动Zep与FastAPI服务。");
        } finally {
            setIsChatting(false);
        }
    };

    return (
        <div className="min-h-screen bg-[#0f172a] text-[#f1f5f9] font-sans selection:bg-sky-500/30 flex flex-col">
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
                </div>
            </header>

            <main className="max-w-[1600px] mx-auto p-8 grid grid-cols-[350px_1fr] gap-8 flex-1 w-full">
                {/* Sidebar */}
                <aside className="space-y-6 flex flex-col">
                    <div className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 backdrop-blur-sm">
                        <h2 className="text-sky-400 font-semibold mb-4 flex items-center gap-2">
                            <History className="w-4 h-4" /> 作品档案库
                        </h2>
                        <div className="space-y-2">
                            <div className="p-3 rounded-xl cursor-pointer transition-all border bg-sky-500/10 border-sky-500/50">
                                <div className="font-medium">test_novel</div>
                                <div className="text-xs text-sky-400/80 mt-1">当前互动世界</div>
                            </div>
                        </div>
                    </div>

                    <div className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 backdrop-blur-sm">
                        <h2 className="text-sky-400 font-semibold mb-4 flex items-center gap-2">
                            <Search className="w-4 h-4" /> 搜索世界实体
                        </h2>
                        <form onSubmit={handleSearch} className="relative mb-2">
                            <input 
                                type="text" 
                                value={searchInput}
                                onChange={(e) => setSearchInput(e.target.value)}
                                placeholder="搜角色 / 地点 / 设定..."
                                className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-sky-500 transition-all pl-10"
                            />
                            <Search className="absolute left-3 top-3 w-4 h-4 text-slate-500" />
                            {isSearching && <Loader2 className="absolute right-3 top-3 w-4 h-4 text-sky-500 animate-spin" />}
                        </form>
                        
                        {/* Node Detail Dashboard */}
                        {nodeDetail && (
                            <div className="mt-4 p-4 bg-sky-500/5 border border-sky-500/20 rounded-xl animate-in fade-in zoom-in duration-300">
                                <div className="flex justify-between items-start mb-2">
                                    <span className="text-[10px] font-bold text-sky-400 uppercase tracking-widest px-2 py-0.5 bg-sky-400/10 rounded border border-sky-400/20">{nodeDetail.type}</span>
                                    <Info className="w-3 h-3 text-sky-400/50" />
                                </div>
                                <h3 className="text-lg font-bold text-white mb-2">{nodeDetail.label}</h3>
                                <div className="text-[11px] text-slate-400 leading-relaxed font-serif max-h-40 overflow-y-auto custom-scrollbar">
                                    {nodeDetail.summary || "Zep 正在通过背景分析该角色的深度设定..."}
                                </div>
                            </div>
                        )}

                        {/* Search Results List */}
                        {searchResults && !nodeDetail && (
                            <div className="mt-4 space-y-4 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                                {searchResults.nodes.length > 0 && (
                                    <div>
                                        <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3 flex items-center gap-2">
                                            <Target className="w-3 h-3" /> 匹配到的逻辑实体
                                        </div>
                                        <div className="space-y-2">
                                            {searchResults.nodes.map(node => (
                                                <div 
                                                    key={node.id} 
                                                    onClick={() => locateNode(node.id)}
                                                    className="flex items-center justify-between p-2.5 rounded-xl bg-white/5 border border-white/5 hover:border-sky-500/50 hover:bg-sky-500/5 cursor-pointer transition-all group"
                                                >
                                                    <span className="text-sm font-medium">{node.label}</span>
                                                    <ChevronRight className="w-3 h-3 opacity-0 group-hover:opacity-100 text-sky-400 transition-all translate-x-[-4px] group-hover:translate-x-0" />
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                {searchResults.facts.length > 0 && (
                                    <div>
                                        <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3 flex items-center gap-2">
                                            <MessageSquare className="w-3 h-3" /> 相关叙事事实
                                        </div>
                                        <div className="space-y-2">
                                            {searchResults.facts.map((fact, i) => (
                                                <div key={i} className="p-3 text-[11px] text-slate-400 bg-black/20 rounded-xl border border-white/5 italic leading-snug">
                                                    “{fact}”
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                {searchResults.nodes.length === 0 && searchResults.facts.length === 0 && (
                                    <div className="text-center py-8 opacity-40">
                                        <div className="text-xs">未探测到相关信息位</div>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    <div className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 backdrop-blur-sm">
                        <h2 className="text-sky-400 font-semibold mb-4">世界设定统计</h2>
                        <div className="grid grid-cols-2 gap-4 text-center">
                            <div className="bg-white/5 p-4 rounded-xl border border-white/5">
                                <div className="text-2xl font-bold">{graphData?.nodes?.length || 0}</div>
                                <div className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">实体角色</div>
                            </div>
                            <div className="bg-white/5 p-4 rounded-xl border border-white/5">
                                <div className="text-2xl font-bold">{graphData?.edges?.length || 0}</div>
                                <div className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">物理关系</div>
                            </div>
                        </div>
                        <button onClick={loadGraph} className="w-full mt-4 text-xs py-2 bg-white/5 hover:bg-white/10 transition-colors rounded-lg border border-white/10">
                            强制刷新后台图谱
                        </button>
                    </div>
                </aside>

                {/* Content Area */}
                <section className="flex flex-col flex-1 h-[calc(100vh-8rem)]">
                    <div className="bg-slate-800/50 flex flex-col border border-white/10 rounded-3xl overflow-hidden backdrop-blur-sm shadow-2xl h-full relative">

                        {/* Nav Tabs */}
                        <div className="px-6 py-4 border-b border-white/10 flex justify-between items-center bg-white/5 z-10 relative">
                            <div className="flex gap-1 p-1 bg-black/20 rounded-lg">
                                <button
                                    onClick={() => setActiveTab('plot')}
                                    className={`px-4 py-1.5 rounded-md text-sm transition-all ${activeTab === 'plot' ? 'bg-sky-500 text-white shadow-lg shadow-sky-500/20' : 'text-slate-400 hover:text-white'}`}
                                >
                                    剧情时间线推演
                                </button>
                                <button
                                    onClick={() => setActiveTab('graph')}
                                    className={`px-4 py-1.5 rounded-md text-sm transition-all ${activeTab === 'graph' ? 'bg-indigo-500 text-white shadow-lg shadow-indigo-500/20' : 'text-slate-400 hover:text-white'}`}
                                >
                                    后台 Zep 物理图谱
                                </button>
                            </div>
                        </div>

                        {/* Visualizer Body */}
                        <div className="relative bg-black/20 flex-1 overflow-hidden" style={{ display: activeTab === 'graph' ? 'block' : 'none' }}>
                            {isGraphLoading && (
                                <div className="absolute inset-0 z-10 flex flex-col items-center justify-center text-slate-500 backdrop-blur-md bg-black/40">
                                    <Loader2 className="w-12 h-12 mb-4 animate-spin opacity-50 text-indigo-400" />
                                    <p className="text-sm tracking-wider">正在拉取由于变动而刷新的世界知识...</p>
                                </div>
                            )}
                            {graphData?.nodes?.length === 0 && !isGraphLoading && (
                                <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500">
                                    <Network className="w-12 h-12 mb-4 opacity-20" />
                                    <p className="text-sm">知识图谱尚在后台生成或未开启，暂无展示内容。</p>
                                </div>
                            )}
                            <div ref={graphContainer} className="w-full h-full" />
                        </div>

                        {/* Chat/Story Body */}
                        <div className="relative flex flex-col flex-1 bg-black/20 overflow-hidden" style={{ display: activeTab === 'plot' ? 'flex' : 'none' }}>
                            <div className="flex-1 overflow-y-auto p-6 space-y-6">

                                {history.length === 0 && (
                                    <div className="text-center h-full flex flex-col justify-center items-center opacity-40">
                                        <PenTool className="w-16 h-16 mb-6 text-sky-400" />
                                        <p>您可以随心所欲输入您的下一步行动或想说的台词。</p>
                                        <p className="text-sm mt-2">引擎将基于您在 Zep 录入的小说背景，推演出合理且具有文学感的情节回应。</p>
                                    </div>
                                )}

                                {history.map((msg, i) => {
                                    if (msg.type === 'user') {
                                        return (
                                            <div key={i} className="flex justify-end animate-in slide-in-from-right duration-300">
                                                <div className="bg-sky-500/20 text-sky-100 border border-sky-500/30 rounded-2xl rounded-tr-sm px-5 py-3 max-w-[70%]">
                                                    {msg.content}
                                                </div>
                                            </div>
                                        );
                                    }

                                    // Render AI response (Parsed & Unpacked)
                                    if (msg.type === 'ai') {
                                        return (
                                            <div key={i} className="space-y-3 max-w-[85%] animate-in slide-in-from-left duration-500">

                                                {/* 意图解构透视看板 */}
                                                <div className="flex gap-2 text-[10px] font-mono tracking-widest pl-1">
                                                    {msg.user_intent_summary?.action && <span className="text-amber-400/80 bg-amber-400/10 px-2 py-0.5 border border-amber-400/20 rounded-md">ACTION PARSED</span>}
                                                    {msg.user_intent_summary?.thought && <span className="text-indigo-400/80 bg-indigo-400/10 px-2 py-0.5 border border-indigo-400/20 rounded-md">THOUGHT PARSED</span>}
                                                    {msg.world_impact?.world_state_changed && <span className="text-emerald-400/80 bg-emerald-400/10 px-2 py-0.5 border border-emerald-400/20 rounded-md">WORLD IMPACT OCCURRED</span>}
                                                </div>

                                                {/* 核心叙事描述 */}
                                                <div className="bg-white/5 border border-white/10 rounded-2xl rounded-tl-sm p-5 space-y-4">
                                                    <div className="text-slate-300 leading-relaxed whitespace-pre-wrap font-serif tracking-wide text-[15px]">
                                                        {msg.story_text}
                                                    </div>

                                                    {/* 如果存在长期世界状态的影响改变通知 */}
                                                    {msg.world_impact?.world_state_changed && msg.world_impact.reason && (
                                                        <div className="mt-4 pt-4 border-t border-emerald-500/20 text-emerald-300/80 text-xs italic flex items-center gap-2">
                                                            ▶ 由于您的干涉，世界线产生震荡: {msg.world_impact.reason}
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    }

                                    return null;
                                })}

                                {isChatting && (
                                    <div className="flex gap-4 p-4 items-center pl-2">
                                        <Loader2 className="w-5 h-5 animate-spin text-sky-400" />
                                        <span className="text-sky-400/60 text-sm animate-pulse">Director AI 正在统筹世界状态并推演未来...</span>
                                    </div>
                                )}
                                <div ref={messagesEndRef} />
                            </div>

                            {/* Input Area */}
                            <div className="p-4 bg-slate-800/80 border-t border-white/10 backdrop-blur-lg z-20">
                                <form
                                    onSubmit={(e) => { e.preventDefault(); handleSendChat(); }}
                                    className="flex gap-3 max-w-4xl mx-auto items-center relative"
                                >
                                    <input
                                        type="text"
                                        value={chatInput}
                                        onChange={(e) => setChatInput(e.target.value)}
                                        disabled={isChatting}
                                        placeholder="执行动作 / 说出对白 / 心中暗想..."
                                        className="flex-1 bg-black/40 border border-white/10 rounded-full px-6 py-4 text-white focus:outline-none focus:border-sky-500 transition-colors focus:ring-1 focus:ring-sky-500 shadow-inner"
                                    />
                                    <button
                                        disabled={isChatting || !chatInput.trim()}
                                        type="submit"
                                        className="absolute right-2 px-4 py-2 bg-sky-500 hover:bg-sky-400 text-white rounded-full transition-all flex items-center gap-2 disabled:opacity-50 shadow-lg shadow-sky-500/20 font-bold"
                                    >
                                        推进 <Send className="w-4 h-4 ml-1" />
                                    </button>
                                </form>
                            </div>
                        </div>

                    </div>
                </section>
            </main>
        </div>
    );
};

export default App;
