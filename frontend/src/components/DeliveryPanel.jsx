import React, { useState, useEffect } from 'react';
import { 
    Folder, FileText, Download, Briefcase, 
    CheckSquare, Square, Archive, ChevronRight,
    Loader2, ExternalLink, Info, AlertTriangle
} from 'lucide-react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';

/** Panel de entrega: las rutas de descarga usan session_id para alinear con /data/outputs en el backend. */
const DeliveryPanel = ({ sessionId, sessionName, results }) => {
    const [structure, setStructure] = useState([]);
    const [loading, setLoading] = useState(true);
    const [downloading, setDownloading] = useState(null);

    // PUENTE DE DATOS: Si no hay resultados de generación, usamos los de auditoría (causales)
    const rawChecklist = results?.formats?.checklists?.sobre || 
                       (results?.causales ? results.causales.filter(c => !c.isRisk).map(c => typeof c.texto === 'object' ? (c.texto.descripcion || c.texto.nombre) : c.texto) : []);
    
    const checklistSobre = rawChecklist;
    const checklistCotejo = results?.formats?.checklists?.cotejo || 
                          (results?.causales ? results.causales.filter(c => c.isRisk).map(c => typeof c.texto === 'object' ? (c.texto.descripcion || c.texto.nombre) : c.texto) : []);

    const [selectedFile, setSelectedFile] = useState(null);

    const fetchStructure = async () => {
        if (!sessionId || sessionId === 'null') {
            setLoading(false);
            return;
        }

        try {
            const res = await axios.get(`${API_BASE}/downloads/list`, { params: { session_id: sessionId } });
            if (res.data.success) {
                setStructure(res.data.data);
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

    const handleDownloadZip = async () => {
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
            alert("Error al descargar el paquete completo");
        } finally {
            setDownloading(null);
        }
    };

    // Extraer datos de los nuevos agentes de Fase 2
    const deliveryData = results?.delivery?.data || {};
    const packagerData = results?.packager?.data?.estructura_sobres || {};
    const economicResumen = results?.economic_writer?.data?.resumen_economico || null;

    const checklistGeneral = deliveryData.checklist || [];
    const alertasLogistica = deliveryData.alertas || [];

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
                <button 
                    onClick={handleDownloadZip}
                    disabled={downloading === 'ZIP'}
                    style={{ 
                        display: 'flex', alignItems: 'center', gap: '8px',
                        padding: '10px 20px', borderRadius: '12px', background: 'var(--primary)',
                        color: 'white', border: 'none', fontWeight: 700, cursor: 'pointer',
                        boxShadow: '0 4px 15px var(--primary-glow)'
                    }}
                >
                    {downloading === 'ZIP' ? <Loader2 size={16} className="animate-spin" /> : <Archive size={16} />}
                    {downloading === 'ZIP' ? 'EMPAQUETANDO...' : 'DESCARGAR EXPEDIENTE COMPLETO'}
                </button>
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
                        <p style={{ fontSize: '13px', color: 'var(--text-muted)', textAlign: 'center', padding: '20px' }}>No se han encontrado archivos. Ejecuta la Generacción de Documentos.</p>
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
                                    <div style={{ color: 'var(--text-secondary)' }}><b>Lugar:</b> {deliveryData.direccion_fisica || 'Ver Guía PDF'}</div>
                                    <div style={{ color: 'var(--text-secondary)' }}><b>Horario:</b> {deliveryData.horario || '09:00 - 15:00'}</div>
                                </>
                            )}
                             <div style={{ color: '#ffb366', fontWeight: 700 }}>⚠️ Límite: {deliveryData.fecha_limite || 'Consultar bases'}</div>
                        </div>
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
