import React, { useState, useEffect } from 'react';
import { 
    Folder, FileText, Download, Briefcase, 
    CheckSquare, Square, Archive, ChevronRight,
    Loader2, ExternalLink, Info, AlertTriangle, Trash2
} from 'lucide-react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';

/** Valores UI cuando el backend no envía dato (no son extractos oficiales de las bases). */
const FALLBACK_LUGAR_TEXTO = 'Ver Guía PDF';
const FALLBACK_HORARIO_ENTREGA = '09:00 - 15:00';
const FALLBACK_LIMITE_TEXTO = 'Consultar bases';

function IndicativoEtiqueta() {
    return (
        <span style={{ fontSize: '9px', fontWeight: 600, opacity: 0.75, marginLeft: '6px', color: '#94a3b8' }}>
            (indicativo — confirmar en bases)
        </span>
    );
}

/** Panel de entrega: las rutas de descarga usan session_id para alinear con /data/outputs en el backend. */
const DeliveryPanel = ({ sessionId, sessionName, results }) => {
    const [structure, setStructure] = useState([]);
    const [loading, setLoading] = useState(true);
    const [downloading, setDownloading] = useState(null);
    /** Backend: carpeta /data/outputs resuelta con al menos un archivo (habilita ZIP aunque el árbol filtrado esté vacío). */
    const [zipAvailable, setZipAvailable] = useState(false);

    // PUENTE DE DATOS: Si no hay resultados de generación, usamos los de auditoría (causales)
    const rawChecklist = results?.formats?.checklists?.sobre || 
                       (results?.causales ? results.causales.filter(c => !c.isRisk).map(c => typeof c.texto === 'object' ? (c.texto.descripcion || c.texto.nombre) : c.texto) : []);
    
    const checklistSobre = rawChecklist;
    const checklistCotejo = results?.formats?.checklists?.cotejo || 
                          (results?.causales ? results.causales.filter(c => c.isRisk).map(c => typeof c.texto === 'object' ? (c.texto.descripcion || c.texto.nombre) : c.texto) : []);

    const [selectedFile, setSelectedFile] = useState(null);
    const [hoveredProvKey, setHoveredProvKey] = useState(null);

    const fetchStructure = async () => {
        if (!sessionId || sessionId === 'null') {
            setZipAvailable(false);
            setLoading(false);
            return;
        }

        try {
            const res = await axios.get(`${API_BASE}/downloads/list`, { params: { session_id: sessionId } });
            if (res.data.success) {
                setStructure(res.data.data);
                setZipAvailable(res.data.zip_available === true);
                if (res.data.data.length > 0 && res.data.data[0].files.length > 0) {
                    setSelectedFile(res.data.data[0].files[0]);
                }
            }
        } catch (err) {
            // Un 404 aquí es normal si no se han generado archivos aún: Silenciamos profesionalmente
            if (err.response?.status !== 404) {
                console.error("Error fetching downloads", err);
            }
            setStructure([]);
            setZipAvailable(false);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchStructure();
    }, [sessionId]);

    const handleDownload = async (filePath, fileName, e) => {
        if (e) e.stopPropagation(); // Evitar seleccionar el archivo al hacer click en descargar
        setDownloading(fileName);
        try {
            const response = await axios.get(`${API_BASE}/downloads/file`, {
                params: { path: filePath, session_id: sessionId },
                responseType: 'blob'
            });
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', fileName);
            document.body.appendChild(link);
            link.click();
            link.remove();
        } catch (err) {
            alert("Error al descargar el archivo");
        } finally {
            setDownloading(null);
        }
    };

    const hasDownloadableFiles = structure.some((folder) => Array.isArray(folder.files) && folder.files.length > 0);
    const canDownloadFullZip = hasDownloadableFiles || zipAvailable;

    const handleClearGenerated = async () => {
        if (!sessionId || sessionId === 'null') return;
        const ok = window.confirm(
            '¿Eliminar todo el expediente generado en disco?\n\n'
            + 'Se borran carpetas SOBRE_*, propuestas técnicas/económicas y administrativos generados. '
            + 'NO se borran las bases PDF ni el dictamen de auditoría.\n\n'
            + 'Después pulsa «GENERAR PROPUESTA» para crear un expediente limpio.'
        );
        if (!ok) return;

        setClearing(true);
        try {
            const res = await axios.delete(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/generated-outputs`,
                { data: { confirm: true } },
            );
            if (res.data?.success) {
                setStructure([]);
                setZipAvailable(false);
                setSelectedFile(null);
                if (typeof onExpedienteCleared === 'function') {
                    onExpedienteCleared(res.data);
                }
                alert(res.data.message || 'Expediente generado eliminado.');
            } else {
                alert(res.data?.message || 'No se pudo limpiar el expediente.');
            }
        } catch (err) {
            const msg = err?.response?.data?.detail || err?.message || 'Error al limpiar expediente';
            alert(typeof msg === 'string' ? msg : JSON.stringify(msg));
        } finally {
            setClearing(false);
            setLoading(true);
            await fetchStructure();
        }
    };

    const handleDownloadZip = async () => {
        if (!canDownloadFullZip) {
            alert("Aun no hay expediente generado para esta sesion. Completa la generacion antes de descargar.");
            return;
        }
        setDownloading('ZIP');
        try {
            const response = await axios.get(`${API_BASE}/downloads/zip`, {
                params: { session_id: sessionId },
                responseType: 'blob'
            });
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `Propuesta_${(sessionName || sessionId || 'licitacion').replace(/\s+/g, '_')}.zip`);
            document.body.appendChild(link);
            link.click();
            link.remove();
        } catch (err) {
            if (err?.response?.status === 409) {
                alert("La sesion existe, pero aun no hay expediente generado para descargar.");
            } else {
                alert("Error al descargar el paquete completo");
            }
        } finally {
            setDownloading(null);
        }
    };

    // Extraer datos de los nuevos agentes de Fase 2
    const deliveryData = results?.delivery?.data || {};
    const packagerData = results?.packager?.data?.estructura_sobres || {};
    const economicResumen = results?.economic_writer?.data?.resumen_economico || null;
    const economicItems = results?.economic?.data?.items || results?.economic?.items || [];

    const checklistGeneral = deliveryData.checklist || [];
    const alertasLogistica = deliveryData.alertas || [];

    const lugarValor = deliveryData.direccion_fisica || FALLBACK_LUGAR_TEXTO;
    const horarioValor = deliveryData.horario || FALLBACK_HORARIO_ENTREGA;
    const limiteValor = deliveryData.fecha_limite || FALLBACK_LIMITE_TEXTO;
    const lugarEsFallback = !deliveryData.direccion_fisica;
    const horarioEsFallback = !deliveryData.horario;
    const limiteEsFallback = !deliveryData.fecha_limite;

    return (
        <div className="delivery-panel" style={{ 
            animation: 'fadeIn 0.5s ease-out',
            padding: '24px',
            background: 'rgba(255,255,255,0.02)',
            borderRadius: '20px',
            border: '1px solid var(--border-glass)',
            marginTop: '20px'
        }}>
            {/* Header con Descarga Global */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                <div>
                    <h3 style={{ fontSize: '20px', fontWeight: 800, color: 'var(--primary)', marginBottom: '4px' }}>Logística y Expedientes</h3>
                    <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Expediente completo organizado por sobres oficiales.</p>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', justifyContent: 'flex-end' }}>
                    <button
                        type="button"
                        onClick={handleClearGenerated}
                        disabled={clearing || downloading === 'ZIP' || !hasGeneratedOnDisk}
                        title="Borra Word/ZIP y sobres generados para volver a empaquetar desde cero"
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            padding: '10px 16px',
                            borderRadius: '12px',
                            background: 'rgba(239, 68, 68, 0.12)',
                            color: '#fca5a5',
                            border: '1px solid rgba(239, 68, 68, 0.35)',
                            fontWeight: 700,
                            fontSize: '11px',
                            cursor: clearing ? 'wait' : 'pointer',
                            opacity: clearing ? 0.7 : 1,
                        }}
                    >
                        {clearing ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                        {clearing ? 'LIMPIANDO...' : 'LIMPIAR EXPEDIENTE GENERADO'}
                    </button>
                    <button 
                        type="button"
                        onClick={handleDownloadZip}
                        disabled={downloading === 'ZIP' || !canDownloadFullZip}
                        title={!canDownloadFullZip ? 'No hay expediente generado aun para descargar' : 'Descargar expediente completo'}
                        style={{ 
                            display: 'flex', alignItems: 'center', gap: '8px',
                            padding: '10px 20px', borderRadius: '12px', background: 'var(--primary)',
                            color: 'white', border: 'none', fontWeight: 700,
                            cursor: (downloading === 'ZIP' || !canDownloadFullZip) ? 'not-allowed' : 'pointer',
                            opacity: (downloading === 'ZIP' || !canDownloadFullZip) ? 0.65 : 1,
                            boxShadow: '0 4px 15px var(--primary-glow)'
                        }}
                    >
                        {downloading === 'ZIP' ? <Loader2 size={16} className="animate-spin" /> : <Archive size={16} />}
                        {downloading === 'ZIP' ? 'EMPAQUETANDO...' : 'DESCARGAR EXPEDIENTE COMPLETO'}
                    </button>
                </div>
            </div>

            {/* ALERTAS DE LOGÍSTICA (NUEVO) */}
            {alertasLogistica.length > 0 && (
                <div style={{ background: 'rgba(255, 77, 77, 0.1)', border: '1px solid rgba(255, 77, 77, 0.2)', borderRadius: '15px', padding: '15px', marginBottom: '25px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {alertasLogistica.map((a, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '12px', color: '#ff8080' }}>
                            <AlertTriangle size={14} />
                            <span style={{ fontWeight: 600 }}>{a}</span>
                        </div>
                    ))}
                </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 3fr) minmax(0, 2fr)', gap: '24px' }}>
                {/* Árbol de Carpetas y Sobres */}
                <div className="folder-tree">
                    <h4 style={{ fontSize: '11px', fontWeight: 900, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '16px', letterSpacing: '1px' }}>Carpeta de Participación</h4>
                    
                    {loading ? (
                        <div style={{ padding: '40px', textAlign: 'center' }}>
                            <Loader2 size={32} className="animate-spin" color="var(--primary)" />
                        </div>
                    ) : structure.length === 0 ? (
                        <p style={{ fontSize: '13px', color: 'var(--text-muted)', textAlign: 'center', padding: '20px' }}>
                            {zipAvailable
                                ? 'El árbol no muestra documentos filtrados (.docx / .pdf / .xlsx), pero hay salida en disco: usa «DESCARGAR EXPEDIENTE COMPLETO» arriba.'
                                : 'No se han encontrado archivos. Ejecuta la Generación de Documentos.'}
                        </p>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            {structure.map((folder, idx) => {
                                const isSobre = folder.folder.includes("SOBRE");
                                return (
                                    <div key={idx} style={{ 
                                        background: isSobre ? 'rgba(59, 130, 246, 0.05)' : 'rgba(255,255,255,0.03)', 
                                        borderRadius: '12px', 
                                        padding: '16px',
                                        border: isSobre ? '1px solid rgba(59, 130, 246, 0.2)' : '1px solid rgba(255,255,255,0.05)',
                                        transition: 'all 0.3s ease'
                                    }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                                            {isSobre ? <Archive size={18} color="var(--primary)" /> : <Folder size={18} color="rgba(255,255,255,0.3)" />}
                                            <span style={{ fontSize: '14px', fontWeight: 800, color: isSobre ? 'white' : 'var(--text-muted)' }}>{folder.folder}</span>
                                        </div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', paddingLeft: '8px' }}>
                                            {folder.files.map((file, fidx) => (
                                                <div 
                                                    key={fidx} 
                                                    onClick={() => setSelectedFile(file)}
                                                    style={{ 
                                                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                                        padding: '8px 12px', 
                                                        background: selectedFile?.name === file.name ? 'rgba(59, 130, 246, 0.15)' : 'rgba(0,0,0,0.2)', 
                                                        borderRadius: '8px',
                                                        border: selectedFile?.name === file.name ? '1px solid var(--primary)' : '1px solid transparent',
                                                        cursor: 'pointer',
                                                        transition: 'all 0.2s ease'
                                                    }}
                                                >
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                        <FileText size={14} color={file.name.includes('.pdf') ? "#ff4d4d" : (file.name.includes('.xlsx') ? "#2ecc71" : "var(--primary)")} />
                                                        <span style={{ 
                                                            fontSize: '12px', 
                                                            color: selectedFile?.name === file.name ? 'white' : 'var(--text-secondary)',
                                                            fontWeight: selectedFile?.name === file.name ? '700' : '400'
                                                        }}>
                                                            {file.name}
                                                        </span>
                                                    </div>
                                                    <button 
                                                        onClick={(e) => handleDownload(file.path, file.name, e)}
                                                        disabled={downloading === file.name}
                                                        style={{ background: 'none', border: 'none', color: 'var(--primary)', cursor: 'pointer' }}
                                                    >
                                                        {downloading === file.name ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                                                    </button>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                {/* DETALLE Y LOGÍSTICA */}
                <div className="file-details">
                    <h4 style={{ fontSize: '11px', fontWeight: 900, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '16px', letterSpacing: '1px' }}>Modalidad de Entrega</h4>
                    
                    {/* TARJETA DE LOGÍSTICA (NUEVO) */}
                    <div style={{ background: 'linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(0,0,0,0.4))', padding: '20px', borderRadius: '16px', border: '1px solid rgba(59, 130, 246, 0.2)', marginBottom: '24px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '15px' }}>
                            <Briefcase size={20} color="var(--primary)" />
                            <span style={{ fontSize: '14px', fontWeight: 800 }}>{deliveryData.tipo || 'Detectando modalidad...'}</span>
                        </div>
                        
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '12px' }}>
                            {deliveryData.tipo === 'ELECTRONICA' ? (
                                <>
                                    <div style={{ color: 'var(--text-secondary)' }}><b>Portal:</b> {deliveryData.portal_nombre}</div>
                                    <a href={deliveryData.portal_url} target="_blank" style={{ color: 'var(--primary)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '5px' }}>
                                        Ir al Portal <ExternalLink size={12} />
                                    </a>
                                </>
                            ) : (
                                <>
                                    <div style={{ color: 'var(--text-secondary)' }}>
                                        <b>Lugar:</b> {lugarValor}
                                        {lugarEsFallback ? <IndicativoEtiqueta /> : null}
                                    </div>
                                    <div style={{ color: 'var(--text-secondary)' }}>
                                        <b>Horario:</b> {horarioValor}
                                        {horarioEsFallback ? <IndicativoEtiqueta /> : null}
                                    </div>
                                </>
                            )}
                            <div style={{ color: '#ffb366', fontWeight: 700 }}>
                                ⚠️ Límite: {limiteValor}
                                {limiteEsFallback ? <IndicativoEtiqueta /> : null}
                            </div>
                        </div>
                        <p style={{ margin: '12px 0 0 0', fontSize: '10px', lineHeight: 1.45, color: 'rgba(148,163,184,0.95)' }}>
                            Los datos de modalidad mostrados aquí no sustituyen la convocatoria oficial: verifica siempre en bases y documentos emitidos por el convocante.
                        </p>
                    </div>

                    {/* Resumen Económico (SI EXISTE) */}
                    {economicResumen && (
                        <div style={{ background: 'rgba(46, 204, 113, 0.05)', padding: '15px', borderRadius: '12px', border: '1px solid rgba(46, 204, 113, 0.2)', marginBottom: '24px' }}>
                             <h5 style={{ fontSize: '10px', color: '#2ecc71', marginBottom: '8px', fontWeight: 900 }}>RESUMEN ECONÓMICO</h5>
                             <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px', fontWeight: 800 }}>
                                 <span>TOTAL PROPUESTA:</span>
                                 <span>${economicResumen.total?.toLocaleString('es-MX', {minimumFractionDigits: 2})} {economicResumen.moneda}</span>
                             </div>
                        </div>
                    )}
                    {Array.isArray(economicItems) && economicItems.length > 0 && (
                        <div style={{ background: 'rgba(56, 189, 248, 0.06)', padding: '15px', borderRadius: '12px', border: '1px solid rgba(56, 189, 248, 0.22)', marginBottom: '24px' }}>
                            <h5 style={{ fontSize: '10px', color: '#7dd3fc', marginBottom: '10px', fontWeight: 900 }}>
                                DETALLE DE PRECIOS Y FUENTE
                            </h5>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '240px', overflowY: 'auto', paddingRight: '4px' }}>
                                {economicItems.slice(0, 25).map((it, idx) => {
                                    const pu = Number(it?.precio_unitario || 0);
                                    const prov = it?.provenance_ui || {};
                                    const sourceLabel = prov?.source_label || 'Catálogo/Inferencia';
                                    const sourceIcon = prov?.source_icon || '⚪';
                                    const detail = prov?.detail || 'Sin detalle de procedencia.';
                                    const rowKey = `${it?.concepto_id || it?.concepto || 'item'}-${idx}`;
                                    const isHovered = hoveredProvKey === rowKey;
                                    const isChat = prov?.source_key === 'chat';
                                    return (
                                        <div
                                            key={rowKey}
                                            style={{
                                                display: 'grid',
                                                gridTemplateColumns: '1fr auto',
                                                gap: '10px',
                                                alignItems: 'center',
                                                background: 'rgba(0,0,0,0.22)',
                                                border: '1px solid rgba(255,255,255,0.07)',
                                                borderRadius: '10px',
                                                padding: '8px 10px',
                                            }}
                                        >
                                            <div style={{ minWidth: 0 }}>
                                                <div style={{ fontSize: '12px', color: '#e5e7eb', fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                                    {it?.concepto || `Concepto ${idx + 1}`}
                                                </div>
                                                <div
                                                    style={{
                                                        fontSize: '11px',
                                                        color: '#9ca3af',
                                                        marginTop: '2px',
                                                        transition: 'all 220ms ease',
                                                        transform: isChat ? (isHovered ? 'scale(1.02)' : 'scale(1)') : 'none',
                                                        textShadow: isChat ? (isHovered ? '0 0 8px rgba(34,197,94,0.55)' : '0 0 0 transparent') : 'none',
                                                    }}
                                                >
                                                    ${pu.toLocaleString('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                                </div>
                                            </div>
                                            <div
                                                style={{
                                                    position: 'relative',
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    gap: '6px',
                                                    borderRadius: '999px',
                                                    border: isHovered ? '1px solid rgba(125,211,252,0.7)' : '1px solid rgba(255,255,255,0.18)',
                                                    padding: '4px 8px',
                                                    fontSize: '10px',
                                                    color: '#cbd5e1',
                                                    background: isHovered ? 'rgba(125,211,252,0.12)' : 'rgba(255,255,255,0.04)',
                                                    whiteSpace: 'nowrap',
                                                    transition: 'all 220ms ease',
                                                    boxShadow: isHovered ? '0 0 10px rgba(125,211,252,0.22)' : 'none',
                                                }}
                                                onMouseEnter={() => setHoveredProvKey(rowKey)}
                                                onMouseLeave={() => setHoveredProvKey(null)}
                                            >
                                                <span>{sourceIcon}</span>
                                                <span>{sourceLabel}</span>
                                                <Info size={11} />
                                                {isHovered && (
                                                    <div
                                                        style={{
                                                            position: 'absolute',
                                                            top: 'calc(100% + 8px)',
                                                            right: 0,
                                                            width: 'min(320px, 60vw)',
                                                            zIndex: 15,
                                                            background: 'rgba(15, 23, 42, 0.96)',
                                                            border: '1px solid rgba(125,211,252,0.35)',
                                                            borderRadius: '10px',
                                                            padding: '8px 10px',
                                                            boxShadow: '0 10px 30px rgba(0,0,0,0.45)',
                                                            whiteSpace: 'normal',
                                                            textAlign: 'left',
                                                            lineHeight: 1.45,
                                                            color: '#e2e8f0',
                                                        }}
                                                    >
                                                        {detail}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    <h4 style={{ fontSize: '11px', fontWeight: 900, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '16px', letterSpacing: '1px' }}>Checklist de Verificación Final</h4>
                    
                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '20px', borderRadius: '16px', border: '1px solid rgba(255,255,255,0.05)' }}>
                        <ul style={{ listStyle: 'none', padding: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            {checklistGeneral.length > 0 ? checklistGeneral.map((item, idx) => (
                                <li key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                                    <Square size={14} color="var(--primary)" style={{ marginTop: '2px', opacity: 0.5 }} />
                                    <span>{item.check}</span>
                                </li>
                            )) : (
                                <li style={{ fontSize: '12px', fontStyle: 'italic', opacity: 0.5 }}>Genera los documentos para poblar el checklist.</li>
                            )}
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default DeliveryPanel;
