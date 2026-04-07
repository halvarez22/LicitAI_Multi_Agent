import React, { useState } from 'react';
import { Upload as UploadIcon, File, CheckCircle } from 'lucide-react';
import { uploadDocument } from '../services/api';

const UploadSection = ({ onComplete }) => {
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);
    const [sessionId, setSessionId] = useState(`SES-${Math.floor(Math.random() * 10000)}`);

    const handleDrop = (e) => {
        e.preventDefault();
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setFile(e.dataTransfer.files[0]);
        }
    };

    const handleUpload = async () => {
        if (!file) return;
        setLoading(true);
        try {
            await uploadDocument(file, sessionId);
            onComplete(sessionId);
        } catch (error) {
            console.error("Error al subir", error);
            alert("Error simulando OCR. Fallback activado para demostración.");
            onComplete(sessionId);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="glass-panel" style={{ maxWidth: '600px', margin: '0 auto', textAlign: 'center' }}>
            <h2 style={{ marginBottom: '16px', fontSize: '28px' }}>Ingesta de Bases</h2>
            <p style={{ color: 'var(--text-muted)', marginBottom: '32px' }}>Sube el PDF de la licitación pública para iniciar el análisis automático.</p>

            <div
                onDragOver={(e) => e.preventDefault()}
                onDrop={handleDrop}
                style={{
                    border: '2px dashed var(--glass-border)',
                    borderRadius: '16px',
                    padding: '48px',
                    marginBottom: '24px',
                    backgroundColor: 'rgba(0,0,0,0.2)',
                    cursor: 'pointer',
                    transition: 'all 0.3s'
                }}
                onClick={() => document.getElementById('file-upload').click()}
            >
                <input
                    id="file-upload"
                    type="file"
                    accept=".pdf,.docx,.png"
                    style={{ display: 'none' }}
                    onChange={(e) => setFile(e.target.files[0])}
                />
                {file ? (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
                        <File size={48} color="var(--primary-color)" />
                        <span style={{ fontWeight: '600' }}>{file.name}</span>
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
                        <UploadIcon size={48} color="var(--text-muted)" />
                        <span>Arrastra y suelta tu archivo aquí o <b style={{ color: 'var(--primary-color)' }}>clica para explorar</b></span>
                    </div>
                )}
            </div>

            <div style={{ textAlign: 'left', marginBottom: '24px' }}>
                <label style={{ display: 'block', fontSize: '14px', marginBottom: '8px', color: 'var(--text-muted)' }}>Session ID autogenerado</label>
                <input
                    type="text"
                    className="input-field"
                    value={sessionId}
                    disabled
                />
            </div>

            <button
                className="btn-primary"
                style={{ width: '100%' }}
                onClick={handleUpload}
                disabled={!file || loading}
            >
                {loading ? (
                    <span className="loader" style={{ display: 'flex', gap: '8px' }}><CheckCircle size={20} /> Procesando OCR-VLM...</span>
                ) : (
                    <><CheckCircle size={20} /> Iniciar Flujo Multi-Agente</>
                )}
            </button>

            <style>{`
        .loader {
          animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
          0% { opacity: 0.6; }
          50% { opacity: 1; }
          100% { opacity: 0.6; }
        }
      `}</style>
        </div>
    );
};

export default UploadSection;
