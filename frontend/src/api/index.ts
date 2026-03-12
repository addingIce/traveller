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

export const fetchKnowledgeGraph = async (collectionName: string) => {
    const { data } = await apiClient.get(`/graph/${collectionName}`);
    return data;
};

export const searchGraph = async (collectionName: string, query: string) => {
    const { data } = await apiClient.get(`/graph/${collectionName}/search`, { params: { query } });
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
export interface NovelInfo {
    collection_name: string;
    title: string;
    status: string;  // processing/completed/failed
    created_at: string;
    chunks_count: number;
}

export interface UploadResponse {
    collection_name: string;
    status: string;
    message: string;
    estimated_time?: number;
}

export interface ProcessStatusResponse {
    collection_name: string;
    status: string;
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
