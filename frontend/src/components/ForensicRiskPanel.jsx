import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { AlertTriangle, CheckCircle2, XCircle, MessageSquare, BookOpen, RefreshCw } from 'lucide-react';
import { API_BASE } from '../apiBase.js';
import ForensicBasesExcerptCard from './ForensicBasesExcerptCard.jsx';
import ForensicEvidenceBadge from './ForensicEvidenceBadge.jsx';
import {
    DECISION_LABELS,
    SEVERITY_COLORS,
    groupRiskItems,
    mergeDecisionStats,
} from '../utils/forensicRiskUtils.js';

/**
 * Panel HITL de riesgos forenses — evaluación, explicación y decisión auditable.
 */
const ForensicRiskPanel = ({
    forensicRisks,
    sessionId,
    onDecisionsUpdated,
    onAskExpert,
    onAskRiskExpert,
    onBatchStop,
}) => {
    const [loadingId, setLoadingId] = useState(null);
    const [batchLoading, setBatchLoading] = useState(false);
    const [error, setError] = useState(null);
    const [notes, setNotes] = useState({});
    const [excerptByRisk, setExcerptByRisk] = useState({});
    const [loadingExcerptId, setLoadingExcerptId] = useState(null);
    const [hydratedItems, setHydratedItems] = useState(null);
    const [reindexLoading, setReindexLoading] = useState(false);

    const items = hydratedItems || forensicRisks?.items || [];
    const groups = useMemo(() => groupRiskItems(items), [items]);
    const stats = forensicRisks?.decision_stats || mergeDecisionStats(items);

    useEffect(() => {
        if (!sessionId) return;
        let cancelled = false;
        (async () => {
            try {
                const res = await axios.get(
                    `${API_BASE}/forensic-risks/${encodeURIComponent(sessionId)}/decisions`,
                );
                const block = res.data?.data?.forensic_risks_v1;
                if (!cancelled && block?.items?.length) {
                    setHydratedItems(block.items);
                }
            } catch {
                /* fallback a props */
            }
        })();
        return () => { cancelled = true; };
    }, [sessionId, forensicRisks?.items?.length]);

    if (!items.length) return null;

    const handleReindexBases = async () => {
        if (!sessionId) return;
        setReindexLoading(true);
        setError(null);
        try {
            await axios.post(
                `${API_BASE}/forensic-risks/${encodeURIComponent(sessionId)}/reindex-bases?force=true`,
            );
            const res = await axios.get(
                `${API_BASE}/forensic-risks/${encodeURIComponent(sessionId)}/decisions`,
            );
            const block = res.data?.data?.forensic_risks_v1;
            if (block?.items?.length) {
                setHydratedItems(block.items);
            }
            setExcerptByRisk({});
        } catch (err) {
            setError(err?.response?.data?.message || err?.message || 'No se pudo reindexar');
        } finally {
            setReindexLoading(false);
        }
    };

    const postDecisions = async (payload) => {
        setError(null);
        const res = await axios.post(
            `${API_BASE}/forensic-risks/${encodeURIComponent(sessionId)}/decisions`,
            payload,
        );
        if (!res.data?.success) {
            throw new Error(res.data?.message || 'No se pudieron guardar las decisiones');
        }
        if (onDecisionsUpdated) {
            onDecisionsUpdated(res.data.data);
        }
        if (res.data?.data?.forensic_risks_v1?.items?.length) {
            setHydratedItems(res.data.data.forensic_risks_v1.items);
        }
        return res.data.data;
    };

    const handleItemDecision = async (riskId, status) => {
        setLoadingId(riskId);
        try {
            await postDecisions({
                decisions: [{
                    risk_id: riskId,
                    status,
                    user_note: notes[riskId] || null,
                }],
            });
        } catch (err) {
            setError(err?.message || 'Error al guardar');
        } finally {
            setLoadingId(null);
        }
    };

    const handleBatch = async (action) => {
        setBatchLoading(true);
        setError(null);
        try {
            const data = await postDecisions({ batch_action: action, decisions: [] });
            if (action === 'stop_expediente' && onBatchStop) {
                onBatchStop(data);
            }
        } catch (err) {
            setError(err?.message || 'Error al procesar la decisión');
        } finally {
            setBatchLoading(false);
        }
    };

    const handleLoadExcerpt = async (item, literal) => {
        if (!sessionId || !literal) return;
        const rid = item.risk_id;
        if (excerptByRisk[rid]?.available) return;
        setLoadingExcerptId(rid);
        setError(null);
        try {
            const params = new URLSearchParams({ literal });
            if (item.page != null && String(item.page).trim() !== '') {
                params.set('page', String(item.page));
            }
            const res = await axios.get(
                `${API_BASE}/forensic-risks/${encodeURIComponent(sessionId)}/bases-excerpt?${params}`,
            );
            const excerpt = res.data?.data;
            if (excerpt?.available) {
                setExcerptByRisk((prev) => ({ ...prev, [rid]: excerpt }));
            } else {
                const chunks = excerpt?.diagnostics?.indexed_chunks;
                const chunkHint = chunks != null
                    ? ` Chunks indexados en sesión: ${chunks}.`
                    : '';
                setError(
                    (excerpt?.user_message
                    || res.data?.message
                    || 'No hay párrafo indexado para este riesgo en la sesión.')
                    + chunkHint,
                );
                if (excerpt?.diagnostics) {
                    setExcerptByRisk((prev) => ({ ...prev, [rid]: { ...excerpt, available: false } }));
                }
            }
        } catch (err) {
            setError(err?.response?.data?.message || err?.message || 'No se pudo cargar el extracto');
        } finally {
            setLoadingExcerptId(null);
        }
    };

    return (
        <div
            id="forensic-risk-panel"
            style={{
                marginBottom: '20px',
                padding: '16px',
                borderRadius: '16px',
                background: 'rgba(231, 76, 60, 0.06)',
                border: '1px solid rgba(231, 76, 60, 0.28)',
            }}
        >
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', marginBottom: '12px' }}>
                <AlertTriangle size={20} color="#ff6b6b" style={{ flexShrink: 0, marginTop: '2px' }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '11px', fontWeight: 900, letterSpacing: '0.6px', color: '#ff8a8a' }}>
                        EVALUACIÓN DE RIESGOS FORENSES
                    </div>
                    <p style={{ fontSize: '12px', lineHeight: 1.55, color: 'rgba(255,255,255,0.82)', margin: '6px 0 0' }}>
                        Estos hallazgos pueden descalificarte o afectar tu oferta. Revisa cada uno, entiende por qué lo
                        marcamos y decide si continúas asumiendo el riesgo o detienes el expediente.
                    </p>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '10px', alignItems: 'center' }}>
                        <button
                            type="button"
                            disabled={reindexLoading || batchLoading}
                            onClick={handleReindexBases}
                            style={{
                                padding: '5px 10px',
                                borderRadius: '8px',
                                border: '1px solid rgba(56,189,248,0.35)',
                                background: 'rgba(56,189,248,0.08)',
                                color: '#7dd3fc',
                                fontSize: '10px',
                                fontWeight: 800,
                                cursor: reindexLoading ? 'wait' : 'pointer',
                            }}
                        >
                            <RefreshCw size={11} style={{ verticalAlign: 'middle', marginRight: '4px' }} />
                            {reindexLoading ? 'Reindexando bases…' : 'Reindexar bases (HRU)'}
                        </button>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '10px', fontSize: '10px' }}>
                        <span>Pendientes: <strong>{stats.pending ?? 0}</strong></span>
                        <span style={{ color: '#2ecc71' }}>Asumidos: <strong>{stats.accepted ?? 0}</strong></span>
                        <span style={{ color: '#e74c3c' }}>Rechazados: <strong>{stats.rejected ?? 0}</strong></span>
                        {(stats.blocking_pending ?? 0) > 0 && (
                            <span style={{ color: '#ff6b6b' }}>
                                Bloqueantes sin decidir: <strong>{stats.blocking_pending}</strong>
                            </span>
                        )}
                    </div>
                </div>
            </div>

            {groups.map((group) => (
                <div key={group.kind} style={{ marginBottom: '14px' }}>
                    <div style={{
                        fontSize: '10px',
                        fontWeight: 900,
                        color: 'var(--text-muted)',
                        marginBottom: '8px',
                        letterSpacing: '0.4px',
                    }}
                    >
                        {group.label} ({group.items.length})
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {group.items.map((item) => {
                            const sev = item.risk_severity || 'medium';
                            const color = SEVERITY_COLORS[sev] || '#f39c12';
                            const st = item.decision_status || 'pending';
                            const literal = item._literal
                                || (typeof item.texto === 'object'
                                    ? (item.texto?.descripcion || item.texto?.nombre)
                                    : item.texto);
                            const busy = loadingId === item.risk_id;
                            return (
                                <div
                                    key={item.risk_id}
                                    style={{
                                        padding: '12px 14px',
                                        borderRadius: '12px',
                                        background: 'rgba(0,0,0,0.28)',
                                        border: `1px solid ${color}44`,
                                        borderLeft: `3px solid ${color}`,
                                    }}
                                >
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
                                        <span style={{
                                            fontSize: '9px',
                                            fontWeight: 800,
                                            padding: '3px 8px',
                                            borderRadius: '6px',
                                            background: `${color}22`,
                                            color,
                                            textTransform: 'uppercase',
                                        }}
                                        >
                                            {sev}
                                        </span>
                                        <span style={{
                                            fontSize: '9px',
                                            fontWeight: 800,
                                            padding: '3px 8px',
                                            borderRadius: '6px',
                                            background: 'rgba(255,255,255,0.06)',
                                            color: st === 'accepted' ? '#2ecc71' : st === 'rejected' ? '#e74c3c' : '#94a3b8',
                                        }}
                                        >
                                            {DECISION_LABELS[st] || st}
                                        </span>
                                        {item.tipo && (
                                            <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>{item.tipo}</span>
                                        )}
                                        {item.page != null && String(item.page).trim() !== '' && (
                                            <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>📄 {item.page}</span>
                                        )}
                                        <ForensicEvidenceBadge evidence={item.evidence_v1 || item} />
                                    </div>
                                    <div style={{ fontSize: '12px', fontWeight: 700, lineHeight: 1.45, marginBottom: '8px' }}>
                                        {literal}
                                    </div>
                                    <div style={{
                                        fontSize: '11px',
                                        lineHeight: 1.5,
                                        color: 'rgba(255,255,255,0.72)',
                                        marginBottom: '10px',
                                        padding: '8px 10px',
                                        borderRadius: '8px',
                                        background: 'rgba(56, 189, 248, 0.07)',
                                        border: '1px solid rgba(56, 189, 248, 0.2)',
                                    }}
                                    >
                                        <strong style={{ color: '#7dd3fc' }}>Por qué es riesgo: </strong>
                                        {item.risk_reason_ux}
                                    </div>
                                    {item.snippet && (
                                        <div style={{
                                            fontSize: '10px',
                                            color: 'var(--text-muted)',
                                            marginBottom: '10px',
                                            fontStyle: 'italic',
                                        }}
                                        >
                                            «{typeof item.snippet === 'string' ? item.snippet.slice(0, 280) : ''}»
                                        </div>
                                    )}
                                    {excerptByRisk[item.risk_id]?.available ? (
                                        <div style={{ marginBottom: '10px' }}>
                                            <ForensicBasesExcerptCard excerpt={excerptByRisk[item.risk_id]} />
                                        </div>
                                    ) : (
                                        <button
                                            type="button"
                                            disabled={loadingExcerptId === item.risk_id || batchLoading}
                                            onClick={() => handleLoadExcerpt(item, literal)}
                                            style={{
                                                marginBottom: '10px',
                                                padding: '6px 10px',
                                                borderRadius: '8px',
                                                border: '1px solid rgba(56,189,248,0.35)',
                                                background: 'rgba(56,189,248,0.08)',
                                                color: '#7dd3fc',
                                                fontSize: '10px',
                                                fontWeight: 800,
                                                cursor: loadingExcerptId === item.risk_id ? 'wait' : 'pointer',
                                            }}
                                        >
                                            <BookOpen size={12} style={{ verticalAlign: 'middle', marginRight: '4px' }} />
                                            {loadingExcerptId === item.risk_id
                                                ? 'Cargando párrafo…'
                                                : 'Ver párrafo en las bases'}
                                        </button>
                                    )}
                                    <textarea
                                        placeholder="Nota opcional (auditoría HITL)…"
                                        value={notes[item.risk_id] || ''}
                                        onChange={(e) => setNotes((prev) => ({ ...prev, [item.risk_id]: e.target.value }))}
                                        rows={2}
                                        style={{
                                            width: '100%',
                                            marginBottom: '8px',
                                            padding: '8px',
                                            borderRadius: '8px',
                                            border: '1px solid rgba(255,255,255,0.1)',
                                            background: 'rgba(0,0,0,0.2)',
                                            color: '#fff',
                                            fontSize: '11px',
                                            resize: 'vertical',
                                        }}
                                    />
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                        <button
                                            type="button"
                                            disabled={busy || batchLoading}
                                            onClick={() => handleItemDecision(item.risk_id, 'accepted')}
                                            style={{
                                                padding: '6px 10px',
                                                borderRadius: '8px',
                                                border: '1px solid rgba(46,204,113,0.4)',
                                                background: 'rgba(46,204,113,0.12)',
                                                color: '#2ecc71',
                                                fontSize: '10px',
                                                fontWeight: 800,
                                                cursor: busy ? 'wait' : 'pointer',
                                            }}
                                        >
                                            <CheckCircle2 size={12} style={{ verticalAlign: 'middle', marginRight: '4px' }} />
                                            Asumir riesgo
                                        </button>
                                        <button
                                            type="button"
                                            disabled={busy || batchLoading}
                                            onClick={() => handleItemDecision(item.risk_id, 'rejected')}
                                            style={{
                                                padding: '6px 10px',
                                                borderRadius: '8px',
                                                border: '1px solid rgba(231,76,60,0.4)',
                                                background: 'rgba(231,76,60,0.1)',
                                                color: '#e74c3c',
                                                fontSize: '10px',
                                                fontWeight: 800,
                                                cursor: busy ? 'wait' : 'pointer',
                                            }}
                                        >
                                            <XCircle size={12} style={{ verticalAlign: 'middle', marginRight: '4px' }} />
                                            Rechazar / actuar
                                        </button>
                                        {(onAskRiskExpert || onAskExpert) && (
                                            <button
                                                type="button"
                                                disabled={busy || batchLoading}
                                                onClick={() => {
                                                    if (onAskRiskExpert) {
                                                        onAskRiskExpert(item);
                                                        return;
                                                    }
                                                    onAskExpert(`Explícame este riesgo forense y qué hacer: ${literal}`);
                                                }}
                                                style={{
                                                    padding: '6px 10px',
                                                    borderRadius: '8px',
                                                    border: '1px solid rgba(255,255,255,0.12)',
                                                    background: 'rgba(255,255,255,0.04)',
                                                    color: '#e2e8f0',
                                                    fontSize: '10px',
                                                    fontWeight: 800,
                                                    cursor: 'pointer',
                                                }}
                                            >
                                                <MessageSquare size={12} style={{ verticalAlign: 'middle', marginRight: '4px' }} />
                                                Preguntar al experto
                                            </button>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            ))}

            {error && (
                <div style={{
                    marginBottom: '10px',
                    padding: '10px',
                    borderRadius: '8px',
                    background: 'rgba(231,76,60,0.12)',
                    border: '1px solid rgba(231,76,60,0.35)',
                    fontSize: '11px',
                    color: '#ff8a8a',
                }}
                >
                    {error}
                </div>
            )}

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '4px' }}>
                <button
                    type="button"
                    disabled={batchLoading}
                    onClick={() => handleBatch('continue_assuming_risks')}
                    style={{
                        flex: 1,
                        minWidth: '160px',
                        padding: '11px',
                        borderRadius: '10px',
                        border: '1px solid rgba(243,156,18,0.45)',
                        background: 'rgba(243,156,18,0.12)',
                        color: '#f39c12',
                        fontSize: '11px',
                        fontWeight: 800,
                        cursor: batchLoading ? 'wait' : 'pointer',
                    }}
                >
                    {batchLoading ? 'Guardando…' : 'Continuar licitación asumiendo riesgos'}
                </button>
                <button
                    type="button"
                    disabled={batchLoading}
                    onClick={() => handleBatch('stop_expediente')}
                    style={{
                        flex: 1,
                        minWidth: '160px',
                        padding: '11px',
                        borderRadius: '10px',
                        border: '1px solid rgba(255,255,255,0.12)',
                        background: 'rgba(0,0,0,0.25)',
                        color: '#e2e8f0',
                        fontSize: '11px',
                        fontWeight: 800,
                        cursor: batchLoading ? 'wait' : 'pointer',
                    }}
                >
                    Detener y revisar expediente
                </button>
            </div>
        </div>
    );
};

export default ForensicRiskPanel;
