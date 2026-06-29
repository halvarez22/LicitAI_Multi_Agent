/**
 * Curación HRU del dictamen — paridad con dictamen_curation_service.py.
 * Política: frontend/src/contracts/dictamen_curation_policy.json
 * (espejo de backend/app/contracts/dictamen_curation_policy.json)
 */
import policy from '../contracts/dictamen_curation_policy.json';
import { ZONA_TAB_ORDER } from './auditSummary.js';

function buildCompliancePorZona(complianceHallazgos) {
    const out = {};
    for (const z of ZONA_TAB_ORDER) out[z] = [];
    out._OTRAS_ZONAS = [];
    for (const h of complianceHallazgos || []) {
        const k = h.zona_origen;
        if (ZONA_TAB_ORDER.includes(k)) out[k].push(h);
        else out._OTRAS_ZONAS.push(h);
    }
    return out;
}

const ACTIONABLE_TIPOS = new Set(
    (policy.actionable_tipo_accion || []).map((v) => String(v).toLowerCase())
);
const ACTIONABLE_CATS = new Set(
    (policy.actionable_non_compliance_categories || []).map((v) => String(v).toLowerCase())
);

function compilePatterns(key) {
    return (policy[key] || [])
        .map((p) => {
            try {
                return new RegExp(p);
            } catch {
                return null;
            }
        })
        .filter(Boolean);
}

const LICITANTE_RX = compilePatterns('licitante_subject_patterns');
const CONVOCANTE_RX = compilePatterns('convocante_subject_patterns');
const MIXED_OVERRIDE_RX = compilePatterns('mixed_obligation_licitante_override_patterns');

function matchesAny(blob, patterns) {
    const text = String(blob || '');
    return patterns.some((rx) => rx.test(text));
}

function hallazgoBlob(h) {
    const parts = [];
    const texto = h?.texto;
    if (texto && typeof texto === 'object') {
        ['descripcion', 'nombre', 'requisito', 'snippet', 'texto_crudo'].forEach((k) => {
            if (texto[k]) parts.push(String(texto[k]));
        });
    } else if (texto) {
        parts.push(String(texto));
    }
    if (h?.snippet) parts.push(String(h.snippet));
    return parts.join(' ').trim();
}

function itemTipoAccion(h) {
    const t = h?.texto;
    if (t && typeof t === 'object' && t.tipo_accion) return String(t.tipo_accion).toLowerCase();
    if (h?.tipo_accion) return String(h.tipo_accion).toLowerCase();
    return '';
}

function itemAudienceField(h) {
    const t = h?.texto;
    if (t && typeof t === 'object' && t.audience) return String(t.audience).toLowerCase();
    if (h?.audience) return String(h.audience).toLowerCase();
    return '';
}

function convocanteTokens(sessionConvocante) {
    if (!sessionConvocante || typeof sessionConvocante !== 'object') return [];
    const tokens = [];
    ['convocante', 'autoridad_convocante', 'dependencia', 'entidad', 'comite', 'destinatario'].forEach(
        (key) => {
            const raw = String(sessionConvocante[key] || '').trim();
            if (!raw) return;
            raw.split(/[\n,;—\-]+/).forEach((chunk) => {
                const c = chunk.trim();
                if (c.length >= 8) tokens.push(c.toLowerCase());
            });
        }
    );
    return [...new Set(tokens)];
}

function matchesSessionConvocante(blob, sessionConvocante) {
    const text = blob.toLowerCase();
    if (!text) return false;
    const tokens = convocanteTokens(sessionConvocante);
    if (tokens.length) {
        const hits = tokens.filter((t) => text.includes(t)).length;
        if (hits >= 1 && !matchesAny(blob, MIXED_OVERRIDE_RX)) {
            if (hits >= 2 || tokens.some((t) => t.length > 20 && text.includes(t))) return true;
        }
    }
    if (matchesAny(blob, CONVOCANTE_RX)) {
        if (matchesAny(blob, MIXED_OVERRIDE_RX)) return false;
        if (matchesAny(blob, LICITANTE_RX)) return false;
        return true;
    }
    return false;
}

export function classifyItemAudience(h, sessionConvocante) {
    const aud = itemAudienceField(h);
    if (aud === 'licitante' || aud === 'convocante' || aud === 'neutral') return aud;
    const blob = hallazgoBlob(h);
    if (matchesAny(blob, LICITANTE_RX)) return 'licitante';
    if (matchesSessionConvocante(blob, sessionConvocante)) return 'convocante';
    if (matchesAny(blob, CONVOCANTE_RX)) return 'convocante';
    return 'neutral';
}

export function resolveCurationReason(h, sessionConvocante) {
    const cat = String(h?.category || '').toLowerCase();
    if (h?.isRisk) return null;
    if (ACTIONABLE_CATS.has(cat)) return null;
    if (cat !== 'compliance') return 'neutral_context';

    const blob = hallazgoBlob(h);
    const tipo = itemTipoAccion(h);
    const audience = classifyItemAudience(h, sessionConvocante);

    if (tipo === 'informativo') return 'informativo';
    if (audience === 'convocante') return 'convocante_narrative';
    if (ACTIONABLE_TIPOS.has(tipo)) return null;
    if (audience === 'licitante') return null;
    return 'not_actionable_tipo';
}

function buildUxGuia(extractionHealth, forensicHealth) {
    const extSt = String(extractionHealth?.status || '').toLowerCase();
    const foreSt = String(forensicHealth?.status || '').toLowerCase();
    if (extSt === 'failed') {
        return 'No se pudo leer o indexar correctamente el PDF de bases. Sube de nuevo el archivo o reprocesa el documento.';
    }
    if ((extSt === 'ok' || extSt === 'degraded') && (foreSt === 'partial' || foreSt === 'failed' || foreSt === 'fail')) {
        return (
            'Las bases se leyeron e indexaron correctamente (materia prima lista). ' +
            'La auditoría automática de requisitos terminó con incidencias. ' +
            'Usa la lista de obligaciones como checklist principal; revisa manualmente las zonas marcadas o vuelve a analizar si hubo bloques vacíos del motor de IA.'
        );
    }
    if (extSt === 'ok' && (foreSt === 'ok' || foreSt === 'success' || !foreSt)) {
        return 'Las bases se leyeron correctamente. Revisa las obligaciones detectadas antes de generar la propuesta.';
    }
    return `Lectura de bases: ${extSt || '?'}. Auditoría forense: ${foreSt || '?'}.`;
}

export function buildForensicAuditHealth(compliance) {
    const compStatus = String(compliance?.status || 'success').toLowerCase();
    const compData = compliance?.data || {};
    let zones = compData?.audit_summary?.zones || compliance?.metrics?.zones || [];
    if (!Array.isArray(zones)) zones = [];
    const zonesFailed = zones.filter((z) => String(z.status).toLowerCase() === 'fail').map((z) => z.zone);
    const zonesPartial = zones.filter((z) => String(z.status).toLowerCase() === 'partial').map((z) => z.zone);
    let emptyBlocks = 0;
    zones.forEach((z) => {
        emptyBlocks += Number(z?.metrics?.blocks_empty_response_count || 0);
    });
    let status = 'ok';
    if (compStatus === 'fail' || compStatus === 'failed' || compStatus === 'error') status = 'failed';
    else if (compStatus === 'partial' || zonesFailed.length || zonesPartial.length) status = 'partial';
    return {
        status,
        compliance_status_raw: compStatus,
        zones_failed: zonesFailed,
        zones_partial: zonesPartial,
        empty_llm_blocks_total: emptyBlocks,
        global_match_pct: compData?.audit_summary?.global_match_pct,
    };
}

export function applyDictamenCurationToBase(base, sessionConvocante = {}, compliance = null) {
    if (!base || typeof base !== 'object') return base;
    const raw = [...(base.causales || [])];
    const actionable = [];
    const archival = [];
    const byReason = {};

    raw.forEach((h) => {
        const reason = resolveCurationReason(h, sessionConvocante);
        const enriched = { ...h, audience: classifyItemAudience(h, sessionConvocante) };
        if (reason === null) actionable.push(enriched);
        else {
            archival.push({ ...enriched, curation_reason: reason });
            byReason[reason] = (byReason[reason] || 0) + 1;
        }
    });

    const compActionable = actionable.filter((h) => h.category === 'compliance');
    const compliancePorZona = buildCompliancePorZona(compActionable);
    const forensic = base.forensicAuditHealth || buildForensicAuditHealth(compliance || {});
    const extraction = base.extractionHealth || {};
    const extSt = String(extraction?.status || '').toLowerCase();
    const foreSt = String(forensic?.status || '').toLowerCase();

    let status = base.status;
    let statusColor = base.statusColor;
    let uxKind = base.uxKind || 'normal';
    if (extSt === 'ok' || extSt === 'degraded') {
        if (foreSt === 'partial' || foreSt === 'failed' || foreSt === 'fail') {
            status = '⚠️ AUDITORÍA CON INCIDENCIAS';
            statusColor = '#f39c12';
            uxKind = 'forensic_partial_extraction_ok';
        }
    } else if (extSt === 'failed') {
        status = '❌ LECTURA DE BASES INCOMPLETA';
        statusColor = '#e74c3c';
        uxKind = 'extraction_failed';
    }

    return {
        ...base,
        causalesRaw: raw,
        causalesArchival: archival,
        causales: actionable,
        obligacionesDetectadas: actionable.length,
        archivalCount: archival.length,
        totalRequisitosLegacy: raw.length,
        totalRequisitos: actionable.length,
        compliancePorZona,
        causalesPorZona: compliancePorZona,
        complianceHallazgosCount: compActionable.length,
        forensicAuditHealth: forensic,
        uxGuiaUsuario: buildUxGuia(extraction, forensic),
        status,
        statusColor,
        uxKind,
        dictamen_schema_version: 3,
        dictamen_curated_v1: {
            schema_version: 'dictamen_curated_v1',
            filter_pipeline_version: policy.policy_version,
            stats: {
                actionable_count: actionable.length,
                archival_count: archival.length,
                source_total: raw.length,
                by_curation_reason: byReason,
            },
            actionable_items: actionable,
            archival_items: archival,
        },
    };
}
