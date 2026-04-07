import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';
import { FileWarning, FileCheck2, RefreshCw, AlertTriangle, Copy } from 'lucide-react';

/**
 * Panel Sprint 2: Actas y Aclaraciones.
 * Flujo: seleccionar PDF ya subido -> procesar acta -> revisar borrador/estado -> regenerar carta 33 Bis.
 */
export default function PostClarificationPanel({ sessionId, sources = [], onAskAboutActa, syncKey }) {
    const [loading, setLoading] = useState(false);
    const [processing, setProcessing] = useState(false);
    const [regenerating, setRegenerating] = useState(false);
    const [error, setError] = useState(null);
    const [copied, setCopied] = useState(false);
    const [ctx, setCtx] = useState(null);
    const [tipoJunta, setTipoJunta] = useState('primera');
    const [docId, setDocId] = useState('');

    const pdfSources = useMemo(
        () => (Array.isArray(sources) ? sources.filter((s) => /\.pdf$/i.test(s?.name || '')) : []),
        [sources]
    );

    useEffect(() => {
        if (!docId && pdfSources.length > 0) setDocId(pdfSources[0].id);
    }, [docId, pdfSources]);

    const fetchContext = useCallback(async () => {
        if (!sessionId) return;
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/post-clarification`
            );
            if (res.data?.success && res.data?.data?.post_clarification_context) {
                setCtx(res.data.data.post_clarification_context);
            } else {
                setCtx(null);
            }
        } catch (e) {
            setCtx(null);
            setError(e?.response?.data?.detail || e?.message || 'Error de red');
        } finally {
            setLoading(false);
        }
    }, [sessionId]);

    useEffect(() => {
        fetchContext();
    }, [fetchContext, syncKey]);

    const processActa = async () => {
        if (!docId) {
            setError('Selecciona un PDF de acta en Fuentes de Verdad.');
            return;
        }
        setProcessing(true);
        setError(null);
        try {
            const res = await axios.post(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/post-clarification/acta`,
                { document_id: docId, tipo_junta: tipoJunta }
            );
            if (res.data?.success && res.data?.data?.post_clarification_context) {
                setCtx(res.data.data.post_clarification_context);
            } else {
                setError(res.data?.message || 'No se pudo procesar el acta.');
            }
        } catch (e) {
            setError(e?.response?.data?.detail || e?.message || 'Error procesando acta');
        } finally {
            setProcessing(false);
        }
    };

    const regenerateCarta = async () => {
        setRegenerating(true);
        setError(null);
        try {
            const res = await axios.post(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/post-clarification/generate-carta-33-bis`,
                { force_regenerate: true }
            );
            if (res.data?.success && res.data?.data?.post_clarification_context) {
                setCtx(res.data.data.post_clarification_context);
            }
        } catch (e) {
            setError(e?.response?.data?.detail || e?.message || 'Error generando carta');
        } finally {
            setRegenerating(false);
        }
    };

    const fallback = Number(ctx?.confianza_extraccion || 0) < 0.7;
    const showHumanReviewBadge = Boolean(ctx) && fallback;

    const copyDraft = async () => {
        const txt = String(ctx?.carta_33_bis_draft || '').trim();
        if (!txt) return;
        try {
            await navigator.clipboard.writeText(txt);
            setCopied(true);
            setTimeout(() => setCopied(false), 1400);
        } catch (_) {
            setError('No se pudo copiar al portapapeles. Copia manualmente desde el cuadro de texto.');
        }
    };

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
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
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
                    Actas y aclaraciones
                </h3>
                <button
                    type="button"
                    onClick={fetchContext}
                    disabled={loading}
                    style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--primary)',
                        cursor: loading ? 'wait' : 'pointer',
                        padding: 0,
                    }}
                    title="Actualizar estado"
                >
                    <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                </button>
            </div>

            <div style={{ display: 'grid', gap: '8px' }}>
                {pdfSources.length === 0 && (
                    <div
                        style={{
                            fontSize: '10px',
                            color: '#fbbf24',
                            background: 'rgba(251,191,36,0.08)',
                            border: '1px solid rgba(251,191,36,0.35)',
                            padding: '8px',
                            borderRadius: '8px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                        }}
                    >
                        <AlertTriangle size={12} />
                        No hay PDF válido en fuentes. Sube o reprocesa un acta de junta para continuar.
                    </div>
                )}
                <select
                    value={docId}
                    onChange={(e) => setDocId(e.target.value)}
                    style={{
                        background: 'rgba(0,0,0,0.35)',
                        color: '#e2e8f0',
                        border: '1px solid rgba(255,255,255,0.12)',
                        borderRadius: '8px',
                        padding: '8px',
                        fontSize: '11px',
                    }}
                >
                    {pdfSources.length === 0 && <option value="">Sin PDF disponible</option>}
                    {pdfSources.map((s) => (
                        <option key={s.id} value={s.id}>
                            {s.name}
                        </option>
                    ))}
                </select>

                <select
                    value={tipoJunta}
                    onChange={(e) => setTipoJunta(e.target.value)}
                    style={{
                        background: 'rgba(0,0,0,0.35)',
                        color: '#e2e8f0',
                        border: '1px solid rgba(255,255,255,0.12)',
                        borderRadius: '8px',
                        padding: '8px',
                        fontSize: '11px',
                    }}
                >
                    <option value="primera">Primera junta</option>
                    <option value="segunda">Segunda junta</option>
                </select>

                <button
                    type="button"
                    onClick={processActa}
                    disabled={processing || !sessionId || !docId}
                    style={{
                        fontSize: '11px',
                        fontWeight: 800,
                        padding: '8px 10px',
                        borderRadius: '8px',
                        border: '1px solid var(--primary)',
                        background: 'rgba(0,212,255,0.12)',
                        color: '#e2e8f0',
                        cursor: processing || !docId ? 'not-allowed' : 'pointer',
                    }}
                >
                    {processing ? 'Procesando acta...' : 'Procesar acta'}
                </button>
            </div>

            {error && (
                <p style={{ marginTop: '8px', fontSize: '10px', color: '#fca5a5' }}>
                    {error}
                </p>
            )}

            {ctx && (
                <div style={{ marginTop: '10px', display: 'grid', gap: '8px' }}>
                    {showHumanReviewBadge && (
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
                            Requiere revisión humana obligatoria (fallback de baja confianza).
                        </div>
                    )}
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                        Estado: <strong style={{ color: '#e2e8f0' }}>{ctx.estado || 'N/D'}</strong> · Confianza: <strong style={{ color: '#e2e8f0' }}>{Number(ctx.confianza_extraccion || 0).toFixed(2)}</strong>
                    </div>
                    {fallback && (
                        <div style={{ fontSize: '10px', color: '#fbbf24', display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <AlertTriangle size={12} />
                            Baja confianza: se aplicó fallback de plantilla. Revisión humana obligatoria.
                        </div>
                    )}
                    {ctx?.preguntas_aclaracion?.length > 0 && (
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                            <div style={{ fontWeight: 700, marginBottom: '4px', color: '#e2e8f0' }}>
                                Preguntas Anexo 10 ({ctx.preguntas_aclaracion.length})
                            </div>
                            <ul style={{ margin: 0, paddingLeft: '16px' }}>
                                {ctx.preguntas_aclaracion.slice(0, 4).map((q, i) => (
                                    <li key={i} style={{ marginBottom: '2px' }}>
                                        [{q.tipo}] {q.pregunta}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {ctx?.carta_33_bis_draft && (
                        <div style={{ display: 'grid', gap: '6px' }}>
                            <textarea
                                readOnly
                                value={ctx.carta_33_bis_draft}
                                style={{
                                    width: '100%',
                                    minHeight: '120px',
                                    resize: 'vertical',
                                    background: 'rgba(0,0,0,0.35)',
                                    border: '1px solid rgba(255,255,255,0.12)',
                                    borderRadius: '8px',
                                    color: '#e2e8f0',
                                    fontSize: '10px',
                                    padding: '8px',
                                    boxSizing: 'border-box',
                                }}
                            />
                            <button
                                type="button"
                                onClick={copyDraft}
                                style={{
                                    justifySelf: 'start',
                                    fontSize: '10px',
                                    padding: '6px 8px',
                                    borderRadius: '8px',
                                    border: '1px solid rgba(255,255,255,0.12)',
                                    background: 'rgba(0,0,0,0.3)',
                                    color: copied ? '#4ade80' : 'var(--text-muted)',
                                    cursor: 'pointer',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '5px',
                                }}
                            >
                                <Copy size={12} />
                                {copied ? 'Copiado' : 'Copiar borrador'}
                            </button>
                        </div>
                    )}
                    <div style={{ display: 'flex', gap: '8px', justifyContent: 'space-between' }}>
                        <button
                            type="button"
                            onClick={regenerateCarta}
                            disabled={regenerating}
                            style={{
                                fontSize: '10px',
                                padding: '6px 8px',
                                borderRadius: '8px',
                                border: '1px solid rgba(255,255,255,0.12)',
                                background: 'rgba(0,0,0,0.3)',
                                color: 'var(--text-muted)',
                                cursor: regenerating ? 'wait' : 'pointer',
                            }}
                        >
                            {regenerating ? 'Regenerando...' : 'Regenerar carta 33 Bis'}
                        </button>
                        {typeof onAskAboutActa === 'function' && (
                            <button
                                type="button"
                                onClick={() => onAskAboutActa(ctx)}
                                style={{
                                    fontSize: '10px',
                                    padding: '6px 8px',
                                    borderRadius: '8px',
                                    border: '1px solid rgba(255,255,255,0.12)',
                                    background: 'rgba(0,0,0,0.3)',
                                    color: 'var(--text-muted)',
                                    cursor: 'pointer',
                                }}
                            >
                                Preguntar en chat
                            </button>
                        )}
                    </div>
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
                        {ctx?.carta_33_bis_docx_path ? (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                                <FileCheck2 size={12} /> Borrador docx: {ctx.carta_33_bis_docx_path}
                            </span>
                        ) : (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                                <FileWarning size={12} /> Aún no hay docx generado.
                            </span>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
