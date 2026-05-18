import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';
import { CalendarClock, CheckCircle2, AlertTriangle, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';

/**
 * Panel de hitos del procedimiento (SubmissionChecklist) — Sprint 1.
 * Datos desde GET /sessions/{id}/submission-checklist
 */
export default function SubmissionChecklistPanel({ sessionId, onAskAboutHito, syncKey }) {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [data, setData] = useState(null);
    /** Acordeón: abierto/cerrado. Por defecto cerrado para no saturar la columna izquierda. */
    const [expanded, setExpanded] = useState(false);
    /** Borradores de evidencia por hito (solo antes de marcar completado). */
    const [evidenciaDraft, setEvidenciaDraft] = useState({});

    const fetchChecklist = useCallback(async () => {
        if (!sessionId) return;
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/submission-checklist`
            );
            if (res.data?.success && res.data?.data?.submission_checklist) {
                setData(res.data.data.submission_checklist);
            } else {
                setData(null);
                setError(res.data?.message || 'Sin checklist (analiza las bases primero).');
            }
        } catch (e) {
            setData(null);
            setError(e?.response?.data?.detail || e?.message || 'Error de red');
        } finally {
            setLoading(false);
        }
    }, [sessionId]);

    useEffect(() => {
        fetchChecklist();
    }, [fetchChecklist, syncKey]);

    const markHito = async (hitoId, estado, evidenciaOpcional) => {
        try {
            const evidencia =
                estado === 'completado'
                    ? (evidenciaOpcional !== undefined ? evidenciaOpcional : evidenciaDraft[hitoId] || '').trim() || null
                    : null;
            const res = await axios.post(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/submission-checklist/${encodeURIComponent(hitoId)}/mark`,
                { estado, evidencia }
            );
            if (res.data?.success && res.data?.data?.submission_checklist) {
                setData(res.data.data.submission_checklist);
                if (estado === 'completado') {
                    setEvidenciaDraft((prev) => {
                        const next = { ...prev };
                        delete next[hitoId];
                        return next;
                    });
                }
            }
        } catch (e) {
            setError(e?.response?.data?.detail || e?.message || 'No se pudo actualizar');
        }
    };

    if (!sessionId) return null;

    // Resumen para cabecera cerrada
    const totalHitos = data?.hitos?.length ?? 0;
    const hitosCompletados = data?.hitos?.filter(h => h.estado === 'completado').length ?? 0;
    const hitosVencidos = data?.hitos?.filter(h => h.estado === 'vencido').length ?? 0;

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
            {/* ── CABECERA ACORDEÓN ── */}
            <button
                type="button"
                aria-expanded={expanded}
                aria-controls="hitos-panel"
                onClick={() => setExpanded(v => !v)}
                style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '8px',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    padding: 0,
                    marginBottom: expanded ? '10px' : 0,
                    borderRadius: '8px',
                    outline: 'none',
                }}
                onFocus={e => e.currentTarget.style.boxShadow = '0 0 0 2px var(--primary)'}
                onBlur={e  => e.currentTarget.style.boxShadow = 'none'}
            >
                {/* Icono + título */}
                <span
                    style={{
                        fontSize: '11px',
                        fontWeight: 900,
                        color: 'var(--text-muted)',
                        textTransform: 'uppercase',
                        letterSpacing: '1px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                    }}
                >
                    <CalendarClock size={14} color="var(--primary)" />
                    Hitos del procedimiento
                </span>

                {/* Derecha: resumen + chevron */}
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                    {data && (
                        <span
                            style={{
                                fontSize: '10px',
                                fontWeight: 800,
                                color: hitosVencidos > 0 ? '#f87171' : 'var(--primary)',
                                background: hitosVencidos > 0 ? 'rgba(248,113,113,0.12)' : 'rgba(0,212,255,0.1)',
                                padding: '3px 8px',
                                borderRadius: '8px',
                                transition: 'all 0.2s',
                            }}
                        >
                            {hitosVencidos > 0
                                ? `⚠ ${hitosVencidos} vencido${hitosVencidos > 1 ? 's' : ''} · ${data.porcentaje_completado ?? 0}%`
                                : `${hitosCompletados}/${totalHitos} · ${data.porcentaje_completado ?? 0}%`
                            }
                        </span>
                    )}
                    {loading
                        ? <RefreshCw size={14} color="var(--text-muted)" className="animate-spin" />
                        : (expanded
                            ? <ChevronUp  size={14} color="var(--text-muted)" />
                            : <ChevronDown size={14} color="var(--text-muted)" />
                          )
                    }
                </span>
            </button>

            {/* ── CUERPO COLAPSABLE ── */}
            <div
                id="hitos-panel"
                hidden={!expanded}
                style={expanded ? {} : { display: 'none' }}
            >
                {loading && (
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '8px 0 0' }}>Cargando checklist…</p>
                )}
                {!loading && error && !data && (
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '8px 0 0' }}>{error}</p>
                )}
                {!loading && data?.hitos?.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '420px', overflowY: 'auto' }}>
                    {data.hitos.map((h) => (
                        <div
                            key={h.id}
                            style={{
                                display: 'grid',
                                gridTemplateColumns: '1fr auto',
                                gap: '8px',
                                alignItems: 'start',
                                padding: '8px',
                                borderRadius: '10px',
                                background: 'rgba(255,255,255,0.03)',
                                border:
                                    h.estado === 'vencido'
                                        ? '1px solid rgba(239,68,68,0.35)'
                                        : '1px solid rgba(255,255,255,0.06)',
                            }}
                        >
                            <div style={{ minWidth: 0 }}>
                                <div style={{ fontSize: '12px', fontWeight: 700, color: '#f1f5f9' }}>{h.nombre}</div>
                                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                    {h.fecha_texto_raw || 'Sin fecha en bases'}
                                </div>
                                {h.estado === 'vencido' && (
                                    <div
                                        style={{
                                            fontSize: '10px',
                                            color: '#f87171',
                                            marginTop: '4px',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '4px',
                                        }}
                                    >
                                        <AlertTriangle size={12} /> Fecha aparentemente vencida
                                    </div>
                                )}
                                {h.evidencia && (
                                    <div style={{ fontSize: '10px', color: 'var(--primary)', marginTop: '4px' }}>
                                        Evidencia: {h.evidencia}
                                    </div>
                                )}
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', alignItems: 'stretch', minWidth: '140px' }}>
                                {h.estado === 'completado' ? (
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '10px', color: '#4ade80', justifyContent: 'flex-end' }}>
                                        <CheckCircle2 size={14} /> Hecho
                                    </span>
                                ) : (
                                    <>
                                        <input
                                            type="text"
                                            aria-label={`Evidencia opcional para ${h.nombre}`}
                                            placeholder="Evidencia (opcional)"
                                            value={evidenciaDraft[h.id] ?? ''}
                                            onChange={(e) =>
                                                setEvidenciaDraft((prev) => ({ ...prev, [h.id]: e.target.value }))
                                            }
                                            style={{
                                                width: '100%',
                                                fontSize: '10px',
                                                padding: '6px 8px',
                                                borderRadius: '8px',
                                                border: '1px solid rgba(255,255,255,0.12)',
                                                background: 'rgba(0,0,0,0.35)',
                                                color: '#e2e8f0',
                                                boxSizing: 'border-box',
                                            }}
                                        />
                                        <button
                                            type="button"
                                            onClick={() => markHito(h.id, 'completado')}
                                            style={{
                                                fontSize: '10px',
                                                fontWeight: 700,
                                                padding: '6px 10px',
                                                borderRadius: '8px',
                                                border: '1px solid var(--primary)',
                                                background: 'rgba(0,212,255,0.12)',
                                                color: '#e2e8f0',
                                                cursor: 'pointer',
                                                whiteSpace: 'nowrap',
                                            }}
                                        >
                                            Marcar hecho
                                        </button>
                                    </>
                                )}
                                {h.estado === 'completado' && (
                                    <button
                                        type="button"
                                        onClick={() => markHito(h.id, 'pendiente')}
                                        style={{
                                            fontSize: '9px',
                                            padding: '4px 8px',
                                            borderRadius: '6px',
                                            border: 'none',
                                            background: 'transparent',
                                            color: 'var(--text-muted)',
                                            cursor: 'pointer',
                                        }}
                                    >
                                        Deshacer
                                    </button>
                                )}
                                {typeof onAskAboutHito === 'function' && (
                                    <button
                                        type="button"
                                        onClick={() => onAskAboutHito(h)}
                                        style={{
                                            fontSize: '9px',
                                            padding: '4px 8px',
                                            borderRadius: '6px',
                                            border: '1px solid rgba(255,255,255,0.12)',
                                            background: 'rgba(0,0,0,0.2)',
                                            color: 'var(--text-muted)',
                                            cursor: 'pointer',
                                        }}
                                    >
                                        Preguntar en chat
                                    </button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
                )}

                {/* Botón refresh — visible solo cuando expandido */}
                <button
                    type="button"
                    onClick={fetchChecklist}
                    disabled={loading}
                    style={{
                        marginTop: '10px',
                        fontSize: '10px',
                        color: 'var(--primary)',
                        background: 'none',
                        border: 'none',
                        cursor: loading ? 'wait' : 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                    }}
                >
                    <RefreshCw size={10} />
                    Actualizar checklist
                </button>
            </div>{/* fin #hitos-panel */}
        </div>
    );
}
