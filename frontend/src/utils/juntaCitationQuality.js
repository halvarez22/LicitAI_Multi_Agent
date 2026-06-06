/**
 * Badge de calidad de cita para preguntas de junta (alineado con provenance_ui.citation_quality).
 */

export const CITATION_QUALITY = {
    CITA_COMPLETA: 'cita_completa',
    SOLO_DOCUMENTO: 'solo_documento',
    DATOS_INSUFICIENTES: 'datos_insuficientes',
};

export const CITATION_QUALITY_META = {
    [CITATION_QUALITY.CITA_COMPLETA]: {
        label: 'Cita completa',
        color: '#22c55e',
        title:
            'La pregunta cita ubicación en bases (cláusula, página o apartado) y contrasta criterios de forma explícita.',
    },
    [CITATION_QUALITY.SOLO_DOCUMENTO]: {
        label: 'Solo documento',
        color: '#f59e0b',
        title:
            'Hay referencia al PDF o anexo, pero el análisis no trae fragmento estructurado de bases con página y apartado.',
    },
    [CITATION_QUALITY.DATOS_INSUFICIENTES]: {
        label: 'Datos insuficientes',
        color: '#94a3b8',
        title:
            'Faltan citas estructuradas en el análisis; conviene re-analizar bases o pulir la pregunta antes de la junta.',
    },
};

const PATTERNS_CITA_COMPLETA = new Set([
    'dual_bases_citation',
    'dual_bases_only',
    'bases_vs_anexo',
    'bases_vs_documento',
    'explicit_conflict',
]);

const PATTERNS_SOLO_DOCUMENTO = new Set([
    'documento_sin_cita_bases',
    'experience_years_conflict',
    'unresolved_se_adjunta',
    'format_placeholders',
    'certification_cluster',
]);

/**
 * @param {object} item - ítem del bundle junta_aclaraciones_questions
 * @returns {keyof typeof CITATION_QUALITY_META}
 */
export function resolveCitationQuality(item) {
    const prov = item?.provenance_ui && typeof item.provenance_ui === 'object' ? item.provenance_ui : {};
    const fromBackend = prov.citation_quality;
    if (fromBackend && CITATION_QUALITY_META[fromBackend]) {
        return fromBackend;
    }

    const pattern = prov.pattern;
    if (PATTERNS_CITA_COMPLETA.has(pattern)) {
        return CITATION_QUALITY.CITA_COMPLETA;
    }
    if (PATTERNS_SOLO_DOCUMENTO.has(pattern) || prov.source === 'thematic_bases') {
        return CITATION_QUALITY.SOLO_DOCUMENTO;
    }

    const p = String(item?.pregunta || '').toLowerCase();
    if (/solicitamos aclaración respecto|podrían interpretarse|umbral general de las bases/i.test(p)) {
        return CITATION_QUALITY.DATOS_INSUFICIENTES;
    }

    const hasUbicacion = /cláusula|clausula|página|pagina|apartado/i.test(p);
    const hasDual = /más adelante|sin embargo/i.test(p);
    if (hasUbicacion && (hasDual || p.includes('establece que'))) {
        return CITATION_QUALITY.CITA_COMPLETA;
    }
    if (/documento «/i.test(p) && !hasUbicacion) {
        return CITATION_QUALITY.SOLO_DOCUMENTO;
    }

    return CITATION_QUALITY.DATOS_INSUFICIENTES;
}

export function getCitationQualityMeta(item) {
    const key = resolveCitationQuality(item);
    return { key, ...CITATION_QUALITY_META[key] };
}
