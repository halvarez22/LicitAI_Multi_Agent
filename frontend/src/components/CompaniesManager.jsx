
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Plus, Search, Loader2, Building2, Trash2, FileText, Upload, CheckCircle2, User, Info, PlayCircle } from 'lucide-react';

import { API_BASE } from '../apiBase.js';

const CompaniesManager = () => {
    const [companies, setCompanies] = useState([]);
    const [loading, setLoading] = useState(false);
    const [searchTerm, setSearchTerm] = useState("");
    const [isCreating, setIsCreating] = useState(false);
    const [newName, setNewName] = useState("");
    const [companyType, setCompanyType] = useState("moral"); // "moral" o "fisica"
    const [selectedCompany, setSelectedCompany] = useState(null);
    const [isExtracting, setIsExtracting] = useState(false);
    const [extractionProgress, setExtractionProgress] = useState(0);
    const [uploadingStatus, setUploadingStatus] = useState({}); // { docTitle: progress }
    const [notification, setNotification] = useState(null);
    const fileInputRef = React.useRef(null);
    const uploadingForRef = React.useRef(null);

    const fetchCompanies = async () => {
        setLoading(true);
        try {
            const res = await axios.get(`${API_BASE}/companies/`);
            if (res.data.success) {
                // Map the DB schema to UI state
                const formatted = res.data.data.map(c => ({
                    id: c.id,
                    name: c.name,
                    type: c.type,
                    updated_at: c.updated_at,
                    docs: Object.keys(c.docs || {}).filter(k => k !== 'LOGOTIPO').length,
                    uploadedDocs: c.docs || {},
                    master_profile: c.master_profile || {}
                }));
                setCompanies(formatted);
            }
        } catch (e) {
            console.error("Error fetching companies", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchCompanies();
    }, []);

    const saveCompanies = async (newCo, isDelete=false) => {
        try {
            if (isDelete) {
                await axios.delete(`${API_BASE}/companies/${newCo.id}`);
            } else {
                await axios.post(`${API_BASE}/companies/`, {
                    id: newCo.id,
                    name: newCo.name,
                    type: newCo.type,
                    docs_metadata: newCo.uploadedDocs || {},
                    master_profile: newCo.master_profile || {}
                });
            }
            fetchCompanies();
        } catch (e) {
            console.error("Error saving company", e);
        }
    };

    const handleCreate = (e) => {
        if (e) e.preventDefault();
        if (!newName.trim()) return;
        
        const newCo = {
            id: `co_${Date.now()}`,
            name: newName,
            type: companyType,
            uploadedDocs: {},
            master_profile: {}
        };
        
        saveCompanies(newCo);
        setNewName("");
        setCompanyType("moral");
        setIsCreating(false);
    };

    const handleDelete = (id) => {
        if (!window.confirm("¿Seguro que deseas eliminar esta empresa?")) return;
        saveCompanies({id}, true);
    };

    const handleFileUploadRequest = (docTitle) => {
        console.log(`📡 [CORP-UPLOAD] Solicitando carga para: ${docTitle}`);
        uploadingForRef.current = docTitle;
        fileInputRef.current.click();
    };
    const handleFileChange = async (e) => {
        const file = e.target.files[0];
        if (!file || !selectedCompany) return;

        const target = uploadingForRef.current;
        setUploadingStatus(prev => ({ ...prev, [target]: 0 }));

        const processUpload = async (previewBase64 = null) => {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('docTitle', target);
            if (previewBase64) {
                formData.append('preview', previewBase64);
            }

            try {
                const res = await axios.post(`${API_BASE}/companies/${selectedCompany.id}/upload`, formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                    onUploadProgress: (progressEvent) => {
                        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                        setUploadingStatus(prev => ({ ...prev, [target]: percentCompleted }));
                    }
                });

                if (res.data.success) {
                    setUploadingStatus(prev => ({ ...prev, [target]: 100 }));
                    setTimeout(() => {
                        const updatedCo = res.data.data;
                        const formatted = {
                            id: updatedCo.id,
                            name: updatedCo.name,
                            type: updatedCo.type,
                            updated_at: updatedCo.updated_at,
                            docs: Object.keys(updatedCo.docs || {}).filter(k => k !== 'LOGOTIPO').length,
                            uploadedDocs: updatedCo.docs || {},
                            master_profile: updatedCo.master_profile || {}
                        };
                        setSelectedCompany(formatted);
                        setCompanies(prev => prev.map(c => c.id === formatted.id ? formatted : c));
                        setUploadingStatus(prev => {
                            const newStatus = { ...prev };
                            delete newStatus[target];
                            return newStatus;
                        });
                        console.log(`✅ [CORP-UPLOAD] ${file.name} cargado físicamente para ${target}`);
                        
                        // Notificación de éxito
                        setNotification({
                            message: `¡${target} cargado y procesado con éxito!`,
                            type: 'success'
                        });
                        setTimeout(() => setNotification(null), 4000);
                    }, 500);
                } else {
                    throw new Error(res.data.message);
                }
            } catch (error) {
                console.error("Upload error", error);
                alert("Error al subir el archivo.");
                setUploadingStatus(prev => {
                    const newStatus = { ...prev };
                    delete newStatus[target];
                    return newStatus;
                });
            }
        };

        if (target === 'LOGOTIPO') {
            const reader = new FileReader();
            reader.onload = (event) => {
                processUpload(event.target.result);
            };
            reader.readAsDataURL(file);
        } else {
            await processUpload();
        }
        
        e.target.value = null; // Reset input
    };

    const filtered = companies.filter(c => c.name.toLowerCase().includes(searchTerm.toLowerCase()));
    if (selectedCompany) {
        const isUploaded = (title) => selectedCompany.uploadedDocs && selectedCompany.uploadedDocs[title];
        
        const requiredDocTitles = (selectedCompany.type || 'moral') === 'moral' 
            ? ['Acta Constitutiva', 'CIF (SAT)'] 
            : ['INE / Identificación', 'CIF (SAT)'];
            
        const uploadedRequiredCount = requiredDocTitles.filter(title => isUploaded(title)).length;
        const totalRequired = requiredDocTitles.length;

        return (
            <div style={{ padding: '0 40px 100px 40px', maxWidth: '1200px', margin: '0 auto', animation: 'fadeIn 0.3s' }}>
                <input type="file" ref={fileInputRef} style={{ display: 'none' }} onChange={handleFileChange} />
                <button 
                    onClick={() => setSelectedCompany(null)}
                    style={{ background: 'none', border: 'none', color: 'var(--primary)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '24px', fontWeight: 600 }}
                >
                    &larr; Volver a Empresas
                </button>
                <div className="glass-panel" style={{ padding: '40px', borderRadius: '24px', position: 'relative', overflow: 'hidden' }}>
                    {/* Decoración de fondo */}
                    <div style={{ position: 'absolute', top: '-50px', right: '-50px', width: '200px', height: '200px', background: 'var(--primary)', filter: 'blur(100px)', opacity: 0.05 }}></div>

                    <div style={{ display: 'flex', gap: '40px', alignItems: 'center', marginBottom: '40px' }}>
                        {/* Slot de Logo Dynamico */}
                        <div style={{ 
                            width: '120px', 
                            height: '120px', 
                            borderRadius: '20px', 
                            border: isUploaded('LOGOTIPO') ? '2px solid var(--primary)' : '2px dashed var(--border-glass)',
                            background: isUploaded('LOGOTIPO') ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0.02)',
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            cursor: 'pointer',
                            transition: 'all 0.3s',
                            flexShrink: 0,
                            position: 'relative',
                            overflow: 'hidden'
                        }}
                        onMouseOver={(e) => e.currentTarget.style.borderColor = 'var(--primary)'}
                        onMouseOut={(e) => e.currentTarget.style.borderColor = isUploaded('LOGOTIPO') ? 'var(--primary)' : 'var(--border-glass)'}
                        onClick={() => handleFileUploadRequest('LOGOTIPO')}
                        >
                            {uploadingStatus['LOGOTIPO'] !== undefined ? (
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                                    <Loader2 className="animate-spin" color="var(--primary)" size={32} />
                                    <span style={{ fontSize: '14px', color: 'var(--primary)', fontWeight: 800 }}>{uploadingStatus['LOGOTIPO']}%</span>
                                </div>
                            ) : isUploaded('LOGOTIPO') ? (
                                <img 
                                    src={selectedCompany.uploadedDocs['LOGOTIPO'].preview} 
                                    alt="Logo" 
                                    style={{ width: '100%', height: '100%', objectFit: 'contain', padding: '10px' }} 
                                />
                            ) : (
                                <>
                                    <Upload size={24} color="var(--text-muted)" />
                                    <span style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '8px', fontWeight: 700 }}>LOGOTIPO</span>
                                </>
                            )}
                            
                            {/* Overlay de hover para cambiar */}
                            {isUploaded('LOGOTIPO') && (
                                <div style={{ 
                                    position: 'absolute', 
                                    inset: 0, 
                                    background: 'rgba(0,0,0,0.4)', 
                                    display: 'flex', 
                                    alignItems: 'center', 
                                    justifyContent: 'center',
                                    opacity: 0,
                                    transition: 'opacity 0.2s'
                                }}
                                onMouseOver={(e) => e.currentTarget.style.opacity = 1}
                                onMouseOut={(e) => e.currentTarget.style.opacity = 0}
                                >
                                    <span style={{ fontSize: '10px', color: 'white', fontWeight: 800 }}>CAMBIAR</span>
                                </div>
                            )}
                        </div>

                        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '18px' }}>
                                {isUploaded('LOGOTIPO') && (
                                    <img 
                                        src={selectedCompany.uploadedDocs['LOGOTIPO'].preview} 
                                        alt="Logo mini" 
                                        style={{ width: '45px', height: '45px', objectFit: 'contain' }} 
                                    />
                                )}
                                <h2 style={{ fontSize: '36px', fontWeight: 900, marginBottom: '0', letterSpacing: '-1.5px', textTransform: 'uppercase' }}>{selectedCompany.name}</h2>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                                <span style={{ 
                                    fontSize: '11px', 
                                    padding: '4px 12px', 
                                    borderRadius: '8px', 
                                    background: (selectedCompany.type || 'moral') === 'moral' ? 'rgba(59, 130, 246, 0.15)' : 'rgba(147, 51, 234, 0.15)',
                                    color: (selectedCompany.type || 'moral') === 'moral' ? 'var(--primary)' : 'var(--secondary)',
                                    fontWeight: 900,
                                    textTransform: 'uppercase',
                                    border: `1px solid ${(selectedCompany.type || 'moral') === 'moral' ? 'rgba(59, 130, 246, 0.3)' : 'rgba(147, 51, 234, 0.3)'}`
                                }}>
                                    {(selectedCompany.type || 'moral') === 'moral' ? 'Persona Moral' : 'Persona Física'}
                                </span>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-muted)', fontSize: '13px' }}>
                                    <Info size={14} />
                                    <span>Este logo se usará para membretar tus formatos y cartas oficiales.</span>
                                </div>
                            </div>
                        </div>
                        
                        <div style={{ padding: '20px', background: 'rgba(255,255,255,0.03)', borderRadius: '16px', border: '1px solid var(--border-glass)', textAlign: 'right' }}>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>ESTADO DEL EXPEDIENTE</div>
                            <div style={{ 
                                color: uploadedRequiredCount >= totalRequired ? 'var(--success)' : 'var(--warning)', 
                                fontWeight: 800, 
                                fontSize: '14px' 
                            }}>
                                {uploadedRequiredCount >= totalRequired ? 'VERIFICADO' : 'INCOMPLETO'} ({uploadedRequiredCount}/{totalRequired})
                            </div>
                        </div>
                    </div>

                    <div style={{ padding: '24px', background: 'rgba(59, 130, 246, 0.03)', borderRadius: '16px', border: '1px solid rgba(59, 130, 246, 0.1)', marginBottom: '32px', display: 'flex', alignItems: 'center', gap: '16px' }}>
                         <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--primary)', boxShadow: '0 0 10px var(--primary)' }}></div>
                         <span style={{ fontSize: '13px', fontWeight: 600 }}>Documentación Maestra para cumplimiento legal y fiscal.</span>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '20px' }}>
                        {( (selectedCompany.type || 'moral') === 'moral' ? [
                            { title: 'Acta Constitutiva', icon: <Building2 className="text-primary" />, required: true },
                            { title: 'Poder Notarial', icon: <FileText className="text-secondary" />, note: 'Podría estar en el Acta' },
                            { title: 'CIF (SAT)', icon: <CheckCircle2 className="text-success" />, required: true },
                        ] : [
                            { title: 'INE / Identificación', icon: <User className="text-primary" />, required: true },
                            { title: 'CIF (SAT)', icon: <CheckCircle2 className="text-success" />, required: true },
                        ]).map((card, i) => {
                            const fileInfo = isUploaded(card.title);
                            return (
                                <div key={i} className="audit-widget" style={{ 
                                    padding: '24px', 
                                    display: 'flex', 
                                    flexDirection: 'column', 
                                    alignItems: 'center', 
                                    gap: '16px', 
                                    position: 'relative',
                                    border: fileInfo ? '1px solid var(--success)' : '1px solid var(--border-glass)',
                                    background: fileInfo ? 'rgba(16, 185, 129, 0.03)' : 'rgba(255,255,255,0.01)',
                                    transition: 'all 0.3s ease',
                                    cursor: 'pointer'
                                }}
                                onClick={() => handleFileUploadRequest(card.title)}
                                onMouseOver={(e) => {
                                    e.currentTarget.style.transform = 'translateY(-8px)';
                                    e.currentTarget.style.borderColor = fileInfo ? 'var(--success)' : 'var(--primary)';
                                    e.currentTarget.style.boxShadow = '0 10px 30px rgba(0,0,0,0.3)';
                                    e.currentTarget.style.background = fileInfo ? 'rgba(16, 185, 129, 0.08)' : 'rgba(255,255,255,0.05)';
                                }}
                                onMouseOut={(e) => {
                                    e.currentTarget.style.transform = 'translateY(0)';
                                    e.currentTarget.style.borderColor = fileInfo ? 'var(--success)' : 'var(--border-glass)';
                                    e.currentTarget.style.boxShadow = 'none';
                                    e.currentTarget.style.background = fileInfo ? 'rgba(16, 185, 129, 0.03)' : 'rgba(255,255,255,0.01)';
                                }}
                                >
                                    {card.required && !fileInfo && (
                                        <span style={{ position: 'absolute', top: '10px', right: '10px', fontSize: '9px', background: 'rgba(239, 68, 68, 0.1)', color: '#ef4444', padding: '2px 6px', borderRadius: '4px', fontWeight: 900, border: '1px solid rgba(239, 68, 68, 0.2)' }}>OBLIGATORIO</span>
                                    )}
                                    {fileInfo && (
                                        <span style={{ position: 'absolute', top: '10px', right: '10px', fontSize: '9px', background: 'rgba(16, 185, 129, 0.1)', color: 'var(--success)', padding: '2px 6px', borderRadius: '4px', fontWeight: 900, border: '1px solid rgba(16, 185, 129, 0.2)' }}>CARGADO</span>
                                    )}
                                    {uploadingStatus[card.title] !== undefined ? (
                                        <div style={{ padding: '20px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
                                            <Loader2 className="animate-spin" color="var(--primary)" size={32} />
                                            <div style={{ fontWeight: 800, fontSize: '12px', color: 'var(--primary)' }}>
                                                {uploadingStatus[card.title] < 100 ? `CARGANDO ${uploadingStatus[card.title]}%` : 'GUARDANDO...'}
                                            </div>
                                        </div>
                                    ) : (
                                        <>
                                            <div style={{ 
                                                width: '48px', 
                                                height: '48px', 
                                                borderRadius: '12px', 
                                                background: 'rgba(255,255,255,0.05)', 
                                                display: 'flex', 
                                                alignItems: 'center', 
                                                justifyContent: 'center',
                                                color: fileInfo ? 'var(--success)' : 'inherit'
                                            }}>
                                                {card.icon}
                                            </div>
                                            <div style={{ textAlign: 'center' }}>
                                                <div style={{ fontWeight: 800, fontSize: '14px' }}>{card.title}</div>
                                                <div style={{ fontSize: '11px', color: fileInfo ? 'var(--success)' : 'var(--warning)', marginTop: '4px', textTransform: 'uppercase' }}>
                                                    {fileInfo ? 'Documento Listo' : 'Pendiente'}
                                                </div>
                                                {fileInfo && <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>{fileInfo.name}</div>}
                                                {card.note && !fileInfo && <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '6px', fontStyle: 'italic' }}>{card.note}</div>}
                                            </div>
                                            <button 
                                                onClick={() => handleFileUploadRequest(card.title)}
                                                className="icon-btn" 
                                                style={{ width: '100%', padding: '8px', fontSize: '11px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-glass)' }}
                                            >
                                                <Upload size={14} style={{ marginRight: '8px' }} /> {fileInfo ? 'REEMPLAZAR' : 'SUBIR DOC'}
                                            </button>
                                        </>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    {/* Acción de Procesamiento Maestro */}
                    {uploadedRequiredCount >= totalRequired && (
                        <div style={{ 
                            marginTop: '64px', 
                            padding: '40px', 
                            background: 'rgba(59, 130, 246, 0.05)', 
                            borderRadius: '24px', 
                            border: '1px solid rgba(59, 130, 246, 0.2)',
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            gap: '24px',
                            animation: 'fadeIn 0.5s ease-out'
                        }}>
                            <div style={{ textAlign: 'center' }}>
                                <h3 style={{ fontSize: '20px', fontWeight: 800, color: '#fff', marginBottom: '8px' }}>Expediente Maestro</h3>
                                <p style={{ color: 'var(--text-muted)', fontSize: '14px', maxWidth: '600px' }}>
                                    {selectedCompany.master_profile && Object.keys(selectedCompany.master_profile).length > 0 
                                      ? "Información extraída y validada por la IA."
                                      : "Nuestros Agentes procesarán esta documentación para extraer automáticamente tu **Identidad Fiscal, Poderes y Solvencia Legal**."}
                                </p>
                            </div>
                            
                            {selectedCompany.master_profile && Object.keys(selectedCompany.master_profile).length > 0 && (
                                <div style={{ 
                                    width: '100%', 
                                    display: 'grid', 
                                    gridTemplateColumns: 'repeat(2, 1fr)', 
                                    gap: '16px',
                                    textAlign: 'left'
                                }}>
                                    {[
                                        { label: 'RFC', value: selectedCompany.master_profile.rfc },
                                        { label: 'RAZÓN SOCIAL', value: selectedCompany.master_profile.razon_social },
                                        { label: 'REPRESENTANTE LEGAL', value: selectedCompany.master_profile.representante_legal },
                                        { label: 'PODERES', value: selectedCompany.master_profile.poderes },
                                        { label: 'OBJETO SOCIAL', value: selectedCompany.master_profile.objeto_social, span: 2 }
                                    ].map((item, idx) => (
                                        <div key={idx} style={{ 
                                            background: 'rgba(255,255,255,0.03)', 
                                            padding: '16px', 
                                            borderRadius: '12px',
                                            border: '1px solid rgba(255,255,255,0.05)',
                                            gridColumn: item.span ? `span ${item.span}` : 'auto'
                                        }}>
                                            <div style={{ fontSize: '9px', fontWeight: 900, color: 'var(--primary)', letterSpacing: '1px', marginBottom: '4px' }}>{item.label}</div>
                                            <div style={{ fontSize: '13px', color: '#fff', fontWeight: 600 }}>{item.value || 'No detectado'}</div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            <button 
                                className="btn-primary glow-active"
                                disabled={isExtracting}
                                style={{ 
                                    padding: '16px 48px', 
                                    fontSize: '18px', 
                                    borderRadius: '16px',
                                    fontWeight: 800,
                                    cursor: isExtracting ? 'not-allowed' : 'pointer',
                                    paddingLeft: '30px', paddingRight: '30px'
                                }}
                                onClick={async () => {
                                    setIsExtracting(true);
                                    let progressItem = 0;
                                    const sim = setInterval(() => {
                                        progressItem += 2;
                                        setExtractionProgress(prev => prev >= 95 ? 95 : prev + 2);
                                    }, 200);

                                    try {
                                        const res = await axios.post(`${API_BASE}/companies/${selectedCompany.id}/analyze`);
                                        clearInterval(sim);
                                        setExtractionProgress(100);

                                        if (res.data.success) {
                                            setTimeout(() => {
                                                const updatedCo = res.data.data;
                                                const formatted = {
                                                    id: updatedCo.id,
                                                    name: updatedCo.name,
                                                    type: updatedCo.type,
                                                    updated_at: updatedCo.updated_at,
                                                    docs: Object.keys(updatedCo.docs || {}).filter(k => k !== 'LOGOTIPO').length,
                                                    uploadedDocs: updatedCo.docs || {},
                                                    master_profile: updatedCo.master_profile || {}
                                                };
                                                setSelectedCompany(formatted);
                                                setCompanies(prev => prev.map(c => c.id === formatted.id ? formatted : c));
                                                setIsExtracting(false);
                                                setExtractionProgress(0);
                                                setNotification({ type: 'success', message: '¡Perfil Maestro Actualizado!' });
                                                setTimeout(() => setNotification(null), 3000);
                                            }, 500);
                                        } else {
                                            throw new Error(res.data.message);
                                        }
                                    } catch (error) {
                                        console.error("Analysis error", error);
                                        clearInterval(sim);
                                        setIsExtracting(false);
                                        setExtractionProgress(0);
                                        alert("Hubo un error al extraer la información.");
                                    }
                                }}
                            >
                                {isExtracting ? (
                                    <>
                                        <Loader2 size={24} style={{ marginRight: '12px', animation: 'spin 2s linear infinite' }} />
                                        ANALIZANDO... {extractionProgress}%
                                    </>
                                ) : (
                                    <>
                                        <PlayCircle size={24} style={{ marginRight: '12px' }} />
                                        {selectedCompany.master_profile && Object.keys(selectedCompany.master_profile).length > 0 ? 'RE-ANALIZAR EXPEDIENTE' : 'ANALIZAR EXPEDIENTE MAESTRO'}
                                    </>
                                )}
                            </button>
                        </div>
                    )}
                </div>
            </div>
        );
    }

    return (
        <div style={{ 
            animation: 'fadeIn 0.6s ease-out', 
            paddingBottom: '100px',
            paddingRight: '15px'
        }}>
            <div style={{ marginBottom: '48px', position: 'relative', maxWidth: '800px', margin: '0 auto 48px auto' }}>
                <Search style={{ position: 'absolute', left: '20px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} size={20} />
                <input 
                    type="text"
                    placeholder="Buscar empresa por razón social..."
                    className="glass-panel"
                    style={{ 
                        width: '100%', 
                        padding: '20px 20px 20px 60px', 
                        borderRadius: '16px',
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid var(--border-glass)',
                        color: 'white',
                        fontSize: '18px',
                        outline: 'none'
                    }}
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                />
            </div>

            <div style={{ 
                display: 'grid', 
                gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', 
                gap: '24px' 
            }}>
                <div 
                    className="glass-panel" 
                    onClick={() => setIsCreating(true)}
                    style={{
                        cursor: 'pointer',
                        padding: '32px',
                        borderRadius: '16px',
                        border: '2px dashed var(--border-glass)',
                        background: 'rgba(147, 51, 234, 0.03)',
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '16px',
                        transition: 'all 0.3s ease',
                        height: '220px'
                    }}
                    onMouseOver={(e) => {
                        e.currentTarget.style.borderColor = 'var(--secondary)';
                        e.currentTarget.style.background = 'rgba(147, 51, 234, 0.08)';
                    }}
                    onMouseOut={(e) => {
                        e.currentTarget.style.borderColor = 'var(--border-glass)';
                        e.currentTarget.style.background = 'rgba(147, 51, 234, 0.03)';
                    }}
                >
                    <div style={{ 
                        width: '56px', 
                        height: '56px', 
                        borderRadius: '12px', 
                        background: 'var(--secondary)', 
                        display: 'flex', 
                        alignItems: 'center', 
                        justifyContent: 'center',
                        color: 'white',
                        boxShadow: '0 0 20px rgba(147, 51, 234, 0.3)'
                    }}>
                        <Plus size={32} strokeWidth={3} />
                    </div>
                    <span style={{ fontSize: '18px', fontWeight: 700 }}>Nueva Empresa</span>
                </div>

                {filtered.map(company => (
                    <div 
                        key={company.id} 
                        className="glass-panel"
                        onClick={() => setSelectedCompany(company)}
                        style={{ 
                            padding: '24px', 
                            borderRadius: '16px', 
                            cursor: 'pointer',
                            position: 'relative',
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'space-between',
                            height: '220px',
                            transition: 'transform 0.2s',
                            border: '1px solid var(--border-glass)'
                        }}
                        onMouseOver={(e) => e.currentTarget.style.transform = 'translateY(-5px)'}
                        onMouseOut={(e) => e.currentTarget.style.transform = 'none'}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                <div style={{ width: '40px', height: '40px', borderRadius: '8px', background: 'rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                                    {company.uploadedDocs?.LOGOTIPO ? (
                                        <img src={company.uploadedDocs.LOGOTIPO.preview} style={{ width: '100%', height: '100%', objectFit: 'contain' }} alt="Logo" />
                                    ) : (
                                        company.type === 'moral' ? <Building2 size={20} color="var(--primary)" /> : <User size={20} color="var(--secondary)" />
                                    )}
                                </div>
                                <span style={{ 
                                    fontSize: '8px', 
                                    fontWeight: 900, 
                                    color: company.type === 'moral' ? 'var(--primary)' : 'var(--secondary)',
                                    letterSpacing: '0.5px'
                                }}>
                                    {company.type === 'moral' ? 'MORAL' : 'FÍSICA'}
                                </span>
                            </div>
                            <button 
                                onClick={(e) => { e.stopPropagation(); handleDelete(company.id); }}
                                className="icon-btn" 
                                style={{ opacity: 0.5 }}
                            >
                                <Trash2 size={16} />
                            </button>
                        </div>
                        
                        <div>
                            <div style={{ fontSize: '16px', fontWeight: 800, marginBottom: '4px', lineHeight: 1.2 }}>{company.name}</div>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Empresa Registrada</div>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '16px', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                            <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--primary)' }}>{company.docs} DOCUMENTOS</div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{new Date(company.updated_at).toLocaleDateString()}</div>
                        </div>
                    </div>
                ))}
            </div>

            {isCreating && (
                <div style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'rgba(0,0,0,0.85)',
                    backdropFilter: 'blur(12px)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 2000
                }}>
                    <div className="glass-panel" style={{ padding: '40px', width: '450px', borderRadius: '24px' }}>
                        <h2 style={{ fontSize: '24px', fontWeight: 800, marginBottom: '24px' }}>Registrar Empresa</h2>
                        <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                            <input 
                                autoFocus
                                type="text" 
                                placeholder="Razón Social (Nombre de la Empresa)"
                                style={{ 
                                    padding: '16px', 
                                    background: 'rgba(0,0,0,0.3)', 
                                    border: '1px solid var(--border-glass)', 
                                    borderRadius: '12px', 
                                    color: 'white',
                                    fontSize: '16px'
                                }}
                                value={newName}
                                onChange={(e) => setNewName(e.target.value)}
                            />
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                <label style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 700 }}>TIPO DE CONTRIBUYENTE</label>
                                <div style={{ display: 'flex', gap: '10px' }}>
                                    <button 
                                        type="button"
                                        onClick={() => setCompanyType("moral")}
                                        style={{ 
                                            flex: 1, 
                                            padding: '10px', 
                                            borderRadius: '8px', 
                                            border: companyType === 'moral' ? '1px solid var(--primary)' : '1px solid var(--border-glass)',
                                            background: companyType === 'moral' ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
                                            color: companyType === 'moral' ? 'white' : 'var(--text-muted)',
                                            fontSize: '12px',
                                            fontWeight: 700,
                                            cursor: 'pointer'
                                        }}
                                    >
                                        Persona Moral
                                    </button>
                                    <button 
                                        type="button"
                                        onClick={() => setCompanyType("fisica")}
                                        style={{ 
                                            flex: 1, 
                                            padding: '10px', 
                                            borderRadius: '8px', 
                                            border: companyType === 'fisica' ? '1px solid var(--secondary)' : '1px solid var(--border-glass)',
                                            background: companyType === 'fisica' ? 'rgba(147, 51, 234, 0.1)' : 'transparent',
                                            color: companyType === 'fisica' ? 'white' : 'var(--text-muted)',
                                            fontSize: '12px',
                                            fontWeight: 700,
                                            cursor: 'pointer'
                                        }}
                                    >
                                        Persona Física
                                    </button>
                                </div>
                            </div>

                            <div style={{ display: 'flex', gap: '16px', marginTop: '10px' }}>
                                <button type="button" className="btn-secondary" onClick={() => setIsCreating(false)} style={{ flex: 1 }}>Cancelar</button>
                                <button type="submit" className="btn-primary" style={{ flex: 1 }}>Registrar</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
            {/* Notificación Flotante */}
            {notification && (
                <div style={{
                    position: 'fixed',
                    bottom: '40px',
                    right: '40px',
                    background: notification.type === 'success' ? 'var(--success)' : 'var(--error)',
                    color: '#000',
                    padding: '16px 32px',
                    borderRadius: '12px',
                    fontWeight: 800,
                    boxShadow: '0 10px 40px rgba(0,0,0,0.5)',
                    zIndex: 1000,
                    animation: 'slideInRight 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px'
                }}>
                    <CheckCircle2 size={24} />
                    {notification.message}
                </div>
            )}
        </div>
    );
};

export default CompaniesManager;
