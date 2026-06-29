import React from 'react';

const MODE_STYLE = {
    index_verified: { bg: 'rgba(46,204,113,0.15)', color: '#2ecc71', label: 'Cita verificada en índice' },
    inference_only: { bg: 'rgba(243,156,18,0.12)', color: '#f39c12', label: 'Inferencia económica (sin ancla)' },
    index_error: { bg: 'rgba(231,76,60,0.12)', color: '#e74c3c', label: 'Error consultando índice' },
};

/**
 * Badge HRU de procedencia de evidencia forense (panel + chat).
 */
export default function ForensicEvidenceBadge({ evidence }) {
    const ev = evidence?.evidence_v1 || evidence || {};
    const mode = ev.evidence_mode || 'inference_only';
    const cfg = MODE_STYLE[mode] || MODE_STYLE.inference_only;
    const page = ev.page ?? evidence?.page;

    return (
        <span
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '9px',
                fontWeight: 800,
                padding: '3px 8px',
                borderRadius: '6px',
                background: cfg.bg,
                color: cfg.color,
                textTransform: 'uppercase',
                letterSpacing: '0.03em',
            }}
            title={ev.provenance_ui?.source || ev.provenance || ''}
        >
            {cfg.label}
            {page != null && mode === 'index_verified' && (
                <span style={{ opacity: 0.9 }}>· pág. {page}</span>
            )}
        </span>
    );
}
