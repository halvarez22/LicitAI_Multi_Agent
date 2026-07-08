/**
 * Fallback UI P0 expediente guiado — espejo de expediente_guided_policy.json.
 * La verdad canónica llega por API /sessions/:id/expediente-guided.
 */

/** @typedef {'bases'|'cotizacion'|'validar_economica'|'plan_documentos'|'materializar'} GuidedStepId */

export const DEFAULT_PANEL_LABELS = Object.freeze({
    analyze_bases: 'Releer bases',
    analyze_bases_first: 'Analizar bases',
    generation_full: 'Crear expediente completo',
    generation_economic: 'Crear archivos económicos',
    generation_technical: 'Crear archivos técnicos',
    generation_full_short: 'Completo',
    generation_economic_short: 'Económica',
    generation_technical_short: 'Técnica',
});

export const DEFAULT_GENERATION_HINTS = Object.freeze({
    full: 'Técnica, formatos administrativos, económica y empaquetado',
    technical: 'Propuesta técnica y formatos admin — sin cotización económica',
    economic: 'Solo propuesta económica — requiere cotización validada en chat',
});

export const DEFAULT_OVERLAY_MESSAGES = Object.freeze({
    bases_analysis_title: 'Releyendo bases…',
    bases_analysis_subtitle: 'Extracción, índice vectorial y dictamen forense',
    document_generation_title: 'Creando archivos…',
    document_generation_subtitle: 'Generación de propuesta y formatos en disco',
    dismiss_hint: 'Seguir navegando (trabajo en segundo plano)',
});

/**
 * @param {Record<string, string>|null|undefined} apiLabels
 * @returns {typeof DEFAULT_PANEL_LABELS}
 */
export function mergePanelLabels(apiLabels) {
    if (!apiLabels || typeof apiLabels !== 'object') return DEFAULT_PANEL_LABELS;
    return { ...DEFAULT_PANEL_LABELS, ...apiLabels };
}

/**
 * @param {Record<string, string>|null|undefined} apiHints
 * @returns {typeof DEFAULT_GENERATION_HINTS}
 */
export function mergeGenerationHints(apiHints) {
    if (!apiHints || typeof apiHints !== 'object') return DEFAULT_GENERATION_HINTS;
    return { ...DEFAULT_GENERATION_HINTS, ...apiHints };
}

/**
 * @param {Record<string, string>|null|undefined} apiOverlays
 * @returns {typeof DEFAULT_OVERLAY_MESSAGES}
 */
export function mergeOverlayMessages(apiOverlays) {
    if (!apiOverlays || typeof apiOverlays !== 'object') return DEFAULT_OVERLAY_MESSAGES;
    return { ...DEFAULT_OVERLAY_MESSAGES, ...apiOverlays };
}

/**
 * @param {string} modeId
 * @param {Record<string, string>} labels
 * @returns {string}
 */
export function panelLabelForGenerationMode(modeId, labels = DEFAULT_PANEL_LABELS) {
    const m = String(modeId || 'full').toLowerCase();
    if (m === 'economic') return labels.generation_economic || DEFAULT_PANEL_LABELS.generation_economic;
    if (m === 'technical') return labels.generation_technical || DEFAULT_PANEL_LABELS.generation_technical;
    return labels.generation_full || DEFAULT_PANEL_LABELS.generation_full;
}

/**
 * @param {string} modeId
 * @param {Record<string, string>} labels
 * @returns {string}
 */
export function panelShortForGenerationMode(modeId, labels = DEFAULT_PANEL_LABELS) {
    const m = String(modeId || 'full').toLowerCase();
    if (m === 'economic') return labels.generation_economic_short || 'Económica';
    if (m === 'technical') return labels.generation_technical_short || 'Técnica';
    return labels.generation_full_short || 'Completo';
}
