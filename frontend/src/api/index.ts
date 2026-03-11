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

export const chatInteract = async (sessionId: string, collectionName: string, message: string): Promise<ChatResponse> => {
    const { data } = await apiClient.post('/chat/interact', {
        session_id: sessionId,
        collection_name: collectionName,
        message,
    });
    return data;
};
