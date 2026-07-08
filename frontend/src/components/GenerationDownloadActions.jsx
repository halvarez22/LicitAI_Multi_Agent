import React, { useCallback, useEffect, useState } from 'react';
import { Download, Loader2, RefreshCw } from 'lucide-react';
import { fetchScopeArtifacts } from '../services/generationDownloadApi.js';
import { GENERATION_MODE_OPTIONS } from '../generationModeUi.js';
import ArtifactDownloadModal from './ArtifactDownloadModal.jsx';

/**
 * Aviso HRU cuando un alcance distinto al destacado ya tiene descargas listas.
 */
export function CrossScopeDownloadHint({ bundle }) {
    const techReady = Boolean(bundle?.technical?.ready) && Number(bundle?.technical?.artifact_count || 0) > 0;
    const ecoReady = Boolean(bundle?.economic?.ready) && Number(bundle?.economic?.artifact_count || 0) > 0;
    if (!techReady && !ecoReady) return null;
    if (techReady && ecoReady) return null;

    const text = ecoReady
        ? 'La cotización económica ya está disponible — bloque ECONÓMICA ↓'
        : 'La propuesta técnica ya está disponible — bloque TÉCNICA ↓';

    return (
        <p
            style={{
                margin: '4px 0 0',
                fontSize: '10px',
                color: '#86efac',
                textAlign: 'center',
                lineHeight: 1.45,
            }}
        >
            {text}
        </p>
    );
}

const SCOPES_BY_MODE = {
    full: 'full',
    technical: 'technical',
    economic: 'economic',
};

export function ScopeDownloadBlock({
    modeId,
    sessionId,
    refreshToken = 0,
    highlighted = false,
    compact = false,
    scopePayload = null,
    onRefreshScope,
}) {
    const [data, setData] = useState(scopePayload);
    const [loading, setLoading] = useState(false);
    const [modalOpen, setModalOpen] = useState(false);

    const scope = SCOPES_BY_MODE[modeId] || modeId;
    const modeOpt = GENERATION_MODE_OPTIONS.find((m) => m.id === modeId);

    const load = useCallback(async () => {
        if (!sessionId || scopePayload != null) return;
        setLoading(true);
        try {
            const payload = await fetchScopeArtifacts(sessionId, scope);
            setData(payload);
        } catch (err) {
            console.warn('[LicitAI] No se pudo cargar artefactos:', scope, err);
            setData({
                ready: false,
                artifact_count: 0,
                artifacts: [],
                empty_reason_message: 'Error al consultar archivos.',
            });
        } finally {
            setLoading(false);
        }
    }, [sessionId, scope, scopePayload]);

    useEffect(() => {
        if (scopePayload != null) {
            setData(scopePayload);
            return;
        }
        load();
    }, [load, refreshToken, scopePayload]);

    const ready = Boolean(data?.ready) && Number(data?.artifact_count || 0) > 0;
    const count = Number(data?.artifact_count || 0);
    const pausedReason = String(data?.empty_reason || '');
    const isPaused = !ready && ['job_blocked', 'document_quality_gate', 'prices_required', 'job_failed'].includes(pausedReason);
    const ctaDefault =
        modeId === 'full'
            ? 'Descargar expediente'
            : modeId === 'technical'
              ? 'Descargar propuesta técnica'
              : 'Descargar cotización económica';

    if (!sessionId && !loading) return null;

    return (
        <>
            <div
                id={`generation-download-${modeId}`}
                style={{
                    marginTop: compact ? '6px' : '8px',
                    padding: compact ? '8px 10px' : '10px 12px',
                    borderRadius: '10px',
                    border: highlighted && ready
                        ? '1px solid rgba(34,197,94,0.55)'
                        : highlighted && isPaused
                          ? '1px solid rgba(251,191,36,0.55)'
                          : isPaused
                            ? '1px solid rgba(251,191,36,0.35)'
                            : '1px solid rgba(255,255,255,0.07)',
                    background: highlighted && ready
                        ? 'rgba(34,197,94,0.08)'
                        : highlighted && isPaused
                          ? 'rgba(251,191,36,0.1)'
                          : isPaused
                            ? 'rgba(251,191,36,0.06)'
                            : 'rgba(15,23,42,0.45)',
                    boxShadow: highlighted && ready
                        ? '0 0 0 1px rgba(34,197,94,0.15)'
                        : highlighted && isPaused
                          ? '0 0 0 1px rgba(251,191,36,0.12)'
                          : 'none',
                    transition: 'border-color 0.3s ease, background 0.3s ease',
                }}
            >
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '8px',
                        marginBottom: ready || data?.empty_reason_message ? '8px' : 0,
                    }}
                >
                    <span
                        style={{
                            fontSize: compact ? '9px' : '10px',
                            fontWeight: 800,
                            color: '#cbd5e1',
                            textTransform: 'uppercase',
                            letterSpacing: '0.03em',
                        }}
                    >
                        {modeOpt?.short || modeId}
                    </span>
                    {onRefreshScope ? (
                        <button
                            type="button"
                            onClick={onRefreshScope}
                            disabled={loading}
                            title="Actualizar lista"
                            style={{
                                background: 'none',
                                border: 'none',
                                color: '#64748b',
                                cursor: loading ? 'wait' : 'pointer',
                                padding: '2px',
                            }}
                        >
                            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                        </button>
                    ) : null}
                </div>

                {loading && !data ? (
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                            fontSize: '11px',
                            color: '#94a3b8',
                        }}
                    >
                        <Loader2 size={12} className="animate-spin" />
                        Buscando archivos…
                    </div>
                ) : ready ? (
                    <p style={{ margin: '0 0 8px', fontSize: '11px', color: '#86efac', lineHeight: 1.4 }}>
                        {count} archivo{count !== 1 ? 's' : ''} listo{count !== 1 ? 's' : ''} para descargar
                    </p>
                ) : (
                    <p style={{ margin: '0 0 8px', fontSize: '10px', color: isPaused ? '#fcd34d' : '#94a3b8', lineHeight: 1.45 }}>
                        {String(data?.empty_reason_message || 'Genera este modo para obtener archivos.')}
                    </p>
                )}

                <button
                    type="button"
                    disabled={!ready}
                    onClick={() => setModalOpen(true)}
                    title={ready ? ctaDefault : String(data?.empty_reason_message || 'Sin archivos aún')}
                    style={{
                        width: '100%',
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '6px',
                        padding: compact ? '8px 6px' : '9px 10px',
                        borderRadius: '9px',
                        border: ready
                            ? '1px solid rgba(56,189,248,0.45)'
                            : '1px solid rgba(100,116,139,0.25)',
                        background: ready ? 'rgba(56,189,248,0.14)' : 'rgba(51,65,85,0.2)',
                        color: ready ? '#bae6fd' : '#64748b',
                        fontSize: compact ? '9px' : '10px',
                        fontWeight: 800,
                        cursor: ready ? 'pointer' : 'not-allowed',
                    }}
                >
                    <Download size={compact ? 12 : 14} />
                    {ctaDefault}
                </button>
            </div>

            <ArtifactDownloadModal
                open={modalOpen}
                onClose={() => setModalOpen(false)}
                sessionId={sessionId}
                scopeData={data}
                modeId={modeId}
            />
        </>
    );
}

/**
 * Panel de descargas contextuales post-generación (F5.6 / F5.8).
 */
export function useGenerationDownloadBundle(sessionId, refreshToken = 0) {
    const [bundle, setBundle] = useState({ full: null, technical: null, economic: null });
    const [loadingAll, setLoadingAll] = useState(false);

    const refreshAll = useCallback(async () => {
        if (!sessionId) return null;
        setLoadingAll(true);
        try {
            const [full, technical, economic] = await Promise.all([
                fetchScopeArtifacts(sessionId, 'full'),
                fetchScopeArtifacts(sessionId, 'technical'),
                fetchScopeArtifacts(sessionId, 'economic'),
            ]);
            const next = { full, technical, economic };
            setBundle(next);
            return next;
        } catch (err) {
            console.warn('[LicitAI] refreshAll artifacts failed', err);
            return null;
        } finally {
            setLoadingAll(false);
        }
    }, [sessionId]);

    useEffect(() => {
        refreshAll();
        if (!sessionId || !refreshToken) return undefined;
        const timers = [800, 2200, 4500].map((delay) =>
            setTimeout(() => {
                refreshAll();
            }, delay)
        );
        return () => timers.forEach(clearTimeout);
    }, [refreshAll, refreshToken, sessionId]);

    return { bundle, refreshAll, loadingAll };
}

export default function GenerationDownloadActions({
    sessionId,
    refreshToken = 0,
    highlightMode = null,
    onScrollToAdvancedLogistics,
}) {
    const { bundle, refreshAll, loadingAll } = useGenerationDownloadBundle(sessionId, refreshToken);

    if (!sessionId) return null;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
            <ScopeDownloadBlock
                modeId="full"
                sessionId={sessionId}
                refreshToken={refreshToken}
                highlighted={highlightMode === 'full'}
                scopePayload={bundle.full}
                onRefreshScope={refreshAll}
            />
            <div style={{ display: 'flex', gap: '8px', width: '100%' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <ScopeDownloadBlock
                        modeId="technical"
                        sessionId={sessionId}
                        refreshToken={refreshToken}
                        highlighted={highlightMode === 'technical'}
                        compact
                        scopePayload={bundle.technical}
                        onRefreshScope={refreshAll}
                    />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <ScopeDownloadBlock
                        modeId="economic"
                        sessionId={sessionId}
                        refreshToken={refreshToken}
                        highlighted={highlightMode === 'economic'}
                        compact
                        scopePayload={bundle.economic}
                        onRefreshScope={refreshAll}
                    />
                </div>
            </div>
            {onScrollToAdvancedLogistics ? (
                <button
                    type="button"
                    onClick={onScrollToAdvancedLogistics}
                    style={{
                        marginTop: '6px',
                        background: 'none',
                        border: 'none',
                        color: '#64748b',
                        fontSize: '10px',
                        textDecoration: 'underline',
                        cursor: 'pointer',
                        alignSelf: 'center',
                        padding: '4px 0',
                    }}
                >
                    Ver logística avanzada (CompraNet, ZIP completo)
                </button>
            ) : null}
            {loadingAll ? (
                <span style={{ fontSize: '9px', color: '#475569', textAlign: 'center' }}>
                    Actualizando listado…
                </span>
            ) : null}
        </div>
    );
}
