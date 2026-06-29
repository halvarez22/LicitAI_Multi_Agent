/**
 * Riesgos forenses — paridad con forensic_risk_service.py (fallback cliente).
 */

import { riskSeverityForSubtype, sanitizeEconomicCausales } from './economicAlertUtils.js';

const RISK_REASON_BY_CATEGORY = {
    risk: (
        'Las bases prevén esta condición como causa de desechamiento o incumplimiento grave. '
        + 'Si no la cubres documentalmente, puedes quedar fuera del procedimiento.'
    ),
    economic: (
        'El agente económico detectó una alerta sobre precios, coherencia de oferta o riesgo '
        + 'financiero en tu propuesta respecto a las bases.'
    ),
    economic_gap_context: (
        'Falta contexto en bases o expediente para cotizar con seguridad. '
        + 'Conviene resolverlo antes de ofertar.'
    ),
};

const RISK_GROUP_LABELS = {
    knockout_causal: 'Descalificación / desechamiento',
    economic_alert: 'Riesgo económico',
    economic_context: 'Contexto económico pendiente',
};

const GROUP_ORDER = ['knockout_causal', 'economic_alert', 'economic_context'];

function hallazgoText(h) {
    const t = h?.texto;
    if (typeof t === 'object' && t !== null) {
        return t.descripcion || t.nombre || t.requisito || JSON.stringify(t);
    }
    return t != null ? String(t) : '';
}

function classifyRiskKind(h) {
    const cat = String(h?.category || '').toLowerCase();
    if (cat === 'risk') return 'knockout_causal';
    if (cat === 'economic_gap_context') return 'economic_context';
    return 'economic_alert';
}

function classifyRiskSeverity(kind) {
    if (kind === 'knockout_causal') return 'blocking';
    if (kind === 'economic_alert') return 'high';
    return 'medium';
}

function stableRiskId(h, index) {
    if (h?.id) return String(h.id);
    if (h?.risk_id) return String(h.risk_id);
    return `forensic-risk-${index}`;
}

export function enrichRiskHallazgo(h, index = 0) {
    const kind = classifyRiskKind(h);
    const subtype = String(h?.alert_subtype || '').trim();
    const severity = subtype && h?.category === 'economic'
        ? riskSeverityForSubtype(subtype)
        : classifyRiskSeverity(kind);
    const cat = String(h?.category || '').toLowerCase();
    const reason = String(h?.risk_reason_ux || '').trim()
        || RISK_REASON_BY_CATEGORY[cat]
        || RISK_REASON_BY_CATEGORY.risk;
    return {
        ...h,
        risk_id: stableRiskId(h, index),
        risk_kind: kind,
        risk_severity: severity,
        alert_subtype: subtype || null,
        risk_group_label: RISK_GROUP_LABELS[kind] || 'Riesgo forense',
        risk_reason_ux: reason,
        provenance_ui: {
            agent_id: h?.agent_id,
            category: h?.category,
            alert_subtype: subtype || null,
            page: h?.page,
            snippet: h?.snippet,
            tipo: h?.tipo,
        },
        _literal: hallazgoText(h),
    };
}

export function buildForensicRisksFromCausales(causales) {
    const items = (causales || [])
        .filter((h) => h?.isRisk)
        .map((h, i) => enrichRiskHallazgo(h, i));
    return {
        schema_version: 'forensic_risks_v1',
        items,
        stats: {
            total: items.length,
            blocking: items.filter((x) => x.risk_severity === 'blocking').length,
            high: items.filter((x) => x.risk_severity === 'high').length,
            medium: items.filter((x) => x.risk_severity === 'medium').length,
        },
    };
}

export function mergeDecisionsIntoForensicRisks(forensicRisks, riskDecisions) {
    if (!forensicRisks?.items?.length) return forensicRisks;
    const raw = riskDecisions?.decisions;
    const map = raw && typeof raw === 'object' ? raw : {};
    const items = forensicRisks.items.map((item) => {
        const dec = map[item.risk_id];
        if (!dec) {
            return { ...item, decision_status: item.decision_status || 'pending' };
        }
        return {
            ...item,
            decision_status: dec.status || 'pending',
            user_note: dec.user_note,
            decided_at: dec.decided_at,
        };
    });
    return {
        ...forensicRisks,
        items,
        decision_stats: mergeDecisionStats(items),
    };
}

export function resolveForensicRisksBlock(auditResults) {
    if (!auditResults) return null;
    let block = null;
    if (auditResults.forensic_risks_v1?.items?.length) {
        block = auditResults.forensic_risks_v1;
    } else {
        const fromCausales = buildForensicRisksFromCausales(auditResults.causales);
        block = fromCausales.items.length ? fromCausales : null;
    }
    if (block && auditResults.risk_decisions_v1) {
        block = mergeDecisionsIntoForensicRisks(block, auditResults.risk_decisions_v1);
    }
    return block;
}

export function mergeDecisionStats(items) {
    const pending = items.filter((x) => (x.decision_status || 'pending') === 'pending').length;
    const accepted = items.filter((x) => x.decision_status === 'accepted').length;
    const rejected = items.filter((x) => x.decision_status === 'rejected').length;
    const blockingPending = items.filter(
        (x) => x.risk_severity === 'blocking' && (x.decision_status || 'pending') === 'pending',
    ).length;
    return { pending, accepted, rejected, blocking_pending: blockingPending };
}

export function groupRiskItems(items) {
    const groups = {};
    for (const kind of GROUP_ORDER) groups[kind] = [];
    for (const item of items || []) {
        const k = item.risk_kind || 'economic_alert';
        if (!groups[k]) groups[k] = [];
        groups[k].push(item);
    }
    return GROUP_ORDER.filter((k) => groups[k]?.length).map((k) => ({
        kind: k,
        label: RISK_GROUP_LABELS[k],
        items: groups[k],
    }));
}

export const SEVERITY_COLORS = {
    blocking: '#e74c3c',
    high: '#f39c12',
    medium: '#38bdf8',
};

export const DECISION_LABELS = {
    pending: 'Pendiente de decisión',
    accepted: 'Riesgo asumido',
    rejected: 'Rechazado — requiere acción',
};
