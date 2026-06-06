import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';
import { 
    FileText, CheckCircle2, AlertCircle, HelpCircle, 
    MessageSquare, ChevronRight, Search, FileCheck, Loader2
} from 'lucide-react';
import { buildStableReactKey } from '../utils/stableReactKey.js';

/**
 * Panel de Documentos Detectados (Fast-Track)
 * Carga credenciales empresariales vía GET /document-candidates-summary (sin dictamen completo).
 */
const DocumentCandidatePanel = ({
    candidates: rawCandidatesProp,
    onAskExpert,
    sessionId,
    companyId,
    active = true,
}) => {
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
                    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/document-candidates-summary`,
                    {
                        timeout: 30000,
                        params: companyId ? { company_id: companyId } : undefined,
                    }
                );
                if (cancelled) return;
                if (res.data?.success && res.data?.data?.corporate_physical_document_candidates) {
                    setFetched(res.data.data.corporate_physical_document_candidates);
                } else {
                    setFetched(null);
                    setFetchError(res.data?.message || 'Sin documentos detectados.');
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
    }, [active, sessionId, companyId]);

    const rawCandidates = fetched ?? rawCandidatesProp;

    // Solo credenciales empresariales en presentación física (lista plana).
    const isCorporatePhysical = rawCandidates?._meta?.filtered_corporate_physical_only === true;
    const looksLikeLegacyConsolidated =
        !isCorporatePhysical
        && rawCandidates
        && !Array.isArray(rawCandidates)
        && rawCandidates.sobre_1_tecnico;
    const candidatesArray = looksLikeLegacyConsolidated
        ? []
        : Array.isArray(rawCandidates)
            ? rawCandidates
            : (rawCandidates?.candidate_document_list || []);
    const actionableCount = candidatesArray.length;

    if (loading) {
        return (
            <div style={{ padding: '40px', textAlign: 'center', opacity: 0.7 }}>
                <Loader2 size={32} style={{ margin: '0 auto 12px', animation: 'spin 1s linear infinite' }} />
                <p style={{ fontSize: '13px' }}>Cargando documentos detectados…</p>
            </div>
        );
    }

    if (!candidatesArray.length) {
        return (
            <div style={{ padding: '40px', textAlign: 'center', opacity: 0.5 }}>
                <FileText size={48} style={{ marginBottom: '16px', margin: '0 auto' }} />
                <p style={{ fontSize: '14px' }}>
                    {fetchError
                        ? fetchError
                        : looksLikeLegacyConsolidated
                        ? 'Vista antigua detectada (anexos del pliego). Recarga con Ctrl+F5 o abre de nuevo esta pestaña para cargar credenciales empresariales (IMSS, SAT, actas, etc.).'
                        : 'No se detectaron credenciales empresariales para presentación física. Revisa que las bases estén indexadas o pulsa «Actualizar análisis».'}
                </p>
            </div>
        );
    }

    const renderDocumentCard = (doc, idx, categoryLabel) => {
        const isToGenerate = doc.tipo === 'generar' || doc.tipo_accion_final === 'generar';
        const isPhysical = doc.tipo === 'presentar_fisico' || doc.tipo_accion_final === 'presentar_fisico';
        const nombre = doc.nombre_canonico || doc.nombre;
        const cardKey = buildStableReactKey({
            prefix: 'candidate',
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
                'snippet_representativo',
                'evidence_snippet',
            ],
        });
        
        const evidencia = doc.snippet_representativo || doc.evidence_snippet;
        const conf = doc.confidence ?? 0.7;
        const numItems = doc.items_fusionados ?? 1;

        return (
            <div 
                key={cardKey}
                style={{ 
                    background: 'rgba(255,255,255,0.02)', 
                    border: '1px solid rgba(255,255,255,0.05)',
                    borderRadius: '15px',
                    overflow: 'hidden',
                    transition: 'all 0.2s ease',
                    marginBottom: '10px'
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
                        background: expandedKey === cardKey ? 'rgba(255,255,255,0.03)' : 'transparent'
                    }}
                >
                    <div style={{ 
                        width: '36px', height: '36px', borderRadius: '10px', 
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: isToGenerate ? 'rgba(34, 197, 94, 0.15)' : (isPhysical ? 'rgba(56, 189, 248, 0.15)' : 'rgba(255,255,255,0.05)'),
                        color: isToGenerate ? '#4ade80' : (isPhysical ? '#38bdf8' : 'var(--text-muted)')
                    }}>
                        {isToGenerate ? <FileCheck size={20} /> : <FileText size={20} />}
                    </div>
                    
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: '13px', fontWeight: 700, color: '#f1f5f9', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {doc.numero_anexo ? `[${doc.numero_anexo}] ` : ''}{nombre}
                        </div>
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '2px' }}>
                            <span style={{ fontSize: '10px', textTransform: 'uppercase', fontWeight: 800, color: 'var(--text-muted)' }}>
                                {categoryLabel}
                            </span>
                            <span style={{ width: '3px', height: '3px', borderRadius: '50%', background: 'rgba(255,255,255,0.2)' }} />
                            <span style={{ 
                                fontSize: '10px', fontWeight: 700, 
                                color: isToGenerate ? '#4ade80' : (isPhysical ? '#38bdf8' : 'var(--text-muted)')
                            }}>
                                {isToGenerate ? 'A GENERAR' : (isPhysical ? 'PRESENTAR FÍSICO' : 'INFORMATIVO')}
                            </span>
                            {numItems > 1 && (
                                <>
                                    <span style={{ width: '3px', height: '3px', borderRadius: '50%', background: 'rgba(255,255,255,0.2)' }} />
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
                                color: 'rgba(255,255,255,0.2)'
                            }} 
                        />
                    </div>
                </div>

                {expandedKey === cardKey && (
                    <div style={{ padding: '0 16px 16px 16px', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                        <div style={{ marginTop: '12px' }}>
                            <div style={{ fontSize: '10px', fontWeight: 800, color: 'var(--text-muted)', marginBottom: '6px' }}>EVIDENCIA PRINCIPAL EN BASES:</div>
                            <div style={{ 
                                fontSize: '12px', color: 'rgba(255,255,255,0.7)', lineHeight: 1.5, 
                                background: 'rgba(0,0,0,0.2)', padding: '10px', borderRadius: '8px',
                                fontStyle: 'italic'
                            }}>
                                "{evidencia || 'No hay fragmento de texto disponible.'}"
                            </div>
                        </div>

                        <div style={{ marginTop: '12px', display: 'flex', gap: '10px' }}>
                            <button 
                                onClick={() => onAskExpert(`¿Qué debo cumplir exactamente en el documento "${nombre}"?`)}
                                style={{ 
                                    flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
                                    padding: '8px', borderRadius: '10px', background: 'rgba(255,255,255,0.05)',
                                    border: '1px solid rgba(255,255,255,0.1)', color: '#fff', fontSize: '11px',
                                    fontWeight: 600, cursor: 'pointer'
                                }}
                            >
                                <HelpCircle size={14} /> Explicar documento
                            </button>
                            <button 
                                onClick={() => onAskExpert(`¿En qué página de las bases se menciona el requisito "${nombre}"?`)}
                                style={{ 
                                    flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
                                    padding: '8px', borderRadius: '10px', background: 'rgba(255,255,255,0.05)',
                                    border: '1px solid rgba(255,255,255,0.1)', color: '#fff', fontSize: '11px',
                                    fontWeight: 600, cursor: 'pointer'
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

    return (
        <div className="document-candidate-panel" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '15px' }}>
                <div>
                    <h4 style={{ fontSize: '16px', fontWeight: 800, color: '#f1f5f9', marginBottom: '4px' }}>
                        Documentos empresariales (presentación física)
                    </h4>
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        {`Credenciales del licitante para presentación física (${actionableCount} ítems): IMSS, SAT, actas, pólizas, certificaciones, etc. No incluye anexos del pliego a generar.`}
                    </p>
                </div>
                <div style={{ position: 'relative', flex: 1, maxWidth: '250px' }}>
                    <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                    <input 
                        type="text" 
                        placeholder="Filtrar documentos..." 
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        style={{ 
                            width: '100%', padding: '8px 10px 8px 30px', borderRadius: '10px', 
                            background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)',
                            color: '#fff', fontSize: '12px', outline: 'none'
                        }}
                    />
                </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {candidatesArray
                    .map((doc, idx) => ({ doc, idx }))
                    .filter(({ doc }) => {
                        if (!filter) return true;
                        const nombre = doc.nombre_canonico || doc.nombre || '';
                        return (
                            nombre.toLowerCase().includes(filter.toLowerCase())
                            || 'Expediente empresarial'.toLowerCase().includes(filter.toLowerCase())
                        );
                    })
                    .map(({ doc, idx }) => renderDocumentCard(doc, idx, 'Expediente empresarial'))}
            </div>
        </div>
    );
};

export default DocumentCandidatePanel;
