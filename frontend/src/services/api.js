import axios from 'axios';
import { API_BASE } from '../apiBase.js';

const fullBase =
    API_BASE.startsWith('http')
        ? API_BASE
        : `${typeof window !== 'undefined' ? window.location.origin : ''}${API_BASE}`;

export const api = axios.create({
    baseURL: fullBase,
});

export const uploadDocument = async (file, sessionId, docType = 'bases') => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', sessionId);
    formData.append('document_type', docType);

    const response = await api.post('upload/document', formData, {
        headers: {
            'Content-Type': 'multipart/form-data'
        }
    });
    return response.data;
};

export const startOrchestrator = async (sessionId, companyData = {}, options = {}) => {
    const generationMode = options.generationMode ?? companyData?.generation_mode ?? 'full';
    const streamFromOptions = options.generationStream ?? companyData?.generation_stream ?? null;
    const streamParam =
        streamFromOptions
        || (generationMode === 'technical' ? 'technical' : generationMode === 'economic' ? 'economic' : null);
    const response = await api.post('agents/process', {
        session_id: sessionId,
        company_id: options.companyId ?? companyData?.id ?? null,
        resume_generation: options.resumeGeneration ?? true,
        generation_mode: generationMode,
        ...(streamParam ? { generation_stream: streamParam } : {}),
        company_data: companyData,
    });
    return response.data;
};

export const askChatbot = async (sessionId, query) => {
    const response = await api.post('chatbot/ask', {
        session_id: sessionId,
        query: query
    });
    return response.data;
};
