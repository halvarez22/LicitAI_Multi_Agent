import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';
import { CalendarClock, RefreshCw } from 'lucide-react';
import CriticalDatesList from './CriticalDatesList.jsx';
import { fechaTieneValor } from '../utils/criticalDatesDisplay.js';

/**
 * Panel de fechas críticas del procedimiento (cronograma / SubmissionChecklist).
 * GET /sessions/{id}/submission-checklist — también puede hidratarse desde dictamen.
 */
export default function SubmissionChecklistPanel({
    sessionId,
    onAskAboutHito,
    syncKey,
    flatList = false,
    initialData = null,
}) {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [data, setData] = useState(initialData);

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
                setError(res.data?.message || 'Sin calendario (analiza las bases primero).');
            }
        } catch (e) {
            setData(null);
            setError(e?.response?.data?.detail || e?.message || 'Error de red al cargar calendario');
        } finally {
            setLoading(false);
        }
    }, [sessionId]);

    useEffect(() => {
        if (initialData?.hitos?.length) {
            setData(initialData);
        }
    }, [initialData, syncKey]);

    useEffect(() => {
        fetchChecklist();
    }, [fetchChecklist, syncKey]);

    const [evidenciaDraft, setEvidenciaDraft] = useState({});

    const markHito = async (hitoId, estado, evidenciaOpcional) => {
        try {
            const evidencia =
                estado === 'completado'
                    ? (evidenciaOpcional !== undefined
                          ? evidenciaOpcional
                          : evidenciaDraft[hitoId] || '').trim() || null
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

    const hitos = data?.hitos || [];
    const conFecha = hitos.filter((h) => fechaTieneValor(h.fecha_texto_raw)).length;
    const hitosVencidos = hitos.filter((h) => h.estado === 'vencido').length;

    const listBlock = (
        <>
            {loading && (
                <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '8px 0' }}>
                    Cargando fechas críticas…
                </p>
            )}
            {!loading && error && !hitos.length && (
                <p style={{ fontSize: '11px', color: '#f87171', margin: '8px 0' }}>{error}</p>
            )}
            {!loading && hitos.length > 0 && (
                <CriticalDatesList
                    hitos={hitos}
                    onAskAboutHito={onAskAboutHito}
                    onMarkHito={markHito}
                    evidenciaDraft={evidenciaDraft}
                    onEvidenciaDraftChange={(id, value) =>
                        setEvidenciaDraft((prev) => ({ ...prev, [id]: value }))
                    }
                />
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
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                }}
            >
                <RefreshCw size={10} />
                Actualizar calendario
            </button>
        </>
    );

    if (flatList) {
        return (
            <div
                style={{
                    border: '1px solid rgba(0,212,255,0.2)',
                    borderRadius: '12px',
                    padding: '14px',
                    background: 'rgba(0,0,0,0.25)',
                }}
            >
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginBottom: '12px',
                        gap: '8px',
                    }}
                >
                    <span
                        style={{
                            fontSize: '12px',
                            fontWeight: 800,
                            color: '#e2e8f0',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                        }}
                    >
                        <CalendarClock size={16} color="var(--primary)" />
                        Fechas críticas de la licitación
                    </span>
                    {hitos.length > 0 && (
                        <span
                            style={{
                                fontSize: '10px',
                                fontWeight: 800,
                                color: hitosVencidos > 0 ? '#f87171' : 'var(--primary)',
                                background:
                                    hitosVencidos > 0
                                        ? 'rgba(248,113,113,0.12)'
                                        : 'rgba(0,212,255,0.1)',
                                padding: '4px 10px',
                                borderRadius: '8px',
                            }}
                        >
                            {conFecha}/{hitos.length} con fecha
                            {hitosVencidos > 0 ? ` · ${hitosVencidos} vencido(s)` : ''}
                        </span>
                    )}
                </div>
                {listBlock}
            </div>
        );
    }

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
            <div
                style={{
                    fontSize: '11px',
                    fontWeight: 900,
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: '1px',
                    marginBottom: '10px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                }}
            >
                <CalendarClock size={14} color="var(--primary)" />
                Hitos del procedimiento
            </div>
            {listBlock}
        </div>
    );
}
