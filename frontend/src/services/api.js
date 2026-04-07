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

export const startOrchestrator = async (sessionId, companyData = {}) => {
    const response = await api.post('agents/process', {
        session_id: sessionId,
        company_data: companyData
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
