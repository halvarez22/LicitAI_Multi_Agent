/**
 * Clasificación HRU de alertas económicas — paridad con economic_alert_classifier.py.
 */
import policy from '../contracts/economic_alert_policy.json';

const UX_REASON_BY_SUBTYPE = {
    ...(policy.ux_reason_by_subtype || {}),
    generic_economic: (
        policy.ux_reason_by_subtype?.generic_economic
        || 'El agente económico detectó una condición relevante para tu oferta. '
        + 'Contrasta con tu propuesta y expediente.'
    ),
};

function compilePatterns(key) {
    return (policy[key] || []).map((pat) => {
        try {
            return new RegExp(pat);
        } catch {
            return null;
        }
    }).filter(Boolean);
}

const PATTERNS = {
    convocante_budget: compilePatterns('convocante_budget_patterns'),
    guarantee_insurance: compilePatterns('guarantee_insurance_patterns'),
    offer_floor: compilePatterns('offer_floor_patterns'),
    presupuesto_disambiguation: compilePatterns('presupuesto_disambiguation_trigger_patterns'),
    ambiguous_presupuesto: compilePatterns('ambiguous_presupuesto_patterns'),
};

function matches(text, patterns) {
    return patterns.some((p) => p.test(text));
}

export function alertFingerprint(text) {
    let t = String(text || '').toLowerCase().trim().replace(/\s+/g, ' ');
    t = t.replace(/[^\w\s$.,]/g, '');
    t = t.replace(/(\d)[,\.](?=\d{3})/g, '$1');
    return t.slice(0, 240);
}

function classifyByPrefix(text) {
    const blob = String(text || '').trim();
    if (!blob) return null;
    const prefixes = policy.prefix_subtypes || {};
    for (const [prefix, subtype] of Object.entries(prefixes)) {
        if (blob.startsWith(prefix)) return subtype;
    }
    return null;
}

export function classifyEconomicAlertText(text) {
    const blob = String(text || '').trim();
    if (!blob) return 'generic_economic';
    const byPrefix = classifyByPrefix(blob);
    if (byPrefix) return byPrefix;
    if (matches(blob, PATTERNS.convocante_budget)) return 'convocante_budget';
    if (matches(blob, PATTERNS.guarantee_insurance)) return 'guarantee_insurance';
    if (matches(blob, PATTERNS.offer_floor)) return 'offer_floor';
    if (matches(blob, PATTERNS.presupuesto_disambiguation)) return 'ambiguous_presupuesto';
    if (matches(blob, PATTERNS.ambiguous_presupuesto)) return 'ambiguous_presupuesto';
    return 'generic_economic';
}

function shouldIncludeInForensicRisks(subtype) {
    const excluded = new Set(policy.exclude_from_forensic_risks_subtypes || []);
    return !excluded.has(subtype);
}

export function riskSeverityForSubtype(subtype) {
    if (subtype === 'offer_floor') return 'blocking';
    if (subtype === 'guarantee_insurance' || subtype === 'ambiguous_presupuesto') return 'high';
    if (subtype === 'convocante_budget' || subtype === 'bases_coherence_hint' || subtype === 'session_canonical_hint') {
        return 'medium';
    }
    return 'high';
}

export function sanitizeEconomicCausal(h) {
    const cat = String(h?.category || '').toLowerCase();
    if (!['economic', 'economic_gap_context', 'economic_context'].includes(cat)) return h;
    const norm = normalizeEconomicAlert(h?.texto ?? h);
    const out = {
        ...h,
        alert_subtype: norm.alert_subtype,
        risk_reason_ux: norm.risk_reason_ux,
    };
    if (!norm.include_in_forensic_risks) {
        out.isRisk = false;
        out.category = 'economic_context';
        if (String(out.tipo || '').startsWith('💰')) out.tipo = '📋 CONTEXTO ECONÓMICO';
    }
    return out;
}

export function sanitizeEconomicCausales(causales) {
    return (causales || []).map((h) => sanitizeEconomicCausal(h));
}

export function normalizeEconomicAlert(raw, index = 0) {
    let text;
    let page;
    let snippet;
    let alertId;
    if (raw && typeof raw === 'object') {
        text = raw.descripcion || raw.texto || raw.message || raw.alerta || '';
        page = raw.page;
        snippet = raw.snippet;
        alertId = raw.id;
    } else {
        text = String(raw || '').trim();
    }
    const subtype = classifyEconomicAlertText(text);
    const fp = alertFingerprint(text);
    return {
        texto: text,
        alert_subtype: subtype,
        alert_fingerprint: fp,
        risk_reason_ux: UX_REASON_BY_SUBTYPE[subtype] || UX_REASON_BY_SUBTYPE.generic_economic,
        include_in_forensic_risks: shouldIncludeInForensicRisks(subtype),
        suggested_severity: riskSeverityForSubtype(subtype),
        page,
        snippet,
        id: alertId || `econ-${fp.slice(0, 48) || index}`,
    };
}

function dedupeNormalized(items) {
    const seen = new Set();
    const out = [];
    items.forEach((item) => {
        const fp = item.alert_fingerprint || alertFingerprint(item.texto);
        if (!fp || seen.has(fp)) return;
        seen.add(fp);
        out.push(item);
    });
    return out;
}

/** Devuelve causales (forenses + contexto) desde alertas crudas. */
export function mapEconomicAlertsToCausales(rawList) {
    const normalized = (rawList || [])
        .filter(Boolean)
        .map((a, i) => normalizeEconomicAlert(a, i));
    return dedupeNormalized(normalized).map((norm) => {
        const forensic = norm.include_in_forensic_risks;
        return {
            tipo: forensic ? '💰 ALERTA ECONÓMICA' : '📋 CONTEXTO ECONÓMICO',
            texto: norm.texto,
            isRisk: forensic,
            category: forensic ? 'economic' : 'economic_context',
            id: norm.id,
            page: norm.page,
            snippet: norm.snippet,
            alert_subtype: norm.alert_subtype,
            risk_reason_ux: norm.risk_reason_ux,
            agent_id: 'economic_001',
            zona_origen: null,
            categoria_llm: null,
        };
    });
}

/** Alias: solo ítems que van al panel de riesgos forenses. */
export function mapForensicEconomicAlerts(rawList) {
    return mapEconomicAlertsToCausales(rawList).filter((x) => x.isRisk);
}
