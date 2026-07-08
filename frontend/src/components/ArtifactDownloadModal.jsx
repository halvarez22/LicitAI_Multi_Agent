import React, { useState } from 'react';
import { Download, FileText, Loader2, X } from 'lucide-react';
import { downloadGeneratedFile } from '../services/generationDownloadApi.js';
import { GENERATION_MODE_OPTIONS } from '../generationModeUi.js';

/**
 * Modal compacto: lista de archivos generados por alcance (F5.7).
 */
export default function ArtifactDownloadModal({
    open,
    onClose,
    sessionId,
    scopeData,
    modeId = null,
}) {
    const [downloading, setDownloading] = useState(null);

    if (!open || !scopeData) return null;

    const artifacts = Array.isArray(scopeData.artifacts) ? scopeData.artifacts : [];
    const modeOpt = GENERATION_MODE_OPTIONS.find((m) => m.id === modeId);
    const title = String(scopeData.scope_label || modeOpt?.label || 'Archivos generados');

    const handleDownload = async (art) => {
        const rel = String(art.relative_path || '');
        const name = String(art.filename || 'documento');
        if (!rel || !sessionId) return;
        setDownloading(name);
        try {
            await downloadGeneratedFile(sessionId, rel, name);
        } catch (err) {
            console.error('[LicitAI] Error descargando archivo:', err);
            alert('No se pudo descargar el archivo. Intenta de nuevo.');
        } finally {
            setDownloading(null);
        }
    };

    return (
        <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="artifact-modal-title"
            style={{
                position: 'fixed',
                inset: 0,
                zIndex: 10050,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(0,0,0,0.65)',
                padding: '16px',
            }}
            onClick={onClose}
        >
            <div
                onClick={(e) => e.stopPropagation()}
                style={{
                    width: 'min(480px, 100%)',
                    maxHeight: '80vh',
                    overflow: 'hidden',
                    display: 'flex',
                    flexDirection: 'column',
                    borderRadius: '16px',
                    border: '1px solid rgba(99,102,241,0.35)',
                    background: 'linear-gradient(160deg, rgba(15,23,42,0.98), rgba(30,27,75,0.98))',
                    boxShadow: '0 24px 48px rgba(0,0,0,0.45)',
                }}
            >
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '14px 16px',
                        borderBottom: '1px solid rgba(255,255,255,0.08)',
                    }}
                >
                    <h3
                        id="artifact-modal-title"
                        style={{ margin: 0, fontSize: '14px', fontWeight: 800, color: '#e2e8f0' }}
                    >
                        {title}
                    </h3>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Cerrar"
                        style={{
                            background: 'none',
                            border: 'none',
                            color: '#94a3b8',
                            cursor: 'pointer',
                            padding: '4px',
                        }}
                    >
                        <X size={18} />
                    </button>
                </div>

                <div style={{ padding: '12px 16px', overflowY: 'auto', flex: 1 }}>
                    {artifacts.length === 0 ? (
                        <p style={{ margin: 0, fontSize: '12px', color: '#94a3b8', lineHeight: 1.5 }}>
                            {String(
                                scopeData.empty_reason_message
                                    || 'No hay archivos listos para descargar en este alcance.',
                            )}
                        </p>
                    ) : (
                        <ul
                            style={{
                                listStyle: 'none',
                                margin: 0,
                                padding: 0,
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '8px',
                            }}
                        >
                            {artifacts.map((art) => {
                                const name = String(art.filename || 'documento');
                                const display = String(art.display_name || name);
                                const key = String(art.id || art.relative_path || name);
                                const busy = downloading === name;
                                return (
                                    <li
                                        key={key}
                                        style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                            gap: '10px',
                                            padding: '10px 12px',
                                            borderRadius: '10px',
                                            background: 'rgba(0,0,0,0.25)',
                                            border: '1px solid rgba(255,255,255,0.06)',
                                        }}
                                    >
                                        <div
                                            style={{
                                                display: 'flex',
                                                alignItems: 'flex-start',
                                                gap: '8px',
                                                minWidth: 0,
                                                flex: 1,
                                            }}
                                        >
                                            <FileText
                                                size={16}
                                                color="#7dd3fc"
                                                style={{ flexShrink: 0, marginTop: '2px' }}
                                            />
                                            <div style={{ minWidth: 0 }}>
                                                <div
                                                    style={{
                                                        fontSize: '12px',
                                                        fontWeight: 700,
                                                        color: '#f1f5f9',
                                                        overflow: 'hidden',
                                                        textOverflow: 'ellipsis',
                                                        whiteSpace: 'nowrap',
                                                    }}
                                                    title={name}
                                                >
                                                    {name}
                                                </div>
                                                <div style={{ fontSize: '10px', color: '#94a3b8' }}>
                                                    {display}
                                                </div>
                                            </div>
                                        </div>
                                        <button
                                            type="button"
                                            disabled={busy}
                                            onClick={() => handleDownload(art)}
                                            title="Descargar"
                                            style={{
                                                flexShrink: 0,
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                gap: '4px',
                                                padding: '6px 10px',
                                                borderRadius: '8px',
                                                border: '1px solid rgba(56,189,248,0.4)',
                                                background: 'rgba(56,189,248,0.12)',
                                                color: '#7dd3fc',
                                                fontSize: '10px',
                                                fontWeight: 700,
                                                cursor: busy ? 'wait' : 'pointer',
                                            }}
                                        >
                                            {busy ? (
                                                <Loader2 size={12} className="animate-spin" />
                                            ) : (
                                                <Download size={12} />
                                            )}
                                            Bajar
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </div>
            </div>
        </div>
    );
}
