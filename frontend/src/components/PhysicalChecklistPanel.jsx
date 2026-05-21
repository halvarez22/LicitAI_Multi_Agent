import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';
import { Archive, FileCheck, CheckCircle2, Download, AlertTriangle, FileText, Plus, ExternalLink } from 'lucide-react';
import { useDropzone } from 'react-dropzone';

export default function PhysicalChecklistPanel({ sessionId }) {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [checklistData, setChecklistData] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [uploadSuccess, setUploadSuccess] = useState(false);

    const fetchDeliveryChecklist = useCallback(async () => {
        if (!sessionId) return;
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/delivery-checklist`);
            if (res.data?.success && res.data?.data?.delivery_checklist) {
                setChecklistData(res.data.data.delivery_checklist);
            } else {
                setChecklistData(null);
                setError(res.data?.message || 'Aún no se ha generado el Checklist Físico. Asegúrate de ejecutar el BiddingBinderEngine.');
            }
        } catch (e) {
            setChecklistData(null);
            setError(e?.response?.data?.detail || e?.message || 'Error de red');
        } finally {
            setLoading(false);
        }
    }, [sessionId]);

    useEffect(() => {
        fetchDeliveryChecklist();
    }, [fetchDeliveryChecklist]);

    const onDrop = useCallback(async (acceptedFiles) => {
        if (!acceptedFiles || acceptedFiles.length === 0) return;
        setUploading(true);
        setUploadSuccess(false);
        setError(null);
        try {
            for (const file of acceptedFiles) {
                const formData = new FormData();
                formData.append('files', file);
                await axios.post(`${API_BASE}/upload/${encodeURIComponent(sessionId)}`, formData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
            }
            setUploadSuccess(true);
            setTimeout(() => setUploadSuccess(false), 3000);
            fetchDeliveryChecklist(); // Refrescar si hubo cambios
        } catch (e) {
            setError(e?.response?.data?.detail || e?.message || 'Error al subir los formatos');
        } finally {
            setUploading(false);
        }
    }, [sessionId, fetchDeliveryChecklist]);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop });

    const handleDownloadGuide = async () => {
        try {
            const response = await axios.get(`${API_BASE}/downloads/file`, {
                params: { path: `out/generated/${sessionId}/GUIA_DE_ARMADO_Y_CHECKLIST.docx`, session_id: sessionId },
                responseType: 'blob'
            });
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `GUIA_DE_ARMADO_Y_CHECKLIST.docx`);
            document.body.appendChild(link);
            link.click();
            link.remove();
        } catch (err) {
            alert("Aún no se ha generado la GUIA_DE_ARMADO_Y_CHECKLIST.docx o hubo un error en la descarga.");
        }
    };

    if (!sessionId) return null;

    return (
        <div className="glass-panel" style={{ borderRadius: '16px', padding: '24px', background: 'rgba(15,23,42,0.6)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '16px' }}>
                <Archive size={24} color="var(--primary)" />
                <h2 style={{ fontSize: '18px', fontWeight: 800, margin: 0 }}>Aduana Corporativa (Checklist Físico)</h2>
            </div>

            {loading && <p style={{ color: 'var(--text-muted)' }}>Cargando checklist físico...</p>}
            {error && <p style={{ color: '#f87171' }}>{error}</p>}

            {!loading && !error && checklistData && (
                <div style={{ display: 'grid', gap: '24px' }}>
                    
                    {/* BLOQUE 1: Documentos Externos */}
                    <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                        <h3 style={{ fontSize: '14px', fontWeight: 800, color: 'var(--primary)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <FileCheck size={18} /> Documentos Empresariales (A recabar físicamente)
                        </h3>
                        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            {checklistData.bloque_1_externos?.map((item, idx) => (
                                <li key={idx} style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px', color: '#e2e8f0' }}>
                                    <CheckCircle2 size={16} color="#4ade80" style={{ flexShrink: 0 }} />
                                    <span>{item}</span>
                                </li>
                            ))}
                            {!checklistData.bloque_1_externos?.length && <li style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Ninguno requerido explícitamente.</li>}
                        </ul>
                    </div>

                    {/* BLOQUE 2: Anexos de la Convocante (Dropzone) */}
                    <div style={{ background: 'rgba(56, 189, 248, 0.05)', padding: '16px', borderRadius: '12px', border: '1px solid rgba(56, 189, 248, 0.2)' }}>
                        <h3 style={{ fontSize: '14px', fontWeight: 800, color: '#7dd3fc', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <ExternalLink size={18} /> Formatos Oficiales (Proporcionados por la convocante)
                        </h3>
                        <p style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '16px', lineHeight: 1.5 }}>
                            Si las bases exigen el uso de un anexo específico (ej. Anexo III CompraNet, Carta de no inhabilitación municipal), arrastra el PDF o DOCX aquí. El sistema lo rellenará.
                        </p>
                        <div 
                            {...getRootProps()} 
                            style={{ 
                                border: isDragActive ? '2px dashed var(--primary)' : '2px dashed rgba(255,255,255,0.15)',
                                padding: '30px 20px', 
                                textAlign: 'center', 
                                borderRadius: '12px',
                                background: isDragActive ? 'rgba(0, 212, 255, 0.05)' : 'transparent',
                                cursor: 'pointer',
                                transition: 'all 0.2s ease'
                            }}
                        >
                            <input {...getInputProps()} />
                            <Plus size={24} color={isDragActive ? 'var(--primary)' : 'rgba(255,255,255,0.4)'} style={{ margin: '0 auto 10px auto' }} />
                            {uploading ? (
                                <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Subiendo...</p>
                            ) : isDragActive ? (
                                <p style={{ fontSize: '13px', color: 'var(--primary)', fontWeight: 600 }}>Suelta los formatos aquí...</p>
                            ) : (
                                <p style={{ fontSize: '13px', color: 'rgba(255,255,255,0.6)' }}>Arrastra y suelta formatos aquí, o haz clic para seleccionar</p>
                            )}
                        </div>
                        {uploadSuccess && <div style={{ marginTop: '10px', fontSize: '12px', color: '#4ade80', display: 'flex', alignItems: 'center', gap: '6px' }}><CheckCircle2 size={14}/> Formatos ingeridos correctamente</div>}
                    </div>

                    {/* BLOQUE 3: Protocolo de Armado */}
                    <div style={{ background: 'rgba(239, 68, 68, 0.05)', padding: '16px', borderRadius: '12px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
                        <h3 style={{ fontSize: '14px', fontWeight: 800, color: '#fca5a5', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <AlertTriangle size={18} /> Protocolo de Armado Estricto
                        </h3>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                            <div style={{ background: 'rgba(0,0,0,0.3)', padding: '12px', borderRadius: '8px' }}>
                                <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 700, marginBottom: '4px' }}>Tinta</div>
                                <div style={{ fontSize: '13px', fontWeight: 600, color: '#fff' }}>{checklistData.protocolo_armado?.tinta || 'No especificada'}</div>
                            </div>
                            <div style={{ background: 'rgba(0,0,0,0.3)', padding: '12px', borderRadius: '8px' }}>
                                <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 700, marginBottom: '4px' }}>Foliado</div>
                                <div style={{ fontSize: '13px', fontWeight: 600, color: '#fff' }}>{checklistData.protocolo_armado?.foliado || 'No especificado'}</div>
                            </div>
                            <div style={{ background: 'rgba(0,0,0,0.3)', padding: '12px', borderRadius: '8px', gridColumn: 'span 2' }}>
                                <div style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 700, marginBottom: '4px' }}>Rúbrica</div>
                                <div style={{ fontSize: '13px', fontWeight: 600, color: '#fff' }}>{checklistData.protocolo_armado?.rubricado || 'No especificado'}</div>
                            </div>
                        </div>
                    </div>

                    {/* BOTÓN DESCARGA GUÍA */}
                    <button
                        onClick={handleDownloadGuide}
                        style={{
                            marginTop: '10px',
                            padding: '16px',
                            background: 'linear-gradient(135deg, var(--primary), var(--secondary))',
                            border: 'none',
                            borderRadius: '12px',
                            color: '#fff',
                            fontWeight: 800,
                            fontSize: '14px',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '10px',
                            boxShadow: '0 4px 15px var(--primary-glow)'
                        }}
                    >
                        <Download size={20} />
                        DESCARGAR GUÍA DE ARMADO Y ETIQUETA
                    </button>

                </div>
            )}
        </div>
    );
}
