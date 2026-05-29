import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { LayoutList, Loader2, RefreshCw, Save, AlertCircle } from 'lucide-react';
import { API_BASE } from '../apiBase.js';

const cardStyle = {
    border: '1px solid rgba(56, 189, 248, 0.35)',
    background: 'rgba(15, 23, 42, 0.75)',
    borderRadius: '12px',
    padding: '12px 14px',
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
};

const btnPrimary = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '8px',
    padding: '8px 14px',
    borderRadius: '10px',
    border: 'none',
    background: 'var(--primary)',
    color: '#fff',
    fontSize: '12px',
    fontWeight: 700,
    cursor: 'pointer',
};

const btnGhost = {
    ...btnPrimary,
    background: 'rgba(255,255,255,0.08)',
    border: '1px solid rgba(255,255,255,0.15)',
    color: 'var(--text-muted)',
};

/**
 * Tabla de resolución masiva de precios (Hito B) contra /interaction-blocks/preview y /mass-save.
 * @param {{ sessionId: string, companyId: string, onAfterSave?: () => Promise<void> }} props
 */
export default function BlockResolutionPanel({ sessionId, companyId, onAfterSave }) {
    const [block, setBlock] = useState(null);
    const [values, setValues] = useState({});
    const [info, setInfo] = useState(null);
    const [err, setErr] = useState(null);
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);

    const resetForm = useCallback((nextBlock) => {
        setBlock(nextBlock);
        const init = {};
        (nextBlock?.items || []).forEach((it) => {
            const sid = String(it.suggested_value ?? '');
            init[it.item_id] = sid !== '' && sid !== 'null' ? String(it.suggested_value) : '';
        });
        setValues(init);
    }, []);

    const loadPreview = useCallback(async () => {
        if (!sessionId || !companyId) {
            setBlock(null);
            setInfo(null);
            setErr(null);
            return;
        }
        setLoading(true);
        setErr(null);
        setInfo(null);
        try {
            const res = await axios.post(`${API_BASE}/interaction-blocks/preview`, undefined, {
                params: { session_id: sessionId, company_id: companyId },
            });
            const body = res.data;
            if (body?.success && body?.data?.capture_complete) {
                const cap = body.data.capture_status || {};
                setBlock(null);
                setInfo(
                    body.message ||
                        `Cotización registrada (${cap.filled ?? '?'}/${cap.total ?? '?'} precios). Usa Generar propuesta en el panel.`
                );
                setErr(null);
                return;
            }
            if (!body?.success || !body?.data) {
                const msg = body?.message || 'No hay bloque disponible en este momento.';
                setBlock(null);
                setInfo(msg);
                return;
            }
            resetForm(body.data);
            setInfo(null);
        } catch (e) {
            const msg = e?.response?.data?.detail || e?.message || 'Error al cargar el bloque.';
            setBlock(null);
            setErr(String(msg));
        } finally {
            setLoading(false);
        }
    }, [sessionId, companyId, resetForm]);

    useEffect(() => {
        loadPreview();
    }, [loadPreview]);

    const handleChange = (itemId, v) => {
        setValues((prev) => ({ ...prev, [itemId]: v }));
    };

    const handleSave = async () => {
        if (!block?.block_id || !sessionId || !companyId) return;
        const rows = (block.items || []).map((it) => ({
            item_id: it.item_id,
            value: values[it.item_id] ?? '',
        }));
        const correlationId =
            typeof crypto !== 'undefined' && crypto.randomUUID
                ? crypto.randomUUID()
                : `blk-${Date.now()}`;
        setSaving(true);
        setErr(null);
        try {
            const res = await axios.post(`${API_BASE}/interaction-blocks/mass-save`, {
                session_id: sessionId,
                company_id: companyId,
                block_id: block.block_id,
                correlation_id: correlationId,
                rows,
            });
            const body = res.data;
            if (!body?.success) {
                setErr(body?.message || 'El servidor no aceptó el guardado.');
                return;
            }
            const data = body.data || {};
            const failed = data.failed_items || [];
            if (failed.length > 0) {
                setErr(
                    `${failed.length} fila(s) con error. Revisa los valores numéricos. Detalle: ${failed
                        .map((f) => `${f.item_id}: ${f.error}`)
                        .join(' · ')}`
                );
            } else {
                setErr(null);
            }
            if (typeof onAfterSave === 'function') {
                await onAfterSave();
            }
            await loadPreview();
        } catch (e) {
            const msg = e?.response?.data?.message || e?.response?.data?.detail || e?.message || 'Error de red.';
            setErr(String(msg));
        } finally {
            setSaving(false);
        }
    };

    if (!sessionId || !companyId) {
        return null;
    }

    return (
        <div style={cardStyle}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                    <LayoutList size={18} color="var(--primary)" />
                    <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: '12px', fontWeight: 800, color: '#e0f2fe' }}>Resolución por bloque</div>
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>
                            Vista masiva de precios (opcional si ya importaste Excel en el chat).
                        </div>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={() => loadPreview()}
                    disabled={loading}
                    title="Recargar vista del bloque"
                    style={{ ...btnGhost, padding: '6px 10px' }}
                >
                    <RefreshCw size={14} className={loading ? 'spin' : ''} />
                </button>
            </div>

            {info && !block && (
                <div
                    style={{
                        fontSize: '11px',
                        color: info.includes('registrada') || info.includes('lista') ? '#86efac' : 'var(--text-muted)',
                        lineHeight: 1.45,
                    }}
                >
                    {info}
                </div>
            )}
            {err && (
                <div
                    style={{
                        fontSize: '11px',
                        color: '#fecaca',
                        display: 'flex',
                        gap: '8px',
                        alignItems: 'flex-start',
                        lineHeight: 1.4,
                    }}
                >
                    <AlertCircle size={14} style={{ flexShrink: 0, marginTop: '2px' }} />
                    <span>{err}</span>
                </div>
            )}

            {block && (
                <>
                    <div
                        style={{
                            fontSize: '10px',
                            color: 'var(--text-muted)',
                            borderLeft: '3px solid rgba(56,189,248,0.6)',
                            paddingLeft: '8px',
                        }}
                    >
                        <div style={{ fontWeight: 700, color: '#bae6fd' }}>{block.anchor?.title || 'Anclaje'}</div>
                        {block.anchor?.page != null && (
                            <div>Página en bases (si consta): {block.anchor.page}</div>
                        )}
                        <div style={{ marginTop: '4px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                            {block.anchor?.legal_reference
                                ? String(block.anchor.legal_reference).slice(0, 420)
                                : 'Sin referencia literal en metadatos.'}
                            {block.anchor?.legal_reference && String(block.anchor.legal_reference).length > 420
                                ? '…'
                                : ''}
                        </div>
                        <div style={{ marginTop: '6px', fontSize: '9px', opacity: 0.85 }}>
                            Procedencia UI: {block.anchor?.provenance || '—'} · {block.metadata?.total_items || 0}{' '}
                            partidas
                        </div>
                    </div>

                    <div style={{ overflowX: 'auto', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.08)' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
                            <thead>
                                <tr style={{ background: 'rgba(255,255,255,0.04)', textAlign: 'left' }}>
                                    <th style={{ padding: '8px', fontWeight: 700 }}>Concepto</th>
                                    <th style={{ padding: '8px', width: '48px' }}>U.</th>
                                    <th style={{ padding: '8px', width: '72px' }}>Sug.</th>
                                    <th style={{ padding: '8px', minWidth: '100px' }}>Precio</th>
                                </tr>
                            </thead>
                            <tbody>
                                {(block.items || []).map((it) => (
                                    <tr key={it.item_id} style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                                        <td style={{ padding: '8px', verticalAlign: 'middle' }}>{it.label}</td>
                                        <td style={{ padding: '8px', color: 'var(--text-muted)' }}>{it.unit}</td>
                                        <td style={{ padding: '8px', color: 'var(--text-muted)' }}>
                                            {it.suggested_value != null ? it.suggested_value : '—'}
                                        </td>
                                        <td style={{ padding: '6px' }}>
                                            <input
                                                type="text"
                                                inputMode="decimal"
                                                value={values[it.item_id] ?? ''}
                                                onChange={(e) => handleChange(it.item_id, e.target.value)}
                                                placeholder={it.example || '0'}
                                                style={{
                                                    width: '100%',
                                                    boxSizing: 'border-box',
                                                    background: 'rgba(0,0,0,0.25)',
                                                    border: '1px solid rgba(255,255,255,0.12)',
                                                    borderRadius: '6px',
                                                    padding: '6px 8px',
                                                    color: '#fff',
                                                    fontSize: '11px',
                                                }}
                                            />
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    <button type="button" onClick={handleSave} disabled={saving} style={{ ...btnPrimary, opacity: saving ? 0.7 : 1 }}>
                        {saving ? <Loader2 size={14} className="spin" /> : <Save size={14} />}
                        Guardar bloque en catálogo
                    </button>
                </>
            )}

            {loading && !block && (
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <Loader2 size={14} className="spin" />
                    Cargando bloque…
                </div>
            )}
        </div>
    );
}
