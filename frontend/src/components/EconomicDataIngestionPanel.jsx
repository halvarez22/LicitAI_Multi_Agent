import React, { useState, useRef } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase';
import { UploadCloud, FileSpreadsheet, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react';

export default function EconomicDataIngestionPanel({ sessionId, companyId, onIngestionSuccess }) {
    const [dragActive, setDragActive] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [result, setResult] = useState(null); // { type: 'success'|'error', msg: string }
    const inputRef = useRef(null);

    const handleDrag = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setDragActive(true);
        } else if (e.type === 'dragleave') {
            setDragActive(false);
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleFile(e.dataTransfer.files[0]);
        }
    };

    const handleChange = (e) => {
        e.preventDefault();
        if (e.target.files && e.target.files[0]) {
            handleFile(e.target.files[0]);
        }
    };

    const handleFile = async (file) => {
        if (!file.name.toLowerCase().endsWith('.xlsx') && !file.name.toLowerCase().endsWith('.xls')) {
            setResult({ type: 'error', msg: 'Solo se permiten archivos Excel (.xlsx, .xls)' });
            return;
        }

        if (!sessionId || !companyId) {
            setResult({ type: 'error', msg: 'Falta sesión o empresa seleccionada.' });
            return;
        }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', sessionId);
        formData.append('company_id', companyId);

        setUploading(true);
        setResult(null);

        try {
            const res = await axios.post(`${API_BASE}/upload/ingest-economic-excel`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            if (res.data?.success) {
                setResult({ type: 'success', msg: res.data.message || 'Datos importados y recalculados exitosamente.' });
                if (onIngestionSuccess) onIngestionSuccess();
            } else {
                setResult({ type: 'error', msg: res.data?.message || 'Error en la importación.' });
            }
        } catch (error) {
            setResult({ type: 'error', msg: error?.response?.data?.detail || error.message || 'Error de red' });
        } finally {
            setUploading(false);
            if (inputRef.current) inputRef.current.value = '';
        }
    };

    return (
        <div style={{ marginBottom: '12px', padding: '12px', background: 'rgba(0,0,0,0.25)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.08)' }}>
            <div style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-muted)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                Ingesta de Plantilla Económica (Vía B)
            </div>
            
            <div 
                onDragEnter={handleDrag} 
                onDragLeave={handleDrag} 
                onDragOver={handleDrag} 
                onDrop={handleDrop}
                onClick={() => inputRef.current && inputRef.current.click()}
                style={{
                    border: `1px dashed ${dragActive ? 'var(--primary)' : 'rgba(255,255,255,0.2)'}`,
                    background: dragActive ? 'rgba(0,212,255,0.08)' : 'rgba(255,255,255,0.03)',
                    borderRadius: '8px',
                    padding: '16px',
                    textAlign: 'center',
                    cursor: uploading ? 'not-allowed' : 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '8px',
                    transition: 'all 0.2s ease'
                }}
            >
                <input 
                    ref={inputRef} 
                    type="file" 
                    accept=".xlsx,.xls" 
                    onChange={handleChange} 
                    style={{ display: 'none' }} 
                    disabled={uploading}
                />
                
                {uploading ? (
                    <>
                        <Loader2 className="animate-spin" size={24} color="var(--primary)" />
                        <span style={{ fontSize: '11px', color: 'var(--primary)', fontWeight: 600 }}>Procesando y recalculando LFT...</span>
                    </>
                ) : (
                    <>
                        <UploadCloud size={24} color={dragActive ? 'var(--primary)' : 'rgba(255,255,255,0.5)'} />
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                            <strong style={{ color: '#fff' }}>Arrastra un Excel</strong> o haz clic para subir plantilla de costos
                        </span>
                    </>
                )}
            </div>

            {result && (
                <div style={{ 
                    marginTop: '8px', 
                    padding: '8px 10px', 
                    borderRadius: '6px', 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: '6px',
                    background: result.type === 'success' ? 'rgba(74, 222, 128, 0.15)' : 'rgba(248, 113, 113, 0.15)',
                    border: `1px solid ${result.type === 'success' ? 'rgba(74, 222, 128, 0.3)' : 'rgba(248, 113, 113, 0.3)'}`,
                    color: result.type === 'success' ? '#4ade80' : '#f87171',
                    fontSize: '11px'
                }}>
                    {result.type === 'success' ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
                    {result.msg}
                </div>
            )}
        </div>
    );
}
