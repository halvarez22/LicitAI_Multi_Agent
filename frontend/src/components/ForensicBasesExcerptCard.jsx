import React, { useState } from 'react';
import { BookOpen, ChevronDown, ChevronUp, FileText } from 'lucide-react';

/**
 * Tarjeta forense HRU: párrafo literal indexado de las bases (sin abrir PDF físico).
 */
export default function ForensicBasesExcerptCard({ excerpt, compact = false }) {
    const [expanded, setExpanded] = useState(!compact);
    const [showFullPage, setShowFullPage] = useState(false);

    if (!excerpt || !excerpt.available) {
        return null;
    }

    const page = excerpt.page;
    const source = excerpt.source || 'bases';
    const paragraph = excerpt.paragraph || '';
    const fullPage = excerpt.page_text_truncated;

    return (
        <div
            style={{
                marginTop: compact ? 0 : '12px',
                border: '1px solid rgba(56,189,248,0.35)',
                borderRadius: '10px',
                background: 'rgba(56,189,248,0.06)',
                overflow: 'hidden',
            }}
        >
            <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '8px',
                    padding: '10px 12px',
                    background: 'rgba(0,0,0,0.15)',
                    border: 'none',
                    color: '#bae6fd',
                    cursor: 'pointer',
                    fontSize: '12px',
                    fontWeight: 700,
                    textAlign: 'left',
                }}
            >
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <BookOpen size={14} />
                    Ver párrafo en las bases
                    {page != null && (
                        <span style={{ opacity: 0.85, fontWeight: 600 }}>
                            — pág. {page}
                        </span>
                    )}
                </span>
                {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>

            {expanded && (
                <div style={{ padding: '12px 14px', fontSize: '13px', lineHeight: 1.55, color: '#e2e8f0' }}>
                    <div
                        style={{
                            display: 'grid',
                            gap: '8px',
                            marginBottom: '10px',
                            fontSize: '11px',
                            color: '#94a3b8',
                        }}
                    >
                        <div>
                            <strong style={{ color: '#cbd5e1' }}>Ubicación:</strong>{' '}
                            {source}
                            {page != null ? ` · página ${page}` : ''}
                        </div>
                        {excerpt.match_confidence && (
                            <div>
                                <strong style={{ color: '#cbd5e1' }}>Confianza del ancla:</strong>{' '}
                                {excerpt.match_confidence}
                            </div>
                        )}
                    </div>

                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                            marginBottom: '6px',
                            fontSize: '11px',
                            fontWeight: 800,
                            color: '#7dd3fc',
                            textTransform: 'uppercase',
                            letterSpacing: '0.04em',
                        }}
                    >
                        <FileText size={12} />
                        Texto literal (índice de sesión)
                    </div>
                    <blockquote
                        style={{
                            margin: 0,
                            padding: '10px 12px',
                            borderLeft: '3px solid rgba(56,189,248,0.6)',
                            background: 'rgba(0,0,0,0.25)',
                            borderRadius: '0 8px 8px 0',
                            whiteSpace: 'pre-wrap',
                            fontStyle: 'normal',
                        }}
                    >
                        {paragraph}
                    </blockquote>

                    {fullPage && (
                        <div style={{ marginTop: '10px' }}>
                            <button
                                type="button"
                                onClick={() => setShowFullPage((v) => !v)}
                                style={{
                                    background: 'transparent',
                                    border: '1px solid rgba(255,255,255,0.15)',
                                    color: '#94a3b8',
                                    fontSize: '11px',
                                    padding: '4px 10px',
                                    borderRadius: '6px',
                                    cursor: 'pointer',
                                }}
                            >
                                {showFullPage ? 'Ocultar página completa' : 'Ver página completa indexada'}
                            </button>
                            {showFullPage && (
                                <div
                                    style={{
                                        marginTop: '8px',
                                        maxHeight: '220px',
                                        overflowY: 'auto',
                                        padding: '10px',
                                        background: 'rgba(0,0,0,0.2)',
                                        borderRadius: '8px',
                                        fontSize: '12px',
                                        whiteSpace: 'pre-wrap',
                                        color: '#cbd5e1',
                                    }}
                                >
                                    {fullPage}
                                </div>
                            )}
                        </div>
                    )}

                    {excerpt.provenance_ui?.source && (
                        <div style={{ marginTop: '8px', fontSize: '10px', color: '#64748b' }}>
                            Fuente: {excerpt.provenance_ui.source}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
