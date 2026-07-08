/**
 * Etiquetas UI universales para modos de generación desacoplados (F3 / HRU).
 * Alineado con backend/app/contracts/generation_mode_policy.json — sin hardcode por licitación.
 */

/** @typedef {'full'|'technical'|'economic'} GenerationModeId */

/** @type {ReadonlyArray<{ id: GenerationModeId, label: string, short: string, hint: string }>} */
export const GENERATION_MODE_OPTIONS = Object.freeze([
    {
        id: 'full',
        label: 'Generar completo',
        short: 'Completo',
        hint: 'Técnica, formatos administrativos, económica y empaquetado',
    },
    {
        id: 'technical',
        label: 'Generar técnica',
        short: 'Técnica',
        hint: 'Propuesta técnica y formatos admin — sin cotización económica',
    },
    {
        id: 'economic',
        label: 'Generar económica',
        short: 'Económica',
        hint: 'Solo propuesta económica — requiere precios capturados',
    },
]);

/** @type {Record<string, string>} */
export const GENERATION_STAGE_LABELS_ES = Object.freeze({
    datagap: 'Verificación de datos',
    technical: 'Propuesta técnica',
    formats: 'Formatos administrativos',
    economic_writer: 'Propuesta económica',
    economic: 'Propuesta económica',
    packager: 'Empaquetado',
    document_packager: 'Empaquetado',
    delivery: 'Entrega',
});

/** @type {Record<string, string>} */
export const GENERATION_JOB_STATUS_LABELS_ES = Object.freeze({
    pending: 'Pendiente',
    running: 'En curso',
    done: 'Listo',
    blocked: 'En pausa',
    skipped: 'Omitida (modo parcial)',
    error: 'Error',
    resumed: 'Reanudada',
});

/**
 * @param {string} stage
 * @returns {string}
 */
export function generationStageLabelEs(stage) {
    return GENERATION_STAGE_LABELS_ES[stage] || String(stage || '').replace(/_/g, ' ');
}

/**
 * @param {string} status
 * @returns {string}
 */
export function generationJobStatusLabelEs(status) {
    const key = String(status || 'pending').toLowerCase();
    return GENERATION_JOB_STATUS_LABELS_ES[key] || key;
}

/**
 * @param {Record<string, unknown>|null|undefined} generationState
 * @returns {string}
 */
export function formatGenerationStateJobsSummaryHuman(generationState) {
    const jobs = generationState?.jobs;
    if (!Array.isArray(jobs) || jobs.length === 0) return '';
    const mode = generationState?.generation_mode
        ? `\nModo: **${generationModeLabelEs(generationState.generation_mode)}**`
        : '';
    const lines = jobs.map((j) => {
        if (!j || typeof j !== 'object') return null;
        const id = generationStageLabelEs(String(j.id || ''));
        const st = generationJobStatusLabelEs(String(j.status || 'pending'));
        return `• ${id}: ${st}`;
    }).filter(Boolean);
    return lines.length ? `${mode}\n\nEstado de la cola:\n${lines.join('\n')}` : '';
}

/**
 * @param {string} modeId
 * @returns {string}
 */
export function generationModeLabelEs(modeId) {
    const found = GENERATION_MODE_OPTIONS.find((m) => m.id === modeId);
    return found?.label || String(modeId || 'completo');
}

/**
 * @param {string} status
 * @returns {{ bg: string, color: string, border: string }}
 */
export function generationJobStatusStyle(status) {
    const st = String(status || 'pending').toLowerCase();
    if (st === 'done') {
        return { bg: 'rgba(34,197,94,0.12)', color: '#4ade80', border: 'rgba(34,197,94,0.35)' };
    }
    if (st === 'running') {
        return { bg: 'rgba(99,102,241,0.2)', color: '#a5b4fc', border: 'rgba(99,102,241,0.45)' };
    }
    if (st === 'blocked') {
        return { bg: 'rgba(251,191,36,0.12)', color: '#fbbf24', border: 'rgba(251,191,36,0.35)' };
    }
    if (st === 'skipped') {
        return { bg: 'rgba(148,163,184,0.1)', color: '#94a3b8', border: 'rgba(148,163,184,0.25)' };
    }
    if (st === 'error') {
        return { bg: 'rgba(248,113,113,0.12)', color: '#f87171', border: 'rgba(248,113,113,0.35)' };
    }
    return { bg: 'rgba(255,255,255,0.05)', color: 'rgba(226,232,240,0.65)', border: 'rgba(255,255,255,0.08)' };
}
