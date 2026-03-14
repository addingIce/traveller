import axios from 'axios';

const apiClient = axios.create({
    baseURL: '/api/v1',
    headers: {
        'Content-Type': 'application/json',
    },
});

export interface IntentSummary {
    action?: string;
    dialogue?: string;
    thought?: string;
}

export interface WorldImpact {
    world_state_changed: boolean;
    reason?: string;
}

export interface ChatResponse {
    story_text: string;
    user_intent_summary: IntentSummary;
    world_impact: WorldImpact;
    ui_hints: string[];
}

// Session & Timeline Types
export interface SessionInfo {
    session_id: string;
    novel_id: string;
    user_id: string;
    session_name: string;
    created_at: string;
    last_interaction_at: string | null;
    parent_session_id: string | null;
    is_root: boolean;
}

export interface BookmarkInfo {
    id: string;
    session_id: string;
    name: string;
    description: string | null;
    created_at: string;
    checkpoint_id: string;
}

export interface ChapterInfo {
    id: string;
    title: string;
    content_preview: string;
    order: number;
}

export const fetchKnowledgeGraph = async (collectionName: string) => {
    const { data } = await apiClient.get(`/graph/${collectionName}`);
    return data;
};

export const searchGraph = async (collectionName: string, query: string) => {
    const { data } = await apiClient.get(`/graph/${collectionName}/search`, { params: { query } });
    return data;
};

export const fetchGraphFacts = async (collectionName: string, query: string, signal?: AbortSignal) => {
    const { data } = await apiClient.get(`/graph/${collectionName}/facts`, { params: { query }, signal });
    return data;
};

export const fetchNodeDetail = async (uuid: string) => {
    const { data } = await apiClient.get(`/graph/node/${uuid}`);
    return data;
};

export const chatInteract = async (sessionId: string, collectionName: string, message: string): Promise<ChatResponse> => {
    const { data } = await apiClient.post('/chat/interact', {
        session_id: sessionId,
        collection_name: collectionName,
        message,
    });
    return data;
};

// 小说管理相关接口和类型
export type NovelStatus = 'queued' | 'processing' | 'completed' | 'extracting' | 'ready' | 'failed' | 'unknown';

export interface NovelInfo {
    collection_name: string;
    title: string;
    status: NovelStatus;
    created_at: string;
    chunks_count: number;
}

export interface UploadResponse {
    collection_name: string;
    title: string;
    status: string;
    message: string;
    estimated_time?: number;
}

export interface ProcessStatusResponse {
    collection_name: string;
    status: NovelStatus;
    progress: number;
    chunks_processed: number;
    total_chunks: number;
    error_message?: string;
}

export const uploadNovel = async (file: File, title?: string): Promise<UploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    if (title) formData.append('title', title);
    
    const { data } = await apiClient.post('/novels/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
};

export const getNovelsList = async (): Promise<{ novels: NovelInfo[] }> => {
    const { data } = await apiClient.get('/novels');
    return data;
};

export const getNovelStatus = async (collectionName: string): Promise<ProcessStatusResponse> => {
    const { data } = await apiClient.get(`/novels/${collectionName}/status`);
    return data;
};

export const deleteNovel = async (collectionName: string): Promise<void> => {
    await apiClient.delete(`/novels/${collectionName}`);
};

// 系统配置相关接口和类型
export interface PerformanceConfig {
    graphiti_llm_max_concurrency: number;
    graphiti_llm_min_interval: number;
    batch_size: number;
    batch_delay: number;
    poll_interval: number;
    status_poll_interval: number;
}

export interface BusinessConfig {
    max_file_size_mb: number;
    chunk_min_length: number;
    chunk_max_length: number;
    zep_timeout: number;
    neo4j_timeout: number;
}

export interface APIConfig {
    llm_api_key: string;
    llm_base_url: string;
    llm_model: string;
    model_director: string;  // 导演模型（剧情推演）
    model_parser: string;  // 解析模型（意图分析）
    model_zep_extractor: string;  // Zep 提取模型（知识图谱）
    model_graphiti: string;  // Graphiti 模型（实体提取）
    embedding_api_key: string;
    embedding_base_url: string;
    embedding_model: string;
}

export interface SystemConfig {
    performance: PerformanceConfig;
    business: BusinessConfig;
    api: APIConfig;
}

export const getConfig = async (): Promise<SystemConfig> => {
    const { data } = await apiClient.get('/config');
    return data;
};

export const updateConfig = async (config: SystemConfig): Promise<{ success: boolean; message: string }> => {
    const { data } = await apiClient.post('/config', config);
    return data;
};

export const reloadConfig = async (): Promise<{ success: boolean; message: string; config: SystemConfig }> => {
    const { data } = await apiClient.post('/config/reload');
    return data;
};

export const resetConfig = async (): Promise<{ success: boolean; message: string; config: SystemConfig }> => {
    const { data } = await apiClient.post('/config/reset');
    return data;
};

export const getConfigPresets = async (): Promise<Record<string, any>> => {
    const { data } = await apiClient.get('/config/presets');
    return data;
};

export const restartServices = async (): Promise<{ success: boolean; message: string; output?: string }> => {
    const { data } = await apiClient.post('/config/restart');
    return data;
};

export const getServicesStatus = async (): Promise<{ success: boolean; status: string }> => {
    const { data } = await apiClient.get('/config/services/status');
    return data;
};

// --- Session & Timeline API ---

export const createSession = async (novelId: string, userId: string, sessionName?: string): Promise<SessionInfo> => {
    const { data } = await apiClient.post('/sessions', {
        novel_id: novelId,
        user_id: userId,
        session_name: sessionName,
    });
    return data;
};

export const listSessions = async (novelId: string): Promise<SessionInfo[]> => {
    const { data } = await apiClient.get(`/sessions/${novelId}`);
    return data;
};

export const createBookmark = async (sessionId: string, name: string, description?: string): Promise<BookmarkInfo> => {
    const { data } = await apiClient.post(`/sessions/${sessionId}/bookmark`, {
        name,
        description,
    });
    return data;
};

export const branchSession = async (sessionId: string, bookmarkId: string, newSessionName?: string): Promise<SessionInfo> => {
    const { data } = await apiClient.post(`/sessions/${sessionId}/branch`, {
        bookmark_id: bookmarkId,
        new_session_name: newSessionName,
    });
    return data;
};

export const getChapters = async (novelId: string): Promise<ChapterInfo[]> => {
    const { data } = await apiClient.get(`/sessions/${novelId}/chapters`);
    return data;
};
