
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Plus, Search, Loader2, Building2, Trash2, FileText, Upload, CheckCircle2, User, Info, PlayCircle, Pencil, X } from 'lucide-react';

import { API_BASE } from '../apiBase.js';
import {
    formatProfileFieldValue,
    hasMeaningfulMasterProfile,
    normalizeMasterProfileForUi,
} from '../utils/masterProfileDisplay.js';

const formatCompanyFromApi = (company) => ({
    id: company.id,
    name: company.name,
    type: company.type,
    updated_at: company.updated_at,
    docs: Object.keys(company.docs || {}).filter((key) => key !== 'LOGOTIPO').length,
    uploadedDocs: company.docs || {},
    master_profile: normalizeMasterProfileForUi(company.master_profile || {}),
});

const isProfileAnalysisProcessing = (profile) => profile?._analysis_status === 'processing';

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
    const [isEditingName, setIsEditingName] = useState(false);
    const [editingNameValue, setEditingNameValue] = useState("");
    const fileInputRef = React.useRef(null);
    const uploadingForRef = React.useRef(null);
    const uploadAbortRef = React.useRef(null);   // AbortController para uploads
    const analyzeAbortRef = React.useRef(null);  // AbortController para análisis
    const profileAnalysisNotifiedRef = React.useRef(null);
    const uploadQueueRef = React.useRef([]);
    const uploadWorkerActiveRef = React.useRef(false);
    const selectedCompanyIdRef = React.useRef(null);

    useEffect(() => {
        selectedCompanyIdRef.current = selectedCompany?.id || null;
    }, [selectedCompany?.id]);

    const refreshCompanyFromApi = async (companyId) => {
        const res = await axios.get(`${API_BASE}/companies/${companyId}`);
        if (!res.data.success) {
            throw new Error(res.data.message || 'No se pudo refrescar la empresa');
        }
        const formatted = formatCompanyFromApi(res.data.data);
        setSelectedCompany((prev) => (prev?.id === formatted.id ? formatted : prev));
        setCompanies((prev) => prev.map((company) => (company.id === formatted.id ? formatted : company)));
        return formatted;
    };

    const runUploadWorker = async () => {
        if (uploadWorkerActiveRef.current) return;
        uploadWorkerActiveRef.current = true;

        while (uploadQueueRef.current.length > 0) {
            const job = uploadQueueRef.current[0];
            const companyId = selectedCompanyIdRef.current;
            if (!companyId || companyId !== job.companyId) {
                uploadQueueRef.current.shift();
                continue;
            }

            const { docTitle, file, previewBase64 } = job;
            const controller = new AbortController();
            uploadAbortRef.current = controller;

            const formData = new FormData();
            formData.append('file', file);
            formData.append('docTitle', docTitle);
            if (previewBase64) {
                formData.append('preview', previewBase64);
            }

            try {
                await axios.post(`${API_BASE}/companies/${companyId}/upload`, formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                    signal: controller.signal,
                    onUploadProgress: (progressEvent) => {
                        const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                        setUploadingStatus((prev) => ({ ...prev, [docTitle]: percentCompleted }));
                    },
                });

                setUploadingStatus((prev) => ({ ...prev, [docTitle]: 100 }));
                await refreshCompanyFromApi(companyId);
                console.log(`✅ [CORP-UPLOAD] ${file.name} cargado para ${docTitle}`);

                setNotification({
                    message: docTitle === 'LOGOTIPO'
                        ? `¡${docTitle} cargado correctamente!`
                        : `¡${docTitle} encolado y registrado! Extrayendo expediente en segundo plano…`,
                    type: 'success',
                });
                setTimeout(() => setNotification(null), 5000);
            } catch (error) {
                if (axios.isCancel(error) || error.name === 'CanceledError' || error.name === 'AbortError') {
                    uploadQueueRef.current = [];
                    setNotification({ type: 'info', message: 'Cola de cargas cancelada.' });
                    setTimeout(() => setNotification(null), 3000);
                } else {
                    console.error('Upload error', error);
                    setNotification({
                        type: 'warning',
                        message: `Error al subir "${docTitle}". Puedes reintentarlo.`,
                    });
                    setTimeout(() => setNotification(null), 6000);
                }
            } finally {
                uploadQueueRef.current.shift();
                setUploadingStatus((prev) => {
                    const next = { ...prev };
                    delete next[docTitle];
                    return next;
                });
                uploadAbortRef.current = null;
            }
        }

        uploadWorkerActiveRef.current = false;
    };

    const enqueueCompanyUpload = (docTitle, file, previewBase64 = null) => {
        if (!selectedCompanyIdRef.current) return;
        uploadQueueRef.current.push({
            companyId: selectedCompanyIdRef.current,
            docTitle,
            file,
            previewBase64,
        });
        setUploadingStatus((prev) => ({ ...prev, [docTitle]: prev[docTitle] ?? 0 }));
        runUploadWorker();
    };

    const fetchCompanies = async () => {
        setLoading(true);
        try {
            const res = await axios.get(`${API_BASE}/companies/`);
            if (res.data.success) {
                setCompanies(res.data.data.map(formatCompanyFromApi));
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

    const getCompanyDoc = (title) => selectedCompany?.uploadedDocs?.[title];

    const isDocRegistered = (title) => {
        const doc = getCompanyDoc(title);
        return Boolean(doc?.path || doc?.name);
    };

    /** Estado UX del documento: missing | processing | ready | weak_ocr | ocr_failed */
    const getDocOcrState = (title) => {
        const doc = getCompanyDoc(title);
        if (!doc?.path && !doc?.name) return 'missing';
        const status = doc.status || '';
        if (status === 'UPLOADED' || status === 'PROCESSING') return 'processing';
        if (status === 'ANALYZED') return 'ready';
        if (status === 'LOW_TEXT_QUALITY') return 'weak_ocr';
        if (status === 'OCR_FAILED') return 'ocr_failed';
        return 'registered';
    };

    const isUploaded = (title) => isDocRegistered(title);

    const isProcessing = (title) => getDocOcrState(title) === 'processing';

    // Polling: documentos en cola OCR o extracción LLM de perfil maestro en background
    useEffect(() => {
        let interval;
        const docTerminalStatuses = new Set(['ANALYZED', 'LOW_TEXT_QUALITY', 'OCR_FAILED']);
        const hasPendingDocs = selectedCompany && Object.entries(selectedCompany.uploadedDocs || {}).some(
            ([title, doc]) => title !== 'LOGOTIPO' && (doc?.path || doc?.name) && !docTerminalStatuses.has(doc.status)
        );
        const analysisProcessing = selectedCompany && isProfileAnalysisProcessing(selectedCompany.master_profile);
        const shouldPoll = selectedCompany && (hasPendingDocs || analysisProcessing) && !isExtracting;

        if (shouldPoll) {
            console.log("🔄 [POLLING] Expediente en proceso (OCR o extracción de perfil), refresco cada 3s...");
            interval = setInterval(async () => {
                try {
                    const res = await axios.get(`${API_BASE}/companies/${selectedCompany.id}`);
                    if (res.data.success) {
                        const formatted = formatCompanyFromApi(res.data.data);
                        const docsChanged = JSON.stringify(formatted.uploadedDocs) !== JSON.stringify(selectedCompany.uploadedDocs);
                        const profileChanged = JSON.stringify(formatted.master_profile) !== JSON.stringify(selectedCompany.master_profile);

                        if (docsChanged || profileChanged) {
                            const wasProcessing = isProfileAnalysisProcessing(selectedCompany.master_profile);
                            const nowReady = formatted.master_profile?._analysis_status === 'ready';
                            const nowFailed = formatted.master_profile?._analysis_status === 'failed';

                            setSelectedCompany(formatted);
                            setCompanies((prev) => prev.map((company) => (company.id === formatted.id ? formatted : company)));

                            if (wasProcessing && nowReady && hasMeaningfulMasterProfile(formatted.master_profile)) {
                                const notifyKey = `${formatted.id}:ready:${formatted.updated_at || ''}`;
                                if (profileAnalysisNotifiedRef.current !== notifyKey) {
                                    profileAnalysisNotifiedRef.current = notifyKey;
                                    setNotification({
                                        type: 'success',
                                        message: '¡Expediente Maestro extraído automáticamente!',
                                    });
                                    setTimeout(() => setNotification(null), 5000);
                                }
                            } else if (wasProcessing && nowFailed) {
                                const notifyKey = `${formatted.id}:failed:${formatted.updated_at || ''}`;
                                if (profileAnalysisNotifiedRef.current !== notifyKey) {
                                    profileAnalysisNotifiedRef.current = notifyKey;
                                    setNotification({
                                        type: 'warning',
                                        message: formatted.master_profile?._analysis_error
                                            || 'No se pudo extraer el perfil maestro. Usa «RE-ANALIZAR EXPEDIENTE».',
                                    });
                                    setTimeout(() => setNotification(null), 7000);
                                }
                            }
                        }
                    }
                } catch (e) {
                    console.error("Error en polling", e);
                }
            }, 3000);
        }

        return () => {
            if (interval) clearInterval(interval);
        };
    }, [selectedCompany, isExtracting]);

    const saveCompanies = async (newCo, isDelete=false) => {
        try {
            if (isDelete) {
                await axios.delete(`${API_BASE}/companies/${newCo.id}`);
                fetchCompanies();
                return;
            }
            const res = await axios.post(`${API_BASE}/companies/`, {
                id: newCo.id,
                name: newCo.name,
                type: newCo.type,
            });
            if (res.data.success && res.data.data) {
                const formatted = formatCompanyFromApi(res.data.data);
                setSelectedCompany(formatted);
                setCompanies((prev) => [formatted, ...prev.filter((c) => c.id !== formatted.id)]);
            } else {
                fetchCompanies();
            }
        } catch (e) {
            console.error("Error saving company", e);
        }
    };

    const handleRename = async () => {
        const trimmed = editingNameValue.trim();
        if (!trimmed || !selectedCompany) return;
        try {
            const updated = { ...selectedCompany, name: trimmed };
            await axios.post(`${API_BASE}/companies/`, {
                id: updated.id,
                name: trimmed,
                type: updated.type,
            });
            setSelectedCompany(prev => ({ ...prev, name: trimmed }));
            setCompanies(prev => prev.map(c => c.id === selectedCompany.id ? { ...c, name: trimmed } : c));
            setIsEditingName(false);
            setNotification({ type: 'success', message: `Empresa renombrada a "${trimmed}" correctamente.` });
            setTimeout(() => setNotification(null), 4000);
        } catch (e) {
            console.error("Error renombrando empresa", e);
            alert("No se pudo renombrar la empresa.");
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
    const handleFileChange = (e) => {
        const file = e.target.files[0];
        if (!file || !selectedCompany) return;

        const target = uploadingForRef.current;
        if (target === 'LOGOTIPO') {
            const reader = new FileReader();
            reader.onload = (event) => {
                enqueueCompanyUpload(target, file, event.target.result);
            };
            reader.readAsDataURL(file);
        } else {
            enqueueCompanyUpload(target, file);
        }

        e.target.value = null;
    };

    const filtered = companies.filter(c => c.name.toLowerCase().includes(searchTerm.toLowerCase()));
    if (selectedCompany) {

        const requiredDocTitles = (selectedCompany.type || 'moral') === 'moral' 
            ? ['Acta Constitutiva', 'CIF (SAT)'] 
            : ['INE / Identificación', 'CIF (SAT)'];
            
        const uploadedRequiredCount = requiredDocTitles.filter(title => isDocRegistered(title)).length;
        const totalRequired = requiredDocTitles.length;
        const allRequiredAnalyzed = requiredDocTitles.every(title => getDocOcrState(title) === 'ready');
        const anyRequiredOcrIssue = requiredDocTitles.some(title => {
            const st = getDocOcrState(title);
            return st === 'weak_ocr' || st === 'ocr_failed';
        });
        const isMoral = (selectedCompany.type || 'moral') === 'moral';
        const profileFields = isMoral ? [
            { label: 'RFC', value: selectedCompany.master_profile.rfc },
            { label: 'RAZÓN SOCIAL', value: selectedCompany.master_profile.razon_social },
            { label: 'REPRESENTANTE LEGAL', value: selectedCompany.master_profile.representante_legal },
            { label: 'PODERES', value: selectedCompany.master_profile.poderes },
            { label: 'DIRECCIÓN FISCAL', value: selectedCompany.master_profile.domicilio_fiscal, span: 2 },
            { label: 'OBJETO SOCIAL', value: selectedCompany.master_profile.objeto_social, span: 2 },
        ] : [
            { label: 'RFC', value: selectedCompany.master_profile.rfc },
            { label: 'NOMBRE COMPLETO', value: selectedCompany.master_profile.razon_social },
            { label: 'TITULAR', value: selectedCompany.master_profile.representante_legal },
            { label: 'DIRECCIÓN FISCAL', value: selectedCompany.master_profile.domicilio_fiscal, span: 2 },
            { label: 'ACTIVIDAD ECONÓMICA', value: selectedCompany.master_profile.objeto_social, span: 2 },
        ];

        return (
            <div style={{ padding: '0 40px 100px 40px', maxWidth: '1200px', margin: '0 auto', animation: 'fadeIn 0.3s' }}>
                <input type="file" ref={fileInputRef} style={{ display: 'none' }} onChange={handleFileChange} />
                <button 
                    onClick={() => {
                        setSelectedCompany(null);
                        setIsExtracting(false);
                        setExtractionProgress(0);
                        setUploadingStatus({});
                    }}
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
                                {isEditingName ? (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1 }}>
                                        <input
                                            autoFocus
                                            type="text"
                                            value={editingNameValue}
                                            onChange={e => setEditingNameValue(e.target.value)}
                                            onKeyDown={e => { if (e.key === 'Enter') handleRename(); if (e.key === 'Escape') setIsEditingName(false); }}
                                            style={{
                                                fontSize: '22px', fontWeight: 900, letterSpacing: '-1px',
                                                textTransform: 'uppercase', background: 'rgba(255,255,255,0.07)',
                                                border: '2px solid var(--primary)', borderRadius: '10px',
                                                color: 'white', padding: '8px 14px', outline: 'none', flex: 1
                                            }}
                                        />
                                        <button onClick={handleRename} className="btn-primary" style={{ padding: '8px 18px', fontSize: '13px', borderRadius: '8px', fontWeight: 800 }}>GUARDAR</button>
                                        <button onClick={() => setIsEditingName(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '6px' }}><X size={20} /></button>
                                    </div>
                                ) : (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                        <h2 style={{ fontSize: '36px', fontWeight: 900, marginBottom: '0', letterSpacing: '-1.5px', textTransform: 'uppercase' }}>{selectedCompany.name}</h2>
                                        <button
                                            title="Renombrar empresa"
                                            onClick={() => { setEditingNameValue(selectedCompany.name); setIsEditingName(true); }}
                                            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border-glass)', borderRadius: '8px', color: 'var(--text-muted)', cursor: 'pointer', padding: '6px 8px', transition: 'all 0.2s' }}
                                            onMouseOver={e => { e.currentTarget.style.color = 'white'; e.currentTarget.style.borderColor = 'var(--primary)'; }}
                                            onMouseOut={e => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border-glass)'; }}
                                        >
                                            <Pencil size={16} />
                                        </button>
                                    </div>
                                )}
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
                                color: uploadedRequiredCount < totalRequired
                                    ? 'var(--warning)'
                                    : allRequiredAnalyzed
                                        ? 'var(--success)'
                                        : anyRequiredOcrIssue
                                            ? '#f59e0b'
                                            : 'var(--success)', 
                                fontWeight: 800, 
                                fontSize: '14px' 
                            }}>
                                {uploadedRequiredCount < totalRequired
                                    ? 'INCOMPLETO'
                                    : allRequiredAnalyzed
                                        ? 'VERIFICADO'
                                        : anyRequiredOcrIssue
                                            ? 'COMPLETO — REVISAR OCR'
                                            : 'COMPLETO'} ({uploadedRequiredCount}/{totalRequired})
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
                            const docState = getDocOcrState(card.title);
                            const fileInfo = isDocRegistered(card.title);
                            const doc = getCompanyDoc(card.title);
                            const isWarningDoc = docState === 'weak_ocr' || docState === 'ocr_failed';
                            const accentColor = docState === 'processing'
                                ? 'var(--primary)'
                                : isWarningDoc
                                    ? (docState === 'ocr_failed' ? '#ef4444' : '#f59e0b')
                                    : fileInfo
                                        ? 'var(--success)'
                                        : 'inherit';
                            const cardBorder = !fileInfo
                                ? '1px solid var(--border-glass)'
                                : isWarningDoc
                                    ? `1px solid ${docState === 'ocr_failed' ? 'rgba(239, 68, 68, 0.5)' : 'rgba(245, 158, 11, 0.5)'}`
                                    : '1px solid var(--success)';
                            const cardBg = !fileInfo
                                ? 'rgba(255,255,255,0.01)'
                                : isWarningDoc
                                    ? (docState === 'ocr_failed' ? 'rgba(239, 68, 68, 0.05)' : 'rgba(245, 158, 11, 0.05)')
                                    : 'rgba(16, 185, 129, 0.03)';
                            const statusBadge = docState === 'processing'
                                ? 'PROCESANDO...'
                                : docState === 'weak_ocr'
                                    ? 'OCR DÉBIL'
                                    : docState === 'ocr_failed'
                                        ? 'ERROR OCR'
                                        : 'CARGADO';
                            const statusSubtitle = docState === 'ready'
                                ? 'Documento Listo'
                                : docState === 'processing'
                                    ? 'Analizando...'
                                    : docState === 'weak_ocr'
                                        ? 'Revisar legibilidad'
                                        : docState === 'ocr_failed'
                                            ? 'Reintentar subida'
                                            : fileInfo
                                                ? 'Registrado'
                                                : 'Pendiente';
                            return (
                                <div key={i} className="audit-widget" style={{ 
                                    padding: '24px', 
                                    display: 'flex', 
                                    flexDirection: 'column', 
                                    alignItems: 'center', 
                                    gap: '16px', 
                                    position: 'relative',
                                    border: cardBorder,
                                    background: cardBg,
                                    transition: 'all 0.3s ease',
                                    cursor: 'pointer'
                                }}
                                onClick={() => handleFileUploadRequest(card.title)}
                                onMouseOver={(e) => {
                                    e.currentTarget.style.transform = 'translateY(-8px)';
                                    e.currentTarget.style.borderColor = fileInfo ? accentColor : 'var(--primary)';
                                    e.currentTarget.style.boxShadow = '0 10px 30px rgba(0,0,0,0.3)';
                                    e.currentTarget.style.background = fileInfo ? cardBg.replace('0.03', '0.08').replace('0.05', '0.1') : 'rgba(255,255,255,0.05)';
                                }}
                                onMouseOut={(e) => {
                                    e.currentTarget.style.transform = 'translateY(0)';
                                    e.currentTarget.style.borderColor = fileInfo ? accentColor : 'var(--border-glass)';
                                    e.currentTarget.style.boxShadow = 'none';
                                    e.currentTarget.style.background = cardBg;
                                }}
                                >
                                    {card.required && !fileInfo && (
                                        <span style={{ position: 'absolute', top: '10px', right: '10px', fontSize: '9px', background: 'rgba(239, 68, 68, 0.1)', color: '#ef4444', padding: '2px 6px', borderRadius: '4px', fontWeight: 900, border: '1px solid rgba(239, 68, 68, 0.2)' }}>OBLIGATORIO</span>
                                    )}
                                    {fileInfo && (
                                        <span style={{ 
                                            position: 'absolute', 
                                            top: '10px', 
                                            right: '10px', 
                                            fontSize: '9px', 
                                            background: docState === 'processing'
                                                ? 'rgba(59, 130, 246, 0.1)'
                                                : isWarningDoc
                                                    ? (docState === 'ocr_failed' ? 'rgba(239, 68, 68, 0.1)' : 'rgba(245, 158, 11, 0.1)')
                                                    : 'rgba(16, 185, 129, 0.1)', 
                                            color: accentColor, 
                                            padding: '2px 6px', 
                                            borderRadius: '4px', 
                                            fontWeight: 900, 
                                            border: `1px solid ${docState === 'processing'
                                                ? 'rgba(59, 130, 246, 0.2)'
                                                : isWarningDoc
                                                    ? (docState === 'ocr_failed' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(245, 158, 11, 0.2)')
                                                    : 'rgba(16, 185, 129, 0.2)'}`
                                        }}>
                                            {statusBadge}
                                        </span>
                                    )}
                                    {uploadingStatus[card.title] !== undefined ? (
                                        <div style={{ padding: '20px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
                                            <Loader2 className="animate-spin" color="var(--primary)" size={32} />
                                            <div style={{ fontWeight: 800, fontSize: '12px', color: 'var(--primary)' }}>
                                                {uploadingStatus[card.title] < 100 ? `CARGANDO ${uploadingStatus[card.title]}%` : 'ANALIZANDO...'}
                                            </div>
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    if (uploadAbortRef.current) {
                                                        uploadAbortRef.current.abort();
                                                        uploadAbortRef.current = null;
                                                    }
                                                    uploadQueueRef.current = [];
                                                    setUploadingStatus(prev => {
                                                        const s = { ...prev };
                                                        delete s[card.title];
                                                        return s;
                                                    });
                                                }}
                                                style={{
                                                    background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
                                                    color: '#ef4444', borderRadius: '8px', padding: '6px 16px',
                                                    fontSize: '11px', fontWeight: 800, cursor: 'pointer'
                                                }}
                                            >
                                                <X size={12} style={{ marginRight: '6px', display: 'inline' }} />
                                                CANCELAR
                                            </button>
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
                                                color: fileInfo ? accentColor : 'inherit'
                                            }}>
                                                {card.icon}
                                            </div>
                                            <div style={{ textAlign: 'center' }}>
                                                <div style={{ fontWeight: 800, fontSize: '14px' }}>{card.title}</div>
                                                <div style={{ fontSize: '11px', color: fileInfo ? accentColor : 'var(--warning)', marginTop: '4px', textTransform: 'uppercase' }}>
                                                    {statusSubtitle}
                                                </div>
                                                {fileInfo && doc?.name && <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>{doc.name}</div>}
                                                {card.note && !fileInfo && <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '6px', fontStyle: 'italic' }}>{card.note}</div>}
                                            </div>
                                            <button 
                                                type="button"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleFileUploadRequest(card.title);
                                                }}
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
                                    {hasMeaningfulMasterProfile(selectedCompany.master_profile)
                                      ? "Información extraída y validada por la IA."
                                      : isProfileAnalysisProcessing(selectedCompany.master_profile)
                                        ? (isMoral
                                            ? "Extrayendo RFC, representante legal y objeto social del expediente. Esto puede tardar uno o dos minutos."
                                            : "Extrayendo RFC, nombre completo y domicilio fiscal desde INE/CIF. Esto puede tardar uno o dos minutos.")
                                        : (isMoral
                                            ? "Nuestros Agentes procesarán esta documentación para extraer automáticamente tu **Identidad Fiscal, Poderes y Solvencia Legal**."
                                            : "Nuestros Agentes procesarán INE y CIF para extraer automáticamente tu **RFC, Nombre Completo y Domicilio Fiscal**.")}
                                </p>
                            </div>

                            {isProfileAnalysisProcessing(selectedCompany.master_profile) && !isExtracting && (
                                <div style={{
                                    width: '100%',
                                    padding: '16px 20px',
                                    borderRadius: '12px',
                                    border: '1px solid rgba(59, 130, 246, 0.25)',
                                    background: 'rgba(59, 130, 246, 0.08)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '12px',
                                    color: '#dbeafe',
                                    fontSize: '13px',
                                    fontWeight: 600,
                                }}>
                                    <Loader2 size={18} style={{ animation: 'spin 2s linear infinite' }} />
                                    Analizando expediente maestro en segundo plano…
                                </div>
                            )}
                            
                            {hasMeaningfulMasterProfile(selectedCompany.master_profile) && (
                                <div style={{ 
                                    width: '100%', 
                                    display: 'grid', 
                                    gridTemplateColumns: 'repeat(2, 1fr)', 
                                    gap: '16px',
                                    textAlign: 'left'
                                }}>
                                    {profileFields.map((item, idx) => (
                                        <div key={idx} style={{ 
                                            background: 'rgba(255,255,255,0.03)', 
                                            padding: '16px', 
                                            borderRadius: '12px',
                                            border: '1px solid rgba(255,255,255,0.05)',
                                            gridColumn: item.span ? `span ${item.span}` : 'auto'
                                        }}>
                                            <div style={{ fontSize: '9px', fontWeight: 900, color: 'var(--primary)', letterSpacing: '1px', marginBottom: '4px' }}>{item.label}</div>
                                            <div style={{ fontSize: '13px', color: '#fff', fontWeight: 600, whiteSpace: 'pre-wrap' }}>
                                                {formatProfileFieldValue(item.value)}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            <button 
                                className="btn-primary glow-active"
                                disabled={isExtracting || isProfileAnalysisProcessing(selectedCompany.master_profile)}
                                style={{ 
                                    padding: '16px 48px', 
                                    fontSize: '18px', 
                                    borderRadius: '16px',
                                    fontWeight: 800,
                                    cursor: isExtracting ? 'not-allowed' : 'pointer',
                                    paddingLeft: '30px', paddingRight: '30px'
                                }}
                                onClick={async () => {
                                    if (hasMeaningfulMasterProfile(selectedCompany.master_profile)) {
                                        if (!window.confirm("⚠️ ATENCIÓN: Esta empresa ya tiene un Expediente Maestro extraído y validado.\n\nSi continúas, la Inteligencia Artificial volverá a leer los documentos y REESCRIBIRÁ todos los datos actuales.\n\n¿Estás completamente seguro de que deseas reescribir el expediente?")) {
                                            return;
                                        }
                                    }
                                    setIsExtracting(true);
                                    let progressItem = 0;
                                    const sim = setInterval(() => {
                                        progressItem += 2;
                                        setExtractionProgress(prev => prev >= 95 ? 95 : prev + 2);
                                    }, 200);
                                    const controller = new AbortController();
                                    analyzeAbortRef.current = controller;

                                    try {
                                        const res = await axios.post(`${API_BASE}/companies/${selectedCompany.id}/analyze`, {}, {
                                            signal: controller.signal
                                        });
                                        analyzeAbortRef.current = null;
                                        clearInterval(sim);
                                        setExtractionProgress(100);

                                        if (res.data.success) {
                                            setTimeout(() => {
                                                const formatted = formatCompanyFromApi(res.data.data);
                                                setSelectedCompany(formatted);
                                                setCompanies(prev => prev.map(c => c.id === formatted.id ? formatted : c));
                                                setIsExtracting(false);
                                                setExtractionProgress(0);
                                                const rr = res.data.rfc_resolution;
                                                let msg = '¡Perfil Maestro Actualizado!';
                                                if (rr && rr.changed_from_llm) {
                                                    msg = `RFC corregido automáticamente: ${String(rr.previous_llm_rfc || '—')} → ${String(rr.final_rfc || '')}. Si subes o sustituyes documentos, vuelve a pulsar «RE-ANALIZAR EXPEDIENTE».`;
                                                } else if (formatted.type === 'moral' && formatted.master_profile?.rfc) {
                                                    msg = '¡Perfil Maestro actualizado! Si cambias el expediente (nuevos PDF), usa de nuevo «RE-ANALIZAR EXPEDIENTE» para refrescar OCR y perfil.';
                                                }
                                                setNotification({ type: 'success', message: msg });
                                                setTimeout(() => setNotification(null), rr && rr.changed_from_llm ? 9000 : 5000);
                                            }, 500);
                                        } else {
                                            throw new Error(res.data.message);
                                        }
                                    } catch (error) {
                                        clearInterval(sim);
                                        analyzeAbortRef.current = null;
                                        if (axios.isCancel(error) || error.name === 'CanceledError' || error.name === 'AbortError') {
                                            console.log('⛔ Análisis cancelado por usuario');
                                            setNotification({ type: 'info', message: 'Análisis cancelado. El documento no fue modificado.' });
                                            setTimeout(() => setNotification(null), 4000);
                                        } else {
                                            console.error("Analysis error", error);
                                            alert("Hubo un error al extraer la información.");
                                        }
                                        setIsExtracting(false);
                                        setExtractionProgress(0);
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
                                        {hasMeaningfulMasterProfile(selectedCompany.master_profile) ? 'RE-ANALIZAR EXPEDIENTE' : 'ANALIZAR EXPEDIENTE MAESTRO'}
                                    </>
                                )}
                            </button>

                            {isExtracting && (
                                <button
                                    onClick={() => {
                                        if (analyzeAbortRef.current) {
                                            analyzeAbortRef.current.abort();
                                            analyzeAbortRef.current = null;
                                        }
                                        setIsExtracting(false);
                                        setExtractionProgress(0);
                                    }}
                                    style={{
                                        padding: '12px 32px', fontSize: '14px', borderRadius: '12px',
                                        fontWeight: 800, background: 'rgba(239,68,68,0.1)',
                                        border: '1px solid rgba(239,68,68,0.4)', color: '#ef4444',
                                        cursor: 'pointer'
                                    }}
                                >
                                    <X size={16} style={{ marginRight: '8px', display: 'inline', verticalAlign: 'middle' }} />
                                    CANCELAR ANÁLISIS
                                </button>
                            )}
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
                        onClick={async () => {
                            profileAnalysisNotifiedRef.current = null;
                            setIsExtracting(false);
                            setExtractionProgress(0);
                            setUploadingStatus({});
                            try {
                                const res = await axios.get(`${API_BASE}/companies/${company.id}`);
                                if (res.data.success) {
                                    setSelectedCompany(formatCompanyFromApi(res.data.data));
                                } else {
                                    setSelectedCompany(company);
                                }
                            } catch (error) {
                                console.error('Error cargando empresa', error);
                                setSelectedCompany(company);
                            }
                        }}
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
                    background: notification.type === 'success' ? 'var(--success)' : notification.type === 'info' ? 'var(--primary)' : 'var(--error)',
                    color: '#fff',
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
                    {notification.type === 'info' ? <X size={24} /> : <CheckCircle2 size={24} />}
                    {notification.message}
                </div>
            )}
        </div>
    );
};

export default CompaniesManager;
