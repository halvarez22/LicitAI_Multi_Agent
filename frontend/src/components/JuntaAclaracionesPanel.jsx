import React, { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';
import {
    MessageCircleQuestion,
    RefreshCw,
    Copy,
    CheckCircle2,
    XCircle,
    Send,
    ChevronDown,
    ChevronRight,
    MapPin,
} from 'lucide-react';
import { CITATION_QUALITY_META, getCitationQualityMeta } from '../utils/juntaCitationQuality.js';

const TIPO_LABEL = {
    tecnica: 'Técnica',
    legal: 'Legal',
    economica: 'Económica',
    administrativa: 'Administrativa',
};

const SOURCE_LABEL = {
    analyst_junta: 'Analista (junta)',
    analyst_gap: 'Brecha estratégica',
    analyst_alert: 'Alerta bases',
    evidence_conflict: 'Inconsistencia bases/documentos',
    mini_dictamen: 'Anexo / plantilla',
    thematic_bases: 'Detectado en bases',
    go_no_go: 'Go/No-Go',
    compliance: 'Compliance',
};

/**
 * Listado de preguntas para la convocante (junta de aclaraciones).
 * GET /sessions/{id}/junta-aclaraciones-questions
 */
export default function JuntaAclaracionesPanel({
    sessionId,
    companyId,
    active = true,
    syncKey,
    onAskExpert,
}) {
    const [expanded, setExpanded] = useState(true);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [bundle, setBundle] = useState(null);
    const [copied, setCopied] = useState(false);
    const [plainText, setPlainText] = useState('');

    const fetchQuestions = useCallback(
        async (refresh = false) => {
            if (!sessionId) return;
            setLoading(true);
            setError(null);
            try {
                const res = await axios.get(
                    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/junta-aclaraciones-questions`,
                    {
                        timeout: 30000,
                        params: {
                            ...(refresh ? { refresh: 'true' } : {}),
                            format: 'text',
                            ...(companyId ? { company_id: companyId } : {}),
                            ...(refresh ? { _ts: String(Date.now()) } : {}),
                        },
                    }
                );
                if (res.data?.success && res.data?.data?.junta_aclaraciones_questions) {
                    setBundle(res.data.data.junta_aclaraciones_questions);
                    setPlainText(res.data.data.plain_text || '');
                } else {
                    setBundle(null);
                    setPlainText('');
                    setError(res.data?.message || 'Sin listado (analiza las bases primero).');
                }
            } catch (e) {
                setBundle(null);
                setPlainText('');
                setError(e?.response?.data?.detail || e?.message || 'Error de red');
            } finally {
                setLoading(false);
            }
        },
        [sessionId, companyId]
    );

    useEffect(() => {
        if (active === false || !sessionId) return;
        fetchQuestions(false);
    }, [fetchQuestions, active, sessionId, syncKey]);

    const items = useMemo(() => {
        const raw = bundle?.items;
        return Array.isArray(raw) ? raw.filter((it) => it?.status !== 'excluida') : [];
    }, [bundle]);

    const summary = bundle?.summary || {};

    const setStatus = async (questionId, status) => {
        try {
            const res = await axios.post(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/junta-aclaraciones-questions/${encodeURIComponent(questionId)}/status`,
                { status }
            );
            if (res.data?.success && res.data?.data?.junta_aclaraciones_questions) {
                setBundle(res.data.data.junta_aclaraciones_questions);
            }
        } catch (e) {
            setError(e?.response?.data?.detail || e?.message || 'No se pudo actualizar');
        }
    };

    const handleCopy = async () => {
        let text = plainText;
        if (!text && items.length) {
            text = items.map((it, i) => `${i + 1}. [${(it.tipo || '').toUpperCase()}] ${it.pregunta}`).join('\n\n');
        }
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            setError('No se pudo copiar al portapapeles');
        }
    };

    const headerLine = bundle
        ? `${summary.total ?? items.length} pregunta(s) · ${summary.listas_para_junta ?? items.length} para junta`
        : 'Sin listado generado';

    return (
        <div
            style={{
                padding: '14px 16px',
                borderRadius: '14px',
                border: '1px solid rgba(56, 189, 248, 0.25)',
                background: 'rgba(14, 165, 233, 0.06)',
            }}
        >
            <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    width: '100%',
                    background: 'none',
                    border: 'none',
                    color: '#f8fafc',
                    cursor: 'pointer',
                    padding: 0,
                    marginBottom: expanded ? '12px' : 0,
                }}
            >
                {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                <MessageCircleQuestion size={18} color="#38bdf8" />
                <strong style={{ fontSize: '13px' }}>Preguntas para la Junta (convocante)</strong>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: 'auto' }}>
                    {headerLine}
                </span>
            </button>

            {expanded && (
                <>
                    <p style={{ margin: '0 0 12px', fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                        Preguntas redactadas para formular a la <strong>convocante</strong> en la junta de
                        aclaraciones. Se consolidan hallazgos del analista, inconsistencias en bases/documentos y
                        tickets de anexos. El chat interno (perfil/precios) es aparte.
                    </p>

                    <div
                        style={{
                            display: 'flex',
                            flexWrap: 'wrap',
                            gap: '6px',
                            marginBottom: '10px',
                            fontSize: '10px',
                            fontWeight: 600,
                        }}
                        aria-label="Leyenda de calidad de citas"
                    >
                        {Object.entries(CITATION_QUALITY_META).map(([key, meta]) => (
                            <span
                                key={key}
                                title={meta.title}
                                style={citationBadgeStyle(meta.color)}
                            >
                                <MapPin size={10} style={{ marginRight: '4px', verticalAlign: '-1px' }} />
                                {meta.label}
                            </span>
                        ))}
                    </div>

                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' }}>
                        <button
                            type="button"
                            onClick={() => fetchQuestions(true)}
                            disabled={loading}
                            style={btnStyle(false)}
                        >
                            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                            {loading ? 'Actualizando…' : 'Regenerar listado'}
                        </button>
                        <button type="button" onClick={handleCopy} disabled={!items.length} style={btnStyle(false)}>
                            <Copy size={14} />
                            {copied ? 'Copiado' : 'Copiar para portal'}
                        </button>
                    </div>

                    {error && (
                        <p style={{ color: '#fca5a5', fontSize: '12px', marginBottom: '8px' }}>{error}</p>
                    )}

                    {loading && !items.length && (
                        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Generando preguntas…</p>
                    )}

                    {!loading && items.length === 0 && !error && (
                        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                            Aún no hay preguntas. Ejecuta <strong>Analizar bases</strong> o pulsa Regenerar.
                        </p>
                    )}

                    <div style={{ display: 'grid', gap: '10px' }}>
                        {items.map((it, idx) => {
                            const citationMeta = getCitationQualityMeta(it);
                            return (
                            <div
                                key={it.question_id || idx}
                                style={{
                                    padding: '12px 14px',
                                    borderRadius: '12px',
                                    background: 'rgba(15, 23, 42, 0.45)',
                                    border: '1px solid rgba(255,255,255,0.08)',
                                }}
                            >
                                <div
                                    style={{
                                        display: 'flex',
                                        flexWrap: 'wrap',
                                        gap: '6px',
                                        marginBottom: '8px',
                                        fontSize: '10px',
                                        fontWeight: 700,
                                    }}
                                >
                                    <span style={badge('#0ea5e9')}>{TIPO_LABEL[it.tipo] || it.tipo}</span>
                                    <span style={badge(it.prioridad === 'alta' ? '#f59e0b' : '#64748b')}>
                                        {String(it.prioridad || 'media').toUpperCase()}
                                    </span>
                                    <span style={badge('#8b5cf6')}>
                                        {SOURCE_LABEL[it.source] || it.source}
                                    </span>
                                    <span
                                        style={citationBadgeStyle(citationMeta.color)}
                                        title={citationMeta.title}
                                    >
                                        <MapPin size={10} style={{ marginRight: '4px', verticalAlign: '-1px' }} />
                                        {citationMeta.label}
                                    </span>
                                    {it.status && it.status !== 'borrador' && (
                                        <span style={badge('#22c55e')}>{it.status}</span>
                                    )}
                                </div>
                                <p style={{ margin: '0 0 8px', fontSize: '13px', color: '#f1f5f9', lineHeight: 1.45 }}>
                                    <strong>{idx + 1}.</strong> {it.pregunta}
                                </p>
                                {it.archivo_fuente && (
                                    <p style={{ margin: '0 0 8px', fontSize: '11px', color: 'var(--text-muted)' }}>
                                        Ref.: {it.archivo_fuente}
                                        {it.pagina ? ` · p. ${it.pagina}` : ''}
                                    </p>
                                )}
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                    <button
                                        type="button"
                                        style={btnStyle(true)}
                                        onClick={() => setStatus(it.question_id, 'aprobada')}
                                        title="Incluir en el paquete para la junta"
                                    >
                                        <CheckCircle2 size={13} /> Aprobar
                                    </button>
                                    <button
                                        type="button"
                                        style={btnStyle(true)}
                                        onClick={() => setStatus(it.question_id, 'enviada')}
                                    >
                                        <Send size={13} /> Enviada
                                    </button>
                                    <button
                                        type="button"
                                        style={btnStyle(true)}
                                        onClick={() => setStatus(it.question_id, 'excluida')}
                                    >
                                        <XCircle size={13} /> Excluir
                                    </button>
                                    {onAskExpert && (
                                        <button
                                            type="button"
                                            style={btnStyle(true)}
                                            onClick={() =>
                                                onAskExpert(
                                                    `Ayúdame a pulir esta pregunta para la junta de aclaraciones: «${it.pregunta}»`
                                                )
                                            }
                                        >
                                            Pulir en chat
                                        </button>
                                    )}
                                </div>
                            </div>
                            );
                        })}
                    </div>
                </>
            )}
        </div>
    );
}

function btnStyle(compact) {
    return {
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: compact ? '6px 10px' : '8px 14px',
        borderRadius: '10px',
        border: '1px solid rgba(255,255,255,0.12)',
        background: 'rgba(0,0,0,0.25)',
        color: '#e2e8f0',
        fontSize: '11px',
        fontWeight: 700,
        cursor: 'pointer',
    };
}

function badge(color) {
    return {
        padding: '2px 8px',
        borderRadius: '6px',
        background: `${color}22`,
        color,
        border: `1px solid ${color}44`,
    };
}

function citationBadgeStyle(color) {
    return {
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 8px',
        borderRadius: '6px',
        background: `${color}18`,
        color,
        border: `1px solid ${color}55`,
        fontSize: '10px',
        fontWeight: 700,
        cursor: 'help',
    };
}
