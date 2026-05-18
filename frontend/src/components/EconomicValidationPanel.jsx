import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';
import { AlertTriangle, CheckCircle2, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react';

function colorByState(st) {
    if (st === 'ok') return '#4ade80';
    if (st === 'blocking') return '#f87171';
    return '#fbbf24';
}

function labelByState(st) {
    if (st === 'ok') return 'OK';
    if (st === 'blocking') return 'BLOCKING';
    return 'WARN';
}

/**
 * Sprint 3 UI: estado de validaciones económicas determinísticas.
 */
export default function EconomicValidationPanel({ sessionId, syncKey, onAskAboutValidation }) {
    const [expanded, setExpanded] = useState(false);
    const [loading, setLoading] = useState(false);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState(null);
    const [validation, setValidation] = useState(null);

    const fetchValidations = useCallback(async () => {
        if (!sessionId) return;
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/economic-validations`
            );
            if (res.data?.success && res.data?.data?.validation_result) {
                setValidation(res.data.data.validation_result);
            } else {
                setValidation(null);
            }
        } catch (e) {
            setValidation(null);
            setError(e?.response?.data?.detail || e?.message || 'Error de red');
        } finally {
            setLoading(false);
        }
    }, [sessionId]);

    useEffect(() => {
        fetchValidations();
    }, [fetchValidations, syncKey]);

    const refreshValidations = async () => {
        if (!sessionId) return;
        setRefreshing(true);
        setError(null);
        try {
            const res = await axios.post(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/economic-validations/refresh`
            );
            if (res.data?.success && res.data?.data?.validation_result) {
                setValidation(res.data.data.validation_result);
            } else {
                setError(res.data?.message || 'No se pudieron recalcular validaciones.');
            }
        } catch (e) {
            setError(e?.response?.data?.detail || e?.message || 'Error refrescando validaciones');
        } finally {
            setRefreshing(false);
        }
    };

    const perfil = String(validation?.perfil_usado || '');
    const isGeneric = !!perfil && perfil === 'generic';
    const vals = Array.isArray(validation?.validations) ? validation.validations : [];
    const blockingIssues = Array.isArray(validation?.blocking_issues) ? validation.blocking_issues : [];
    const alerts = Array.isArray(validation?.alerts) ? validation.alerts : [];

    const stats = useMemo(() => {
        const out = { ok: 0, warn: 0, blocking: 0 };
        for (const v of vals) {
            const st = String(v?.estado || '');
            if (st === 'ok' || st === 'warn' || st === 'blocking') out[st] += 1;
        }
        return out;
    }, [vals]);

    const headerSummary = useMemo(() => {
        if (!validation && !error) return 'Sin datos · genera propuesta o pulsa refrescar';
        if (error) return 'Error al cargar · expande para detalle';
        return `OK ${stats.ok} · WARN ${stats.warn} · BLOCKING ${stats.blocking}`;
    }, [validation, error, stats]);

    const toggleExpanded = () => setExpanded((v) => !v);

    const onAccordionKeyDown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggleExpanded();
        }
    };

    const bodyId = 'economic-validation-panel-body';

    if (!sessionId) return null;

    return (
        <div
            className="glass-panel"
            style={{
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: '12px',
                padding: '12px',
                background: 'rgba(0,0,0,0.2)',
            }}
        >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px', marginBottom: expanded ? '10px' : 0 }}>
                <div
                    role="button"
                    tabIndex={0}
                    aria-expanded={expanded}
                    aria-controls={bodyId}
                    onClick={toggleExpanded}
                    onKeyDown={onAccordionKeyDown}
                    style={{
                        flex: 1,
                        minWidth: 0,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '8px',
                        borderRadius: '8px',
                        padding: '4px 6px',
                        margin: '-4px -6px',
                    }}
                >
                    {expanded ? (
                        <ChevronDown size={16} color="var(--primary)" style={{ flexShrink: 0, marginTop: '2px' }} />
                    ) : (
                        <ChevronRight size={16} color="var(--primary)" style={{ flexShrink: 0, marginTop: '2px' }} />
                    )}
                    <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                            <h3
                                style={{
                                    fontSize: '11px',
                                    fontWeight: 900,
                                    color: 'var(--text-muted)',
                                    textTransform: 'uppercase',
                                    letterSpacing: '1px',
                                    margin: 0,
                                }}
                            >
                                Validaciones económicas
                            </h3>
                            {!expanded && blockingIssues.length > 0 && (
                                <span
                                    style={{
                                        fontSize: '9px',
                                        fontWeight: 800,
                                        color: '#fecaca',
                                        background: 'rgba(248,113,113,0.2)',
                                        border: '1px solid rgba(248,113,113,0.45)',
                                        borderRadius: '999px',
                                        padding: '2px 8px',
                                    }}
                                >
                                    {blockingIssues.length} bloqueante{blockingIssues.length === 1 ? '' : 's'}
                                </span>
                            )}
                        </div>
                        <p style={{ margin: '4px 0 0 0', fontSize: '10px', color: 'rgba(226,232,240,0.72)', lineHeight: 1.35 }}>
                            {headerSummary}
                        </p>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={(e) => {
                        e.stopPropagation();
                        refreshValidations();
                    }}
                    disabled={refreshing}
                    title="Recalcular validaciones"
                    style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--primary)',
                        cursor: refreshing ? 'wait' : 'pointer',
                        padding: '4px',
                        flexShrink: 0,
                    }}
                >
                    <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
                </button>
            </div>

            {expanded && (
                <div id={bodyId}>
                    {(loading || refreshing) && (
                        <p style={{ margin: 0, fontSize: '10px', color: 'var(--text-muted)' }}>
                            {refreshing ? 'Recalculando...' : 'Cargando...'}
                        </p>
                    )}
                    {!loading && !refreshing && error && (
                        <p style={{ margin: 0, fontSize: '10px', color: '#fca5a5' }}>{error}</p>
                    )}
                    {!loading && !refreshing && !validation && !error && (
                        <p style={{ margin: 0, fontSize: '10px', color: 'var(--text-muted)' }}>
                            No hay validaciones económicas aún. Genera propuesta o pulsa refrescar.
                        </p>
                    )}

                    {!loading && !refreshing && validation && (
                        <div style={{ display: 'grid', gap: '8px' }}>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                                Perfil usado: <strong style={{ color: '#e2e8f0' }}>{perfil || 'N/D'}</strong>
                            </div>
                            {isGeneric && (
                                <div
                                    style={{
                                        fontSize: '10px',
                                        color: '#fbbf24',
                                        background: 'rgba(251,191,36,0.08)',
                                        border: '1px solid rgba(251,191,36,0.35)',
                                        borderRadius: '8px',
                                        padding: '6px 8px',
                                        fontWeight: 700,
                                    }}
                                >
                                    Perfil genérico detectado: algunas reglas específicas podrían no aplicar.
                                </div>
                            )}

                            <div style={{ display: 'flex', gap: '8px', fontSize: '10px', color: 'var(--text-muted)' }}>
                                <span>
                                    OK: <strong style={{ color: '#4ade80' }}>{stats.ok}</strong>
                                </span>
                                <span>
                                    WARN: <strong style={{ color: '#fbbf24' }}>{stats.warn}</strong>
                                </span>
                                <span>
                                    BLOCKING: <strong style={{ color: '#f87171' }}>{stats.blocking}</strong>
                                </span>
                            </div>

                            {blockingIssues.length > 0 && (
                                <div
                                    style={{
                                        fontSize: '10px',
                                        color: '#fecaca',
                                        background: 'rgba(248,113,113,0.08)',
                                        border: '1px solid rgba(248,113,113,0.35)',
                                        borderRadius: '8px',
                                        padding: '6px 8px',
                                    }}
                                >
                                    <div style={{ fontWeight: 700, marginBottom: '4px' }}>Issues bloqueantes</div>
                                    <ul style={{ margin: 0, paddingLeft: '16px' }}>
                                        {blockingIssues.slice(0, 5).map((b, i) => (
                                            <li key={i}>{b}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {alerts.length > 0 && (
                                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                                    <div style={{ fontWeight: 700, color: '#e2e8f0', marginBottom: '4px' }}>Alertas</div>
                                    <ul style={{ margin: 0, paddingLeft: '16px' }}>
                                        {alerts.slice(0, 5).map((a, i) => (
                                            <li key={i}>{a}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            <div style={{ display: 'grid', gap: '6px', maxHeight: '220px', overflowY: 'auto' }}>
                                {vals.map((v, idx) => (
                                    <div
                                        key={`${v.regla}-${idx}`}
                                        style={{
                                            border: `1px solid ${colorByState(v.estado)}55`,
                                            background: `${colorByState(v.estado)}11`,
                                            borderRadius: '8px',
                                            padding: '6px 8px',
                                        }}
                                    >
                                        <div
                                            style={{
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                alignItems: 'center',
                                                gap: '8px',
                                            }}
                                        >
                                            <div style={{ fontSize: '10px', fontWeight: 700, color: '#e2e8f0' }}>{v.regla}</div>
                                            <div style={{ fontSize: '9px', color: colorByState(v.estado), fontWeight: 800 }}>
                                                {labelByState(v.estado)}
                                            </div>
                                        </div>
                                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '3px' }}>{v.evidencia}</div>
                                    </div>
                                ))}
                            </div>

                            {typeof onAskAboutValidation === 'function' && (
                                <button
                                    type="button"
                                    onClick={() => onAskAboutValidation(validation)}
                                    style={{
                                        justifySelf: 'start',
                                        fontSize: '10px',
                                        padding: '6px 8px',
                                        borderRadius: '8px',
                                        border: '1px solid rgba(255,255,255,0.12)',
                                        background: 'rgba(0,0,0,0.3)',
                                        color: 'var(--text-muted)',
                                        cursor: 'pointer',
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '5px',
                                    }}
                                >
                                    {stats.blocking > 0 ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}
                                    Preguntar al chat sobre validaciones
                                </button>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
