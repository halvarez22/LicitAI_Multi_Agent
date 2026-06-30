import React from 'react';
import { AlertTriangle, CheckCircle2, CalendarClock } from 'lucide-react';
import { formatFechaDisplay } from '../utils/criticalDatesDisplay.js';

/** @param {Record<string, unknown>|undefined|null} prov */
function hitoProvenanceLabel(prov) {
    if (!prov || typeof prov !== 'object') return null;
    if (prov.anchor_kind === 'indexed' && prov.page != null) {
        return `Cita en bases · pág. ${prov.page}`;
    }
    if (prov.anchor_kind === 'checklist_fallback' || prov.badge === 'checklist_calendar') {
        return 'Calendario del expediente (Fechas críticas)';
    }
    return null;
}

/**
 * Lista legible de hitos del procedimiento (fechas críticas).
 * @param {object} props
 * @param {Array} props.hitos
 * @param {boolean} [props.compact]
 * @param {(h: object) => void} [props.onAskAboutHito]
 * @param {(hitoId: string, estado: string, evidencia?: string|null) => void} [props.onMarkHito]
 * @param {Record<string, string>} [props.evidenciaDraft]
 * @param {(id: string, value: string) => void} [props.onEvidenciaDraftChange]
 */
export default function CriticalDatesList({
    hitos = [],
    compact = false,
    onAskAboutHito,
    onMarkHito,
    evidenciaDraft = {},
    onEvidenciaDraftChange,
}) {
    if (!hitos.length) {
        return (
            <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '8px 0 0' }}>
                No hay fechas críticas cargadas. Pulsa «Actualizar análisis» o «Actualizar calendario».
            </p>
        );
    }

    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'column',
                gap: compact ? '6px' : '8px',
                maxHeight: compact ? '280px' : '420px',
                overflowY: 'auto',
            }}
        >
            {hitos.map((h) => {
                const fecha = formatFechaDisplay(h.fecha_texto_raw);
                const provLabel = hitoProvenanceLabel(h.provenance_ui);
                const literal = String(h.bases_literal || '').trim();
                const vencido = h.estado === 'vencido';
                const hecho = h.estado === 'completado';
                return (
                    <div
                        key={h.id}
                        style={{
                            display: 'grid',
                            gridTemplateColumns: onMarkHito ? '1fr auto' : '1fr',
                            gap: '8px',
                            alignItems: 'start',
                            padding: compact ? '8px 10px' : '10px 12px',
                            borderRadius: '10px',
                            background: 'rgba(255,255,255,0.03)',
                            border: vencido
                                ? '1px solid rgba(239,68,68,0.35)'
                                : '1px solid rgba(255,255,255,0.08)',
                        }}
                    >
                        <div style={{ minWidth: 0 }}>
                            <div
                                style={{
                                    fontSize: compact ? '11px' : '12px',
                                    fontWeight: 700,
                                    color: '#f1f5f9',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '6px',
                                }}
                            >
                                <CalendarClock size={12} color="var(--primary)" />
                                {h.nombre}
                            </div>
                            <div
                                style={{
                                    fontSize: compact ? '11px' : '12px',
                                    color: vencido ? '#f87171' : '#94a3b8',
                                    marginTop: '4px',
                                    fontWeight: 600,
                                }}
                                title={literal || undefined}
                            >
                                {fecha}
                            </div>
                            {literal && literal !== fecha && (
                                <div
                                    style={{
                                        fontSize: '10px',
                                        color: '#64748b',
                                        marginTop: '4px',
                                        lineHeight: 1.35,
                                    }}
                                    title={literal}
                                >
                                    {literal.length > 160 ? `${literal.slice(0, 157).trim()}…` : literal}
                                </div>
                            )}
                            {provLabel && (
                                <div
                                    style={{
                                        fontSize: '9px',
                                        color: '#64748b',
                                        marginTop: '4px',
                                        fontWeight: 700,
                                        letterSpacing: '0.02em',
                                    }}
                                >
                                    {provLabel}
                                </div>
                            )}
                            {vencido && (
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
                                    <AlertTriangle size={11} /> Fecha del calendario ya pasó (referencia en bases)
                                </div>
                            )}
                        </div>
                        {onMarkHito && (
                            <div
                                style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '6px',
                                    minWidth: compact ? '120px' : '140px',
                                }}
                            >
                                {hecho ? (
                                    <span
                                        style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '4px',
                                            fontSize: '10px',
                                            color: '#4ade80',
                                            justifyContent: 'flex-end',
                                        }}
                                    >
                                        <CheckCircle2 size={14} /> Hecho
                                    </span>
                                ) : (
                                    <>
                                        {!compact && (
                                            <input
                                                type="text"
                                                aria-label={`Evidencia ${h.nombre}`}
                                                placeholder="Evidencia (opcional)"
                                                value={evidenciaDraft[h.id] ?? ''}
                                                onChange={(e) =>
                                                    onEvidenciaDraftChange?.(h.id, e.target.value)
                                                }
                                                style={{
                                                    width: '100%',
                                                    fontSize: '10px',
                                                    padding: '6px 8px',
                                                    borderRadius: '8px',
                                                    border: '1px solid rgba(255,255,255,0.12)',
                                                    background: 'rgba(0,0,0,0.35)',
                                                    color: '#e2e8f0',
                                                }}
                                            />
                                        )}
                                        <button
                                            type="button"
                                            onClick={() => onMarkHito(h.id, 'completado')}
                                            style={{
                                                fontSize: '10px',
                                                fontWeight: 700,
                                                padding: '6px 10px',
                                                borderRadius: '8px',
                                                border: '1px solid var(--primary)',
                                                background: 'rgba(0,212,255,0.12)',
                                                color: '#e2e8f0',
                                                cursor: 'pointer',
                                            }}
                                        >
                                            Marcar hecho
                                        </button>
                                    </>
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
                                            background: 'transparent',
                                            color: 'var(--text-muted)',
                                            cursor: 'pointer',
                                        }}
                                    >
                                        Preguntar en chat
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
