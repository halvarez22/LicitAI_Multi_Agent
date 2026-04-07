import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';
import { CalendarClock, CheckCircle2, AlertTriangle } from 'lucide-react';

/**
 * Panel de hitos del procedimiento (SubmissionChecklist) — Sprint 1.
 * Datos desde GET /sessions/{id}/submission-checklist
 */
export default function SubmissionChecklistPanel({ sessionId, onAskAboutHito, syncKey }) {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [data, setData] = useState(null);
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
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', marginBottom: '10px' }}>
                <h3
                    style={{
                        fontSize: '11px',
                        fontWeight: 900,
                        color: 'var(--text-muted)',
                        textTransform: 'uppercase',
                        letterSpacing: '1px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        margin: 0,
                    }}
                >
                    <CalendarClock size={14} color="var(--primary)" />
                    Hitos del procedimiento
                </h3>
                {data && (
                    <span
                        style={{
                            fontSize: '10px',
                            fontWeight: 800,
                            color: 'var(--primary)',
                            background: 'rgba(0,212,255,0.1)',
                            padding: '4px 8px',
                            borderRadius: '8px',
                        }}
                    >
                        {data.porcentaje_completado ?? 0}% listo
                    </span>
                )}
            </div>

            {loading && (
                <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: 0 }}>Cargando checklist…</p>
            )}
            {!loading && error && !data && (
                <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: 0 }}>{error}</p>
            )}
            {!loading && data?.hitos?.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '280px', overflowY: 'auto' }}>
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
                }}
            >
                Actualizar checklist
            </button>
        </div>
    );
}
