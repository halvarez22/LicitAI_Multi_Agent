import React, { useCallback, useEffect, useState } from 'react';

import axios from 'axios';

import { Copy, Grid3x3, Loader2, RefreshCw } from 'lucide-react';

import { API_BASE } from '../apiBase.js';

import { buildMatrixExcelTsv } from '../utils/matrixExcelClipboard.js';



const cardStyle = {

    border: '1px solid rgba(34, 197, 94, 0.35)',

    background: 'rgba(15, 23, 42, 0.75)',

    borderRadius: '12px',

    padding: '12px 14px',

    display: 'flex',

    flexDirection: 'column',

    gap: '10px',

};



const actionBtnStyle = {

    fontSize: '10px',

    padding: '6px 10px',

    borderRadius: '8px',

    border: '1px solid rgba(34, 197, 94, 0.35)',

    background: 'rgba(34, 197, 94, 0.12)',

    color: '#86efac',

    cursor: 'pointer',

    display: 'inline-flex',

    alignItems: 'center',

    gap: '6px',

};



/**

 * Matriz orientadora de captura económica (capture_matrix_blocks en sesión).

 */

export default function CaptureMatrixPanel({ sessionId }) {

    const [blocks, setBlocks] = useState([]);

    const [excelTsv, setExcelTsv] = useState('');

    const [loading, setLoading] = useState(false);

    const [err, setErr] = useState(null);

    const [copied, setCopied] = useState(false);

    const [copyErr, setCopyErr] = useState(null);
    const [captureStatus, setCaptureStatus] = useState(null);
    const [captureSummary, setCaptureSummary] = useState('');

    const load = useCallback(async () => {

        if (!sessionId) {

            setBlocks([]);

            setExcelTsv('');

            return;

        }

        setLoading(true);

        setErr(null);

        try {

            const res = await axios.get(

                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/capture-matrix-blocks`

            );

            const body = res.data;

            if (body?.success && Array.isArray(body?.data?.blocks)) {

                const loaded = body.data.blocks;

                setBlocks(loaded);

                const fromApi = String(body.data.excel_clipboard_tsv || '').trim();

                setExcelTsv(fromApi || buildMatrixExcelTsv(loaded));
                setCaptureStatus(body.data.capture_status || null);
                setCaptureSummary(String(body.data.capture_summary || '').trim());
            } else {
                setBlocks([]);
                setExcelTsv('');
                setCaptureStatus(null);
                setCaptureSummary('');
            }

        } catch (e) {

            setErr(e?.response?.data?.detail || e.message || 'Error al cargar matriz');

            setBlocks([]);

            setExcelTsv('');

        } finally {

            setLoading(false);

        }

    }, [sessionId]);



    useEffect(() => {

        load();

    }, [load]);



    const copyForExcel = async () => {

        const txt = excelTsv || buildMatrixExcelTsv(blocks);

        if (!txt) {

            setCopyErr('No hay filas para copiar.');

            return;

        }

        setCopyErr(null);

        try {

            await navigator.clipboard.writeText(txt);

            setCopied(true);

            setTimeout(() => setCopied(false), 2200);

        } catch (_) {

            setCopyErr('No se pudo copiar. Selecciona el texto del cuadro inferior y copia manualmente (Ctrl+C).');

        }

    };



    if (!sessionId || (!loading && blocks.length === 0 && !err)) {

        return null;

    }



    const rowCount = blocks.reduce((n, b) => n + (b.matrix_rows || []).length, 0);



    return (

        <div style={cardStyle}>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 700, fontSize: 12 }}>

                    <Grid3x3 size={16} />

                    Matriz de precios (anexo)

                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>

                    <button

                        type="button"

                        onClick={copyForExcel}

                        disabled={loading || rowCount === 0}

                        title="Copia todas las filas al portapapeles para pegar en Excel"

                        style={{

                            ...actionBtnStyle,

                            opacity: loading || rowCount === 0 ? 0.5 : 1,

                            color: copied ? '#4ade80' : actionBtnStyle.color,

                        }}

                    >

                        <Copy size={13} />

                        {copied ? '¡Copiado! Pega en Excel' : 'Copiar para Excel'}

                    </button>

                    <button type="button" onClick={load} disabled={loading} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>

                        {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}

                    </button>

                </div>

            </div>

            <div style={{ fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.45 }}>
                {captureSummary ? (
                    <span style={{ color: captureStatus?.capture_complete ? '#86efac' : undefined }}>
                        {captureSummary.replace(/\*\*/g, '')}
                    </span>
                ) : captureStatus?.capture_complete ? (
                    <span style={{ color: '#86efac' }}>
                        Cotización lista: <strong>{captureStatus.filled}</strong> /{' '}
                        <strong>{captureStatus.total}</strong> precios. Usa <strong>Generar propuesta</strong>.
                    </span>
                ) : rowCount > 0 ? (
                    <>
                        <strong>{rowCount}</strong> concepto(s). Completa precios en Excel y usa{' '}
                        <strong>📎 Adjuntar cotización</strong> en el chat. Opcional:{' '}
                        <strong>Copiar para Excel</strong>.
                    </>
                ) : (
                    'Cargando conceptos…'
                )}
            </div>

            {copyErr && <div style={{ fontSize: 10, color: '#fca5a5' }}>{copyErr}</div>}

            {err && <div style={{ fontSize: 11, color: '#fca5a5' }}>{err}</div>}

            {blocks.map((block, bi) => (

                <div key={bi} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>

                    <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>

                        {block.intro_message || block.source_file}

                    </div>

                    <div style={{ overflowX: 'auto' }}>

                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>

                            <thead>

                                <tr>

                                    {(block.matrix_columns || []).map((col) => (

                                        <th

                                            key={col.key}

                                            style={{

                                                textAlign: 'left',

                                                padding: '6px 8px',

                                                borderBottom: '1px solid rgba(255,255,255,0.12)',

                                                color: '#86efac',

                                            }}

                                        >

                                            {col.title || col.key}

                                        </th>

                                    ))}

                                </tr>

                            </thead>

                            <tbody>

                                {(block.matrix_rows || []).slice(0, 24).map((row, ri) => (

                                    <tr key={ri}>

                                        {(block.matrix_columns || []).map((col) => (

                                            <td

                                                key={col.key}

                                                style={{

                                                    padding: '5px 8px',

                                                    borderBottom: '1px solid rgba(255,255,255,0.06)',

                                                }}

                                            >

                                                {col.key === 'label' && row.provenance_ui?.badge ? (
                                                    <span
                                                        title={[
                                                            row.provenance_ui.source_file,
                                                            row.provenance_ui.sheet,
                                                            row.provenance_ui.row != null
                                                                ? `fila ${row.provenance_ui.row}`
                                                                : '',
                                                        ]
                                                            .filter(Boolean)
                                                            .join(' · ')}
                                                        style={{
                                                            marginRight: 6,
                                                            fontSize: 9,
                                                            padding: '1px 5px',
                                                            borderRadius: 4,
                                                            background: row.provenance_ui.filled
                                                                ? 'rgba(34,197,94,0.2)'
                                                                : 'rgba(148,163,184,0.15)',
                                                            color: row.provenance_ui.filled ? '#86efac' : '#94a3b8',
                                                        }}
                                                    >
                                                        {row.provenance_ui.badge}
                                                    </span>
                                                ) : null}
                                                {row[col.key] ?? '—'}

                                            </td>

                                        ))}

                                    </tr>

                                ))}

                            </tbody>

                        </table>

                    </div>

                    {(block.matrix_rows || []).length > 24 && (

                        <div style={{ fontSize: 10, opacity: 0.6 }}>

                            +{(block.matrix_rows || []).length - 24} filas — usa Copiar para Excel para verlas todas

                        </div>

                    )}

                </div>

            ))}

        </div>

    );

}

