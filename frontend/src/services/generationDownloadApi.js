import { api } from './api.js';

/**
 * Lista artefactos descargables por alcance HRU (F5.2).
 * @param {string} sessionId
 * @param {'technical'|'economic'|'full'} scope
 * @returns {Promise<Record<string, unknown>>}
 */
export const fetchScopeArtifacts = async (sessionId, scope = 'full') => {
    if (!sessionId) {
        return { ready: false, artifact_count: 0, artifacts: [] };
    }
    const response = await api.get('downloads/artifacts', {
        params: { session_id: sessionId, scope },
    });
    return response.data?.data || {};
};

/**
 * Descarga un archivo individual vía API canónica.
 * @param {string} sessionId
 * @param {string} relativePath
 * @param {string} filename
 */
export const downloadGeneratedFile = async (sessionId, relativePath, filename) => {
    const response = await api.get('downloads/file', {
        params: { session_id: sessionId, path: relativePath },
        responseType: 'blob',
    });
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename || 'documento');
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
};
