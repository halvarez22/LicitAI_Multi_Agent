import React, { useState, useEffect, useRef, useCallback } from 'react';
import { 
    FileText, Search, Shield, AlertTriangle, CheckCircle, 
    Download, Clock, ChevronRight, MessageSquare, Bot, 
    User, Send, Bell, Plus, FileSearch, Loader2, ArrowLeft,
    Copy, DownloadCloud, FileCheck, Info, Trash2, Eraser, RefreshCw
} from 'lucide-react';
import axios from 'axios';
import DeliveryPanel from './components/DeliveryPanel';
import SubmissionChecklistPanel from './components/SubmissionChecklistPanel';
import PostClarificationPanel from './components/PostClarificationPanel';
import EconomicValidationPanel from './components/EconomicValidationPanel';
import Dashboard from './components/Dashboard';
import ExportPDF from './components/ExportPDF';
import LicitacionesGrid from './components/LicitacionesGrid';
import ForensicCard from './components/ForensicCard';
import {
    processAuditResults,
    ZONA_TAB_ORDER,
    enrichDictamenFromStorage,
    applyInfrastructureUxOverrides,
    synthesizePipelineTelemetryFromDictamen,
} from './utils/auditSummary';
import { LICITAI_APP_VERSION } from './appVersion.js';
import { API_BASE } from './apiBase.js';

/**
 * Claves `${sessionId}::${companyKey}` ya usadas para el bootstrap del chat (POST /chatbot/ask vacío).
 * Vive fuera del componente para sobrevivir al doble montaje de React Strict Mode (los useRef se reinician).
 */
const chatProactiveBootstrapDoneKeys = new Set();

const AGENTS_JOB_POLL_MS = 2500;
const AGENTS_JOB_TIMEOUT_MS = 40 * 60 * 1000;

/**
 * El backend responde 202 a POST /agents/process con job_id; el resultado real llega vía GET .../jobs/{id}/status.
 * @param {string} jobId
 * @param {(msg: string) => void} [onProgress]
 * @returns {Promise<object>} Cuerpo `result` guardado en Redis (status, data, chatbot_message, …)
 */
/**
 * @typedef {{ message?: string, pct?: number, status?: string }} JobProgressUpdate
 * @param {string} jobId
 * @param {(u: JobProgressUpdate) => void} [onProgress] — `pct` viene del backend (`job.progress.pct`, 0–100).
 */
async function pollAgentsJobUntilDone(jobId, onProgress) {
    const t0 = Date.now();
    while (Date.now() - t0 < AGENTS_JOB_TIMEOUT_MS) {
        const st = await axios.get(`${API_BASE}/agents/jobs/${jobId}/status`, { timeout: 120000 });
        if (!st.data?.success) {
            throw new Error(st.data?.message || 'No se pudo leer el estado del análisis.');
        }
        const job = st.data.data || {};
        const prog = job.progress || {};
        const msg = prog.message;
        const rawPct = prog.pct;
        const pct = typeof rawPct === 'number' && !Number.isNaN(rawPct) ? rawPct : undefined;
        if (onProgress && (msg || pct !== undefined || job.status === 'COMPLETED' || job.status === 'FAILED')) {
            onProgress({ message: msg, pct, status: job.status });
        }
        if (job.status === 'COMPLETED') {
            if (!job.result) throw new Error('Job completado sin resultado en el servidor.');
            return job.result;
        }
        if (job.status === 'FAILED') {
            const err = job.error || job.forensic_traceback || 'El análisis falló en el servidor.';
            throw new Error(typeof err === 'string' ? err : JSON.stringify(err));
        }
        await new Promise((r) => setTimeout(r, AGENTS_JOB_POLL_MS));
    }
    throw new Error('Tiempo de espera agotado. El análisis sigue en curso o el servidor tardó demasiado; revisa los logs del backend.');
}

/** Fallbacks en español si el backend devuelve waiting_for_data sin chatbot_message */
const WAITING_FOR_DATA_FALLBACK_AUDIT_ES =
    "El análisis quedó en pausa: faltan datos para continuar (por ejemplo precios o expediente). Revisa el mensaje del sistema o completa lo que te pida el asistente y vuelve a intentar cuando esté listo.";
const WAITING_FOR_DATA_FALLBACK_GENERATION_ES =
    "Faltan datos para generar documentos. Revisa la lista anterior o sube la documentación indicada; cuando los tengas, responde aquí o vuelve a pulsar Generar.";

// --- Sub-componente para mostrar resultados de auditoría ---
const AnalysisResults = ({ results, onAskExpert, sessionId, companyId }) => {
    const [activeZoneTab, setActiveZoneTab] = useState('all');
    const [expandedKey, setExpandedKey] = useState(null);

    useEffect(() => {
        setExpandedKey(null);
    }, [activeZoneTab]);

    if (!results) return null;

    const porZona = results.compliancePorZona || {};
    const allCompliance = results.causales.filter((c) => c.category === 'compliance');
    const otrosHallazgos = results.causales.filter((c) => c.category !== 'compliance');
    const visibleCompliance =
        activeZoneTab === 'all' ? allCompliance : porZona[activeZoneTab] || [];
    const otrasZonasList = porZona._OTRAS_ZONAS || [];
    const tabBtn = (id, label, count, isActive) => (
        <button
            type="button"
            key={id}
            onClick={() => setActiveZoneTab(id)}
            style={{
                padding: '6px 10px',
                borderRadius: '10px',
                border: isActive ? '1px solid var(--primary)' : '1px solid rgba(255,255,255,0.08)',
                background: isActive ? 'rgba(0, 212, 255, 0.12)' : 'rgba(0,0,0,0.25)',
                color: '#fff',
                fontSize: '10px',
                fontWeight: 800,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
            }}
        >
            {label} ({count})
        </button>
    );

    return (
        <div style={{ maxHeight: '600px', overflowY: 'auto', padding: '15px', background: 'rgba(255,255,255,0.02)', borderRadius: '20px', border: '1px solid rgba(255,255,255,0.05)', scrollbarWidth: 'thin' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: '15px', paddingBottom: '15px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                    <Shield size={20} color="var(--primary)" />
                    <h3 style={{ fontSize: '15px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '1px' }}>Dictamen Forense</h3>
                </div>
                <ExportPDF auditResults={results} sessionId={sessionId} />
            </div>
            
            {results.uxGuiaUsuario && (
                <div
                    style={{
                        marginBottom: '16px',
                        padding: '14px 16px',
                        borderRadius: '14px',
                        background: 'rgba(56, 189, 248, 0.08)',
                        border: '1px solid rgba(56, 189, 248, 0.35)',
                        fontSize: '12px',
                        lineHeight: 1.55,
                        color: 'rgba(255,255,255,0.88)',
                    }}
                >
                    <div style={{ fontWeight: 800, marginBottom: '6px', color: '#7dd3fc' }}>Qué significa esto</div>
                    {results.uxGuiaUsuario}
                </div>
            )}

            <div style={{ marginBottom: '20px', padding: '15px', borderRadius: '15px', background: 'rgba(0,0,0,0.3)', border: `1px solid ${results.statusColor || 'rgba(255,255,255,0.02)'}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                    <div style={{ fontSize: '14px', fontWeight: 900, color: results.statusColor || '#2ecc71' }}>{results.status || "✅ COMPLETADO"}</div>
                </div>
                {results.errorText && <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '10px' }}>{results.errorText}</div>}
                
                {results.zones && results.zones.filter(z => z.status !== 'pass').length > 0 && (
                    <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {results.zones.filter(z => z.status !== 'pass').map((z, idx) => (
                             <div key={idx} style={{ padding: '10px', background: 'rgba(255,255,255,0.02)', borderRadius: '10px', fontSize: '11px', borderLeft: `3px solid ${z.status === 'partial' ? '#f39c12' : '#e74c3c'}` }}>
                                 <strong style={{ color: z.status === 'partial' ? '#f39c12' : '#e74c3c' }}>{z.zone} ({z.status.toUpperCase()}):</strong> <span style={{ color: 'var(--text-muted)' }}>{z.reason}</span>
                             </div>
                        ))}
                    </div>
                )}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '20px' }}>
                <div className="audit-widget">
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)', fontWeight: 800 }}>REQUISITOS (TOTAL)</div>
                    <div style={{ fontSize: '24px', fontWeight: 900 }}>{results.totalRequisitos}</div>
                </div>
                <div className="audit-widget">
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)', fontWeight: 800 }}>RIESGOS</div>
                    <div style={{ fontSize: '24px', fontWeight: 900, color: '#ff4d4d' }}>{results.riesgos}</div>
                </div>
            </div>

            {allCompliance.length > 0 && (
                <div style={{ marginBottom: '16px' }}>
                    <div style={{ fontSize: '10px', fontWeight: 900, color: 'var(--text-muted)', marginBottom: '8px', letterSpacing: '0.5px' }}>
                        COMPLIANCE POR ZONA DE EXTRACCIÓN
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' }}>
                        {tabBtn('all', 'Todos', allCompliance.length, activeZoneTab === 'all')}
                        {ZONA_TAB_ORDER.map((z) => {
                            const n = (porZona[z] || []).length;
                            if (n === 0) return null;
                            const short = z.replace('/LEGAL', '').replace('/ANEXOS', '').replace('/SEGUROS', '').replace('/OPERATIVO', '');
                            return tabBtn(z, short, n, activeZoneTab === z);
                        })}
                        {otrasZonasList.length > 0
                            ? tabBtn('_OTRAS_ZONAS', 'Otras zonas', otrasZonasList.length, activeZoneTab === '_OTRAS_ZONAS')
                            : null}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {visibleCompliance.map((c, i) => {
                            const cardKey = `${activeZoneTab}-${i}-${c.id || ''}`;
                            return (
                                <ForensicCard
                                    key={cardKey}
                                    ubicacion={c.page}
                                    seccion={c.tipo}
                                    textoLiteral={typeof c.texto === 'object' ? (c.texto.descripcion || c.texto.nombre || JSON.stringify(c.texto)) : c.texto}
                                    snippet={c.snippet}
                                    zonaOrigen={c.zona_origen}
                                    bucketKey={c.bucketKey}
                                    zonaExplicita={c.zona_explicita !== false}
                                    categoriaLlm={c.categoria_llm}
                                    isExpanded={expandedKey === cardKey}
                                    isRisk={c.isRisk}
                                    onClick={() => setExpandedKey(expandedKey === cardKey ? null : cardKey)}
                                    onAskExpert={onAskExpert}
                                    sessionId={sessionId}
                                    agentId={c.agent_id}
                                    entityRef={c.id}
                                    companyId={companyId}
                                />
                            );
                        })}
                    </div>
                </div>
            )}

            {otrosHallazgos.length > 0 && (
                <div style={{ marginTop: '8px' }}>
                    <div style={{ fontSize: '10px', fontWeight: 900, color: 'var(--text-muted)', marginBottom: '8px', letterSpacing: '0.5px' }}>
                        OTROS HALLAZGOS (BASES, RIESGOS, ECONÓMICO)
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {otrosHallazgos.map((c, i) => {
                            const cardKey = `otros-${i}-${c.id || ''}`;
                            return (
                                <ForensicCard
                                    key={cardKey}
                                    ubicacion={c.page}
                                    seccion={c.tipo}
                                    textoLiteral={typeof c.texto === 'object' ? (c.texto.descripcion || c.texto.nombre || JSON.stringify(c.texto)) : c.texto}
                                    snippet={c.snippet}
                                    isExpanded={expandedKey === cardKey}
                                    isRisk={c.isRisk}
                                    onClick={() => setExpandedKey(expandedKey === cardKey ? null : cardKey)}
                                    onAskExpert={onAskExpert}
                                    sessionId={sessionId}
                                    agentId={c.agent_id}
                                    entityRef={c.id}
                                    companyId={companyId}
                                />
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
};

const App = () => {
    // 1. ESTADOS DE SESIÓN Y COMPAÑÍA (Carga inicial desde persistencia)
    const [sessionId, setSessionId] = useState(() => {
        const saved = localStorage.getItem('licit_session_id');
        return (saved && saved !== "null") ? saved : null;
    });
    const [sessionName, setSessionName] = useState('');
    const [companies, setCompanies] = useState([]);
    const [selectedCompanyId, setSelectedCompanyId] = useState(() => 
        localStorage.getItem('licitai_selected_company') || ''
    );


    // 2. ESTADOS DE UI
    const [sources, setSources] = useState([]);
    const [auditResults, setAuditResults] = useState(null);
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [isGenerating, setIsGenerating] = useState(false);
    const [reprocessingDocId, setReprocessingDocId] = useState(null);
    const [auditProgress, setAuditProgress] = useState({ percent: 0, currentFile: "" });
    const [chatMessages, setChatMessages] = useState([]);
    const [chatInput, setChatInput] = useState("");
    const [isThinking, setIsThinking] = useState(false);
    const [generationResults, setGenerationResults] = useState(null);
    const [dragOffset, setDragOffset] = useState({ x: 30, y: 30 });
    const [isDragging, setIsDragging] = useState(false);

    // --- RESIZE STATES: Para anchos de páneles ajustables ---
    const [leftWidth, setLeftWidth] = useState(300);
    const [rightWidth, setRightWidth] = useState(400);
    const [isResizingLeft, setIsResizingLeft] = useState(false);
    const [isResizingRight, setIsResizingRight] = useState(false);
    const [isHoverLeft, setIsHoverLeft] = useState(false);
    const [isHoverRight, setIsHoverRight] = useState(false);

    const fileInputRef = useRef(null);
    const chatEndRef = useRef(null);
    /** Solo para limpiar claves del Set de módulo al cambiar de sesión. */
    const prevSessionIdForChatBootstrapRef = useRef(null);

    // --- HELPER: Inyectar guía del asistente en el chat ---
    const pushAssistantGuidance = (text, isGlow = false) => {
        const body = text || "⚠️ No se recibió mensaje del asistente.";
        const botMsg = { sender: 'bot', text: body, isGlow: isGlow };
        setChatMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.sender === 'bot' && last?.text === body) return prev;
            return [...prev, botMsg];
        });
        
        // Foco visual: Scroll automático al nuevo mensaje
        setTimeout(() => {
            chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }, 100);
    };

    const clearExpertChat = () => {
        setChatMessages([]);
        setIsThinking(false);
    };

    // RESIZE & PERSISTENCIA
    useEffect(() => {
        const handleMouseMove = (e) => {
            if (isResizingLeft) {
                const newWidth = Math.max(200, Math.min(e.clientX, 600));
                setLeftWidth(newWidth);
            }
            if (isResizingRight) {
                const newWidth = Math.max(250, Math.min(window.innerWidth - e.clientX, 800));
                setRightWidth(newWidth);
            }
        };
        const handleMouseUp = () => {
            setIsResizingLeft(false);
            setIsResizingRight(false);
        };
        if (isResizingLeft || isResizingRight) {
            window.addEventListener('mousemove', handleMouseMove);
            window.addEventListener('mouseup', handleMouseUp);
        }
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isResizingLeft, isResizingRight]);

    useEffect(() => {
        if (sessionId) {
            localStorage.setItem('licit_session_id', sessionId);
        } else {
            localStorage.removeItem('licit_session_id');
        }
    }, [sessionId]);

    useEffect(() => {
        prevSessionIdForChatBootstrapRef.current = sessionId;
    }, [sessionId]);

    // Tras elegir empresa: primera llamada al chat con query vacía (API ya lo permite) para mostrar pending_questions o mensaje guía.
    useEffect(() => {
        if (!sessionId) return;

        // El bloqueo vive en el Set de módulo (fuera del componente).
        // Se borra en F5 (permitiendo un nuevo saludo) pero persiste entre montajes de Strict Mode.
        const key = `bootstrap::${sessionId}`;
        if (chatProactiveBootstrapDoneKeys.has(key)) return;
        chatProactiveBootstrapDoneKeys.add(key);

        console.log(`[LicitAI] Chat Bootstrap iniciado para: ${sessionId}`);

        let cancelled = false;
        (async () => {
            try {
                const res = await axios.post(`${API_BASE}/chatbot/ask`, {
                    query: '',
                    session_id: sessionId,
                    company_id: selectedCompanyId || null,
                });
                if (cancelled) return;
                const text = (res.data?.reply || '').trim();
                if (!text) return;
                
                setChatMessages((prev) => {
                    // Evitar duplicidad visual total mediante chequeo de contenido en todo el historial reciente.
                    if (prev.some(m => m.text === text)) return prev;
                    
                    const glow = text.includes('📋') || text.includes('**') || text.includes('✨');
                    const updated = [...prev, { sender: 'bot', text, isGlow: glow }];
                    
                    setTimeout(() => {
                        chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
                    }, 100);
                    
                    return updated;
                });
            } catch (err) {
                console.warn('[LicitAI] Error en bootstrap del chat:', err);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [sessionId]);



    useEffect(() => {
        if (selectedCompanyId) {
            localStorage.setItem('licitai_selected_company', selectedCompanyId);
        }
    }, [selectedCompanyId]);

    const fetchSources = useCallback(async () => {
        if (!sessionId || sessionId === 'null') return;
        try {
            const res = await axios.get(
                `${API_BASE}/upload/list/${encodeURIComponent(sessionId)}`
            );
            const raw = res.data?.data?.documents;
            const docs = Array.isArray(raw) ? raw : [];
            console.log(`[LicitAI] fetchSources → ${docs.length} doc(s) para sesión: ${sessionId}`);
            setSources(docs);
        } catch (err) {
            console.error('[LicitAI] Error fetchSources:', err);
            // No vaciamos sources: mejor lista stale que vacía si falla la red
        }
    }, [sessionId]);

    // CARGA INICIAL (Solo si hay sesión)
    useEffect(() => {
        if (sessionId) {
            // NO limpiamos sources aquí para evitar el flash de lista vacía.
            fetchCompanies();
            fetchSources();
            fetchSessionName();
            fetchDictamen();

            const savedCompany = localStorage.getItem('licitai_selected_company');
            if (savedCompany) {
                setSelectedCompanyId(savedCompany);
            } else {
                setSelectedCompanyId('');
            }
        }
    }, [sessionId, fetchSources]);

    const fetchSessionName = async () => {
        try {
            const res = await axios.get(`${API_BASE}/sessions`);
            if (res.data.success) {
                const found = res.data.data.licitaciones.find(s => s.id === sessionId);
                if (found) setSessionName(found.name);
            }
        } catch (err) {
            console.error("Error fetching session name:", err);
        }
    };

    const fetchDictamen = async () => {
        if (!sessionId || sessionId === "null") return;
        try {
            const res = await axios.get(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/dictamen`
            );
            if (res.data.success && res.data.data.dictamen) {
                const d = res.data.data.dictamen;
                // Dictámenes viejos: se guardó "éxito" con 0 ítems al confundir job_id con resultados del orquestador.
                const looksLikeStaleEnqueueBug =
                    d.dictamen_schema_version !== 2 &&
                    d.statusRaw === 'success' &&
                    (d.totalRequisitos === 0 || d.totalRequisitos == null) &&
                    (!Array.isArray(d.causales) || d.causales.length === 0);
                if (looksLikeStaleEnqueueBug) {
                    console.warn(
                        '[LicitAI] Ignorando dictamen en Postgres (posible guardado erróneo pre-job-polling). Pulsa de nuevo «Analizar bases».'
                    );
                    setAuditResults(null);
                    return;
                }
                let enriched = enrichDictamenFromStorage(d);
                const inferredTelem = synthesizePipelineTelemetryFromDictamen(enriched);
                if (inferredTelem) {
                    enriched = { ...enriched, pipelineTelemetry: inferredTelem };
                }
                setAuditResults(applyInfrastructureUxOverrides(enriched));
            }
        } catch (err) {
            console.error("Error fetching dictamen from Postgres:", err);
        }
    };

    const saveDictamenToPostgres = async (dictamen) => {
        try {
            await axios.post(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/dictamen`,
                { dictamen: dictamen }
            );
        } catch (err) {
            console.error("Error saving dictamen to Postgres:", err);
        }
    };

    const fetchCompanies = async () => {
        try {
            const res = await axios.get(`${API_BASE}/companies/`);
            setCompanies(res.data.data || []);
        } catch (err) {
            console.error("Error fetching companies:", err);
        }
    };

    const handleFileUpload = async (e) => {
        const files = Array.from(e.target.files);
        if (files.length === 0) return;

        setIsAnalyzing(true);

        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('session_id', sessionId);
            
            try {
                // PASO 1: Subir archivo al servidor
                setAuditProgress({ percent: 10, currentFile: `📤 Subiendo ${file.name}...` });
                const uploadRes = await axios.post(`${API_BASE}/upload/upload`, formData);
                
                if (!uploadRes.data.success) {
                    console.error("Error en upload:", uploadRes.data.message);
                    continue;
                }

                const doc_id = uploadRes.data.data?.doc_id;
                if (!doc_id) {
                    console.error("No se recibió doc_id del servidor.");
                    continue;
                }

                // PASO 2: Disparar extracción OCR + indexación vectorial
                setAuditProgress({ percent: 40, currentFile: `🔍 Extrayendo texto de ${file.name}...` });
                const formDataProcess = new FormData();
                formDataProcess.append('session_id', sessionId);
                
                const processRes = await axios.post(
                    `${API_BASE}/upload/process/${doc_id}`,
                    formDataProcess,
                    { timeout: 600000 }
                );

                if (processRes.data.success) {
                    setAuditProgress({ percent: 90, currentFile: `✅ ${file.name} indexado correctamente.` });
                    console.log(`✅ ${file.name} procesado e indexado.`);
                } else {
                    console.error(`Error procesando ${file.name}:`, processRes.data.message);
                }

            } catch (err) {
                console.error("Error en pipeline de ingesta:", file.name, err);
                setAuditProgress({ percent: 0, currentFile: `❌ Error procesando ${file.name}` });
            }
        }
        
        await fetchSources();
        setIsAnalyzing(false);
        setAuditProgress({ percent: 0, currentFile: "" });
    };


    const handleDeleteSource = async (docId, docName) => {
        const etiqueta = docName ? ` «${docName}»` : '';
        const avisoQuitarDocumento =
            `¿Quitar este documento${etiqueta} de la licitación?\n\n` +
            'Si lo quitas, el informe de auditoría (dictamen) y los resultados de generación dejarán de mostrarse, ' +
            'porque ya no coinciden con la documentación que tienes en esta carpeta. No se borra la licitación en sí: ' +
            'solo se actualiza lo que puedes consultar hasta que vuelvas a tener las bases cargadas y pulses «Actualizar análisis».\n\n' +
            '¿Quieres continuar?';

        if (!window.confirm(avisoQuitarDocumento)) return;

        try {
            const formData = new FormData();
            formData.append('session_id', sessionId);
            await axios.delete(`${API_BASE}/upload/${docId}`, { data: formData });

            setAuditResults(null);
            setGenerationResults(null);

            fetchSources();

            pushAssistantGuidance(
                'Listo: ese documento ya no forma parte de la licitación. El informe que veías dejó de mostrarse porque estaba ligado a los archivos que tenías; es normal, no significa que se haya “perdido” la licitación. Cuando tengas otra vez las bases en la lista de la izquierda, pulsa «Actualizar análisis» para obtener un informe nuevo.',
                true
            );
        } catch (err) {
            console.error("Error deleting source:", err);
            alert('No se pudo quitar el documento. Intenta de nuevo en unos momentos.');
        }
    };

    const handleReprocessSource = async (docId, docName) => {
        if (!sessionId || reprocessingDocId) return;
        const etiqueta = docName ? ` «${docName}»` : '';
        const ok = window.confirm(
            `¿Volver a procesar${etiqueta}?\n\n` +
                'Se eliminarán los fragmentos vectoriales antiguos de este archivo y se repetirá la extracción ' +
                '(PDF/imagen → OCR; Excel → partidas en base de datos + índice). ' +
                'Luego puedes pulsar «Actualizar análisis».\n\n' +
                '¿Continuar?'
        );
        if (!ok) return;

        setReprocessingDocId(docId);
        setAuditProgress({ percent: 12, currentFile: `↻ Reprocesando ${docName || 'documento'}…` });
        try {
            const formData = new FormData();
            formData.append('session_id', sessionId);
            await axios.post(
                `${API_BASE}/upload/process/${docId}?force=true`,
                formData,
                { timeout: 600000 }
            );
            setAuditProgress({ percent: 100, currentFile: `✅ ${docName || 'Documento'} reindexado` });
            await fetchSources();
            setTimeout(() => setAuditProgress({ percent: 0, currentFile: '' }), 1600);
            pushAssistantGuidance(
                `Listo: «${docName || docId}» se reprocesó (vectores y, si es Excel, partidas económicas). Pulsa «Actualizar análisis» cuando quieras refrescar el dictamen.`,
                false
            );
        } catch (err) {
            console.error('Error reprocesando fuente:', err);
            const det = err?.response?.data?.detail;
            alert(
                typeof det === 'string'
                    ? det
                    : err?.message || 'No se pudo reprocesar el documento.'
            );
            setAuditProgress({ percent: 0, currentFile: '' });
        } finally {
            setReprocessingDocId(null);
        }
    };

    const triggerFullAudit = async () => {
        setIsAnalyzing(true);
        setAuditProgress({ percent: 10, currentFile: "Iniciando Auditoría..." });

        const pulseInterval = setInterval(() => {
            setAuditProgress(prev => {
                if (prev.percent < 90) return { ...prev, percent: prev.percent + 2 };
                return prev;
            });
        }, 3000);

        try {
            const res = await axios.post(`${API_BASE}/agents/process`, {
                session_id: sessionId,
                company_id: selectedCompanyId || null,
                company_data: { "mode": "analysis_only" }
            });

            clearInterval(pulseInterval);

            const encolado = res.data?.data;
            let orchestrator = null;

            if (encolado?.job_id) {
                setAuditProgress((prev) => ({
                    ...prev,
                    currentFile: 'Análisis en servidor: sincronizando estado…',
                }));
                orchestrator = await pollAgentsJobUntilDone(encolado.job_id, (u) => {
                    setAuditProgress((prev) => {
                        const nextMsg = u.message || prev.currentFile;
                        let nextPct = prev.percent;
                        if (typeof u.pct === 'number' && !Number.isNaN(u.pct)) {
                            const p = Math.max(0, Math.min(100, u.pct));
                            nextPct = Math.max(prev.percent, p);
                        }
                        return { ...prev, currentFile: nextMsg, percent: nextPct };
                    });
                });
            } else if (encolado && (encolado.analysis || encolado.compliance || encolado.economic)) {
                orchestrator = {
                    status: res.data.status,
                    data: encolado,
                    chatbot_message: res.data.chatbot_message,
                    agent_decision: res.data.agent_decision,
                    pipelineTelemetry: res.data.pipelineTelemetry,
                };
            }

            if (orchestrator?.data) {
                const auditPayload = {
                    ...orchestrator.data,
                    ...(orchestrator.agent_decision && typeof orchestrator.agent_decision === 'object'
                        ? { orchestrator_decision: orchestrator.agent_decision }
                        : {}),
                    ...(orchestrator.pipelineTelemetry && typeof orchestrator.pipelineTelemetry === 'object'
                        ? { pipelineTelemetry: orchestrator.pipelineTelemetry }
                        : {}),
                    ...(orchestrator.metadata && typeof orchestrator.metadata === 'object'
                        ? { metadata: orchestrator.metadata }
                        : {}),
                };
                const nuevosDictamen = processAuditResults(auditPayload);
                if (nuevosDictamen) {
                    nuevosDictamen.dictamen_schema_version = 2;
                    nuevosDictamen.fechaAuditoria = new Date().toLocaleString('es-MX');
                    setAuditResults(nuevosDictamen);
                    await saveDictamenToPostgres(nuevosDictamen);
                } else {
                    console.error('processAuditResults devolvió null; payload:', auditPayload);
                    pushAssistantGuidance(
                        'El análisis terminó pero el formato de resultados no es reconocible. Revisa la consola y los logs del backend.',
                        true
                    );
                }
            }

            const orchStatus = orchestrator?.status;
            if (orchStatus === 'success') {
                pushAssistantGuidance(
                    "Análisis de bases completado. El dictamen forense está actualizado y la información ya está indexada para consultas. Si necesitas generar documentos o completar datos del expediente, te iré guiando por este chat.",
                    false
                );
            } else if (orchStatus === 'waiting_for_data') {
                let waitMsg = orchestrator?.chatbot_message || WAITING_FOR_DATA_FALLBACK_AUDIT_ES;
                const hints = orchestrator?.agent_decision?.waiting_hints;
                const gapAlerts = Array.isArray(hints?.alertas_contexto_bases)
                    ? hints.alertas_contexto_bases.filter(Boolean)
                    : [];
                if (gapAlerts.length) {
                    waitMsg +=
                        '\n\n**Avisos de bases y partidas (revisar antes de cotizar):**\n' +
                        gapAlerts.slice(0, 8).map((x) => `• ${x}`).join('\n');
                }
                pushAssistantGuidance(waitMsg, true);
            } else if (orchStatus === 'error') {
                pushAssistantGuidance(
                    orchestrator?.chatbot_message || "No se pudo completar el análisis de las bases. Revisa el estado de las fuentes o los logs del sistema.",
                    true
                );
            }

            const cierreMsg =
                orchStatus === 'success'
                    ? 'Análisis completado'
                    : orchStatus === 'waiting_for_data'
                      ? 'Análisis en pausa: faltan datos'
                      : orchStatus === 'error'
                        ? 'Proceso finalizado con incidencias'
                        : 'Proceso finalizado';
            setAuditProgress((prev) => ({ ...prev, percent: 100, currentFile: cierreMsg }));
            await new Promise((r) => setTimeout(r, 700));

            await fetchSources();

        } catch (err) {
            clearInterval(pulseInterval);
            console.error("Audit error:", err);
            setAuditProgress((prev) => ({
                ...prev,
                currentFile: 'Error durante el análisis',
                percent: Math.max(prev.percent, 5),
            }));
            await new Promise((r) => setTimeout(r, 450));
            alert(err?.message || "Error durante la auditoría. Revisa el backend.");
        } finally {
            setIsAnalyzing(false);
            setAuditProgress({ percent: 0, currentFile: "" });
        }
    };

    const triggerGeneration = async () => {
        if (!selectedCompanyId) {
            alert("Selecciona una empresa en la barra superior para guardar tus datos.");
            return;
        }

        setGenerationResults(null); 
        pushAssistantGuidance("🚀 Validando expediente y preparando documentos...", false);
        setIsGenerating(true);

        try {
            const res = await axios.post(`${API_BASE}/agents/process`, {
                session_id: sessionId,
                company_id: selectedCompanyId,
                company_data: { "mode": "generation_only" }
            });

            const encolado = res.data?.data;
            let orchestrator = null;

            if (encolado?.job_id) {
                orchestrator = await pollAgentsJobUntilDone(encolado.job_id);
            } else if (encolado) {
                orchestrator = { status: res.data.status, data: encolado, chatbot_message: res.data.chatbot_message };
            }

            const orchStatus = orchestrator?.status;
            if (orchStatus === "waiting_for_data") {
                pushAssistantGuidance(
                    orchestrator?.chatbot_message || WAITING_FOR_DATA_FALLBACK_GENERATION_ES,
                    true
                );
            } else if (orchStatus === "success") {
                setGenerationResults(orchestrator.data || orchestrator);
                pushAssistantGuidance("✅ Documentos generados con éxito. Puedes revisarlos en el panel de expedientes.", false);
            } else if (orchStatus === "error") {
                pushAssistantGuidance(
                    orchestrator?.chatbot_message || "No se pudo completar la generación. Revisa el backend o vuelve a intentar.",
                    true
                );
            }

        } catch (err) {
            console.error("Generation error:", err);
            alert(err?.message || "Error en la generación.");
        } finally {
            setIsGenerating(false);
        }
    };

    const handleSendMessage = async (e) => {
        if (e) e.preventDefault();
        if (!chatInput.trim()) return;

        // Validación de contexto para Intake
        if (!selectedCompanyId) {
             setChatMessages(prev => [...prev, { sender: 'bot', text: "⚠️ Selecciona una empresa en la barra superior para que pueda guardar tus datos." }]);
             return;
        }

        const userMsg = { sender: 'user', text: chatInput };
        setChatMessages(prev => [...prev, userMsg]);
        setChatInput("");
        setIsThinking(true);

        try {
            const res = await axios.post(`${API_BASE}/chatbot/ask`, {
                query: chatInput,
                session_id: sessionId,
                company_id: selectedCompanyId
            });
            
            const botData = res.data?.data || {};
            const botMsg = { 
                sender: 'bot', 
                text: botData.respuesta || res.data.reply,
                citations: botData.citas || res.data.citations || [],
                confidence: botData.confianza || res.data.confidence,
                isGlow: botData.tipo === 'data_saved' || botData.tipo === 'pending_question'
            };
            setChatMessages(prev => [...prev, botMsg]);
            
            // Auto-scroll
            setTimeout(() => {
                chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
            }, 100);

        } catch (err) {
            console.error("Chat error:", err);
        } finally {
            setIsThinking(false);
        }
    };

    // --- VISTA DE SELECCIÓN ---
    if (!sessionId) {
        return <LicitacionesGrid onSelectSession={(id) => setSessionId(id)} />;
    }

    // --- VISTA DE TRABAJO ---
    return (
        <div className="licitai-root dark" style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#0a0d14', color: '#fff', fontFamily: 'Inter, sans-serif' }}>
            
            {/* HEADER */}
            <header className="app-header">
                <div
                    className="brand"
                    onClick={() => setSessionId(null)}
                    style={{ cursor: 'pointer', minWidth: 0, flex: '0 1 auto' }}
                >
                    <div className="brand-logo"><Shield size={20} color="white" /></div>
                    <span className="brand-name">LicitAI</span>
                    <span
                        className="brand-session-meta"
                        style={{
                            color: '#ffffff',
                            WebkitTextFillColor: '#ffffff',
                            flexShrink: 0,
                            maxWidth: 'min(52vw, 520px)',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                        }}
                        title={sessionName || 'SISTEMA'}
                    >
                        v{LICITAI_APP_VERSION} — {sessionName || 'SISTEMA'}
                    </span>
                </div>
                
                <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
                    {auditResults && (
                        <div
                            className="header-summary-badge"
                            title="El total agrupa requisitos de bases, compliance y otros hallazgos. Puede variar si repites el análisis (el modelo no es idéntico cada vez) o si se unifican textos repetidos al cargar el dictamen."
                        >
                            <div>REQUISITOS: <span className="header-stat">{auditResults.totalRequisitos}</span></div>
                            <div style={{ paddingLeft: '10px', borderLeft: '1px solid rgba(255,255,255,0.1)' }}>RIESGOS: <span className="header-stat risk">{auditResults.riesgos}</span></div>
                        </div>
                    )}
                    
                    <select 
                        aria-label="Seleccionar empresa"
                        value={selectedCompanyId} 
                        onChange={e => setSelectedCompanyId(e.target.value)} 
                        style={{ background: 'rgba(255,255,255,0.05)', color: 'white', border: '1px solid rgba(255,255,255,0.1)', padding: '8px 15px', borderRadius: '12px', fontSize: '13px' }}
                    >
                        <option value="">-- SELECCIONA EMPRESA --</option>
                        {Array.isArray(companies) ? companies.map(c => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                        )) : null}
                    </select>
                    
                    <button 
                        aria-label="Cerrar sesión"
                        title="Volver a la selección de licitaciones"
                        onClick={() => setSessionId(null)} 
                        style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
                    >
                        <ArrowLeft size={18} />
                    </button>
                </div>
            </header>

            <main style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
                
                {/* IZQUIERDA: FUENTES — el aside tiene altura fija desde el flex-row padre.
                    El bloque de fuentes (flex:1) absorbe el espacio libre y hace scroll interno.
                    Los botones de acción quedan siempre visibles al final. */}
                <aside
                    style={{
                        width: `${leftWidth}px`,
                        minWidth: 0,
                        minHeight: 0,
                        borderRight: '1px solid rgba(255,255,255,0.05)',
                        display: 'flex',
                        flexDirection: 'column',
                        padding: '20px',
                        gap: '20px',
                        transition: isResizingLeft ? 'none' : 'width 0.3s ease',
                        /* Scroll del panel completo si dictamen + fuentes no caben; evita que el bloque de fuentes quede en 0px */
                        overflowY: 'auto',
                        overflowX: 'hidden',
                    }}
                >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h3 style={{ fontSize: '11px', fontWeight: 900, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>FUENTES DE VERDAD</h3>
                        <button 
                            aria-label="Añadir nuevo documento"
                            title="Subir bases (PDF, Excel de costos, Word, imágenes)"
                            onClick={() => fileInputRef.current.click()} 
                            style={{ background: 'none', border: 'none', color: 'var(--primary)', cursor: 'pointer' }}
                        >
                            <Plus size={20} />
                        </button>
                        <input
                            type="file"
                            ref={fileInputRef}
                            hidden
                            multiple
                            accept=".pdf,.xlsx,.xls,.doc,.docx,image/*"
                            onChange={handleFileUpload}
                        />
                    </div>

                    <div
                        style={{
                            flex: '1 1 auto',
                            flexShrink: 0,
                            minHeight: '220px',
                            maxHeight: '38vh',
                            overflowY: 'auto',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '10px',
                            border: '1px solid rgba(255,255,255,0.08)',
                            borderRadius: '12px',
                            padding: '8px',
                            background: 'rgba(0,0,0,0.2)',
                        }}
                    >
                        {sources.length === 0 && (
                            <p
                                style={{
                                    fontSize: '11px',
                                    lineHeight: 1.5,
                                    color: 'var(--text-muted)',
                                    margin: '4px 0 0 0',
                                    padding: '8px 4px',
                                }}
                            >
                                Aún no hay fuentes en esta carpeta. Usa + para subir PDF o Excel. Si acabas de entrar,
                                espera un momento; si ya había archivos, recarga o revisa la consola (F12) por errores de red.
                            </p>
                        )}
                        {sources.map(src => (
                            <div key={src.id} style={{ background: 'rgba(255,255,255,0.03)', padding: '12px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: '12px' }}>
                                <FileText size={18} color="var(--primary)" />
                                <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
                                    <div
                                        style={{
                                            fontSize: '12px',
                                            fontWeight: 600,
                                            whiteSpace: 'nowrap',
                                            textOverflow: 'ellipsis',
                                            overflow: 'hidden',
                                            color: '#f1f5f9',
                                        }}
                                    >
                                        {src.name}
                                    </div>
                                    <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{src.status}</div>
                                </div>
                                <button
                                    type="button"
                                    aria-label={`Reprocesar e indexar de nuevo ${src.name}`}
                                    title="Vuelve a extraer texto y reindexar (y repuebla partidas si es Excel). Útil tras actualizar el pipeline sin borrar el archivo."
                                    disabled={!!reprocessingDocId || isAnalyzing}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleReprocessSource(src.id, src.name);
                                    }}
                                    style={{
                                        background: 'none',
                                        border: 'none',
                                        color: reprocessingDocId === src.id ? 'var(--primary)' : 'rgba(255,255,255,0.35)',
                                        cursor:
                                            reprocessingDocId || isAnalyzing ? 'not-allowed' : 'pointer',
                                        padding: '5px',
                                        borderRadius: '5px',
                                        flexShrink: 0,
                                    }}
                                    onMouseOver={(e) => {
                                        if (!reprocessingDocId && !isAnalyzing) e.currentTarget.style.color = 'var(--primary)';
                                    }}
                                    onMouseOut={(e) => {
                                        if (reprocessingDocId !== src.id)
                                            e.currentTarget.style.color = 'rgba(255,255,255,0.35)';
                                    }}
                                >
                                    <RefreshCw
                                        size={14}
                                        className={reprocessingDocId === src.id ? 'animate-spin' : ''}
                                    />
                                </button>
                                <button 
                                    aria-label={`Quitar documento ${src.name} de esta licitación`}
                                    title="Quitar documento: el informe actual dejará de mostrarse hasta que vuelvas a analizar con la documentación cargada"
                                    onClick={(e) => { e.stopPropagation(); handleDeleteSource(src.id, src.name); }}
                                    style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.2)', cursor: 'pointer', padding: '5px', borderRadius: '5px' }}
                                    onMouseOver={(e) => e.currentTarget.style.color = '#ff4d4d'}
                                    onMouseOut={(e) => e.currentTarget.style.color = 'rgba(255,255,255,0.2)'}
                                >
                                    <Trash2 size={14} />
                                </button>
                            </div>
                        ))}
                    </div>

                    <SubmissionChecklistPanel
                        sessionId={sessionId}
                        syncKey={auditResults?.fechaAuditoria || ''}
                        onAskAboutHito={(h) => {
                            const q = `Según las bases de esta licitación, ¿qué debo cumplir respecto al hito «${h.nombre}»? Contexto: ${h.fecha_texto_raw || 'sin fecha textual'}.`;
                            setChatInput(q);
                        }}
                    />

                    <PostClarificationPanel
                        sessionId={sessionId}
                        sources={sources}
                        syncKey={auditResults?.fechaAuditoria || ''}
                        onAskAboutActa={(ctx) => {
                            const q = `Ayúdame a revisar el borrador de carta 33 Bis y las preguntas Anexo 10. Estado: ${ctx?.estado || 'N/D'}, confianza de extracción: ${ctx?.confianza_extraccion ?? 'N/D'}.`;
                            setChatInput(q);
                        }}
                    />

                    <EconomicValidationPanel
                        sessionId={sessionId}
                        syncKey={auditResults?.fechaAuditoria || ''}
                        onAskAboutValidation={(val) => {
                            const q = `Revisemos las validaciones económicas. Perfil: ${val?.perfil_usado || 'N/D'}. Bloqueos: ${(val?.blocking_issues || []).length}. ¿Qué debo corregir primero?`;
                            setChatInput(q);
                        }}
                    />

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <button 
                            disabled={isAnalyzing} 
                            onClick={triggerFullAudit} 
                            title={auditResults ? 'Vuelve a ejecutar agentes y actualiza el dictamen en el servidor' : 'Primera auditoría de bases para esta sesión'}
                            style={{ width: '100%', padding: '12px', borderRadius: '12px', background: 'var(--primary)', border: 'none', color: '#fff', fontWeight: 800, fontSize: '12px', cursor: isAnalyzing ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', boxShadow: '0 4px 15px var(--primary-shadow)' }}
                        >
                            {isAnalyzing ? <Loader2 className="animate-spin" size={16} /> : <FileSearch size={16} />}
                            {auditResults ? 'ACTUALIZAR ANÁLISIS' : 'ANALIZAR BASES'}
                        </button>
                        {auditResults?.fechaAuditoria && (
                            <p style={{ margin: 0, fontSize: '10px', color: 'var(--text-muted)', lineHeight: 1.45, textAlign: 'center' }}>
                                Último dictamen en servidor: {auditResults.fechaAuditoria}
                                {auditResults.uxKind === 'rag_index_missing'
                                    ? ' · Falta índice vectorial para auditar de nuevo'
                                    : ''}
                            </p>
                        )}

                        <button 
                            disabled={isGenerating} 
                            onClick={triggerGeneration} 
                            style={{ width: '100%', padding: '12px', borderRadius: '12px', background: 'linear-gradient(135deg, var(--primary), var(--secondary))', border: 'none', color: '#fff', fontWeight: 800, fontSize: '12px', cursor: isGenerating ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', boxShadow: '0 4px 15px var(--primary-glow)' }}
                        >
                            {isGenerating ? <Loader2 className="animate-spin" size={16} /> : <DownloadCloud size={16} />}
                            GENERAR PROPUESTA
                        </button>
                    </div>
                    
                    <div style={{ marginTop: '10px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '15px' }}>
                         <AnalysisResults 
                             results={auditResults} 
                             onAskExpert={(q) => { setChatInput(q); }}
                             sessionId={sessionId}
                             companyId={selectedCompanyId} 
                         />
                    </div>
                </aside>

                {/* VISUAL RESIZER IZQUIERDO */}
                <div 
                    onMouseDown={() => setIsResizingLeft(true)}
                    onMouseEnter={() => setIsHoverLeft(true)}
                    onMouseLeave={() => setIsHoverLeft(false)}
                    style={{ 
                        width: '4px', 
                        cursor: 'col-resize', 
                        background: (isResizingLeft || isHoverLeft) ? 'var(--primary)' : 'rgba(255,255,255,0.05)', 
                        zIndex: 10,
                        transition: 'background 0.2s'
                    }}
                />

                {/* CENTRO: RESULTADOS */}
                <section style={{ flex: 1, display: 'flex', flexDirection: 'column', overflowY: 'auto', padding: '30px', gap: '30px', background: 'rgba(0,0,0,0.1)' }}>
                    <Dashboard
                        sessionId={sessionId}
                        auditResults={auditResults}
                        isAnalyzing={isAnalyzing}
                        auditProgress={auditProgress}
                    />
                    <DeliveryPanel results={generationResults || auditResults || {}} sessionName={sessionName} sessionId={sessionId} />
                </section>

                {/* VISUAL RESIZER DERECHO (CON HOVER Y LUZ) */}
                <div 
                    onMouseDown={() => setIsResizingRight(true)}
                    onMouseEnter={() => setIsHoverRight(true)}
                    onMouseLeave={() => setIsHoverRight(false)}
                    style={{ 
                        width: '6px', 
                        cursor: 'col-resize', 
                        background: (isResizingRight || isHoverRight) ? 'var(--primary)' : 'rgba(255,255,255,0.05)', 
                        transition: 'background 0.2s',
                        zIndex: 10,
                        position: 'relative',
                        boxShadow: (isResizingRight || isHoverRight) ? '0 0 10px var(--primary-glow)' : 'none'
                    }}
                />

                {/* DERECHA: CHAT EXPERTO */}
                <aside style={{ width: `${rightWidth}px`, borderLeft: '1px solid rgba(255,255,255,0.05)', display: 'flex', flexDirection: 'column', background: 'rgba(0,0,0,0.2)', transition: isResizingRight ? 'none' : 'width 0.3s ease' }}>
                    <div style={{ padding: '20px', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
                            <Bot size={20} color="var(--primary)" />
                            <h3 style={{ fontSize: '15px', fontWeight: 800, margin: 0 }}>EXPERTO RAG</h3>
                        </div>
                        <button
                            type="button"
                            onClick={clearExpertChat}
                            disabled={chatMessages.length === 0 && !isThinking}
                            title="Vaciar mensajes del panel (no borra datos en el servidor)"
                            aria-label="Limpiar conversación del experto"
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '6px',
                                padding: '8px 10px',
                                borderRadius: '10px',
                                border: '1px solid rgba(255,255,255,0.12)',
                                background: 'rgba(255,255,255,0.06)',
                                color: 'var(--text-muted)',
                                fontSize: '11px',
                                fontWeight: 700,
                                cursor: chatMessages.length === 0 && !isThinking ? 'not-allowed' : 'pointer',
                                opacity: chatMessages.length === 0 && !isThinking ? 0.45 : 1,
                            }}
                        >
                            <Eraser size={14} />
                            Limpiar chat
                        </button>
                    </div>

                    <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '15px' }}>
                        {chatMessages.length === 0 ? (
                            <div style={{ margin: 'auto', textAlign: 'center', opacity: 0.2 }}>
                                <Bot size={50} style={{ marginBottom: '15px' }} />
                                <p style={{ fontSize: '13px' }}>El experto forense puede ayudarte con el análisis de bases y los datos faltantes del expediente.</p>
                            </div>
                        ) : (
                            chatMessages.map((msg, i) => (
                                <div key={i} style={{ alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start', maxWidth: '85%' }}>
                                    <div style={{ background: msg.sender === 'user' ? 'var(--primary)' : 'rgba(255,255,255,0.05)', color: '#fff', padding: '12px 16px', borderRadius: msg.sender === 'user' ? '15px 15px 0 15px' : '0 15px 15px 15px', fontSize: '14px', lineHeight: 1.5, border: msg.isGlow ? '2px solid var(--primary)' : '1px solid rgba(255,255,255,0.05)', boxShadow: msg.isGlow ? '0 0 20px var(--primary-glow)' : 'none' }}>
                                        {msg.text}
                                    </div>
                                    {msg.citations && <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '5px' }}>{msg.citations.length} citas detectadas.</div>}
                                </div>
                            ))
                        )}
                        <div ref={chatEndRef} />
                        {isThinking && <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', gap: '10px' }}><Loader2 className="spin" size={14} /> Trabajando...</div>}
                    </div>

                    <form onSubmit={handleSendMessage} style={{ padding: '20px', borderTop: '1px solid rgba(255,255,255,0.05)', display: 'flex', gap: '10px' }}>
                        <input type="text" value={chatInput} onChange={e => setChatInput(e.target.value)} placeholder="Pregunta sobre las bases o aporta un dato del expediente…" style={{ flex: 1, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', padding: '12px 15px', borderRadius: '10px', color: '#fff', outline: 'none' }} />
                        <button type="submit" style={{ background: 'var(--primary)', border: 'none', color: '#fff', padding: '10px 15px', borderRadius: '10px', cursor: 'pointer' }}><Send size={18} /></button>
                    </form>
                </aside>

            </main>

            {/* OVERLAY DE CARGA (DRAGGABLE) */}
            {isAnalyzing && (
                <div 
                    onMouseDown={(e) => {
                        setIsDragging(true);
                        // No necesitamos preventDefault necesariamente pero sí registrar el inicio
                    }}
                    onMouseMove={(e) => {
                        if (isDragging) {
                            setDragOffset({ x: window.innerWidth - e.clientX - 150, y: window.innerHeight - e.clientY - 50 });
                        }
                    }}
                    onMouseUp={() => setIsDragging(false)}
                    style={{ 
                        position: 'fixed', 
                        bottom: `${dragOffset.y}px`, 
                        right: `${dragOffset.x}px`, 
                        background: 'rgba(0,0,0,0.95)', 
                        padding: '20px', 
                        borderRadius: '15px', 
                        border: '2px solid var(--primary)', 
                        width: '300px', 
                        zIndex: 10000, 
                        boxShadow: '0 20px 50px rgba(0,0,0,0.7)',
                        cursor: isDragging ? 'grabbing' : 'grab',
                        userSelect: 'none'
                    }}
                >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '10px' }}>
                        <span style={{ fontSize: '12px', fontWeight: 800 }}>PROCESANDO...</span>
                        <span style={{ fontSize: '12px', color: 'var(--primary)' }}>{auditProgress.percent}%</span>
                    </div>
                    <div style={{ height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${auditProgress.percent}%`, background: 'var(--primary)', transition: 'width 0.3s' }}></div>
                    </div>
                    <div style={{ fontSize: '10px', marginTop: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>{auditProgress.currentFile}</div>
                    <div style={{ fontSize: '9px', textAlign: 'center', marginTop: '10px', opacity: 0.5 }}>Arrastra para mover</div>
                </div>
            )}
        </div>
    );
};

export default App;
