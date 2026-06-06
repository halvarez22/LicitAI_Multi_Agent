import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';
import {
    FileText, AlertCircle, HelpCircle, ChevronRight, Search, FileCheck, Sparkles, Loader2,
} from 'lucide-react';
import { countActionableDeliverables } from '../utils/auditSummary';
import { buildStableReactKey } from '../utils/stableReactKey.js';

/**
 * Inventario previo a la generación: formatos y anexos del pliego (GET /pliego-formats-panel).
 */
const DetectedFormatsPanel = ({ formats: rawFormatsProp, onAskExpert, sessionId, active = true }) => {
    const [filter, setFilter] = useState('');
    const [expandedKey, setExpandedKey] = useState(null);
    const [fetched, setFetched] = useState(null);
    const [loading, setLoading] = useState(false);
    const [fetchError, setFetchError] = useState(null);

    useEffect(() => {
        if (!active || !sessionId) return undefined;
        let cancelled = false;
        (async () => {
            setLoading(true);
            setFetchError(null);
            try {
                const res = await axios.get(
                    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/pliego-formats-panel`,
                    { timeout: 30000 }
                );
                if (cancelled) return;
                if (res.data?.success && res.data?.data?.pliego_formats_panel) {
                    setFetched(res.data.data.pliego_formats_panel);
                } else {
                    setFetched(null);
                    setFetchError(res.data?.message || 'Sin formatos detectados.');
                }
            } catch (e) {
                if (!cancelled) {
                    setFetched(null);
                    setFetchError(e?.response?.data?.detail || e?.message || 'Error de red');
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [active, sessionId]);

    const rawFormats = fetched ?? rawFormatsProp;

    const isConsolidated =
        rawFormats
        && typeof rawFormats === 'object'
        && !Array.isArray(rawFormats)
        && rawFormats.sobre_1_tecnico;
    const actionableCount = countActionableDeliverables(rawFormats);
    const candidatesArray = Array.isArray(rawFormats)
        ? rawFormats
        : (rawFormats?.candidate_document_list || []);

    if (loading) {
        return (
            <div style={{ padding: '40px', textAlign: 'center', opacity: 0.7 }}>
                <Loader2 size={32} style={{ margin: '0 auto 12px', animation: 'spin 1s linear infinite' }} />
                <p style={{ fontSize: '13px' }}>Cargando formatos detectados…</p>
            </div>
        );
    }

    if (!isConsolidated && !candidatesArray.length) {
        return (
            <div style={{ padding: '40px', textAlign: 'center', opacity: 0.5 }}>
                <FileText size={48} style={{ marginBottom: '16px', margin: '0 auto' }} />
                <p style={{ fontSize: '14px' }}>
                    {fetchError
                        ? fetchError
                        : 'Aún no hay formatos ni anexos detectados. Ejecuta Analizar bases para construir el inventario del expediente.'}
                </p>
            </div>
        );
    }

    const renderDocumentCard = (doc, idx, categoryLabel) => {
        const isToGenerate =
            doc.tipo === 'generar'
            || doc.tipo_accion_final === 'generar'
            || doc.tipo_accion_propuesto === 'generar';
        const isPhysical =
            doc.tipo === 'presentar_fisico' || doc.tipo_accion_final === 'presentar_fisico';
        const nombre = doc.nombre_canonico || doc.nombre;
        const cardKey = buildStableReactKey({
            prefix: 'fmt',
            scope: categoryLabel,
            index: idx,
            item: doc,
            identityFields: [
                'id',
                'document_id',
                'nombre_canonico',
                'nombre',
                'numero_anexo',
                'tipo',
                'tipo_accion_final',
                'tipo_accion_propuesto',
                'snippet_representativo',
                'evidence_snippet',
            ],
        });
        const evidencia = doc.snippet_representativo || doc.evidence_snippet;
        const conf = doc.confidence ?? 0.7;
        const numItems = doc.items_fusionados ?? 1;

        const actionLabel = isToGenerate
            ? 'A GENERAR'
            : (isPhysical ? 'PRESENTAR FÍSICO' : 'INFORMATIVO');

        return (
            <div
                key={cardKey}
                style={{
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.05)',
                    borderRadius: '15px',
                    overflow: 'hidden',
                    transition: 'all 0.2s ease',
                    marginBottom: '10px',
                }}
            >
                <div
                    onClick={() => setExpandedKey(expandedKey === cardKey ? null : cardKey)}
                    style={{
                        padding: '12px 16px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '12px',
                        cursor: 'pointer',
                        background: expandedKey === cardKey ? 'rgba(255,255,255,0.03)' : 'transparent',
                    }}
                >
                    <div
                        style={{
                            width: '36px',
                            height: '36px',
                            borderRadius: '10px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: isToGenerate
                                ? 'rgba(34, 197, 94, 0.15)'
                                : (isPhysical ? 'rgba(56, 189, 248, 0.15)' : 'rgba(255,255,255,0.05)'),
                            color: isToGenerate
                                ? '#4ade80'
                                : (isPhysical ? '#38bdf8' : 'var(--text-muted)'),
                        }}
                    >
                        {isToGenerate ? <FileCheck size={20} /> : <FileText size={20} />}
                    </div>

                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div
                            style={{
                                fontSize: '13px',
                                fontWeight: 700,
                                color: '#f1f5f9',
                                whiteSpace: 'nowrap',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                            }}
                        >
                            {doc.numero_anexo ? `[${doc.numero_anexo}] ` : ''}{nombre}
                        </div>
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '2px', flexWrap: 'wrap' }}>
                            <span
                                style={{
                                    fontSize: '10px',
                                    textTransform: 'uppercase',
                                    fontWeight: 800,
                                    color: 'var(--text-muted)',
                                }}
                            >
                                {categoryLabel}
                            </span>
                            <span
                                style={{
                                    width: '3px',
                                    height: '3px',
                                    borderRadius: '50%',
                                    background: 'rgba(255,255,255,0.2)',
                                }}
                            />
                            <span
                                style={{
                                    fontSize: '10px',
                                    fontWeight: 700,
                                    color: isToGenerate
                                        ? '#4ade80'
                                        : (isPhysical ? '#38bdf8' : 'var(--text-muted)'),
                                }}
                            >
                                {actionLabel}
                            </span>
                            <span
                                style={{
                                    width: '3px',
                                    height: '3px',
                                    borderRadius: '50%',
                                    background: 'rgba(255,255,255,0.2)',
                                }}
                            />
                            <span style={{ fontSize: '10px', fontWeight: 700, color: '#a78bfa' }}>
                                PENDIENTE
                            </span>
                            {numItems > 1 && (
                                <>
                                    <span
                                        style={{
                                            width: '3px',
                                            height: '3px',
                                            borderRadius: '50%',
                                            background: 'rgba(255,255,255,0.2)',
                                        }}
                                    />
                                    <span style={{ fontSize: '10px', fontWeight: 800, color: '#f39c12' }}>
                                        ({numItems} menciones consolidadas)
                                    </span>
                                </>
                            )}
                        </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        {conf < 0.7 && (
                            <AlertCircle size={14} color="#f39c12" title="Confianza baja - requiere revisión" />
                        )}
                        <ChevronRight
                            size={18}
                            style={{
                                transform: expandedKey === cardKey ? 'rotate(90deg)' : 'rotate(0deg)',
                                transition: 'transform 0.2s ease',
                                color: 'rgba(255,255,255,0.2)',
                            }}
                        />
                    </div>
                </div>

                {expandedKey === cardKey && (
                    <div style={{ padding: '0 16px 16px 16px', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                        <div style={{ marginTop: '12px' }}>
                            <div
                                style={{
                                    fontSize: '10px',
                                    fontWeight: 800,
                                    color: 'var(--text-muted)',
                                    marginBottom: '6px',
                                }}
                            >
                                EVIDENCIA PRINCIPAL EN BASES:
                            </div>
                            <div
                                style={{
                                    fontSize: '12px',
                                    color: 'rgba(255,255,255,0.7)',
                                    lineHeight: 1.5,
                                    background: 'rgba(0,0,0,0.2)',
                                    padding: '10px',
                                    borderRadius: '8px',
                                    fontStyle: 'italic',
                                }}
                            >
                                "{evidencia || 'No hay fragmento de texto disponible.'}"
                            </div>
                        </div>

                        <div style={{ marginTop: '12px', display: 'flex', gap: '10px' }}>
                            <button
                                type="button"
                                onClick={() =>
                                    onAskExpert(`¿Qué debe incluir el formato "${nombre}" según las bases?`)
                                }
                                style={{
                                    flex: 1,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '8px',
                                    padding: '8px',
                                    borderRadius: '10px',
                                    background: 'rgba(255,255,255,0.05)',
                                    border: '1px solid rgba(255,255,255,0.1)',
                                    color: '#fff',
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    cursor: 'pointer',
                                }}
                            >
                                <HelpCircle size={14} /> Explicar formato
                            </button>
                            <button
                                type="button"
                                onClick={() =>
                                    onAskExpert(
                                        `¿En qué página de las bases se menciona el formato o anexo "${nombre}"?`,
                                    )
                                }
                                style={{
                                    flex: 1,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '8px',
                                    padding: '8px',
                                    borderRadius: '10px',
                                    background: 'rgba(255,255,255,0.05)',
                                    border: '1px solid rgba(255,255,255,0.1)',
                                    color: '#fff',
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    cursor: 'pointer',
                                }}
                            >
                                <Search size={14} /> Ver ubicación exacta
                            </button>
                        </div>
                    </div>
                )}
            </div>
        );
    };

    const matchesFilter = (doc, categoryLabel) => {
        if (!filter) return true;
        const nombre = doc.nombre_canonico || doc.nombre || '';
        return (
            nombre.toLowerCase().includes(filter.toLowerCase())
            || (categoryLabel && categoryLabel.toLowerCase().includes(filter.toLowerCase()))
        );
    };

    let consolidatedListIndex = 0;
    const renderFilteredCard = (doc, categoryLabel) => {
        if (!matchesFilter(doc, categoryLabel)) return null;
        const card = renderDocumentCard(doc, consolidatedListIndex, categoryLabel);
        consolidatedListIndex += 1;
        return card;
    };

    const generarCount = isConsolidated
        ? [
            ...(rawFormats.sobre_1_tecnico || []),
            ...(rawFormats.sobre_2_economico || []),
            ...(rawFormats.requisitos_legales || []),
            ...(rawFormats.otros_requisitos_criticos || []),
        ].filter(
            (d) =>
                d.tipo === 'generar'
                || d.tipo_accion_final === 'generar'
                || d.tipo_accion_propuesto === 'generar',
        ).length
        : candidatesArray.filter(
            (d) =>
                d.tipo === 'generar'
                || d.tipo_accion_final === 'generar'
                || d.tipo_accion_propuesto === 'generar',
        ).length;

    return (
        <div className="detected-formats-panel" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '15px' }}>
                <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                        <Sparkles size={18} color="#a78bfa" />
                        <h4 style={{ fontSize: '16px', fontWeight: 800, color: '#f1f5f9', margin: 0 }}>
                            Formatos/Anexos Detectados
                        </h4>
                    </div>
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                        {`Inventario detectado en las bases (${actionableCount} ítems; ${generarCount} marcados a generar). `}
                        La app rellenará estos formatos al pulsar <strong>Generar</strong>; aquí solo se muestra el plan del expediente.
                    </p>
                </div>
                <div style={{ position: 'relative', flex: 1, maxWidth: '250px' }}>
                    <Search
                        size={14}
                        style={{
                            position: 'absolute',
                            left: '10px',
                            top: '50%',
                            transform: 'translateY(-50%)',
                            color: 'var(--text-muted)',
                        }}
                    />
                    <input
                        type="text"
                        placeholder="Filtrar formatos..."
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        style={{
                            width: '100%',
                            padding: '8px 10px 8px 30px',
                            borderRadius: '10px',
                            background: 'rgba(255,255,255,0.05)',
                            border: '1px solid rgba(255,255,255,0.1)',
                            color: '#fff',
                            fontSize: '12px',
                            outline: 'none',
                        }}
                    />
                </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {isConsolidated ? (
                    <>
                        {rawFormats.sobre_1_tecnico?.length > 0 && (
                            <div>
                                <h5
                                    style={{
                                        fontSize: '12px',
                                        fontWeight: 800,
                                        color: '#4ade80',
                                        marginBottom: '10px',
                                        letterSpacing: '0.5px',
                                    }}
                                >
                                    📂 SOBRE 1: PROPUESTA TÉCNICA
                                </h5>
                                {rawFormats.sobre_1_tecnico.map((doc) =>
                                    renderFilteredCard(doc, 'Propuesta Técnica'),
                                )}
                            </div>
                        )}
                        {rawFormats.sobre_2_economico?.length > 0 && (
                            <div>
                                <h5
                                    style={{
                                        fontSize: '12px',
                                        fontWeight: 800,
                                        color: '#38bdf8',
                                        marginBottom: '10px',
                                        letterSpacing: '0.5px',
                                    }}
                                >
                                    💰 SOBRE 2: PROPUESTA ECONÓMICA
                                </h5>
                                {rawFormats.sobre_2_economico.map((doc) =>
                                    renderFilteredCard(doc, 'Propuesta Económica'),
                                )}
                            </div>
                        )}
                        {rawFormats.requisitos_legales?.length > 0 && (
                            <div>
                                <h5
                                    style={{
                                        fontSize: '12px',
                                        fontWeight: 800,
                                        color: '#f39c12',
                                        marginBottom: '10px',
                                        letterSpacing: '0.5px',
                                    }}
                                >
                                    ⚖️ REQUISITOS LEGALES
                                </h5>
                                {rawFormats.requisitos_legales.map((doc) =>
                                    renderFilteredCard(doc, 'Documentación Legal'),
                                )}
                            </div>
                        )}
                        {rawFormats.otros_requisitos_criticos?.length > 0 && (
                            <div>
                                <h5
                                    style={{
                                        fontSize: '12px',
                                        fontWeight: 800,
                                        color: '#e74c3c',
                                        marginBottom: '10px',
                                        letterSpacing: '0.5px',
                                    }}
                                >
                                    ⚠️ OTROS REQUISITOS CRÍTICOS
                                </h5>
                                {rawFormats.otros_requisitos_criticos.map((doc) =>
                                    renderFilteredCard(doc, 'Requisito General'),
                                )}
                            </div>
                        )}
                    </>
                ) : (
                    <div>
                        {candidatesArray
                            .map((doc, idx) => ({ doc, idx }))
                            .filter(({ doc }) => matchesFilter(doc, 'Formato / Anexo'))
                            .map(({ doc, idx }) => renderDocumentCard(doc, idx, 'Formato / Anexo'))}
                    </div>
                )}
            </div>
        </div>
    );
};

export default DetectedFormatsPanel;
