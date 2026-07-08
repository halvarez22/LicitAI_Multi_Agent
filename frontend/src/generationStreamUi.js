/**
 * F6/F7 — UI de streams de generación concurrentes (HRU / ADR-001).
 * Alineado con backend/app/contracts/generation_concurrency_policy.json.
 * Sin hardcode por licitación.
 */

import { generationModeLabelEs, generationStageLabelEs } from './generationModeUi.js';

/** @typedef {'technical'|'economic'|'full'} GenerationStreamId */
/** @typedef {'full'|'technical'|'economic'} GenerationModeId */

/** Jobs por stream (espejo policy F6). */
export const GENERATION_STREAM_JOB_IDS = Object.freeze({
    technical: Object.freeze(['datagap', 'technical', 'formats']),
    economic: Object.freeze(['economic_writer']),
    shared: Object.freeze(['packager', 'delivery']),
});

/** @type {ReadonlyArray<{ id: GenerationStreamId, label: string }>} */
export const GENERATION_STREAM_PANELS = Object.freeze([
    { id: 'technical', label: 'Cola técnica' },
    { id: 'economic', label: 'Cola económica' },
]);

const EMPTY_PROGRESS = Object.freeze({ percent: 0, message: '', held: false });

/**
 * @returns {Record<GenerationStreamId, { active: boolean, progress: { percent: number, message: string, held: boolean } }>}
 */
export function createInitialGenerationStreamRuns() {
    return {
        technical: { active: false, progress: { ...EMPTY_PROGRESS } },
        economic: { active: false, progress: { ...EMPTY_PROGRESS } },
        full: { active: false, progress: { ...EMPTY_PROGRESS } },
    };
}

/**
 * @param {GenerationModeId|string} modeId
 * @returns {GenerationStreamId}
 */
export function generationStreamIdForMode(modeId) {
    const m = String(modeId || 'full').toLowerCase();
    if (m === 'technical') return 'technical';
    if (m === 'economic') return 'economic';
    return 'full';
}

/**
 * @param {GenerationModeId|string} modeId
 * @returns {GenerationStreamId|null}
 */
export function generationStreamParamForMode(modeId) {
    const stream = generationStreamIdForMode(modeId);
    return stream === 'full' ? null : stream;
}

/**
 * @param {Record<string, { active?: boolean }>|null|undefined} runs
 * @param {GenerationStreamId} streamId
 */
export function isGenerationStreamActive(runs, streamId) {
    return Boolean(runs?.[streamId]?.active);
}

/**
 * @param {Record<string, { active?: boolean }>|null|undefined} runs
 */
export function isAnyGenerationStreamActive(runs) {
    if (!runs) return false;
    return Object.values(runs).some((r) => r?.active);
}

/**
 * @param {Record<string, { active?: boolean }>|null|undefined} runs
 * @param {GenerationModeId|string} modeId
 */
export function isStreamActiveForMode(runs, modeId) {
    return isGenerationStreamActive(runs, generationStreamIdForMode(modeId));
}

/**
 * @param {{
 *   runs: Record<string, { active?: boolean }>|null|undefined,
 *   modeId: GenerationModeId|string,
 *   isAnalyzing?: boolean,
 *   hasCompany?: boolean,
 * }} ctx
 */
export function isGenerationModeButtonDisabled(ctx) {
    const { runs, modeId, isAnalyzing, hasCompany } = ctx;
    if (isAnalyzing || !hasCompany) return true;
    const stream = generationStreamIdForMode(modeId);
    if (stream === 'full') {
        return isAnyGenerationStreamActive(runs);
    }
    if (isGenerationStreamActive(runs, stream)) return true;
    if (isGenerationStreamActive(runs, 'full')) return true;
    return false;
}

/**
 * @param {Record<string, { active?: boolean }>|null|undefined} runs
 * @returns {string|null}
 */
export function dualStreamParallelBannerEs(runs) {
    const tech = isGenerationStreamActive(runs, 'technical');
    const eco = isGenerationStreamActive(runs, 'economic');
    if (tech && eco) {
        return 'Técnica y económica en paralelo — cada equipo puede seguir en su alcance.';
    }
    if (tech && !eco) {
        return 'Generación técnica en curso — puedes cotizar y generar la económica en paralelo.';
    }
    if (eco && !tech) {
        return 'Generación económica en curso — puedes avanzar la técnica en paralelo.';
    }
    return null;
}

/**
 * @param {Record<string, { active?: boolean, progress?: { percent: number, message: string, held: boolean } }>} runs
 */
export function primaryGenerationProgressForDisplay(runs) {
    const order = ['full', 'technical', 'economic'];
    let best = { ...EMPTY_PROGRESS };
    let anyActive = false;
    let anyHeld = false;
    for (const id of order) {
        const run = runs?.[id];
        if (!run) continue;
        if (run.active) anyActive = true;
        if (run.progress?.held) anyHeld = true;
        if (run.active || (run.progress?.percent || 0) > 0) {
            const p = run.progress || EMPTY_PROGRESS;
            if (p.percent >= best.percent) {
                best = { percent: p.percent, message: p.message || '', held: Boolean(p.held) };
            }
        }
    }
    if (!anyActive && best.percent === 0) {
        return { ...EMPTY_PROGRESS };
    }
    return { ...best, held: anyHeld || best.held };
}

/**
 * @param {Array<{ id?: string }>|null|undefined} jobs
 * @param {GenerationStreamId} streamId
 */
export function filterJobsForStream(jobs, streamId) {
    const allowed = GENERATION_STREAM_JOB_IDS[streamId];
    if (!Array.isArray(jobs) || !allowed) return [];
    const set = new Set(allowed);
    return jobs.filter((j) => j && set.has(String(j.id || '')));
}

/**
 * @param {Record<string, unknown>|null|undefined} generationState
 * @param {GenerationStreamId} streamId
 */
export function jobsForStreamPanel(generationState, streamId) {
    const streams = generationState?.streams;
    if (streams && typeof streams === 'object') {
        const stream = streams[streamId];
        const raw = stream?.jobs;
        if (Array.isArray(raw) && raw.length > 0) {
            return raw;
        }
    }
    return filterJobsForStream(
        Array.isArray(generationState?.jobs) ? generationState.jobs : [],
        streamId
    );
}

/**
 * @param {Record<string, unknown>|null|undefined} generationState
 */
export function shouldShowDualStreamPanels(generationState) {
    if (generationState?.streams && typeof generationState.streams === 'object') {
        return true;
    }
    const active = generationState?.active_streams;
    return Array.isArray(active) && active.length > 0;
}

/**
 * @param {Record<string, unknown>|null|undefined} generationState
 * @param {GenerationStreamId} streamId
 */
export function streamPanelModeLabel(generationState, streamId) {
    const streams = generationState?.streams;
    if (streams && typeof streams === 'object') {
        const mode = streams[streamId]?.generation_mode;
        if (mode) return generationModeLabelEs(String(mode));
    }
    if (streamId === 'technical') return generationModeLabelEs('technical');
    if (streamId === 'economic') return generationModeLabelEs('economic');
    return null;
}

/**
 * Resumen humano de jobs por stream (chat).
 * @param {Record<string, unknown>|null|undefined} generationState
 */
export function formatDualStreamJobsSummaryHuman(generationState) {
    if (!shouldShowDualStreamPanels(generationState)) return '';
    const lines = [];
    for (const panel of GENERATION_STREAM_PANELS) {
        const jobs = jobsForStreamPanel(generationState, panel.id);
        if (!jobs.length) continue;
        const jobLines = jobs.map((j) => {
            const id = generationStageLabelEs(String(j.id || ''));
            const st = String(j.status || 'pending');
            return `  • ${id}: ${st}`;
        });
        lines.push(`**${panel.label}:**\n${jobLines.join('\n')}`);
    }
    return lines.length ? `\n\n${lines.join('\n\n')}` : '';
}
