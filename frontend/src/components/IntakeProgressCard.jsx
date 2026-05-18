import React from 'react';

function clampPct(current, total) {
    const c = Number(current);
    const t = Number(total);
    if (!Number.isFinite(c) || !Number.isFinite(t) || t <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((c / t) * 100)));
}

export default function IntakeProgressCard({
    progressCurrent = 0,
    progressTotal = 0,
    progressLabel = '',
    blockingCount = 0,
    remainingCount = 0,
    isResumed = false,
    auditMode = false,
}) {
    if (!progressTotal || progressTotal <= 0) return null;
    const pct = clampPct(progressCurrent, progressTotal);
    const risk = Number(blockingCount || 0) > 0;

    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
                padding: '12px',
                borderRadius: '12px',
                border: risk ? '1px solid rgba(245,158,11,0.45)' : '1px solid rgba(125,211,252,0.4)',
                background: risk ? 'rgba(245,158,11,0.08)' : 'rgba(56,189,248,0.08)',
            }}
        >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                <div style={{ fontSize: '12px', fontWeight: 800, color: '#e2e8f0' }}>Estado de Intake</div>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                    {isResumed && (
                        <span style={{ fontSize: '10px', padding: '3px 8px', borderRadius: 999, background: 'rgba(99,102,241,0.2)', color: '#c7d2fe' }}>
                            Reanudado
                        </span>
                    )}
                    {auditMode && (
                        <span style={{ fontSize: '10px', padding: '3px 8px', borderRadius: 999, background: 'rgba(148,163,184,0.2)', color: '#cbd5e1' }}>
                            Modo auditoría
                        </span>
                    )}
                </div>
            </div>

            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{progressLabel || `Pregunta ${progressCurrent} de ${progressTotal}`}</div>

            <div
                aria-label="Progreso de intake"
                style={{
                    height: '8px',
                    borderRadius: '999px',
                    background: 'rgba(255,255,255,0.08)',
                    overflow: 'hidden',
                }}
            >
                <div
                    style={{
                        width: `${pct}%`,
                        height: '100%',
                        borderRadius: '999px',
                        background: risk
                            ? 'linear-gradient(90deg, rgba(245,158,11,0.9), rgba(251,191,36,0.9))'
                            : 'linear-gradient(90deg, rgba(34,197,94,0.9), rgba(56,189,248,0.9))',
                        transition: 'width 0.5s cubic-bezier(0.4, 0, 0.2, 1)',
                    }}
                />
            </div>

            <div style={{ display: 'flex', gap: '12px', fontSize: '11px' }}>
                <span style={{ color: '#fbbf24' }}>Bloqueantes: <strong>{Number(blockingCount || 0)}</strong></span>
                <span style={{ color: '#cbd5e1' }}>Pendientes: <strong>{Number(remainingCount || 0)}</strong></span>
            </div>

            <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.35 }}>
                {risk
                    ? 'Prioriza los bloqueantes para habilitar generación segura.'
                    : 'Avance estable. Continuemos con los pendientes de integridad.'}
            </div>
        </div>
    );
}
