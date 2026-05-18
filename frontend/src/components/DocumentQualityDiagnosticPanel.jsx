import React from 'react';

function fmtPct(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 'N/D';
    return `${(n * 100).toFixed(1)}%`;
}

function fmtNum(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 'N/D';
    return String(n);
}

function recommendationByReason(reason) {
    const r = String(reason || '').toLowerCase();
    if (r.includes('unknown_ratio')) {
        return 'Revisar clasificación del ComplianceAgent y confirmar tipo_accion en requisitos ambiguos.';
    }
    if (r.includes('evidence_match_ratio')) {
        return 'Agregar evidencia literal (snippet/página) o reindexar documentos con OCR mejorado.';
    }
    if (r.includes('min_items')) {
        return 'Validar que la convocatoria y anexos estén completos y repetir análisis.';
    }
    return 'Reejecutar análisis y validar que las bases cargadas contengan anexos y tablas completas.';
}

export default function DocumentQualityDiagnosticPanel({ snapshot, blocked, onRevalidate, busy }) {
    const metrics = snapshot?.metrics || {};
    const reason = snapshot?.reason || '';
    const stateLabel = blocked ? 'Bloqueado por gate documental' : 'Sin bloqueo documental activo';
    const badgeBg = blocked ? 'rgba(239,68,68,0.2)' : 'rgba(16,185,129,0.2)';
    const badgeColor = blocked ? '#fecaca' : '#bbf7d0';

    return (
        <div style={{ border: '1px solid rgba(255,255,255,0.1)', borderRadius: 12, padding: 14, background: 'rgba(0,0,0,0.2)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
                <strong style={{ fontSize: 13, color: '#e2e8f0' }}>Diagnóstico de calidad documental</strong>
                <span style={{ fontSize: 10, padding: '4px 8px', borderRadius: 999, background: badgeBg, color: badgeColor }}>
                    {stateLabel}
                </span>
            </div>

            <p style={{ marginTop: 10, marginBottom: 10, fontSize: 12, color: 'rgba(226,232,240,0.8)' }}>
                Motivo: <code>{reason || 'Sin motivo disponible'}</code>
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(120px, 1fr))', gap: 8 }}>
                <div style={{ fontSize: 12, color: 'rgba(226,232,240,0.85)' }}>unknown_ratio: <strong>{fmtPct(metrics.unknown_ratio)}</strong></div>
                <div style={{ fontSize: 12, color: 'rgba(226,232,240,0.85)' }}>evidence_match_ratio: <strong>{fmtPct(metrics.evidence_match_ratio)}</strong></div>
                <div style={{ fontSize: 12, color: 'rgba(226,232,240,0.85)' }}>generar_count: <strong>{fmtNum(metrics.generar_count)}</strong></div>
                <div style={{ fontSize: 12, color: 'rgba(226,232,240,0.85)' }}>total_items: <strong>{fmtNum(metrics.total_items)}</strong></div>
            </div>

            <div style={{ marginTop: 10, fontSize: 11, color: 'rgba(148,163,184,0.95)', lineHeight: 1.5 }}>
                Umbrales: max_unknown_ratio=<code>{fmtPct(metrics.max_unknown_ratio)}</code> · min_evidence_match_ratio=<code>{fmtPct(metrics.min_evidence_match_ratio)}</code> · min_items=<code>{fmtNum(metrics.min_items)}</code>
            </div>

            <p style={{ marginTop: 10, marginBottom: 0, fontSize: 12, color: 'rgba(226,232,240,0.8)' }}>
                Recomendación: {recommendationByReason(reason)}
            </p>

            <div style={{ marginTop: 12 }}>
                <button
                    type="button"
                    onClick={onRevalidate}
                    disabled={busy}
                    style={{
                        border: '1px solid rgba(56,189,248,0.5)',
                        borderRadius: 10,
                        background: busy ? 'rgba(56,189,248,0.12)' : 'rgba(56,189,248,0.2)',
                        color: '#e2e8f0',
                        fontSize: 12,
                        fontWeight: 700,
                        padding: '8px 12px',
                        cursor: busy ? 'not-allowed' : 'pointer',
                    }}
                >
                    {busy ? 'Revalidando…' : 'Revalidar análisis'}
                </button>
            </div>
        </div>
    );
}
