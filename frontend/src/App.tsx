import React, { useState, useEffect, useRef } from 'react';
import { Network, History, Brain, ChevronRight, PenTool, Send, Loader2, Upload, Trash2, Plus, BookOpen, ZoomIn, ZoomOut, LocateFixed, Zap } from 'lucide-react';
import G6 from '@antv/g6';
import { fetchKnowledgeGraph, chatInteract, ChatResponse, searchGraph, fetchGraphFacts, fetchNodeDetail, NovelInfo, NovelStatus, uploadNovel, getNovelsList, getNovelStatus, deleteNovel, getConfig, updateConfig, reloadConfig, resetConfig, getConfigPresets, restartServices, getServicesStatus, SystemConfig, SessionInfo, ChapterInfo, listSessions, getChapters, createSession, createBookmark, branchSession, DirectorMode, listBookmarks, BookmarkInfo, deleteSession, deleteBookmark, getSessionMessages, SessionMessage } from './api';
import { Search, Info, Target, MessageSquare, Settings, Save, RotateCcw, AlertCircle, CheckCircle, RefreshCw } from 'lucide-react';

const SESSION_KEY = "traveller_session_id";
const TERMINAL_NOVEL_STATUSES = new Set<NovelStatus>(['ready', 'failed']);
const IN_PROGRESS_NOVEL_STATUSES = new Set<NovelStatus>(['queued', 'processing', 'completed', 'extracting']);
const CHUNK_PROGRESS_STATUSES = new Set<NovelStatus>(['processing']);
const NOVEL_STATUS_META: Partial<Record<NovelStatus, { color: string; label: string }>> = {
    ready: { color: 'text-emerald-400', label: '✓ 就绪' },
    completed: { color: 'text-sky-400', label: '📝 分块完成' },
    extracting: { color: 'text-purple-400', label: '🔄 实体提取中' },
    processing: { color: 'text-amber-400', label: '⏳ 处理中' },
    queued: { color: 'text-slate-400', label: '⏸️ 排队中' },
    failed: { color: 'text-red-400', label: '✗ 失败' },
};

const getNovelCountLabel = (status: NovelStatus, count: number): string => {
    if (CHUNK_PROGRESS_STATUSES.has(status)) {
        return `${count} 个片段`;
    }
    return `${count} 个实体`;
};

type AggregatedRelation = {
    id: string;
    label: string;
    direction: string;
    directionLabel: string;
};

type AggregatedEdgeDetail = {
    id: string;
    source: string;
    target: string;
    sourceLabel: string;
    targetLabel: string;
    count: number;
    primaryLabel: string;
    relations: AggregatedRelation[];
};

const getPrimaryRelationLabel = (relations: AggregatedRelation[]): string => {
    if (relations.length === 0) return 'related';
    const counts = new Map<string, number>();
    const order: string[] = [];
    for (const relation of relations) {
        const label = relation.label || 'related';
        if (!counts.has(label)) {
            order.push(label);
        }
        counts.set(label, (counts.get(label) || 0) + 1);
    }
    let bestLabel = order[0];
    let bestCount = counts.get(bestLabel) || 0;
    for (const label of order) {
        const currentCount = counts.get(label) || 0;
        if (currentCount > bestCount) {
            bestLabel = label;
            bestCount = currentCount;
        }
    }
    return bestLabel;
};

const prepareGraphRenderData = (raw: any): { nodes: any[]; edges: any[] } => {
    const nodes = Array.isArray(raw?.nodes) ? raw.nodes : [];
    const edges = Array.isArray(raw?.edges) ? raw.edges : [];
    if (edges.length === 0) {
        return { nodes, edges };
    }

    const nodeNameMap = new Map<string, string>();
    for (const node of nodes) {
        if (node?.id) {
            nodeNameMap.set(node.id, String(node?.label || node.id));
        }
    }

    const grouped = new Map<string, AggregatedEdgeDetail>();
    for (let edgeIndex = 0; edgeIndex < edges.length; edgeIndex += 1) {
        const edge = edges[edgeIndex];
        if (!edge?.source || !edge?.target) continue;
        const src = String(edge.source);
        const tgt = String(edge.target);
        const pairKey = [src, tgt].sort().join('<->');
        const relation: AggregatedRelation = {
            id: String(edge.id || `${pairKey}:${edgeIndex}`),
            label: String(edge.label || 'related').trim() || 'related',
            direction: `${src}->${tgt}`,
            directionLabel: `${nodeNameMap.get(src) || src} -> ${nodeNameMap.get(tgt) || tgt}`,
        };
        if (!grouped.has(pairKey)) {
            grouped.set(pairKey, {
                id: `agg:${pairKey}`,
                source: src,
                target: tgt,
                sourceLabel: nodeNameMap.get(src) || src,
                targetLabel: nodeNameMap.get(tgt) || tgt,
                count: 0,
                primaryLabel: relation.label,
                relations: [],
            });
        }
        const bucket = grouped.get(pairKey)!;
        bucket.relations.push(relation);
        bucket.count += 1;
    }

    const groupedEdges = Array.from(grouped.values());
    const labelDivider = groupedEdges.length > 120 ? 4 : groupedEdges.length > 80 ? 3 : groupedEdges.length > 45 ? 2 : 1;

    const renderedEdges = groupedEdges.map((edgeDetail, index) => {
        const primaryLabel = getPrimaryRelationLabel(edgeDetail.relations);
        const displayLabel = edgeDetail.count > 1
            ? `${primaryLabel} +${edgeDetail.count - 1}`
            : primaryLabel;
        const lineWidth = Math.min(1 + Math.log2(edgeDetail.count + 1), 4);
        const shouldShowLabel = edgeDetail.count > 1 || labelDivider === 1 || index % labelDivider === 0;

        return {
            ...edgeDetail,
            primaryLabel,
            type: 'line',
            label: shouldShowLabel ? displayLabel : '',
            style: {
                lineWidth,
            },
            labelCfg: shouldShowLabel
                ? {
                    autoRotate: true,
                    refY: -6,
                }
                : undefined,
        };
    });

    return { nodes, edges: renderedEdges };
};

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

interface ModalConfig {
    show: boolean;
    type: 'info' | 'success' | 'warning' | 'error';
    title: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    onConfirm?: () => void;
    onCancel?: () => void;
    showCancel?: boolean;
}

const App: React.FC = () => {
    const [activeTab, setActiveTab] = useState<'graph' | 'plot'>('plot');
    const [graphData, setGraphData] = useState<any>(null);
    const [isGraphLoading, setIsGraphLoading] = useState(false);
    const [chatInput, setChatInput] = useState("");
    const [isChatting, setIsChatting] = useState(false);
    
    // Search & Selection State
    const [searchInput, setSearchInput] = useState("");
    const [isSearching, setIsSearching] = useState(false);
    const [isFactsLoading, setIsFactsLoading] = useState(false);
    const [searchResults, setSearchResults] = useState<{ nodes: any[], facts: string[] } | null>(null);
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
    const [nodeDetail, setNodeDetail] = useState<any | null>(null);
    const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
    const [edgeDetail, setEdgeDetail] = useState<AggregatedEdgeDetail | null>(null);

    // Custom type for generic message history inside the app UI
    const [history, setHistory] = useState<(ChatResponse & { type: 'ai' } | { type: 'user', content: string })[]>([]);

    // Novel Management State
    const [novels, setNovels] = useState<NovelInfo[]>([]);
    const [isUploading, setIsUploading] = useState(false);
    const [currentCollection, setCurrentCollection] = useState<string>('');
    const [showUploadModal, setShowUploadModal] = useState(false);
    const [uploadTitle, setUploadTitle] = useState('');
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Session & Timeline State
    const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
    const [directorMode, setDirectorMode] = useState<DirectorMode>(DirectorMode.SANDBOX);
    const [sessions, setSessions] = useState<SessionInfo[]>([]);
    const [isSessionsLoading, setIsSessionsLoading] = useState(false);
    const [chapters, setChapters] = useState<ChapterInfo[]>([]);
    const [isChaptersLoading, setIsChaptersLoading] = useState(false);
    const [showBookmarkModal, setShowBookmarkModal] = useState(false);
    const [bookmarkName, setBookmarkName] = useState('');
    const [bookmarks, setBookmarks] = useState<any[]>([]);
    const [isBookmarksLoading, setIsBookmarksLoading] = useState(false);

    // System Config State
    const [config, setConfig] = useState<SystemConfig | null>(null);
    const [isConfigLoading, setIsConfigLoading] = useState(false);
    const [configSaveStatus, setConfigSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
    const [selectedPreset, setSelectedPreset] = useState<string>('');
    const [showConfigModal, setShowConfigModal] = useState(false);
    const [isRestarting, setIsRestarting] = useState(false);
    const [showHelpModal, setShowHelpModal] = useState(false);
    const [showNewSessionModal, setShowNewSessionModal] = useState(false);
    const [newSessionName, setNewSessionName] = useState('');
    const [startChapterId, setStartChapterId] = useState<string | null>(null);
    const [startChapterTitle, setStartChapterTitle] = useState<string | null>(null);
    const [activeSection, setActiveSection] = useState<string>('presets');

    const graphContainer = useRef<HTMLDivElement>(null);
    const graphRef = useRef<any>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const searchPanelRef = useRef<HTMLDivElement>(null);
    const pendingFocusNodeIdRef = useRef<string | null>(null);
    const factsAbortControllerRef = useRef<AbortController | null>(null);
    const searchTokenRef = useRef<number>(0);

    // Modal State
    const [modalConfig, setModalConfig] = useState<ModalConfig>({
        show: false,
        type: 'info',
        title: '',
        message: '',
        confirmText: '确定',
        cancelText: '取消',
        showCancel: false
    });

    const showAlert = (title: string, message: string, type: ModalConfig['type'] = 'info') => {
        setModalConfig({
            show: true,
            type,
            title,
            message,
            confirmText: '确定',
            showCancel: false
        });
    };

    const showConfirm = (title: string, message: string, onConfirm: () => void, type: ModalConfig['type'] = 'warning') => {
        setModalConfig({
            show: true,
            type,
            title,
            message,
            confirmText: '确定',
            cancelText: '取消',
            showCancel: true,
            onConfirm,
            onCancel: () => setModalConfig(prev => ({ ...prev, show: false }))
        });
    };

    // 当前小说是否就绪（只有 ready 状态才能进行剧情推演和创建平行宇宙）
    const currentNovel = novels.find(n => n.collection_name === currentCollection);
    const isNovelReady = currentNovel?.status === 'ready';
    
    // 当前选中的 session 是否为原始剧情线（原始剧情线禁止推进剧情）
    const isCurrentSessionRoot = sessions.find(s => s.session_id === currentSessionId)?.is_root ?? false;

    // Auto scroll to bottom
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [history]);

    // Load novels list on component mount
    useEffect(() => {
        loadNovelsList();
    }, []);

    // Poll novels list status when there are in-progress novels
    useEffect(() => {
        const interval = setInterval(async () => {
            const hasInProgressNovels = novels.some(
                n => IN_PROGRESS_NOVEL_STATUSES.has(n.status)
            );
            if (hasInProgressNovels) {
                await loadNovelsList();
            }
        }, 5000); // 每 5 秒检查一次

        return () => clearInterval(interval);
    }, [novels]);

    // Load config on component mount
    useEffect(() => {
        loadConfig();
    }, []);

    // Handle ESC key to close config modal
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && showConfigModal) {
                setShowConfigModal(false);
            }
        };

        if (showConfigModal) {
            document.addEventListener('keydown', handleKeyDown);
        }

        return () => {
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [showConfigModal]);

    // Intersection Observer for highlighting active section
    useEffect(() => {
        if (!showConfigModal) return;

        const sections = ['presets', 'performance', 'business', 'api'];
        const observerOptions = {
            root: document.querySelector('.custom-scrollbar'),
            threshold: 0.3
        };

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    setActiveSection(entry.target.id);
                }
            });
        }, observerOptions);

        sections.forEach(sectionId => {
            const element = document.getElementById(sectionId);
            if (element) {
                observer.observe(element);
            }
        });

        return () => {
            sections.forEach(sectionId => {
                const element = document.getElementById(sectionId);
                if (element) {
                    observer.unobserve(element);
                }
            });
        };
    }, [showConfigModal]);

    // Auto-select first completed novel when novels are loaded
    useEffect(() => {
        if (!currentCollection && novels.length > 0) {
            const completedNovel = novels.find(n => n.status === 'completed');
            if (completedNovel) {
                setCurrentCollection(completedNovel.collection_name);
            } else if (novels.length > 0) {
                // If no completed novel, select the first one
                setCurrentCollection(novels[0].collection_name);
            }
        }
    }, [novels, currentCollection]);

    // Load graph data whenever currentCollection changes.
    // This keeps sidebar statistics in sync even when graph tab is not active.
    useEffect(() => {
        if (currentCollection) {
            loadGraph();
            loadSessions();
            loadChapters();
        }
    }, [currentCollection]);

    // Load bookmarks whenever currentSessionId changes
    useEffect(() => {
        if (currentSessionId) {
            loadBookmarks(currentSessionId);
        }
    }, [currentSessionId]);

    // Clear graph data when currentSessionId changes (force reload on next graph tab switch)
    useEffect(() => {
        setGraphData(null);
        if (currentCollection && activeTab === 'graph') {
            loadGraph(true, currentSessionId || undefined);
        }
    }, [currentSessionId]);

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

    useEffect(() => {
        if (factsAbortControllerRef.current) {
            factsAbortControllerRef.current.abort();
            factsAbortControllerRef.current = null;
        }
        setIsFactsLoading(false);
    }, [currentCollection, activeTab]);

    const clearGraph = () => {
        // 清理旧的 G6 图谱实例
        if (graphRef.current) {
            graphRef.current.destroy();
            graphRef.current = null;
        }
        // 清空图谱与选择态
        setGraphData(null);
        setNodeDetail(null);
        setSelectedNodeId(null);
        setEdgeDetail(null);
        setSelectedEdgeId(null);
    };

// Config Management Functions
const loadConfig = async () => {
    setIsConfigLoading(true);
    try {
        const configData = await getConfig();
        setConfig(configData);
    } catch (error) {
        console.error("加载配置失败", error);
    } finally {
        setIsConfigLoading(false);
    }
};

const handleSaveConfig = async () => {
    if (!config) return;
    
    setConfigSaveStatus('saving');
    try {
        await updateConfig(config);
        setConfigSaveStatus('saved');
        setTimeout(() => setConfigSaveStatus('idle'), 2000);
    } catch (error) {
        console.error("保存配置失败", error);
        setConfigSaveStatus('error');
    }
};

const handleResetConfig = async () => {
    try {
        const response = await resetConfig();
        setConfig(response.config);
        setConfigSaveStatus('saved');
        setTimeout(() => setConfigSaveStatus('idle'), 2000);
    } catch (error) {
        console.error("重置配置失败", error);
        setConfigSaveStatus('error');
    }
};

const handleApplyPreset = async (presetKey: string) => {
    try {
        const presets = await getConfigPresets();
        const preset = presets[presetKey];
        if (preset && preset.config) {
            setConfig(preset.config);
            setSelectedPreset(presetKey);
            setConfigSaveStatus('saving');
            await updateConfig(preset.config);
            setConfigSaveStatus('saved');
            setTimeout(() => setConfigSaveStatus('idle'), 2000);
        }
    } catch (error) {
        console.error("应用预设失败", error);
        setConfigSaveStatus('error');
    }
};

const handleRestartServices = async () => {
    showConfirm('危险操作', '确定要重启 Docker 服务吗？这将导致服务短暂中断。', async () => {
        setIsRestarting(true);
        try {
            const response = await restartServices();
            if (response.success) {
                showAlert('成功', '服务重启成功！配置已生效。', 'success');
            } else {
                showAlert('失败', '服务重启失败：' + response.message, 'error');
            }
        } catch (error) {
            console.error("重启服务失败", error);
            showAlert('错误', '重启服务时出错，请检查控制台日志。', 'error');
        } finally {
            setIsRestarting(false);
        }
    });
};

const loadGraph = async (renderNow: boolean = true, sessionId?: string) => {
    if (!currentCollection) {
        console.log("No collection selected, skipping graph load");
        return;
    }
    setIsGraphLoading(true);
    try {
        const data = await fetchKnowledgeGraph(currentCollection, sessionId || currentSessionId || undefined);
        setGraphData(data);
        if (renderNow && activeTab === 'graph') renderGraph(data);
    } catch (e) {
        console.error("加载图谱失败", e);
    } finally {
        setIsGraphLoading(false);
    }
};

const scrollToSection = (sectionId: string) => {
    const element = document.getElementById(sectionId);
    if (element) {
        element.scrollIntoView({ behavior: 'smooth' });
        setActiveSection(sectionId);
    }
};

    // Novel Management Functions
    const loadNovelsList = async () => {
        try {
            const data = await getNovelsList();
            setNovels(data.novels);
        } catch (e) {
            console.error("加载小说列表失败", e);
        }
    };

    const handleFileUpload = async (file: File) => {
        // 验证文件
        if (!file.name.endsWith('.txt')) {
            showAlert('格式错误', '仅支持 .txt 文本文件', 'error');
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            showAlert('文件过大', '文件大小不能超过 10MB', 'error');
            return;
        }

        // 打开模态框让用户输入标题
        setSelectedFile(file);
        setUploadTitle(file.name.replace('.txt', ''));
        setShowUploadModal(true);
    };

    const handleConfirmUpload = async () => {
        if (!selectedFile) return;

        if (!uploadTitle.trim()) {
            showAlert('信息不全', '请输入小说标题', 'warning');
            return;
        }

        setIsUploading(true);
        setShowUploadModal(false);
        try {
            const response = await uploadNovel(selectedFile, uploadTitle.trim());
            
            // 立即将新小说添加到列表中，避免用户等待
            const newNovel: NovelInfo = {
                collection_name: response.collection_name,
                title: response.title,
                status: 'processing', // 显示为处理中
                created_at: new Date().toISOString(),
                chunks_count: 0
            };
            setNovels(prevNovels => [newNovel, ...prevNovels]);
            
            // 如果当前没有选中的小说，自动选中新上传的小说
            if (!currentCollection) {
                setCurrentCollection(response.collection_name);
            }
            
            // 开始轮询状态
            pollStatus(response.collection_name);
            // 同时也刷新小说列表（确保数据一致性）
            loadNovelsList();
            
            setUploadTitle('');
            showAlert('上传成功', `小说《${uploadTitle}》已进入排队队列。`, 'success');
        } catch (error) {
            showAlert('上传失败', '服务器处理请求时出错', 'error');
            console.error(error);
        } finally {
            setIsUploading(false);
        }
    };

    const handleCancelUpload = () => {
        setShowUploadModal(false);
        setSelectedFile(null);
        setUploadTitle('');
    };

    const pollStatus = (collectionName: string) => {
        let lastStatus: string | null = null;
        const interval = setInterval(async () => {
            try {
                const status = await getNovelStatus(collectionName);
                // 只在状态首次变为 completed/extracting/ready 时调用 loadChapters
                if (['completed', 'extracting', 'ready'].includes(status.status) && lastStatus !== status.status) {
                    loadChapters();
                }
                lastStatus = status.status;
                if (TERMINAL_NOVEL_STATUSES.has(status.status)) {
                    clearInterval(interval);
                    await loadNovelsList();
                }
            } catch (e) {
                clearInterval(interval);
            }
        }, 3000);
    };

    const handleDeleteNovel = async (collectionName: string) => {
        showConfirm('删除确认', '确定要删除这部小说吗？此操作将清除所有关联的图谱和剧情数据。', async () => {
            try {
                await deleteNovel(collectionName);
                setNovels(prev => {
                    const next = prev.filter(n => n.collection_name !== collectionName);
                    if (currentCollection === collectionName) {
                        setCurrentCollection(next[0]?.collection_name || '');
                    }
                    return next;
                });
                // 如果删除的是当前小说，切换到第一个可用小说
                if (currentCollection === collectionName) {
                    clearGraph();  // 清理旧图谱
                    setCurrentSessionId('');
                    setSessions([]);
                    setChapters([]);
                    setHistory([]);
                }
                showAlert('已删除', '小说档案已安全移除', 'success');
                // 后台刷新以确保一致性
                loadNovelsList();
            } catch (e) {
                showAlert('删除失败', '无法完成删除操作，请稍后重试', 'error');
                console.error(e);
            }
        });
    };

    const handleSelectNovel = (collectionName: string) => {
        if (currentCollection === collectionName) return;
        setCurrentCollection(collectionName);
        setCurrentSessionId(''); // Reset session when switching novel
        setSessions([]);
        setChapters([]);
        clearGraph();
    };

    // --- Session & Timeline Functions ---
    const loadSessions = async () => {
        if (!currentCollection) return;
        setIsSessionsLoading(true);
        try {
            const data = await listSessions(currentCollection);
            setSessions(data);
            
            // Auto select: prefer root session, then first session if no root
            if (data.length > 0) {
                const root = data.find(s => s.is_root);
                const targetId = root?.session_id || data[0].session_id;
                // Only update if not already selected
                if (currentSessionId !== targetId) {
                    setCurrentSessionId(targetId);
                }
            } else {
                // No sessions available, clear selection
                setCurrentSessionId('');
            }
        } catch (e) {
            console.error("加载 Session 失败", e);
        } finally {
            setIsSessionsLoading(false);
        }
    };

    const loadChapters = async () => {
        if (!currentCollection) return;
        setIsChaptersLoading(true);
        try {
            const data = await getChapters(currentCollection);
            setChapters(data);
        } catch (e) {
            console.error("加载章节失败", e);
        } finally {
            setIsChaptersLoading(false);
        }
    };

    const handleCreateSession = async () => {
        if (!currentCollection || !newSessionName.trim()) return;
        if (!isNovelReady) {
            showAlert('未就绪', "作品尚未处理完成，请等待状态变为「就绪」后再创建平行宇宙", 'warning');
            return;
        }
        try {
            const newSess = await createSession(currentCollection, sessionId, newSessionName.trim(), startChapterId || undefined);
            setSessions(prev => [newSess, ...prev]);
            setCurrentSessionId(newSess.session_id);
            setHistory([]); 
            setShowNewSessionModal(false);
            setNewSessionName('');
            setStartChapterId(null);
            setStartChapterTitle(null);
        } catch (e) {
            showAlert('创建失败', '无法初始化平行宇宙，请检查服务器连接。', 'error');
        }
    };

    const handleSwitchSession = async (sid: string) => {
        setCurrentSessionId(sid);
        setHistory([]);
        loadGraph(true, sid);
        loadBookmarks(sid);
        
        // 加载历史消息
        try {
            const messages = await getSessionMessages(sid);
            const historyItems: (ChatResponse & { type: 'ai' } | { type: 'user', content: string })[] = [];
            
            for (const msg of messages) {
                if (msg.role === 'user') {
                    historyItems.push({ type: 'user', content: msg.content });
                } else if (msg.role === 'assistant') {
                    historyItems.push({
                        type: 'ai',
                        story_text: msg.content,
                        user_intent_summary: { action: undefined, dialogue: undefined, thought: undefined, intensity: 3, metadata: {} },
                        world_impact: { world_state_changed: false },
                        ui_hints: []
                    });
                }
            }
            setHistory(historyItems);
        } catch (e) {
            console.error("Failed to load session history", e);
        }
    };

    const loadBookmarks = async (sid: string) => {
        setIsBookmarksLoading(true);
        try {
            const data = await listBookmarks(sid);
            setBookmarks(data);
        } catch (e) {
            console.error("Failed to load bookmarks", e);
        } finally {
            setIsBookmarksLoading(false);
        }
    };

    const handleCreateBookmark = async () => {
        if (!currentSessionId || !bookmarkName.trim()) return;
        try {
            await createBookmark(currentSessionId, bookmarkName.trim());
            setShowBookmarkModal(false);
            setBookmarkName('');
            loadBookmarks(currentSessionId);
            showAlert('创建成功', '书签已保存至当前观测点', 'success');
        } catch (e) {
            showAlert('创建失败', '无法保存书签，请检查网络连接', 'error');
        }
    };

    const handleBranchFromBookmark = async (bookmarkId: string) => {
        if (!currentSessionId) return;
        try {
            setIsSessionsLoading(true);
            const newSession = await branchSession(currentSessionId, bookmarkId);
            await loadSessions();
            setCurrentSessionId(newSession.session_id);
            setHistory([]); 
            showAlert('分支开启', `已成功从书签切入新的平行宇宙：${newSession.session_name}`, 'success');
        } catch (e) {
            showAlert('操作失败', '无法从该观测点开启分支', 'error');
        } finally {
            setIsSessionsLoading(false);
        }
    };

    const handleDeleteSession = async (sessionId: string, sessionName: string, isRoot: boolean) => {
        if (isRoot) {
            showAlert('权限限制', '原始剧情线（根宇宙）是时空基准，不可删除。', 'warning');
            return;
        }
        showConfirm('删除确认', `确定要销毁平行宇宙「${sessionName}」吗？此操作将永久抹除该轴的所有历史记录，不可撤销。`, async () => {
            try {
            await deleteSession(sessionId);
            await loadSessions();
            // If deleted session was current, switch to root or first
            if (currentSessionId === sessionId) {
                const root = sessions.find(s => s.is_root && s.session_id !== sessionId);
                if (root) {
                    setCurrentSessionId(root.session_id);
                } else if (sessions.length > 1) {
                    const remaining = sessions.filter(s => s.session_id !== sessionId);
                    setCurrentSessionId(remaining[0].session_id);
                } else {
                    setCurrentSessionId('');
                }
            }
            showAlert('已销毁', `平行宇宙「${sessionName}」已被安全移除。`, 'success');
        } catch (e: any) {
            showAlert('删除失败', e.response?.data?.detail || "无法执行删除指令", 'error');
        }
        });
    };

    const handleDeleteBookmark = async (bookmarkId: string, bookmarkName: string) => {
        if (!currentSessionId) return;
        showConfirm('删除确认', `确定要移除书签「${bookmarkName}」吗？移除后将无法通过此点直接开启平行宇宙。`, async () => {
            try {
                await deleteBookmark(currentSessionId, bookmarkId);
                await loadBookmarks(currentSessionId);
                showAlert('已移除', `书签「${bookmarkName}」已被清理。`, 'success');
            } catch (e: any) {
                showAlert('删除失败', e.response?.data?.detail || "无法执行清理指令", 'error');
            }
        });
    };

    const handleUploadClick = () => {
        fileInputRef.current?.click();
    };

    const cancelFactsRequest = () => {
        if (factsAbortControllerRef.current) {
            factsAbortControllerRef.current.abort();
            factsAbortControllerRef.current = null;
        }
        setIsFactsLoading(false);
    };

    const scrollToSearchPanel = () => {
        if (!searchPanelRef.current) return;
        searchPanelRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            handleFileUpload(file);
        }
        // 重置 input 以便可以再次选择同一个文件
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    // 初始化时加载小说列表
    useEffect(() => {
        loadNovelsList();
    }, []);

    const renderGraph = (data: any) => {
        if (!graphContainer.current) return;

        // Cleanup old graph first (before checking data)
        if (graphRef.current) {
            graphRef.current.destroy();
            graphRef.current = null;
        }

        // Return early if no data
        if (data.nodes?.length === 0) return;
        const renderData = prepareGraphRenderData(data);

        graphRef.current = new G6.Graph({
            container: graphContainer.current,
            renderer: 'svg',
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
                labelCfg: {
                    autoRotate: true,
                    style: { fill: '#94a3b8', fontSize: 10, background: { fill: '#0b1220', padding: [2, 4], radius: 2 } },
                },
            },
            modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
            nodeStateStyles: {
                selected: {
                    stroke: '#f8fafc',
                    lineWidth: 4,
                    fill: '#0ea5e9',
                },
            },
            edgeStateStyles: {
                selected: {
                    stroke: '#38bdf8',
                    lineWidth: 3,
                },
            },
        });

        graphRef.current.data(renderData);
        graphRef.current.render();

        if (pendingFocusNodeIdRef.current) {
            const pendingId = pendingFocusNodeIdRef.current;
            pendingFocusNodeIdRef.current = null;
            const pendingNode = graphRef.current.findById(pendingId);
            if (pendingNode) {
                graphRef.current.focusItem(pendingNode, true, {
                    easing: 'easeCubic',
                    duration: 500,
                });
                handleNodeClick(pendingId);
            }
        }

        // Add Listeners
        graphRef.current.on('node:click', (e: any) => {
            const id = e.item.getModel().id;
            handleNodeClick(id as string);
        });

        graphRef.current.on('edge:click', (e: any) => {
            const model = e.item.getModel() as AggregatedEdgeDetail;
            setSelectedEdgeId(model.id);
            setEdgeDetail(model);
            setSelectedNodeId(null);
            setNodeDetail(null);
            scrollToSearchPanel();
            if (graphRef.current) {
                graphRef.current.getNodes().forEach((n: any) => {
                    graphRef.current.setItemState(n, 'selected', false);
                });
                graphRef.current.getEdges().forEach((edge: any) => {
                    graphRef.current.setItemState(edge, 'selected', false);
                });
                graphRef.current.setItemState(e.item, 'selected', true);
            }
        });

        graphRef.current.on('canvas:click', () => {
            setSelectedNodeId(null);
            setSelectedEdgeId(null);
            setNodeDetail(null);
            setEdgeDetail(null);
            if (graphRef.current) {
                graphRef.current.getNodes().forEach((n: any) => {
                    graphRef.current.setItemState(n, 'selected', false);
                });
                graphRef.current.getEdges().forEach((edge: any) => {
                    graphRef.current.setItemState(edge, 'selected', false);
                });
            }
        });
    };

    const handleSearch = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!searchInput.trim() || !currentCollection) return;

        cancelFactsRequest();
        setIsSearching(true);
        setIsFactsLoading(false);
        const queryText = searchInput.trim();
        const token = searchTokenRef.current + 1;
        searchTokenRef.current = token;
        try {
            const results = await searchGraph(currentCollection, queryText);
            setSearchResults({ ...results, facts: [] });
            setNodeDetail(null); // 清除之前的节点详情，确保搜索结果列表能正常显示
            setSelectedNodeId(null); // 清除选中的节点
            setEdgeDetail(null);
            setSelectedEdgeId(null);
            setActiveTab('graph'); // 自动跳转到图谱页查看

            setIsFactsLoading(true);
            const controller = new AbortController();
            factsAbortControllerRef.current = controller;
            fetchGraphFacts(currentCollection, queryText, controller.signal)
                .then((factsResult) => {
                    if (searchTokenRef.current !== token) return;
                    setSearchResults((prev) => {
                        if (!prev) return prev;
                        return { ...prev, facts: factsResult.facts || [] };
                    });
                })
                .catch((error) => {
                    if (error?.name === 'CanceledError' || error?.name === 'AbortError') {
                        return;
                    }
                })
                .finally(() => {
                    if (searchTokenRef.current === token) {
                        setIsFactsLoading(false);
                    }
                });
        } catch (e) {
            console.error("搜索失败", e);
        } finally {
            setIsSearching(false);
        }
    };

    const handleNodeClick = async (id: string) => {
        setSelectedNodeId(id);
        setSelectedEdgeId(null);
        setEdgeDetail(null);
        scrollToSearchPanel();
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
                graphRef.current.getEdges().forEach((edge: any) => {
                    graphRef.current.setItemState(edge, 'selected', false);
                });
                graphRef.current.setItemState(node, 'selected', true);
            }
        }
    };

    const locateNode = (id: string) => {
        setActiveTab('graph');
        if (!graphRef.current) {
            pendingFocusNodeIdRef.current = id;
            return;
        }
        const node = graphRef.current.findById(id);
        if (!node) {
            pendingFocusNodeIdRef.current = id;
            return;
        }
        graphRef.current.focusItem(node, true, {
            easing: 'easeCubic',
            duration: 500,
        });
        handleNodeClick(id);
    };

    const fitGraphView = () => {
        if (!graphRef.current) return;
        graphRef.current.fitView(20);
    };

    const zoomGraph = (delta: number) => {
        if (!graphRef.current) return;
        const currentZoom = graphRef.current.getZoom();
        const nextZoom = Math.max(0.2, Math.min(2.5, currentZoom + delta));
        graphRef.current.zoomTo(nextZoom, { x: 0, y: 0 });
    };

    const resetGraphZoom = () => {
        if (!graphRef.current) return;
        graphRef.current.zoomTo(1, { x: 0, y: 0 });
        if (typeof graphRef.current.fitCenter === 'function') {
            graphRef.current.fitCenter();
        }
    };

    const handleSendChat = async () => {
        if (!chatInput.trim() || isChatting || !currentCollection) return;
        if (!isNovelReady) {
            showAlert('未就绪', "作品尚未处理完成，请等待状态变为「就绪」后再进行剧情推演", 'warning');
            return;
        }

        const userMessage = chatInput.trim();
        setHistory(prev => [...prev, { type: 'user', content: userMessage }]);
        setChatInput("");
        setIsChatting(true);

        try {
            const sessToUse = currentSessionId || sessionId;
            const aiResponse = await chatInteract(sessToUse, currentCollection, userMessage, directorMode);
            setHistory(prev => [...prev, { type: 'ai', ...aiResponse }]);

            // If the action caused a long-term change, refresh our graph quietly
            if (aiResponse.world_impact.world_state_changed) {
                loadGraph();
            }
        } catch (e) {
            console.error("互动失败", e);
            showAlert('推演失败', '剧情推演遇到时空扰动。请检查 Zep 与 FastAPI 服务是否正常运行。', 'error');
        } finally {
            setIsChatting(false);
        }
    };

    return (
        <div className="h-screen overflow-hidden bg-[#0f172a] text-[#f1f5f9] font-sans selection:bg-sky-500/30 flex flex-col">
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
                    <button
                        onClick={() => setShowConfigModal(true)}
                        className="p-2 rounded-lg bg-white/5 hover:bg-white/10 hover:text-white text-slate-400 transition-all"
                        title="系统配置"
                    >
                        <Settings className="w-5 h-5" />
                    </button>
                </div>
            </header>

            <main className="max-w-[1600px] mx-auto p-8 grid grid-cols-[350px_1fr] gap-8 flex-1 w-full min-h-0 overflow-hidden">
                {/* Sidebar */}
                <aside className="space-y-6 flex flex-col h-full min-h-0 overflow-y-auto pr-2 custom-scrollbar">
                    <div className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 backdrop-blur-sm">
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-sky-400 font-semibold flex items-center gap-2">
                                <BookOpen className="w-4 h-4" /> 作品档案库
                            </h2>
                            <button
                                onClick={handleUploadClick}
                                disabled={isUploading}
                                className="p-2 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 text-sky-400 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                                title="上传新小说"
                            >
                                {isUploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                            </button>
                        </div>
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".txt"
                            onChange={handleFileChange}
                            className="hidden"
                        />
                        <div className="space-y-2 max-h-[300px] overflow-y-auto custom-scrollbar">
                            {novels.length === 0 && (
                                <div className="text-center py-8 text-slate-500 text-sm">
                                    <Upload className="w-8 h-8 mx-auto mb-2 opacity-50" />
                                    暂无小说，点击 + 上传
                                </div>
                            )}
                            {novels.map((novel) => (
                                <div
                                    key={novel.collection_name}
                                    className={`p-3 rounded-xl cursor-pointer transition-all border ${
                                        currentCollection === novel.collection_name
                                            ? 'bg-sky-500/10 border-sky-500/50'
                                            : 'bg-white/5 border-white/5 hover:border-white/10'
                                    }`}
                                >
                                    <div className="flex justify-between items-start">
                                        <div className="flex-1 min-w-0" onClick={() => handleSelectNovel(novel.collection_name)}>
                                            <div className="font-medium truncate">{novel.title}</div>
                                            <div className="text-xs text-slate-500 mt-1 flex items-center gap-2">
                                                <span className={NOVEL_STATUS_META[novel.status]?.color || 'text-red-400'}>
                                                    {NOVEL_STATUS_META[novel.status]?.label || '✗ 失败'}
                                                </span>
                                                <span>• {getNovelCountLabel(novel.status, novel.chunks_count)}</span>
                                            </div>
                                        </div>
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleDeleteNovel(novel.collection_name);
                                            }}
                                            className="p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400 transition-all"
                                            title="删除"
                                        >
                                            <Trash2 className="w-3 h-3" />
                                        </button>
                                    </div>
                                    {IN_PROGRESS_NOVEL_STATUSES.has(novel.status) && (
                                        <div className="mt-2 w-full bg-black/30 rounded-full h-1">
                                            <div className="bg-sky-500 h-1 rounded-full animate-pulse" style={{ width: '50%' }} />
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* 上传标题模态框 */}
                    {showUploadModal && (
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
                                            onChange={(e) => setUploadTitle(e.target.value)}
                                            placeholder="请输入小说标题"
                                            className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-sky-500 transition-all"
                                            autoFocus
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') {
                                                    handleConfirmUpload();
                                                }
                                            }}
                                        />
                                    </div>
                                    <div className="text-xs text-slate-500">
                                        已选择文件: {selectedFile?.name}
                                    </div>
                                    <div className="flex gap-3 pt-2">
                                        <button
                                            onClick={handleCancelUpload}
                                            className="flex-1 px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 text-sm transition-all"
                                        >
                                            取消
                                        </button>
                                        <button
                                            onClick={handleConfirmUpload}
                                            className="flex-1 px-4 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-600 text-white text-sm transition-all"
                                        >
                                            开始上传
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    <div className="bg-slate-800/50 border border-white/10 rounded-2xl p-4 backdrop-blur-sm">
                        <div className="flex justify-between items-center mb-3">
                            <h2 className="text-sky-400 font-semibold text-sm">图景统计</h2>
                            <button onClick={() => loadGraph()} title="强制刷新" className="text-slate-500 hover:text-sky-400 transition-colors">
                                <RefreshCw className="w-3 h-3" />
                            </button>
                        </div>
                        <div className="grid grid-cols-2 gap-3 text-center">
                            <div className="bg-white/5 p-2.5 rounded-xl border border-white/5">
                                <div className="text-lg font-bold text-white">{graphData?.nodes?.length || 0}</div>
                                <div className="text-[9px] text-slate-500 uppercase tracking-widest mt-0.5">实体</div>
                            </div>
                            <div className="bg-white/5 p-2.5 rounded-xl border border-white/5">
                                <div className="text-lg font-bold text-white">{graphData?.edges?.length || 0}</div>
                                <div className="text-[9px] text-slate-500 uppercase tracking-widest mt-0.5">关系</div>
                            </div>
                        </div>
                    </div>

                    <div ref={searchPanelRef} className="bg-slate-800/50 border border-white/10 rounded-2xl p-4 backdrop-blur-sm">
                        <h2 className="text-sky-400 font-semibold mb-3 flex items-center gap-2 text-sm">
                            <Search className="w-3 h-3" /> 搜索世界实体
                        </h2>
                        <form onSubmit={handleSearch} className="relative mb-2">
                            <input 
                                type="text" 
                                value={searchInput}
                                onChange={(e) => setSearchInput(e.target.value)}
                                placeholder="角色 / 场景 / 设定..."
                                className="w-full bg-black/30 border border-white/10 rounded-xl px-3 py-2 text-xs focus:outline-none focus:border-sky-500 transition-all pl-9"
                            />
                            <Search className="absolute left-3 top-2.5 w-3.5 h-3.5 text-slate-500" />
                            {isSearching && <Loader2 className="absolute right-3 top-2.5 w-3.5 h-3.5 text-sky-500 animate-spin" />}
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

                        {/* Edge Detail Dashboard */}
                        {edgeDetail && !nodeDetail && (
                            <div className="mt-4 p-4 bg-indigo-500/5 border border-indigo-500/20 rounded-xl animate-in fade-in zoom-in duration-300">
                                <div className="flex justify-between items-start mb-2">
                                    <span className="text-[10px] font-bold text-indigo-300 uppercase tracking-widest px-2 py-0.5 bg-indigo-400/10 rounded border border-indigo-300/20">
                                        关系聚合
                                    </span>
                                    <Info className="w-3 h-3 text-indigo-300/60" />
                                </div>
                                <h3 className="text-sm font-semibold text-white mb-1">
                                    {edgeDetail.sourceLabel} → {edgeDetail.targetLabel}
                                </h3>
                                <div className="text-[11px] text-slate-400 mb-2">
                                    主关系: <span className="text-slate-200">{edgeDetail.primaryLabel}</span> · 共 {edgeDetail.count} 条
                                    {selectedEdgeId ? <span className="ml-2 text-slate-500">#{selectedEdgeId.slice(-8)}</span> : null}
                                </div>
                                <div className="max-h-44 overflow-y-auto custom-scrollbar space-y-1.5 pr-1">
                                    {edgeDetail.relations.map((rel, idx) => (
                                        <div key={rel.id} className="text-[11px] text-slate-300 bg-black/20 border border-white/5 rounded-md px-2 py-1.5 leading-snug">
                                            {idx + 1}. [{rel.directionLabel}] {rel.label}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Search Results List */}
                        {searchResults && !nodeDetail && !edgeDetail && (
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
                                {isFactsLoading && (
                                    <div>
                                        <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3 flex items-center gap-2">
                                            <MessageSquare className="w-3 h-3" /> 相关叙事事实
                                        </div>
                                        <div className="p-3 text-[11px] text-slate-400 bg-black/20 rounded-xl border border-white/5 italic leading-snug">
                                            facts 检索中...
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
                                {searchResults.nodes.length === 0 && searchResults.facts.length === 0 && !isFactsLoading && (
                                    <div className="text-center py-8 opacity-40">
                                        <div className="text-xs">未探测到相关信息位</div>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Parallel Universes (Sessions) Selector */}
                    <div className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 backdrop-blur-sm flex flex-col min-h-[300px]">
                        <div className="flex justify-between items-center mb-4">
                            <div className="text-amber-400 font-semibold flex items-center gap-2 text-sm">
                                <History className="w-4 h-4 shrink-0" />
                                <span>平行宇宙</span>
                            </div>
                            <button
                                onClick={() => {
                                    if (!isNovelReady) {
                                        showAlert('未就绪', "作品尚未处理完成，请等待状态变为「就绪」后再创建平行宇宙", 'warning');
                                        return;
                                    }
                                    setNewSessionName(`新的支线 ${new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`);
                                    setShowNewSessionModal(true);
                                }}
                                disabled={!isNovelReady}
                                className={`w-8 h-8 rounded-lg transition-all flex items-center justify-center border ${
                                    isNovelReady 
                                        ? 'bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border-amber-500/20'
                                        : 'bg-slate-700/50 text-slate-500 border-slate-700 cursor-not-allowed'
                                }`}
                                title={isNovelReady ? "开启新的平行宇宙" : "作品未就绪，无法创建平行宇宙"}
                            >
                                <Plus className="w-4 h-4" />
                            </button>
                        </div>
                        <div className="space-y-2 overflow-y-auto custom-scrollbar max-h-[400px]">
                            {isSessionsLoading ? (
                                <div className="text-center py-4 text-slate-500"><Loader2 className="w-4 h-4 animate-spin mx-auto" /></div>
                            ) : sessions.length === 0 ? (
                                <div className="text-center py-4 text-slate-500 text-xs">暂无平行宇宙</div>
                            ) : (
                                sessions.map((sess) => (
                                    <div
                                        key={sess.session_id}
                                        onClick={() => handleSwitchSession(sess.session_id)}
                                        className={`p-3 rounded-xl cursor-pointer transition-all border group relative ${
                                            currentSessionId === sess.session_id
                                                ? 'bg-amber-500/10 border-amber-500/50'
                                                : 'bg-white/5 border-white/5 hover:border-white/10'
                                        }`}
                                    >
                                        {!sess.is_root && (
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleDeleteSession(sess.session_id, sess.session_name, sess.is_root);
                                                }}
                                                className="absolute right-2 top-2 w-5 h-5 rounded bg-red-500/0 hover:bg-red-500/20 text-red-400/0 group-hover:text-red-400 hover:text-red-400 transition-all flex items-center justify-center"
                                                title="删除此平行宇宙"
                                            >
                                                <Trash2 className="w-3 h-3" />
                                            </button>
                                        )}
                                        <div className="font-medium truncate text-sm flex items-center gap-2 h-5">
                                            {sess.is_root && <BookOpen className="w-3 h-3 text-sky-400 shrink-0" />}
                                            <span className="truncate leading-none">{sess.session_name}</span>
                                        </div>
                                        <div className="text-[10px] text-slate-500 mt-1 flex justify-between">
                                            <span>{sess.is_root ? '原始剧情线' : '玩家分支'}</span>
                                            <span>{sess.last_interaction_at ? new Date(sess.last_interaction_at).toLocaleDateString() : '尚未开始'}</span>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>
                    
                    {/* Bookmark List (Story Snapshots) */}
                    <div className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 backdrop-blur-sm flex flex-col min-h-[300px] mt-4">
                        <div className="flex justify-between items-center mb-4">
                            <div className="text-sky-400 font-semibold flex items-center gap-2 text-sm">
                                <Save className="w-4 h-4 shrink-0" />
                                <span>剧情书签</span>
                            </div>
                            <span className="text-[10px] text-slate-500 uppercase font-mono">{bookmarks.length} Checkpoints</span>
                        </div>
                        <div className="space-y-2 overflow-y-auto custom-scrollbar max-h-[500px]">
                            {isBookmarksLoading ? (
                                <div className="text-center py-4 text-slate-500"><Loader2 className="w-4 h-4 animate-spin mx-auto" /></div>
                            ) : bookmarks.length === 0 ? (
                                <div className="text-center py-8 px-4">
                                    <div className="text-slate-600 text-[10px] leading-relaxed italic">
                                        该宇宙目前还没有存档位。<br/>
                                        <span className="text-sky-500/60">提示：点击右侧聊天消息中 AI 回复旁边的“保存”图标来创建第一个剧情书签。</span>
                                    </div>
                                </div>
                            ) : (
                                bookmarks.map((bm) => (
                                    <div
                                        key={bm.id}
                                        className="p-3 rounded-xl bg-white/5 border border-white/5 hover:border-sky-500/30 transition-all group relative"
                                    >
                                        <button
                                            onClick={() => handleDeleteBookmark(bm.id, bm.name)}
                                            className="absolute right-2 top-2 w-5 h-5 rounded bg-red-500/0 hover:bg-red-500/20 text-red-400/0 group-hover:text-red-400 hover:text-red-400 transition-all flex items-center justify-center"
                                            title="删除此书签"
                                        >
                                            <Trash2 className="w-3 h-3" />
                                        </button>
                                        <div className="font-medium text-slate-200 text-xs mb-1 truncate pr-8">{bm.name}</div>
                                        <div className="text-[10px] text-slate-500 flex justify-between items-center">
                                            <span>{new Date(bm.created_at).toLocaleDateString()}</span>
                                            <button 
                                                onClick={() => handleBranchFromBookmark(bm.id)}
                                                className="opacity-0 group-hover:opacity-100 px-2 py-0.5 bg-sky-500/20 hover:bg-sky-500 text-sky-400 hover:text-white rounded text-[9px] transition-all font-bold uppercase"
                                            >
                                                Branch 分支
                                            </button>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>

                </aside>

                {/* Content Area */}
                <section className="flex flex-col flex-1 h-full min-h-0">
                    <div className="bg-slate-800/50 flex flex-col border border-white/10 rounded-3xl overflow-hidden backdrop-blur-sm shadow-2xl h-full relative">

                        {/* Nav Tabs */}
                        <div className="px-6 py-4 border-b border-white/10 flex justify-between items-center bg-white/5 z-10 relative">
                            <div className="inline-flex items-center gap-1 rounded-xl bg-white/5 border border-white/10 p-1">
                                <button
                                    onClick={() => setActiveTab('plot')}
                                    className={`h-8 px-4 rounded-lg text-sm leading-tight transition-all flex items-center gap-2 ${
                                        activeTab === 'plot'
                                            ? 'bg-sky-500 text-white shadow-lg shadow-sky-500/20'
                                            : 'text-slate-400 hover:text-white'
                                    }`}
                                >
                                    <History className="w-4 h-4 shrink-0" />
                                    <span>平行宇宙</span>
                                </button>
                                <button
                                    onClick={() => setActiveTab('graph')}
                                    className={`h-8 px-4 rounded-lg text-sm leading-tight transition-all flex items-center gap-2 ${
                                        activeTab === 'graph'
                                            ? 'bg-indigo-500 text-white shadow-lg shadow-indigo-500/20'
                                            : 'text-slate-400 hover:text-white'
                                    }`}
                                >
                                    <Network className="w-4 h-4 shrink-0" />
                                    <span>Zep 物理图谱</span>
                                </button>
                            </div>
                        </div>

                        {/* Visualizer Body */}
                        <div className="relative bg-black/20 flex-1 overflow-hidden" style={{ display: activeTab === 'graph' ? 'block' : 'none' }}>
                            <div className="absolute top-4 right-4 z-20 flex items-center gap-2 bg-slate-900/80 border border-white/10 rounded-xl p-2 backdrop-blur-sm">
                                <button
                                    onClick={fitGraphView}
                                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-200 transition-colors"
                                    title="图谱居中（最优尺寸）"
                                >
                                    <LocateFixed className="w-4 h-4" />
                                </button>
                                <button
                                    onClick={() => zoomGraph(0.15)}
                                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-200 transition-colors"
                                    title="放大"
                                >
                                    <ZoomIn className="w-4 h-4" />
                                </button>
                                <button
                                    onClick={() => zoomGraph(-0.15)}
                                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-200 transition-colors"
                                    title="缩小"
                                >
                                    <ZoomOut className="w-4 h-4" />
                                </button>
                                <button
                                    onClick={resetGraphZoom}
                                    className="px-2 py-1 text-xs rounded-lg bg-white/5 hover:bg-white/10 text-slate-200 transition-colors"
                                    title="1:1"
                                >
                                    1:1
                                </button>
                            </div>
                            {isGraphLoading && (
                                <div className="absolute inset-0 z-10 flex flex-col items-center justify-center text-slate-500 backdrop-blur-md bg-black/40">
                                    <Loader2 className="w-12 h-12 mb-4 animate-spin opacity-50 text-indigo-400" />
                                    <p className="text-sm tracking-wider">正在拉取由于变动而刷新的世界知识...</p>
                                </div>
                            )}
                            {graphData?.nodes?.length === 0 && !isGraphLoading && (
                                <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500">
                                    {(() => {
                                        const currentNovel = novels.find(n => n.collection_name === currentCollection);
                                        const status = currentNovel?.status;
                                        
                                        if (status === 'processing') {
                                            return (
                                                <>
                                                    <Loader2 className="w-12 h-12 mb-4 animate-spin opacity-50 text-amber-400" />
                                                    <p className="text-sm">正在处理小说内容，请稍候...</p>
                                                </>
                                            );
                                        } else if (status === 'completed') {
                                            return (
                                                <>
                                                    <Network className="w-12 h-12 mb-4 opacity-20" />
                                                    <p className="text-sm">分块处理完成，等待实体提取开始...</p>
                                                </>
                                            );
                                        } else if (status === 'extracting') {
                                            return (
                                                <>
                                                    <Loader2 className="w-12 h-12 mb-4 animate-spin opacity-50 text-purple-400" />
                                                    <p className="text-sm">正在提取实体和关系，请稍候...</p>
                                                </>
                                            );
                                        } else {
                                            return (
                                                <>
                                                    <Network className="w-12 h-12 mb-4 opacity-20" />
                                                    <p className="text-sm">知识图谱暂无数据，可能小说内容较短或未检测到实体。</p>
                                                </>
                                            );
                                        }
                                    })()}
                                </div>
                            )}
                            <div ref={graphContainer} className="w-full h-full" />
                        </div>

                        {/* Chat/Story Body */}
                        <div className="relative flex flex-col flex-1 bg-black/20 overflow-hidden" style={{ display: activeTab === 'plot' ? 'flex' : 'none' }}>
                            {/* Original Storyline Timeline */}
                            <div className="border-b border-white/5 bg-slate-800/20 p-4">
                                <div className="flex items-center justify-between mb-3">
                                    <h3 className="text-xs font-bold uppercase tracking-widest text-slate-500 flex items-center gap-2">
                                        <History className="w-3 h-3" /> 原始剧情时间线
                                    </h3>
                                    <span className="text-[10px] text-slate-600">{chapters.length} 个章节已载入</span>
                                </div>
                                <div className="flex gap-4 overflow-x-auto pb-2 custom-scrollbar no-scrollbar">
                                    {isChaptersLoading ? (
                                        <Loader2 className="w-4 h-4 animate-spin opacity-50" />
                                    ) : chapters.length === 0 ? (
                                        <p className="text-[10px] text-slate-600">暂无捕捉到明显章节结构</p>
                                    ) : (
                                        chapters.map((ch) => (
                                            <div 
                                                key={ch.id} 
                                                className="min-w-[180px] group bg-white/5 hover:bg-white/10 border border-white/5 hover:border-sky-500/30 rounded-xl p-3 transition-all cursor-pointer relative"
                                            >
                                                <div className="text-xs font-medium text-sky-400 truncate mb-1">{ch.title}</div>
                                                <div className="text-[10px] text-slate-500 line-clamp-2 leading-relaxed">
                                                    {ch.content_preview}
                                                </div>
                                                <button 
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setStartChapterId(ch.id);
                                                        setStartChapterTitle(ch.title);
                                                        setNewSessionName(`基于: ${ch.title}`);
                                                        setShowNewSessionModal(true);
                                                    }}
                                                    className="absolute inset-0 bg-sky-500/80 text-white text-[10px] font-bold opacity-0 group-hover:opacity-100 flex items-center justify-center rounded-xl transition-all"
                                                >
                                                    从本章开启平行宇宙
                                                </button>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </div>
                            
                            <div className="flex-1 overflow-y-auto p-6 space-y-6 flex flex-col">

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
                                                <div className="bg-white/5 border border-white/10 rounded-2xl rounded-tl-sm p-5 space-y-4 group/msg relative">
                                                    <div className="text-slate-300 leading-relaxed whitespace-pre-wrap font-serif tracking-wide text-[15px]">
                                                        {msg.story_text}
                                                    </div>

                                                    {/* Bookmark Button */}
                                                    <button 
                                                        onClick={() => {
                                                            setShowBookmarkModal(true);
                                                            setBookmarkName(`书签 ${new Date().toLocaleTimeString()}`);
                                                        }}
                                                        className="absolute -right-12 top-0 p-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-500 hover:text-amber-400 opacity-0 group-hover/msg:opacity-100 transition-all"
                                                        title="点击创建书签"
                                                    >
                                                        <Save className="w-5 h-5" />
                                                    </button>

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

                            {/* Mode Selector Area */}
                            <div className="px-6 py-2 flex items-center justify-between border-t border-white/5 bg-slate-800/10 backdrop-blur-sm">
                                <div className="flex gap-1 bg-black/40 p-1 rounded-xl border border-white/5">
                                    <button
                                        onClick={() => setDirectorMode(DirectorMode.SANDBOX)}
                                        className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-2 ${
                                            directorMode === DirectorMode.SANDBOX 
                                            ? 'bg-amber-500 text-white shadow-lg shadow-amber-500/20' 
                                            : 'text-slate-400 hover:text-white'
                                        }`}
                                    >
                                        <Zap className="w-3 h-3" /> 沙盒模式 A
                                    </button>
                                    <button
                                        onClick={() => setDirectorMode(DirectorMode.CONVERGENCE)}
                                        className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-2 ${
                                            directorMode === DirectorMode.CONVERGENCE 
                                            ? 'bg-indigo-500 text-white shadow-lg shadow-indigo-500/20' 
                                            : 'text-slate-400 hover:text-white'
                                        }`}
                                    >
                                        <Target className="w-3 h-3" /> 收束模式 B
                                    </button>
                                </div>
                                <div className="text-[10px] text-slate-500 font-medium">
                                    {directorMode === DirectorMode.SANDBOX 
                                        ? "当前状态：自由推演中" 
                                        : "当前状态：剧情引导中"}
                                </div>
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
                                        disabled={isChatting || !isNovelReady || isCurrentSessionRoot}
                                        placeholder={
                                            isCurrentSessionRoot 
                                                ? "原始剧情线不可编辑，请创建平行宇宙进行剧情推演..."
                                                : isNovelReady 
                                                    ? "执行动作 / 说出对白 / 心中暗想..." 
                                                    : "作品尚未就绪，无法进行剧情推演..."
                                        }
                                        className={`flex-1 border rounded-full px-6 py-4 text-white focus:outline-none transition-colors shadow-inner ${
                                            isNovelReady && !isCurrentSessionRoot
                                                ? 'bg-black/40 border-white/10 focus:border-sky-500 focus:ring-1 focus:ring-sky-500'
                                                : 'bg-slate-800 border-slate-700 text-slate-500 cursor-not-allowed'
                                        }`}
                                    />
                                    <button
                                        disabled={isChatting || !chatInput.trim() || !isNovelReady || isCurrentSessionRoot}
                                        type="submit"
                                        className="absolute right-2 px-4 py-2 bg-sky-500 hover:bg-sky-400 text-white rounded-full transition-all flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-sky-500/20 font-bold"
                                    >
                                        推进 <Send className="w-4 h-4 ml-1" />
                                    </button>
                                </form>
                            </div>
                        </div>

                    </div>
                </section>
            </main>

            {/* New Parallel Universe Modal */}
            {showNewSessionModal && (
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
                                value={newSessionName}
                                onChange={(e) => setNewSessionName(e.target.value)}
                                placeholder="例如：被改变的抉择 / 隐藏的真相..."
                                className="w-full bg-black/30 border border-white/10 rounded-xl px-5 py-4 text-white focus:outline-none focus:border-amber-500 transition-all font-medium"
                                autoFocus
                            />
                            <div className="flex gap-3">
                                <button
                                    onClick={() => setShowNewSessionModal(false)}
                                    className="flex-1 px-4 py-3.5 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 font-medium transition-all"
                                >
                                    放弃
                                </button>
                                <button
                                    onClick={handleCreateSession}
                                    disabled={!newSessionName.trim()}
                                    className="flex-1 px-4 py-3.5 rounded-xl bg-amber-500 hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold transition-all shadow-lg shadow-amber-500/20"
                                >
                                    确认开启
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Bookmark Modal */}
            {showBookmarkModal && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in">
                    <div className="bg-slate-800 border border-white/10 rounded-2xl p-6 w-full max-w-sm shadow-2xl animate-in zoom-in duration-200">
                        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-amber-400">
                            <Save className="w-5 h-5" />
                            创建书签
                        </h3>
                        <p className="text-xs text-slate-400 mb-4">保存当前故事节点以便稍后分支到“平行宇宙”</p>
                        <input
                            type="text"
                            value={bookmarkName}
                            onChange={(e) => setBookmarkName(e.target.value)}
                            className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-2.5 text-sm mb-4 focus:outline-none focus:border-amber-500"
                            placeholder="书签名称"
                            autoFocus
                        />
                        <div className="flex gap-3">
                            <button
                                onClick={() => setShowBookmarkModal(false)}
                                className="flex-1 px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 text-sm"
                            >
                                取消
                            </button>
                            <button
                                onClick={handleCreateBookmark}
                                className="flex-1 px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-600 text-white text-sm"
                            >
                                确定
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Config Modal */}
            {showConfigModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <div 
                        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                        onClick={() => setShowConfigModal(false)}
                    />
                    <div className="relative bg-slate-900 border border-white/10 rounded-2xl shadow-2xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col">
                        {/* Modal Header */}
                        <div className="px-6 py-4 border-b border-white/10 flex justify-between items-center bg-slate-800/50">
                            <div>
                                <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                                    <Settings className="w-6 h-6 text-emerald-400" />
                                    系统配置
                                </h2>
                                <p className="text-sm text-slate-400 mt-1">配置系统参数，调整后立即生效</p>
                            </div>
                            <div className="flex gap-3">
                                <button
                                    onClick={handleRestartServices}
                                    disabled={isRestarting}
                                    className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-600 text-white text-sm transition-all flex items-center gap-2 disabled:opacity-50"
                                >
                                    {isRestarting ? (
                                        <>
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                            重启中...
                                        </>
                                    ) : (
                                        <>
                                            <RefreshCw className="w-4 h-4" />
                                            重启服务
                                        </>
                                    )}
                                </button>
                                <button
                                    onClick={handleResetConfig}
                                    className="px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 text-sm transition-all flex items-center gap-2"
                                >
                                    <RotateCcw className="w-4 h-4" />
                                    重置
                                </button>
                                <button
                                    onClick={handleSaveConfig}
                                    disabled={configSaveStatus === 'saving'}
                                    className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm transition-all flex items-center gap-2 disabled:opacity-50"
                                >
                                    {configSaveStatus === 'saving' ? (
                                        <>
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                            保存中...
                                        </>
                                    ) : configSaveStatus === 'saved' ? (
                                        <>
                                            <CheckCircle className="w-4 h-4" />
                                            已保存
                                        </>
                                    ) : (
                                        <>
                                            <Save className="w-4 h-4" />
                                            保存配置
                                        </>
                                    )}
                                </button>
                                <button
                                    onClick={() => setShowHelpModal(true)}
                                    className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-600 text-white text-sm transition-all flex items-center gap-2"
                                >
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                    </svg>
                                    帮助
                                </button>
                                <button
                                    onClick={() => setShowConfigModal(false)}
                                    className="p-2 rounded-lg hover:bg-white/10 text-slate-400 transition-all"
                                >
                                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                    </svg>
                                </button>
                            </div>
                        </div>

                        {/* Modal Body */}
                        <div className="flex-1 flex overflow-hidden">
                            {/* Sidebar Navigation */}
                            <div className="w-48 border-r border-white/10 p-4 flex flex-col gap-2">
                                <button
                                    onClick={() => scrollToSection('presets')}
                                    className={`text-left px-4 py-3 rounded-lg transition-all ${
                                        activeSection === 'presets'
                                            ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30'
                                            : 'hover:bg-white/5 text-slate-400'
                                    }`}
                                >
                                    配置预设
                                </button>
                                <button
                                    onClick={() => scrollToSection('performance')}
                                    className={`text-left px-4 py-3 rounded-lg transition-all ${
                                        activeSection === 'performance'
                                            ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30'
                                            : 'hover:bg-white/5 text-slate-400'
                                    }`}
                                >
                                    性能参数
                                </button>
                                <button
                                    onClick={() => scrollToSection('business')}
                                    className={`text-left px-4 py-3 rounded-lg transition-all ${
                                        activeSection === 'business'
                                            ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30'
                                            : 'hover:bg-white/5 text-slate-400'
                                    }`}
                                >
                                    业务参数
                                </button>
                                <button
                                    onClick={() => scrollToSection('api')}
                                    className={`text-left px-4 py-3 rounded-lg transition-all ${
                                        activeSection === 'api'
                                            ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30'
                                            : 'hover:bg-white/5 text-slate-400'
                                    }`}
                                >
                                    API 配置
                                </button>
                            </div>
                            
                            {/* Config Content */}
                            <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
                            {isConfigLoading ? (
                                <div className="flex flex-col items-center justify-center py-20">
                                    <Loader2 className="w-12 h-12 mb-4 animate-spin opacity-50 text-emerald-400" />
                                    <p className="text-sm tracking-wider">正在加载配置...</p>
                                </div>
                            ) : config ? (
                                <div className="max-w-4xl mx-auto space-y-6">
                                    {/* Presets */}
                                    <div id="presets" className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 scroll-mt-4">
                                        <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                                            <Target className="w-5 h-5 text-sky-400" />
                                            配置预设
                                        </h3>
                                        <div className="grid grid-cols-3 gap-4">
                                            <button
                                                onClick={() => handleApplyPreset('default')}
                                                className={`p-4 rounded-xl border transition-all ${
                                                    selectedPreset === 'default'
                                                        ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-400'
                                                        : 'bg-white/5 border-white/10 hover:border-sky-500/50 text-slate-300'
                                                }`}
                                            >
                                                <div className="font-medium">默认配置</div>
                                                <div className="text-xs text-slate-500 mt-1">适合大多数场景</div>
                                            </button>
                                            <button
                                                onClick={() => handleApplyPreset('high_concurrency')}
                                                className={`p-4 rounded-xl border transition-all ${
                                                    selectedPreset === 'high_concurrency'
                                                        ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-400'
                                                        : 'bg-white/5 border-white/10 hover:border-sky-500/50 text-slate-300'
                                                }`}
                                            >
                                                <div className="font-medium">高并发模式</div>
                                                <div className="text-xs text-slate-500 mt-1">无限制 LLM</div>
                                            </button>
                                            <button
                                                onClick={() => handleApplyPreset('low_latency')}
                                                className={`p-4 rounded-xl border transition-all ${
                                                    selectedPreset === 'low_latency'
                                                        ? 'bg-emerald-500/10 border-emerald-500/50 text-emerald-400'
                                                        : 'bg-white/5 border-white/10 hover:border-sky-500/50 text-slate-300'
                                                }`}
                                            >
                                                <div className="font-medium">低延迟模式</div>
                                                <div className="text-xs text-slate-500 mt-1">快速响应</div>
                                            </button>
                                        </div>
                                    </div>

                                    {/* Performance Config */}
                                    <div id="performance" className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 scroll-mt-4">
                                        <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                                            <Brain className="w-5 h-5 text-purple-400" />
                                            性能参数
                                        </h3>
                                        <div className="grid grid-cols-2 gap-6">
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">LLM 最大并发数</label>
                                                <input
                                                    type="number"
                                                    value={config.performance.graphiti_llm_max_concurrency}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        performance: {
                                                            ...config.performance,
                                                            graphiti_llm_max_concurrency: parseInt(e.target.value) || 1
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">同时发送给 LLM 的最大请求数</p>
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">LLM 请求间隔（秒）</label>
                                                <input
                                                    type="number"
                                                    step="0.1"
                                                    value={config.performance.graphiti_llm_min_interval}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        performance: {
                                                            ...config.performance,
                                                            graphiti_llm_min_interval: parseFloat(e.target.value) || 0.1
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">两次请求之间的最小间隔</p>
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">批量写入大小</label>
                                                <input
                                                    type="number"
                                                    value={config.performance.batch_size}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        performance: {
                                                            ...config.performance,
                                                            batch_size: parseInt(e.target.value) || 1
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">每批写入 Zep 的消息数量</p>
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">批次间延迟（秒）</label>
                                                <input
                                                    type="number"
                                                    step="0.1"
                                                    value={config.performance.batch_delay}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        performance: {
                                                            ...config.performance,
                                                            batch_delay: parseFloat(e.target.value) || 0.1
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">每批写入后的等待时间</p>
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">轮询间隔（秒）</label>
                                                <input
                                                    type="number"
                                                    value={config.performance.poll_interval}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        performance: {
                                                            ...config.performance,
                                                            poll_interval: parseInt(e.target.value) || 1
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">小说列表状态更新间隔</p>
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">状态轮询间隔（秒）</label>
                                                <input
                                                    type="number"
                                                    value={config.performance.status_poll_interval}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        performance: {
                                                            ...config.performance,
                                                            status_poll_interval: parseInt(e.target.value) || 1
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">单个小说状态更新间隔</p>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Business Config */}
                                    <div id="business" className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 scroll-mt-4">
                                        <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                                            <PenTool className="w-5 h-5 text-orange-400" />
                                            业务参数
                                        </h3>
                                        <div className="grid grid-cols-2 gap-6">
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">最大文件大小（MB）</label>
                                                <input
                                                    type="number"
                                                    value={config.business.max_file_size_mb}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        business: {
                                                            ...config.business,
                                                            max_file_size_mb: parseInt(e.target.value) || 1
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">上传文件的最大大小</p>
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">分段最小长度</label>
                                                <input
                                                    type="number"
                                                    value={config.business.chunk_min_length}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        business: {
                                                            ...config.business,
                                                            chunk_min_length: parseInt(e.target.value) || 10
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">文本分段的最小字符数</p>
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">分段最大长度</label>
                                                <input
                                                    type="number"
                                                    value={config.business.chunk_max_length}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        business: {
                                                            ...config.business,
                                                            chunk_max_length: parseInt(e.target.value) || 100
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">文本分段的最大字符数</p>
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">Zep 超时时间（秒）</label>
                                                <input
                                                    type="number"
                                                    value={config.business.zep_timeout}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        business: {
                                                            ...config.business,
                                                            zep_timeout: parseInt(e.target.value) || 60
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">Zep API 调用的超时时间</p>
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm text-slate-300">Neo4j 超时时间（秒）</label>
                                                <input
                                                    type="number"
                                                    value={config.business.neo4j_timeout}
                                                    onChange={(e) => setConfig({
                                                        ...config,
                                                        business: {
                                                            ...config.business,
                                                            neo4j_timeout: parseInt(e.target.value) || 30
                                                        }
                                                    })}
                                                    className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                />
                                                <p className="text-xs text-slate-500">Neo4j 操作的超时时间</p>
                                            </div>
                                        </div>
                                    </div>

                                    {/* API Config */}
                                    <div id="api" className="bg-slate-800/50 border border-white/10 rounded-2xl p-6 scroll-mt-4">
                                        <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                                            <Network className="w-5 h-5 text-cyan-400" />
                                            API 配置
                                        </h3>
                                        <div className="space-y-6">
                                            <div className="grid grid-cols-2 gap-6">
                                                <div className="space-y-2">
                                                    <label className="text-sm text-slate-300">LLM API Key</label>
                                                    <input
                                                        type="password"
                                                        value={config.api.llm_api_key}
                                                        onChange={(e) => setConfig({
                                                            ...config,
                                                            api: {
                                                                ...config.api,
                                                                llm_api_key: e.target.value
                                                            }
                                                        })}
                                                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                        placeholder="sk-..."
                                                    />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-sm text-slate-300">LLM Base URL</label>
                                                    <input
                                                        type="text"
                                                        value={config.api.llm_base_url}
                                                        onChange={(e) => setConfig({
                                                            ...config,
                                                            api: {
                                                                ...config.api,
                                                                llm_base_url: e.target.value
                                                            }
                                                        })}
                                                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                        placeholder="https://api.openai.com/v1"
                                                    />
                                                </div>
                                            </div>
                                            <div className="grid grid-cols-2 gap-6">
                                                <div className="space-y-2">
                                                    <label className="text-sm text-slate-300">Embedding API Key</label>
                                                    <input
                                                        type="password"
                                                        value={config.api.embedding_api_key}
                                                        onChange={(e) => setConfig({
                                                            ...config,
                                                            api: {
                                                                ...config.api,
                                                                embedding_api_key: e.target.value
                                                            }
                                                        })}
                                                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                        placeholder="sk-..."
                                                    />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-sm text-slate-300">Embedding Base URL</label>
                                                    <input
                                                        type="text"
                                                        value={config.api.embedding_base_url}
                                                        onChange={(e) => setConfig({
                                                            ...config,
                                                            api: {
                                                                ...config.api,
                                                                embedding_base_url: e.target.value
                                                            }
                                                        })}
                                                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                        placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                                                    />
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-sm text-slate-300">Embedding 模型</label>
                                                    <input
                                                        type="text"
                                                        value={config.api.embedding_model}
                                                        onChange={(e) => setConfig({
                                                            ...config,
                                                            api: {
                                                                ...config.api,
                                                                embedding_model: e.target.value
                                                            }
                                                        })}
                                                        className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                        placeholder="text-embedding-v4"
                                                    />
                                                </div>
                                            </div>

                                            {/* 独立模型配置 */}
                                            <div className="border-t border-white/10 pt-6">
                                                <h4 className="text-sm font-semibold text-cyan-400 mb-4 flex items-center gap-2">
                                                    <Network className="w-4 h-4" />
                                                    功能模型配置
                                                </h4>
                                                <div className="grid grid-cols-2 gap-6">
                                                    <div className="space-y-2">
                                                        <label className="text-sm text-slate-300">导演模型 (剧情推演)</label>
                                                        <input
                                                            type="text"
                                                            value={config.api.model_director}
                                                            onChange={(e) => setConfig({
                                                                ...config,
                                                                api: {
                                                                    ...config.api,
                                                                    model_director: e.target.value
                                                                }
                                                            })}
                                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                            placeholder="gpt-4o"
                                                        />
                                                        <p className="text-xs text-slate-500">用于剧情生成、NPC对话、复杂推演</p>
                                                    </div>
                                                    <div className="space-y-2">
                                                        <label className="text-sm text-slate-300">解析模型 (意图分析)</label>
                                                        <input
                                                            type="text"
                                                            value={config.api.model_parser}
                                                            onChange={(e) => setConfig({
                                                                ...config,
                                                                api: {
                                                                    ...config.api,
                                                                    model_parser: e.target.value
                                                                }
                                                            })}
                                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                            placeholder="gpt-4o-mini"
                                                        />
                                                        <p className="text-xs text-slate-500">用于极速解构玩家输入，追求低延迟</p>
                                                    </div>
                                                    <div className="space-y-2">
                                                        <label className="text-sm text-slate-300">Zep 提取模型 (知识图谱)</label>
                                                        <input
                                                            type="text"
                                                            value={config.api.model_zep_extractor}
                                                            onChange={(e) => setConfig({
                                                                ...config,
                                                                api: {
                                                                    ...config.api,
                                                                    model_zep_extractor: e.target.value
                                                                }
                                                            })}
                                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                            placeholder="gpt-4o-mini"
                                                        />
                                                        <p className="text-xs text-slate-500">用于高质量事实提取和摘要生成</p>
                                                    </div>
                                                    <div className="space-y-2">
                                                        <label className="text-sm text-slate-300">Graphiti 模型 (实体提取)</label>
                                                        <input
                                                            type="text"
                                                            value={config.api.model_graphiti}
                                                            onChange={(e) => setConfig({
                                                                ...config,
                                                                api: {
                                                                    ...config.api,
                                                                    model_graphiti: e.target.value
                                                                }
                                                            })}
                                                            className="w-full bg-black/30 border border-white/10 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-emerald-500 transition-all"
                                                            placeholder="gpt-4o"
                                                        />
                                                        <p className="text-xs text-slate-500">用于高精度实体和关系提取</p>
                                                    </div>
                                                </div>
                                            </div>

                                            <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4 flex items-start gap-3">
                                                <Info className="w-5 h-5 text-emerald-400 mt-0.5 flex-shrink-0" />
                                                <div className="text-sm text-slate-300">
                                                    <p className="font-medium text-emerald-400 mb-1">配置提示</p>
                                                    <p>API Key 将保存到后端 .env 文件中。修改后需要重启 Docker 服务才能完全生效。</p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ) : null}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Help Modal */}
            {showHelpModal && (
                <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
                    <div 
                        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                        onClick={() => setShowHelpModal(false)}
                    />
                    <div className="relative bg-slate-900 border border-white/10 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
                        {/* Modal Header */}
                        <div className="px-6 py-4 border-b border-white/10 flex justify-between items-center bg-slate-800/50">
                            <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                                <svg className="w-6 h-6 text-sky-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                </svg>
                                配置帮助
                            </h2>
                            <button
                                onClick={() => setShowHelpModal(false)}
                                className="p-2 rounded-lg hover:bg-white/10 text-slate-400 transition-all"
                            >
                                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>

                        {/* Modal Body */}
                        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
                            <div className="max-w-3xl mx-auto space-y-8">
                                {/* 配置预设说明 */}
                                <section>
                                    <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                                        <Target className="w-5 h-5 text-sky-400" />
                                        配置预设
                                    </h3>
                                    <div className="space-y-4">
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-sky-400 mb-2">默认配置</h4>
                                            <p className="text-slate-300 text-sm">适合大多数场景的平衡配置，兼顾性能和质量。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-sky-400 mb-2">高并发模式</h4>
                                            <p className="text-slate-300 text-sm">适合高并发 LLM，最大化处理速度，需要较强的 LLM 提供商支持。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-sky-400 mb-2">低延迟模式</h4>
                                            <p className="text-slate-300 text-sm">优先考虑响应速度，适合小文件快速处理。</p>
                                        </div>
                                    </div>
                                </section>

                                {/* 性能参数详解 */}
                                <section>
                                    <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                                        <Brain className="w-5 h-5 text-purple-400" />
                                        性能参数
                                    </h3>
                                    <div className="space-y-3">
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-purple-400 mb-1">LLM 最大并发数</h4>
                                            <p className="text-slate-300 text-sm">同时发送给 LLM 的最大请求数。建议根据 LLM 提供商的限制设置，一般为 1-10。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-purple-400 mb-1">LLM 请求间隔（秒）</h4>
                                            <p className="text-slate-300 text-sm">两次请求之间的最小间隔。避免触发 LLM 提供商的速率限制，一般为 0.1-1.0 秒。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-purple-400 mb-1">批量写入大小</h4>
                                            <p className="text-slate-300 text-sm">每批写入 Zep 的消息数量。较大的值可以提高写入效率，但会增加内存使用。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-purple-400 mb-1">批次间延迟（秒）</h4>
                                            <p className="text-slate-300 text-sm">每批写入后的等待时间。避免对 Zep 服务造成过大压力。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-purple-400 mb-1">轮询间隔（秒）</h4>
                                            <p className="text-slate-300 text-sm">小说列表状态更新间隔。用于定期刷新小说处理状态。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-purple-400 mb-1">状态轮询间隔（秒）</h4>
                                            <p className="text-slate-300 text-sm">单个小说状态更新间隔。用于更频繁地检查特定小说的处理进度。</p>
                                        </div>
                                    </div>
                                </section>

                                {/* 业务参数详解 */}
                                <section>
                                    <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                                        <PenTool className="w-5 h-5 text-orange-400" />
                                        业务参数
                                    </h3>
                                    <div className="space-y-3">
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-orange-400 mb-1">最大文件大小（MB）</h4>
                                            <p className="text-slate-300 text-sm">上传文件的最大大小限制。过大的文件可能会影响处理性能。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-orange-400 mb-1">分段最小/最大长度</h4>
                                            <p className="text-slate-300 text-sm">文本分段的最小和最大字符数。合理的分段可以提高 LLM 处理效率和准确性。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-orange-400 mb-1">Zep 超时时间（秒）</h4>
                                            <p className="text-slate-300 text-sm">Zep API 调用的超时时间。较大的文件处理可能需要更长的超时时间。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-orange-400 mb-1">Neo4j 超时时间（秒）</h4>
                                            <p className="text-slate-300 text-sm">Neo4j 操作的超时时间。复杂查询可能需要更长的超时时间。</p>
                                        </div>
                                    </div>
                                </section>

                                {/* API 配置指南 */}
                                <section>
                                    <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                                        <Network className="w-5 h-5 text-cyan-400" />
                                        API 配置指南
                                    </h3>
                                    <div className="space-y-4">
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-cyan-400 mb-2">导演模型 (剧情推演)</h4>
                                            <p className="text-slate-300 text-sm mb-2">需求：高质量剧情生成、NPC对话、复杂推演</p>
                                            <p className="text-slate-400 text-xs">示例：GPT-4o, Claude-3.5-Sonnet, DeepSeek-Chat</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-cyan-400 mb-2">解析模型 (意图分析)</h4>
                                            <p className="text-slate-300 text-sm mb-2">需求：极速解构玩家输入，追求低延迟</p>
                                            <p className="text-slate-400 text-xs">示例：GPT-4o-mini, DeepSeek-Chat</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-cyan-400 mb-2">Zep 提取模型 (知识图谱)</h4>
                                            <p className="text-slate-300 text-sm mb-2">需求：高质量事实提取和摘要生成</p>
                                            <p className="text-slate-400 text-xs">示例：GPT-4o, GPT-4o-mini</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-cyan-400 mb-2">Graphiti 模型 (实体提取)</h4>
                                            <p className="text-slate-300 text-sm mb-2">需求：高精度实体和关系提取</p>
                                            <p className="text-slate-400 text-xs">示例：GPT-4o, Claude-3.5-Sonnet, DeepSeek-Chat</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-cyan-400 mb-2">Embedding 模型</h4>
                                            <p className="text-slate-300 text-sm mb-2">需求：高质量文本向量化，支持语义搜索</p>
                                            <p className="text-slate-400 text-xs">示例：text-embedding-v4, text-embedding-3-small, text-embedding-ada-002</p>
                                        </div>
                                    </div>
                                </section>

                                {/* 常见问题 */}
                                <section>
                                    <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                                        <AlertCircle className="w-5 h-5 text-amber-400" />
                                        常见问题
                                    </h3>
                                    <div className="space-y-3">
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-amber-400 mb-1">配置修改后需要重启服务吗？</h4>
                                            <p className="text-slate-300 text-sm">是的，Docker 服务需要重启才能完全生效。请点击"重启服务"按钮。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-amber-400 mb-1">如何选择合适的并发数？</h4>
                                            <p className="text-slate-300 text-sm">根据 LLM 提供商的限制和网络状况调整。建议从 1 开始逐步增加，观察性能变化。</p>
                                        </div>
                                        <div className="bg-slate-800/50 border border-white/10 rounded-xl p-4">
                                            <h4 className="font-semibold text-amber-400 mb-1">为什么需要配置多个模型？</h4>
                                            <p className="text-slate-300 text-sm">不同功能对模型的需求不同。剧情推演需要高质量模型，意图解析可以使用更快的模型，这样可以优化性能和成本。</p>
                                        </div>
                                    </div>
                                </section>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Modern Modal System */}
            {modalConfig.show && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
                    <div className="bg-slate-900/90 border border-white/10 rounded-3xl p-8 w-full max-w-md shadow-2xl animate-in zoom-in duration-300 backdrop-blur-xl relative overflow-hidden">
                        {/* Status Accent Bar */}
                        <div className={`absolute top-0 left-0 w-full h-1.5 ${
                            modalConfig.type === 'success' ? 'bg-emerald-500' :
                            modalConfig.type === 'error' ? 'bg-red-500' :
                            modalConfig.type === 'warning' ? 'bg-amber-500' : 'bg-sky-500'
                        }`} />
                        
                        <div className="flex flex-col items-center text-center">
                            <div className={`w-16 h-16 rounded-2xl flex items-center justify-center mb-6 ${
                                modalConfig.type === 'success' ? 'bg-emerald-500/10 text-emerald-400' :
                                modalConfig.type === 'error' ? 'bg-red-500/10 text-red-400' :
                                modalConfig.type === 'warning' ? 'bg-amber-500/10 text-amber-400' : 'bg-sky-500/10 text-sky-400'
                            }`}>
                                {modalConfig.type === 'success' && <CheckCircle className="w-8 h-8" />}
                                {modalConfig.type === 'error' && <AlertCircle className="w-8 h-8" />}
                                {modalConfig.type === 'warning' && <AlertCircle className="w-8 h-8" />}
                                {modalConfig.type === 'info' && <Info className="w-8 h-8" />}
                            </div>
                            
                            <h3 className="text-xl font-bold text-white mb-3">{modalConfig.title}</h3>
                            <p className="text-slate-400 text-sm leading-relaxed mb-8">{modalConfig.message}</p>
                            
                            <div className="flex gap-3 w-full">
                                {modalConfig.showCancel && (
                                    <button
                                        onClick={() => {
                                            if (modalConfig.onCancel) modalConfig.onCancel();
                                            setModalConfig(prev => ({ ...prev, show: false }));
                                        }}
                                        className="flex-1 px-6 py-3 rounded-xl bg-white/5 hover:bg-white/10 text-slate-300 font-medium transition-all border border-white/5"
                                    >
                                        {modalConfig.cancelText || '取消'}
                                    </button>
                                )}
                                <button
                                    onClick={() => {
                                        if (modalConfig.onConfirm) modalConfig.onConfirm();
                                        setModalConfig(prev => ({ ...prev, show: false }));
                                    }}
                                    className={`flex-1 px-6 py-3 rounded-xl font-bold text-white transition-all shadow-lg ${
                                        modalConfig.type === 'success' ? 'bg-emerald-500 hover:bg-emerald-600 shadow-emerald-500/20' :
                                        modalConfig.type === 'error' ? 'bg-red-500 hover:bg-red-600 shadow-red-500/20' :
                                        modalConfig.type === 'warning' ? 'bg-amber-500 hover:bg-amber-600 shadow-amber-500/20' :
                                        'bg-sky-500 hover:bg-sky-600 shadow-sky-500/20'
                                    }`}
                                >
                                    {modalConfig.confirmText || '确定'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default App;
