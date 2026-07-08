import React from 'react';

const STATUS_STYLE = {
    done: { color: '#86efac', border: 'rgba(34,197,94,0.35)', bg: 'rgba(34,197,94,0.08)' },
    current: { color: '#a5b4fc', border: 'rgba(99,102,241,0.55)', bg: 'rgba(99,102,241,0.15)' },
    future: { color: '#94a3b8', border: 'rgba(148,163,184,0.25)', bg: 'rgba(255,255,255,0.03)' },
};

/**
 * Barra de pasos P0 — expediente guiado (HRU, copy desde API).
 */
export default function ExpedienteGuidedStepBar({ guided, compact = false }) {
    if (!guided?.enabled || !Array.isArray(guided.steps) || guided.steps.length === 0) {
        return null;
    }
    const current = guided.steps.find((s) => s.status === 'current');
    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'column',
                gap: compact ? '6px' : '8px',
                marginBottom: compact ? '8px' : '12px',
                padding: compact ? '8px 10px' : '10px 12px',
                borderRadius: '12px',
                border: '1px solid rgba(99,102,241,0.25)',
                background: 'rgba(15,23,42,0.55)',
            }}
        >
            {!compact && current ? (
                <p style={{ margin: 0, fontSize: '10px', color: '#cbd5e1', lineHeight: 1.45 }}>
                    <strong style={{ color: '#a5b4fc' }}>Paso actual:</strong> {current.label}
                    {current.hint ? ` — ${current.hint}` : ''}
                </p>
            ) : null}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {guided.steps.map((step) => {
                    const st = STATUS_STYLE[step.status] || STATUS_STYLE.future;
                    return (
                        <span
                            key={step.id}
                            title={step.hint || step.label}
                            style={{
                                fontSize: compact ? '9px' : '10px',
                                fontWeight: step.status === 'current' ? 800 : 600,
                                padding: '4px 8px',
                                borderRadius: '999px',
                                border: `1px solid ${st.border}`,
                                background: st.bg,
                                color: st.color,
                            }}
                        >
                            {step.label}
                        </span>
                    );
                })}
            </div>
            {guided.capture_summary ? (
                <p style={{ margin: 0, fontSize: '10px', color: '#94a3b8', lineHeight: 1.45 }}>
                    {guided.capture_summary.replace(/\*\*/g, '')}
                </p>
            ) : null}
        </div>
    );
}
