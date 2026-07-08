import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { 
    FileText, Search, Shield, AlertTriangle, CheckCircle, 
    Download, Clock, ChevronRight, MessageSquare, Bot, 
    User, Send, Bell, Plus, FileSearch, Loader2, ArrowLeft,
    Copy, DownloadCloud, FileCheck, Info, Trash2, Eraser, RefreshCw, Paperclip
} from 'lucide-react';
import axios from 'axios';
import { buildStableReactKey } from './utils/stableReactKey.js';
import DeliveryPanel from './components/DeliveryPanel';
import SubmissionChecklistPanel from './components/SubmissionChecklistPanel';
import CriticalDatesList from './components/CriticalDatesList';
import PostClarificationPanel from './components/PostClarificationPanel';
import JuntaAclaracionesPanel from './components/JuntaAclaracionesPanel';
import EconomicValidationPanel from './components/EconomicValidationPanel';
import Dashboard from './components/Dashboard';
import ExportPDF from './components/ExportPDF';
import LicitacionesGrid from './components/LicitacionesGrid';
import GoNoGoPanel from './components/GoNoGoPanel';
import ForensicCard from './components/ForensicCard';
import ForensicRiskPanel from './components/ForensicRiskPanel';
import ForensicBasesExcerptCard from './components/ForensicBasesExcerptCard';
import ForensicEvidenceBadge from './components/ForensicEvidenceBadge';
import ValidationAlert from './components/ValidationAlert';
import JustificationModal from './components/JustificationModal';
import GenerationQueuePanel from './components/GenerationQueuePanel';
import {
    ScopeDownloadBlock,
    CrossScopeDownloadHint,
    useGenerationDownloadBundle,
} from './components/GenerationDownloadActions.jsx';
import {
    GENERATION_MODE_OPTIONS,
    formatGenerationStateJobsSummaryHuman,
    generationModeLabelEs,
    generationStageLabelEs,
} from './generationModeUi.js';
import {
    createInitialGenerationStreamRuns,
    dualStreamParallelBannerEs,
    formatDualStreamJobsSummaryHuman,
    generationStreamIdForMode,
    generationStreamParamForMode,
    isAnyGenerationStreamActive,
    isGenerationModeButtonDisabled,
    isGenerationStreamActive,
    isStreamActiveForMode,
    primaryGenerationProgressForDisplay,
} from './generationStreamUi.js';
import { EXPEDIENTE_CHAT_SHELL_UI } from './expedienteProgressUi.js';
import ValidationPolicyAdmin from './components/ValidationPolicyAdmin';
import BlockResolutionPanel from './components/BlockResolutionPanel';
import CaptureMatrixPanel from './components/CaptureMatrixPanel';
import ExpedienteGuidedStepBar from './components/ExpedienteGuidedStepBar';
import {
    mergeGenerationHints,
    mergeOverlayMessages,
    mergePanelLabels,
    panelLabelForGenerationMode,
    panelShortForGenerationMode,
} from './expedienteGuidedUi.js';
import DocumentQualityDiagnosticPanel from './components/DocumentQualityDiagnosticPanel';
import IntakeProgressCard from './components/IntakeProgressCard';
import DocumentCandidatePanel from './components/DocumentCandidatePanel';
import DetectedFormatsPanel from './components/DetectedFormatsPanel';
import PhysicalChecklistPanel from './components/PhysicalChecklistPanel';
import { useValidationManager } from './hooks/useValidationManager';
import {
    processAuditResults,
    ZONA_TAB_ORDER,
    buildCompliancePorZona,
    enrichDictamenFromStorage,
    applyInfrastructureUxOverrides,
    synthesizePipelineTelemetryFromDictamen,
    pickDocumentCandidatesForPanel,
    pickDetectedFormatsForPanel,
} from './utils/auditSummary';
import { resolveForensicRisksBlock } from './utils/forensicRiskUtils.js';
import { LICITAI_APP_VERSION } from './appVersion.js';
import { API_BASE } from './apiBase.js';
// Interceptor global para atrapar caídas de servidor y evitar UI rota/ERR_EMPTY_RESPONSE
axios.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.isAxiosError && (error.message === 'Network Error' || error.code === 'ERR_NETWORK')) {
            window.dispatchEvent(new CustomEvent('server-connection-error'));
        }
        return Promise.reject(error);
    }
);

/**
 * Claves `${sessionId}::${companyKey}` ya usadas para el bootstrap del chat (POST /chatbot/ask vacío).
 * Vive fuera del componente para sobrevivir al doble montaje de React Strict Mode (los useRef se reinician).
 */
const chatProactiveBootstrapDoneKeys = new Set();

const AGENTS_JOB_POLL_MS = 2500;
/** PDFs grandes (p. ej. vigilancia ~102 pp.) pueden superar 90 min solo en Compliance. */
const AGENTS_JOB_TIMEOUT_MS = 4 * 60 * 60 * 1000;
const AGENTS_JOB_BACKGROUND_TIMEOUT_MS = 2 * 60 * 60 * 1000;
const PENDING_AGENTS_JOB_STORAGE_KEY = 'licitai_pending_agents_job';
const SOURCES_CACHE_KEY = 'licitai_sources_cache';

function loadCachedSources(sessionId) {
    try {
        const raw = sessionStorage.getItem(SOURCES_CACHE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed?.sessionId === sessionId && Array.isArray(parsed.docs) ? parsed.docs : null;
    } catch (_) {
        return null;
    }
}

function saveCachedSources(sessionId, docs) {
    try {
        sessionStorage.setItem(
            SOURCES_CACHE_KEY,
            JSON.stringify({ sessionId, docs, savedAt: Date.now() }),
        );
    } catch (_) { /* ignore quota */ }
}

function clearCachedSources() {
    try {
        sessionStorage.removeItem(SOURCES_CACHE_KEY);
    } catch (_) { /* ignore */ }
}

class AgentsJobStillRunningError extends Error {
    constructor(jobId, progress) {
        super('El análisis sigue en curso en el servidor.');
        this.name = 'AgentsJobStillRunningError';
        this.jobId = jobId;
        this.progress = progress || {};
    }
}

function savePendingAgentsJob(sessionId, jobId) {
    try {
        sessionStorage.setItem(
            PENDING_AGENTS_JOB_STORAGE_KEY,
            JSON.stringify({ sessionId, jobId, savedAt: Date.now() }),
        );
    } catch (_) { /* ignore quota */ }
}

function loadPendingAgentsJob(sessionId) {
    try {
        const raw = sessionStorage.getItem(PENDING_AGENTS_JOB_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed?.sessionId === sessionId ? parsed.jobId : null;
    } catch (_) {
        return null;
    }
}

function clearPendingAgentsJob() {
    try {
        sessionStorage.removeItem(PENDING_AGENTS_JOB_STORAGE_KEY);
    } catch (_) { /* ignore */ }
}

/** Go/No-Go ya reconocido (usuario o política silenciosa en análisis). */
function isGoNoGoAcknowledged(override) {
    const by = override?.authorized_by;
    return by === 'user' || by === 'system_auto';
}

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
async function pollAgentsJobUntilDone(jobId, onProgress, options = {}) {
    const timeoutMs = options.timeoutMs ?? AGENTS_JOB_TIMEOUT_MS;
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
        const st = await axios.get(`${API_BASE}/agents/jobs/${jobId}/status`);
        if (!st.data?.success) {
            throw new Error(st.data?.message || 'No se pudo leer el estado del análisis.');
        }
        const job = st.data.data || {};
        const prog = job.progress || {};
        const msg = prog.message;
        const rawPct = prog.pct;
        const pct = typeof rawPct === 'number' && !Number.isNaN(rawPct) ? rawPct : undefined;
        if (onProgress && (msg || pct !== undefined || job.status === 'COMPLETED' || job.status === 'FAILED')) {
            onProgress({
                message: msg,
                pct,
                status: job.status,
                orchestratorHeld: Boolean(prog.orchestrator_held),
                orchestratorStatus: prog.orchestrator_status,
            });
        }
        if (job.status === 'COMPLETED') {
            clearPendingAgentsJob();
            if (!job.result) throw new Error('Job completado sin resultado en el servidor.');
            return job.result;
        }
        if (job.status === 'FAILED') {
            clearPendingAgentsJob();
            const err = job.error || job.forensic_traceback || 'El análisis falló en el servidor.';
            throw new Error(typeof err === 'string' ? err : JSON.stringify(err));
        }
        await new Promise((r) => setTimeout(r, AGENTS_JOB_POLL_MS));
    }
    const stFinal = await axios.get(`${API_BASE}/agents/jobs/${jobId}/status`);
    const jobFinal = stFinal.data?.data || {};
    if (jobFinal.status === 'RUNNING') {
        throw new AgentsJobStillRunningError(jobId, jobFinal.progress || {});
    }
    throw new Error('Tiempo de espera agotado. El análisis sigue en curso o el servidor tardó demasiado; revisa los logs del backend.');
}

/** Fallbacks en español si el backend devuelve waiting_for_data sin chatbot_message */
const WAITING_FOR_DATA_FALLBACK_AUDIT_ES =
    "El análisis quedó en pausa: faltan datos para continuar (por ejemplo precios o expediente). Revisa el mensaje del sistema o completa lo que te pida el asistente y vuelve a intentar cuando esté listo.";
const WAITING_FOR_DATA_FALLBACK_GENERATION_ES =
    "Faltan datos para generar documentos. Revisa la lista anterior o sube la documentación indicada; cuando los tengas, responde aquí o vuelve a pulsar Generar.";

/** True si el error de polling parece un job zombi/stale, no un fallo real del pipeline. */
function isStaleOrInterruptedJobError(message) {
    const m = String(message || '').toLowerCase();
    return m.includes('interrumpido') || m.includes('sin actividad') || m.includes('stale_job');
}

/**
 * Si el dictamen ya está en Postgres, recupera la UI sin relanzar análisis.
 * @returns {Promise<boolean>} true si se cargó dictamen existente
 */
async function tryLoadExistingDictamen(sessionId, fetchDictamenFn, pushGuidanceFn) {
    if (!sessionId || sessionId === 'null') return false;
    try {
        const res = await axios.get(
            `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/dictamen`,
            { timeout: 45000 },
        );
        if (!res.data?.success || !res.data?.data?.dictamen) return false;
        await fetchDictamenFn();
        const d = res.data.data.dictamen;
        const statusRaw = String(d.statusRaw || '').toLowerCase();
        const hasItems = (d.totalRequisitos ?? 0) > 0 || (Array.isArray(d.causales) && d.causales.length > 0);
        if (!hasItems && statusRaw !== 'success' && statusRaw !== 'partial') return false;
        pushGuidanceFn(
            '✅ **El dictamen forense ya está guardado** para esta licitación. No hace falta volver a analizar las bases. '
            + 'Revisa el panel de auditoría; si necesitas regenerar documentos, usa **Generar** cuando tu empresa esté seleccionada.',
            true,
        );
        return true;
    } catch (_) {
        return false;
    }
}

/**
 * True si hay pendientes `economic_validation_blocking` (corregir plantilla/Excel; no intake numérico).
 * @param {Record<string, unknown>|null|undefined} data — `orchestrator.data`
 */
function orchestratorDataHasEconomicValidationBlocking(data) {
    if (!data || typeof data !== 'object') return false;
    for (const stage of Object.keys(data)) {
        const r = data[stage];
        if (!r || typeof r !== 'object') continue;
        const miss = r.data?.missing ?? r.missing;
        if (!Array.isArray(miss)) continue;
        if (miss.some((m) => m && typeof m === 'object' && m.type === 'economic_validation_blocking')) {
            return true;
        }
    }
    return false;
}

function orchestratorDataHasDocumentQualityGateBlocking(data) {
    if (!data || typeof data !== 'object') return false;
    for (const stage of Object.keys(data)) {
        const r = data[stage];
        if (!r || typeof r !== 'object') continue;
        const miss = r.data?.missing ?? r.missing;
        if (!Array.isArray(miss)) continue;
        if (miss.some((m) => m && typeof m === 'object' && m.type === 'document_quality_gate_blocking')) {
            return true;
        }
    }
    return false;
}

/** Bloqueo por campos vacíos / placeholders en documentos ya generados. */
function orchestratorDataHasDocumentFillQualityGateBlocking(data) {
    if (!data || typeof data !== 'object') return false;
    for (const stage of Object.keys(data)) {
        const r = data[stage];
        if (!r || typeof r !== 'object') continue;
        const miss = r.data?.missing ?? r.missing;
        if (!Array.isArray(miss)) continue;
        if (miss.some((m) => m && typeof m === 'object' && m.type === 'document_fill_quality_gate_blocking')) {
            return true;
        }
    }
    return false;
}

const VALIDATION_NAV_HINTS_ES = {
    chat_pricing:
        'Escríbeme aquí el dato que falta (por ejemplo: «El RFC es ABC123456789» o «El representante legal es Juan Pérez»). Yo lo guardo y seguimos.',
    companies:
        'Arriba, en el menú **Empresa**, selecciona tu empresa y completa RFC, razón social y representante legal. Si aún no la tienes, sal al menú principal → **Empresas** → créala y vuelve.',
    economic_panel:
        'Abre la pestaña **Económico** (debajo del panel central) y revisa precios o totales de la cotización.',
    validation_policy:
        'Abre **Calidad documental** en las herramientas de sesión para ver el detalle.',
    upload_area:
        'Sube el archivo correcto en **Fuentes** (panel izquierdo) y asegúrate de que corresponda a esta licitación.',
};

function humanNavigateHintForValidationTarget(target, event) {
    const t = String(target || '').trim();
    if (VALIDATION_NAV_HINTS_ES[t]) return VALIDATION_NAV_HINTS_ES[t];
    const ux = event?.ux || {};
    const msg = ux.user_message || '';
    if (msg) {
        const plain = String(msg).replace(/\*\*/g, '');
        return plain.length > 300 ? `${plain.slice(0, 297).trim()}…` : plain;
    }
    return 'Revisa la tarjeta de arriba y corrige lo que indique; si tienes duda, pregúntame aquí.';
}

function buildDocumentFillValidationEvents(results) {
    const out = [];
    if (!results || typeof results !== 'object') return out;
    Object.keys(results).forEach((stage) => {
        const r = results[stage];
        const miss = r?.data?.missing ?? r?.missing;
        if (!Array.isArray(miss)) return;
        miss.forEach((m) => {
            if (!m || typeof m !== 'object' || m.type !== 'document_fill_quality_gate_blocking') return;
            out.push({
                error_type: 'document_fill_quality_gate',
                severity: 'block',
                context: { stage, blocking_items: m.blocking_items || [] },
                ux: {
                    title: m.label || 'Faltan datos para armar documentos',
                    user_message:
                        m.question
                        || 'Completa los datos que faltan y vuelve a pulsar **Generar**.',
                    primary_action: { label: 'Escribir en el chat', type: 'navigate', target: 'chat_pricing' },
                    secondary_action: { label: 'Ir a Empresas', type: 'navigate', target: 'companies' },
                    impact: 'Sin este dato no puedo terminar tu propuesta.',
                },
                _stage: stage,
            });
        });
    });
    return out;
}

function buildDocumentQualityValidationEvents(results) {
    const out = [];
    if (!results || typeof results !== 'object') return out;
    Object.keys(results).forEach((stage) => {
        const r = results[stage];
        const miss = r?.data?.missing ?? r?.missing;
        if (!Array.isArray(miss)) return;
        miss.forEach((m) => {
            if (!m || typeof m !== 'object' || m.type !== 'document_quality_gate_blocking') return;
            out.push({
                error_type: 'document_quality_gate',
                severity: 'block',
                context: { stage, reason: m?.document_hint || '' },
                ux: {
                    title: m.label || 'Calidad documental insuficiente',
                    user_message: m.question || m.document_hint || 'Revisa clasificación y evidencia antes de generar.',
                    primary_action: { label: 'Revisar en el chat', type: 'navigate', target: 'chat_pricing' },
                    secondary_action: { label: 'Revisar detalle', type: 'navigate', target: 'validation_policy' },
                    impact: 'Evita sobre-generación y documentos no exigibles por bases.',
                },
                _stage: stage,
            });
        });
    });
    return out;
}

function extractDocumentQualityGateSnapshot(orchestrator) {
    const hintA = orchestrator?.agent_decision?.waiting_hints;
    const hintB = orchestrator?.orchestrator_decision?.waiting_hints;
    const hint = hintA && typeof hintA === 'object' ? hintA : hintB;
    if (hint && typeof hint === 'object') {
        return {
            reason: String(hint.reason || ''),
            metrics: hint.metrics && typeof hint.metrics === 'object' ? hint.metrics : {},
        };
    }

    const data = orchestrator?.data;
    if (data && typeof data === 'object') {
        for (const stage of Object.keys(data)) {
            const r = data[stage];
            const gate = r?.data?.document_quality_gate || r?.document_quality_gate;
            if (gate && typeof gate === 'object') {
                return {
                    reason: String(gate.reason || ''),
                    metrics: gate.metrics && typeof gate.metrics === 'object' ? gate.metrics : {},
                };
            }
        }
    }
    return null;
}

/**
 * Complementa el mensaje del backend cuando la generación queda en `waiting_for_data`
 * (Hito 4: `results.*.data.missing`, `missing_fields`, cola bloqueada).
 * @param {Record<string, unknown>|null|undefined} orchestrator — Cuerpo `result` del job o objeto equivalente.
 * @returns {string} Sufijo en texto plano (vacío si no hay datos extra).
 */
function formatGenerationWaitingExtra(orchestrator) {
    if (!orchestrator || typeof orchestrator !== 'object') return '';
    const parts = [];
    const blockEconomicValidationUi = orchestratorDataHasEconomicValidationBlocking(orchestrator.data);
    const fillBlockingPresent = orchestratorDataHasDocumentFillQualityGateBlocking(orchestrator.data);
    const FILL_GATE_ERROR_TYPES = new Set([
        'placeholder_detected',
        'required_field_missing',
        'cross_field_inconsistency',
        'cross_tender_reference',
        'source_confidence_insufficient',
        'document_fill_quality_gate',
    ]);

    const results = orchestrator.data;
    const stageOrder = [
        'datagap',
        'technical',
        'formats',
        'economic_writer',
        'economic',
        'packager',
        'document_packager',
        'delivery',
    ];
    const processedStages = new Set();

    const pushMissingForStage = (stage, miss) => {
        if (!Array.isArray(miss) || miss.length === 0) return;
        const allEconomicPrice =
            miss.length > 0 &&
            miss.every((m) => m && typeof m === 'object' && m.type === 'economic_price');
        if (allEconomicPrice) {
            // Solo precios: el mensaje del backend + el chat bastan. Listar la cola aquí dispara ansiedad (madrugada / cierre).
            return;
        }
        const label = generationStageLabelEs(stage);
        const lines = miss.slice(0, 18).map((m) => {
            if (typeof m === 'string') return `• ${m}`;
            if (!m || typeof m !== 'object') return null;
            // Las validaciones económicas ya se listan en `validation_events` con texto UX;
            // repetir aquí el `question` duplica jerga (p. ej. "precios_positivos: …").
            if (m.type === 'economic_validation_blocking') return null;
            if (m.type === 'document_fill_quality_gate_blocking') return null;
            const q = m.question || m.label || m.field;
            return q ? `• ${q}` : null;
        }).filter(Boolean);
        if (lines.length) {
            parts.push(`${label} — completar:\n${lines.join('\n')}`);
        }
    };
    const pushValidationEventsForStage = (stage, events) => {
        if (!Array.isArray(events) || events.length === 0) return;
        // Coherencia visual: con bloqueo de validación económica las tarjetas [REVISAR] bastan;
        // no duplicar "Propuesta económica: • Precios…" en el cuerpo del chat (evita disonancia con intake).
        if (
            blockEconomicValidationUi &&
            (stage === 'economic' || stage === 'economic_writer')
        ) {
            return;
        }
        const label = generationStageLabelEs(stage);
        const lines = events
            .slice(0, 10)
            .map((ev) => {
                if (!ev || typeof ev !== 'object') return null;
                const ux = ev.ux && typeof ev.ux === 'object' ? ev.ux : {};
                const title = ux.title || ev.error_type || 'Validación';
                const sev = ev.severity || 'warn';
                if (fillBlockingPresent && FILL_GATE_ERROR_TYPES.has(String(ev.error_type || ''))) {
                    return null;
                }
                // La tarjeta [REVISAR] ya muestra el texto largo; no repetir el mismo muro en el chat.
                if (sev === 'block') {
                    if (ev.error_type === 'precios_positivos') {
                        return '• Precios: revisa tu cotización o Excel (importes en cero o no válidos). Ajusta las partidas y pulsa Continuar para revalidar; el asistente puede orientarte en el chat.';
                    }
                    const shortMsg = ux.user_message || '';
                    if (shortMsg && shortMsg.length < 220) {
                        return `• ${title}: ${String(shortMsg).replace(/\*\*/g, '')}`;
                    }
                    return `• ${title}: usa la tarjeta de arriba o escríbeme aquí si necesitas ayuda.`;
                }
                const msg = ux.user_message || ev.meta?.raw_message || '';
                const impact = ux.impact ? ` (${ux.impact})` : '';
                const short = msg.length > 200 ? `${msg.slice(0, 197).trim()}…` : msg;
                return `• ${title}: ${short}${impact}`.trim();
            })
            .filter(Boolean);
        if (lines.length) {
            parts.push(`${label}:\n${lines.join('\n')}`);
        }
    };

    if (results && typeof results === 'object') {
        for (const stage of stageOrder) {
            const r = results[stage];
            if (!r || typeof r !== 'object') continue;
            processedStages.add(stage);
            const miss = r.data?.missing ?? r.missing;
            pushMissingForStage(stage, miss);
            const events = r.data?.validation_events ?? r.validation_events;
            pushValidationEventsForStage(stage, events);
        }
        for (const stage of Object.keys(results)) {
            if (processedStages.has(stage)) continue;
            const r = results[stage];
            if (!r || typeof r !== 'object') continue;
            const miss = r.data?.missing ?? r.missing;
            pushMissingForStage(stage, miss);
            const events = r.data?.validation_events ?? r.validation_events;
            pushValidationEventsForStage(stage, events);
        }
    }

    if (parts.length === 0) {
        const mf = orchestrator.missing_fields;
        if (Array.isArray(mf) && mf.length) {
            parts.push(
                'Campos pendientes:\n' + mf.slice(0, 24).map((k) => `• ${k}`).join('\n')
            );
        }
    }

    const gs = orchestrator.generation_state;
    const jobs = gs?.jobs;
    if (Array.isArray(jobs)) {
        const blocked = jobs
            .filter((j) => j && j.status === 'blocked')
            .map((j) => generationStageLabelEs(j.id));
        if (blocked.length) {
            parts.push(`Cola de generación: en pausa en — ${blocked.join(', ')}.`);
        }
    }

    return parts.length ? '\n\n' + parts.join('\n\n') : '';
}

/**
 * Resumen legible de generation_state.jobs para mensajes cuando el pipeline no llega a success.
 * @param {Record<string, unknown>|null|undefined} generationState
 * @returns {string}
 */
function formatGenerationStateJobsSummary(generationState) {
    const dual = formatDualStreamJobsSummaryHuman(generationState);
    if (dual) return dual;
    return formatGenerationStateJobsSummaryHuman(generationState);
}

// --- Sub-componente para mostrar resultados de auditoría ---
const AnalysisResults = ({ results, onAskExpert, onAskRiskExpert, sessionId, companyId, onRiskDecisionsUpdated, onRiskBatchStop }) => {
    const [activeZoneTab, setActiveZoneTab] = useState('all');
    const [expandedKey, setExpandedKey] = useState(null);
    const [showArchivoCompleto, setShowArchivoCompleto] = useState(false);
    const [showRiskPanel, setShowRiskPanel] = useState(true);

    useEffect(() => {
        setExpandedKey(null);
    }, [activeZoneTab, showArchivoCompleto]);

    useEffect(() => {
        if ((results?.riesgos ?? 0) > 0) setShowRiskPanel(true);
    }, [results?.riesgos, results?.fechaAuditoria]);

    if (!results) return null;

    const forensicRisksBlock = resolveForensicRisksBlock(results);
    const riskCount = forensicRisksBlock?.stats?.total ?? results.riesgos ?? 0;

    const displayCausales = showArchivoCompleto
        ? [
            ...(results.causales || []),
            ...(results.causalesArchival || []),
        ]
        : (results.causales || []);

    const porZona = showArchivoCompleto
        ? buildCompliancePorZona(displayCausales.filter((c) => c.category === 'compliance'))
        : (results.compliancePorZona || {});
    const allCompliance = displayCausales.filter((c) => c.category === 'compliance');
    const otrosHallazgos = displayCausales.filter((c) => c.category !== 'compliance' && !c.isRisk);
    const visibleCompliance =
        activeZoneTab === 'all' ? allCompliance : porZona[activeZoneTab] || [];
    const otrasZonasList = porZona._OTRAS_ZONAS || [];
    const obligacionesCount =
        results.obligacionesDetectadas ?? results.totalRequisitos ?? displayCausales.length;
    const archivalCount = results.archivalCount ?? (results.causalesArchival || []).length;
    const legacyTotal = results.totalRequisitosLegacy ?? null;

    const healthChip = (label, health) => {
        const st = String(health?.status || 'unknown').toLowerCase();
        let color = '#94a3b8';
        if (st === 'ok' || st === 'success') color = '#2ecc71';
        else if (st === 'degraded' || st === 'partial') color = '#f39c12';
        else if (st === 'failed' || st === 'fail' || st === 'error') color = '#e74c3c';
        return (
            <div
                key={label}
                style={{
                    flex: 1,
                    minWidth: 0,
                    padding: '8px 10px',
                    borderRadius: '10px',
                    background: 'rgba(255,255,255,0.03)',
                    border: `1px solid ${color}55`,
                }}
            >
                <div style={{ fontSize: '8px', fontWeight: 800, color: 'var(--text-muted)', letterSpacing: '0.4px' }}>
                    {label}
                </div>
                <div style={{ fontSize: '11px', fontWeight: 800, color, marginTop: '4px', textTransform: 'uppercase' }}>
                    {st}
                </div>
            </div>
        );
    };
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

    if (results.uxKind === 'rag_index_missing') {
        return (
            <div style={{ maxHeight: '600px', overflowY: 'auto', padding: '15px', background: 'rgba(255,255,255,0.02)', borderRadius: '20px', border: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '15px', paddingBottom: '15px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <Shield size={20} color="var(--primary)" />
                    <h3 style={{ fontSize: '15px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '1px' }}>Dictamen Forense</h3>
                </div>
                <div style={{ padding: '20px', background: 'rgba(56, 189, 248, 0.08)', borderRadius: '15px', border: '1px solid rgba(56, 189, 248, 0.35)', textAlign: 'center' }}>
                    <Shield size={32} color="#7dd3fc" style={{ marginBottom: '15px' }} />
                    <h4 style={{ fontSize: '16px', fontWeight: 800, color: '#7dd3fc', margin: '0 0 10px 0' }}>Sincronización de Expediente Requerida</h4>
                    <p style={{ fontSize: '13px', color: '#e2e8f0', lineHeight: 1.6, margin: 0 }}>
                        Hemos realizado un mantenimiento en el sistema. Para garantizar la tolerancia cero a errores en tu propuesta, necesitamos reconectar tus bases con nuestro motor de análisis. 
                        <br/><br/>
                        Por favor, pulsa el botón <strong>"Analizar Bases"</strong> (arriba a la derecha de este panel) para restaurar tu sesión de forma segura.
                    </p>
                </div>
            </div>
        );
    }

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

            {(results.extractionHealth || results.forensicAuditHealth) && (
                <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
                    {results.extractionHealth
                        ? healthChip('Lectura de bases', results.extractionHealth)
                        : null}
                    {results.forensicAuditHealth
                        ? healthChip('Auditoría forense', results.forensicAuditHealth)
                        : null}
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

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
                <div className="audit-widget">
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)', fontWeight: 800 }}>OBLIGACIONES DETECTADAS</div>
                    <div style={{ fontSize: '24px', fontWeight: 900 }}>{obligacionesCount}</div>
                    {legacyTotal != null && legacyTotal !== obligacionesCount && (
                        <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '4px' }}>
                            {archivalCount} archivados · {legacyTotal} en archivo forense completo
                        </div>
                    )}
                </div>
                <div
                    className="audit-widget"
                    role="button"
                    tabIndex={0}
                    onClick={() => {
                        setShowRiskPanel(true);
                        document.getElementById('forensic-risk-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                            setShowRiskPanel(true);
                            document.getElementById('forensic-risk-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        }
                    }}
                    style={{
                        cursor: riskCount > 0 ? 'pointer' : 'default',
                        outline: showRiskPanel && riskCount > 0 ? '1px solid rgba(231,76,60,0.45)' : undefined,
                    }}
                    title={riskCount > 0 ? 'Ver evaluación de riesgos forenses' : undefined}
                >
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)', fontWeight: 800 }}>RIESGOS</div>
                    <div style={{ fontSize: '24px', fontWeight: 900, color: '#ff4d4d' }}>{riskCount}</div>
                    {riskCount > 0 && (
                        <div style={{ fontSize: '9px', color: '#ff8a8a', marginTop: '4px', fontWeight: 700 }}>
                            Clic para evaluar
                        </div>
                    )}
                </div>
            </div>

            {showRiskPanel && forensicRisksBlock && (
                <ForensicRiskPanel
                    forensicRisks={forensicRisksBlock}
                    sessionId={sessionId}
                    onDecisionsUpdated={onRiskDecisionsUpdated}
                    onAskExpert={onAskExpert}
                    onAskRiskExpert={onAskRiskExpert}
                    onBatchStop={onRiskBatchStop}
                />
            )}

            {riskCount > 0 && (
                <div style={{ marginBottom: '12px' }}>
                    <button
                        type="button"
                        onClick={() => setShowRiskPanel((v) => !v)}
                        style={{
                            width: '100%',
                            padding: '8px 10px',
                            borderRadius: '10px',
                            border: '1px solid rgba(231,76,60,0.25)',
                            background: 'rgba(231,76,60,0.08)',
                            color: '#ffb4b4',
                            fontSize: '10px',
                            fontWeight: 800,
                            cursor: 'pointer',
                        }}
                    >
                        {showRiskPanel ? 'Ocultar panel de riesgos' : `Mostrar evaluación de ${riskCount} riesgos`}
                    </button>
                </div>
            )}

            {archivalCount > 0 && (
                <div style={{ marginBottom: '16px' }}>
                    <button
                        type="button"
                        onClick={() => setShowArchivoCompleto((v) => !v)}
                        style={{
                            width: '100%',
                            padding: '10px 12px',
                            borderRadius: '10px',
                            border: '1px solid rgba(255,255,255,0.12)',
                            background: showArchivoCompleto ? 'rgba(0, 212, 255, 0.1)' : 'rgba(0,0,0,0.25)',
                            color: '#e2e8f0',
                            fontSize: '11px',
                            fontWeight: 800,
                            cursor: 'pointer',
                        }}
                    >
                        {showArchivoCompleto
                            ? 'Ver solo obligaciones del licitante'
                            : `Ver archivo forense completo (+${archivalCount} ítems de contexto)`}
                    </button>
                </div>
            )}

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
                            const cardKey = buildStableReactKey({
                                prefix: 'compliance',
                                scope: activeZoneTab,
                                index: i,
                                item: c,
                                identityFields: ['id', 'tipo', 'page', 'zona_origen', 'bucketKey', 'agent_id', 'snippet'],
                            });
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
                            const cardKey = buildStableReactKey({
                                prefix: 'otros',
                                scope: 'hallazgos',
                                index: i,
                                item: c,
                                identityFields: ['id', 'tipo', 'page', 'zona_origen', 'bucketKey', 'agent_id', 'snippet'],
                            });
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
    // ESTADO GLOBAL: Conexión caída
    const [isServerDisconnected, setIsServerDisconnected] = useState(false);

    useEffect(() => {
        const handleDisconnect = () => setIsServerDisconnected(true);
        window.addEventListener('server-connection-error', handleDisconnect);
        return () => window.removeEventListener('server-connection-error', handleDisconnect);
    }, []);

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
    /** Hitos del procedimiento — fuente primaria: GET /submission-checklist (independiente del dictamen). */
    const [submissionChecklist, setSubmissionChecklist] = useState(null);
    const [submissionChecklistError, setSubmissionChecklistError] = useState(null);
    const [submissionChecklistLoading, setSubmissionChecklistLoading] = useState(false);
    const [sessionHealth, setSessionHealth] = useState(null);
    const [sessionHealthBusy, setSessionHealthBusy] = useState(false);
    const [goNoGoResult, setGoNoGoResult] = useState(null);
    const [showGoNoGoPanel, setShowGoNoGoPanel] = useState(false);
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [analysisOverlayVisible, setAnalysisOverlayVisible] = useState(true);
    const [reprocessingDocId, setReprocessingDocId] = useState(null);
    const [auditProgress, setAuditProgress] = useState({ percent: 0, currentFile: "" });
    const [chatMessages, setChatMessages] = useState([]);
    const [chatInput, setChatInput] = useState("");
    const [isThinking, setIsThinking] = useState(false);
    const [generationResults, setGenerationResults] = useState(null);
    /** Incrementa tras generación OK para que DeliveryPanel relea /downloads/list. */
    const [deliveryRefreshToken, setDeliveryRefreshToken] = useState(0);
    const [dragOffset, setDragOffset] = useState({ x: 30, y: 30 });
    const [isDragging, setIsDragging] = useState(false);
    const [validationEvents, setValidationEvents] = useState([]);
    const [validationBlockingCount, setValidationBlockingCount] = useState(0);
    /** UI: bloqueo por validación económica (Excel/cotización), no intake numérico en chat. */
    const [economicBlockingSessionLatch, setEconomicBlockingSessionLatch] = useState(false);
    const [documentQualityBlockingSessionLatch, setDocumentQualityBlockingSessionLatch] = useState(false);
    const [documentQualityGateSnapshot, setDocumentQualityGateSnapshot] = useState(null);
    const [intakeUiSnapshot, setIntakeUiSnapshot] = useState(null);
    const [validationBusy, setValidationBusy] = useState(false);
    const [validationStartTs, setValidationStartTs] = useState(null);
    const [validationClicks, setValidationClicks] = useState(0);
    const [pendingJustificationEvent, setPendingJustificationEvent] = useState(null);
    const [latestPriceProvenance, setLatestPriceProvenance] = useState(null);
    const [showPriceProvenanceModal, setShowPriceProvenanceModal] = useState(false);
    const [chatProvBadgeHover, setChatProvBadgeHover] = useState(null);
    const [provenanceCardPulse, setProvenanceCardPulse] = useState(false);
    const [provenanceModalAnimIn, setProvenanceModalAnimIn] = useState(false);
    const [provenanceModalPrePulse, setProvenanceModalPrePulse] = useState(false);
    const { acknowledgeWarning, submitJustification, trackValidationEvent } = useValidationManager(sessionId);
    const [generationStreamRuns, setGenerationStreamRuns] = useState(createInitialGenerationStreamRuns);
    const [generationQueueState, setGenerationQueueState] = useState(null);
    const [activeGenerationMode, setActiveGenerationMode] = useState(null);
    const [expedienteGuided, setExpedienteGuided] = useState(null);
    const [generationOverlayVisible, setGenerationOverlayVisible] = useState(true);

    const panelLabels = useMemo(
        () => mergePanelLabels(expedienteGuided?.panel_button_labels),
        [expedienteGuided],
    );
    const generationHints = useMemo(
        () => mergeGenerationHints(expedienteGuided?.generation_hints),
        [expedienteGuided],
    );
    const overlayMessages = useMemo(
        () => mergeOverlayMessages(expedienteGuided?.overlay_messages),
        [expedienteGuided],
    );

    const isAnyGenerationActive = useMemo(
        () => isAnyGenerationStreamActive(generationStreamRuns),
        [generationStreamRuns],
    );
    const generationProgress = useMemo(
        () => primaryGenerationProgressForDisplay(generationStreamRuns),
        [generationStreamRuns],
    );
    const dualStreamBanner = useMemo(
        () => dualStreamParallelBannerEs(generationStreamRuns),
        [generationStreamRuns],
    );

    const setStreamProgressForMode = useCallback((mode, updater) => {
        const streamId = generationStreamIdForMode(mode);
        setGenerationStreamRuns((prev) => ({
            ...prev,
            [streamId]: {
                ...prev[streamId],
                progress:
                    typeof updater === 'function'
                        ? updater(prev[streamId]?.progress || { percent: 0, message: '', held: false })
                        : updater,
            },
        }));
    }, []);

    const setStreamActiveForMode = useCallback((mode, active) => {
        const streamId = generationStreamIdForMode(mode);
        setGenerationStreamRuns((prev) => ({
            ...prev,
            [streamId]: { ...prev[streamId], active },
        }));
    }, []);
    const [downloadHighlightMode, setDownloadHighlightMode] = useState(null);
    const deliveryPanelRef = useRef(null);
    const {
        bundle: downloadBundle,
        refreshAll: refreshDownloadBundle,
        loadingAll: downloadBundleLoading,
    } = useGenerationDownloadBundle(sessionId, deliveryRefreshToken);

    const focusDownloadAfterGeneration = useCallback((mode) => {
        const resolved = mode || 'full';
        setDownloadHighlightMode(resolved);
        setTimeout(() => {
            document
                .getElementById(`generation-download-${resolved}`)
                ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 500);
        setTimeout(() => setDownloadHighlightMode(null), 15000);
    }, []);

    const scrollToDeliveryPanel = useCallback(() => {
        deliveryPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, []);

    // --- RESIZE STATES: Para anchos de páneles ajustables ---
    const [leftWidth, setLeftWidth] = useState(300);
    const [rightWidth, setRightWidth] = useState(400);
    const [isResizingLeft, setIsResizingLeft] = useState(false);
    const [isResizingRight, setIsResizingRight] = useState(false);
    const [isHoverLeft, setIsHoverLeft] = useState(false);
    const [isHoverRight, setIsHoverRight] = useState(false);

    /**
     * Fase C (cinturón A1): herramientas de sesión bajo el Dashboard.
     * null = ningún panel visible (pestaña pulsada de nuevo para contraer).
     * @type {null | 'calendario' | 'checklist_fisico' | 'documentos_candidatos' | 'formatos_detectados' | 'post_junta' | 'economico' | 'calidad_docs' | 'avanzado'}
     */
    const [sessionToolsTab, setSessionToolsTab] = useState(null);

    useEffect(() => {
        auditJobWatchRef.current = null;
        auditJobResumeAttemptedRef.current = null;
        setSessionToolsTab(null);
        setIntakeUiSnapshot(null);
    }, [sessionId]);

    useEffect(() => {
        if (
            sessionToolsTab === 'avanzado' &&
            import.meta.env.VITE_SHOW_VALIDATION_POLICY === 'false'
        ) {
            setSessionToolsTab(null);
        }
    }, [sessionToolsTab]);

    const fileInputRef = useRef(null);
    const chatQuotationFileRef = useRef(null);
    const uploadAbortControllerRef = useRef(null);
    const chatEndRef = useRef(null);
    const chatInputRef = useRef(null);
    const chatFormRef = useRef(null);
    const pendingForensicRiskContextRef = useRef(null);
    const companySelectRef = useRef(null);
    /** Solo para limpiar claves del Set de módulo al cambiar de sesión. */
    const prevSessionIdForChatBootstrapRef = useRef(null);
    /** Evita duplicar polling del mismo job (p. ej. tras F5 + resume). */
    const auditJobWatchRef = useRef(null);
    /** Una sola pasada de resume por sesión (evita bucle por deps inestables). */
    const auditJobResumeAttemptedRef = useRef(null);

    // --- HELPER: Inyectar guía del asistente en el chat ---
    const pushAssistantGuidance = (text, isGlow = false) => {
        const body = text || "⚠️ No se recibió mensaje del asistente.";
        // Dedupe robusto: algunos flujos re-emiten el mismo mensaje con diferencias mínimas de whitespace.
        const dedupeKey = String(body)
            .replace(/\r\n/g, "\n")
            .replace(/[ \t]+\n/g, "\n")
            .replace(/\n{3,}/g, "\n\n")
            .replace(/[ \t]{2,}/g, " ")
            .trim();
        const botMsg = { sender: 'bot', text: body, isGlow: isGlow, _dedupeKey: dedupeKey };
        setChatMessages((prev) => {
            // Evitar duplicados inmediatos y duplicados repetidos en ráfaga (últimos 5).
            const tail = prev.slice(Math.max(0, prev.length - 5));
            if (tail.some((m) => m?.sender === 'bot' && (m?._dedupeKey || "").trim() === dedupeKey)) {
                return prev;
            }
            return [...prev, botMsg];
        });
        
        // Foco visual: Scroll automático al nuevo mensaje
        setTimeout(() => {
            chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }, 100);
    };

    const updateIntakeUiSnapshotFromBotData = useCallback((botData) => {
        if (!botData || typeof botData !== 'object') return;
        if (!botData.intake_active) {
            setIntakeUiSnapshot(null);
            return;
        }
        const total = Number(botData.progress_total || 0);
        if (!Number.isFinite(total) || total <= 0) {
            setIntakeUiSnapshot(null);
            return;
        }
        const current = Number(botData.progress_current || 0);
        const safeCurrent = Number.isFinite(current) ? current : 0;
        const summary = botData.intake_summary && typeof botData.intake_summary === 'object' ? botData.intake_summary : {};
        const blockingCount = Number(summary.blocking_count ?? botData.blocking_count ?? 0) || 0;
        setIntakeUiSnapshot({
            progressCurrent: safeCurrent,
            progressTotal: total,
            progressLabel: String(botData.progress_label || `Pregunta ${safeCurrent} de ${total}`),
            blockingCount,
            remainingCount: Math.max(total - safeCurrent, 0),
            isResumed: String(botData.tipo || '').includes('resume'),
            auditMode: String(import.meta.env.VITE_DOCUMENT_FILL_GATE_MODE || 'audit').toLowerCase() === 'audit',
        });
    }, []);

    const clearExpertChat = () => {
        setChatMessages([]);
        setIsThinking(false);
        setLatestPriceProvenance(null);
        setChatProvBadgeHover(null);
    };

    useEffect(() => {
        if (!latestPriceProvenance) return;
        setProvenanceCardPulse(true);
        const t = setTimeout(() => setProvenanceCardPulse(false), 900);
        return () => clearTimeout(t);
    }, [latestPriceProvenance?.capturedAt]);

    useEffect(() => {
        if (!showPriceProvenanceModal) {
            setProvenanceModalAnimIn(false);
            setProvenanceModalPrePulse(false);
            return;
        }
        setProvenanceModalAnimIn(false);
        const id = requestAnimationFrame(() => {
            setProvenanceModalAnimIn(true);
        });
        setProvenanceModalPrePulse(true);
        const pulseT = setTimeout(() => setProvenanceModalPrePulse(false), 700);
        return () => {
            cancelAnimationFrame(id);
            clearTimeout(pulseT);
        };
    }, [showPriceProvenanceModal]);

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

    // Tras elegir empresa: llamada al chat con query vacía para mostrar pending_questions o mensaje guía.
    const triggerChatbotBootstrap = useCallback(async (force = false) => {
        if (!sessionId) return;
        const key = `bootstrap::${sessionId}::${selectedCompanyId || 'no-company'}`;
        if (!force && chatProactiveBootstrapDoneKeys.has(key)) return;
        chatProactiveBootstrapDoneKeys.add(key);

        console.log(`[LicitAI] Chat Bootstrap iniciado para: ${sessionId} (force=${force})`);

        try {
            const res = await axios.post(`${API_BASE}/chatbot/ask`, {
                query: '',
                session_id: sessionId,
                company_id: selectedCompanyId || null,
            });
            updateIntakeUiSnapshotFromBotData(res.data?.data || {});
            const text = (res.data?.reply || '').trim();
            if (!text) return;
            
            setChatMessages((prev) => {
                if (prev.some(m => m.text === text)) return prev;
                const glow = text.includes('📋') || text.includes('**') || text.includes('✨') || text.includes('|');
                const updated = [...prev, { sender: 'bot', text, isGlow: glow }];
                setTimeout(() => {
                    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
                }, 100);
                return updated;
            });
        } catch (err) {
            console.warn('[LicitAI] Error en bootstrap del chat:', err);
        } finally {
            setIsThinking(false);
        }
    }, [sessionId, selectedCompanyId, updateIntakeUiSnapshotFromBotData]);

    useEffect(() => {
        triggerChatbotBootstrap();
    }, [sessionId, selectedCompanyId, triggerChatbotBootstrap]);

    // Evitar que isThinking quede pegado tras reinicio de backend o peticiones abortadas.
    useEffect(() => {
        setIsThinking(false);
    }, [sessionId, selectedCompanyId]);

    useEffect(() => {
        if (selectedCompanyId) {
            localStorage.setItem('licitai_selected_company', selectedCompanyId);
        }
    }, [selectedCompanyId]);

    const fetchSources = useCallback(async (options = {}) => {
        if (!sessionId || sessionId === 'null') return;
        const { skipCache = false, retries = 5 } = options;

        if (!skipCache) {
            const cached = loadCachedSources(sessionId);
            if (cached?.length) {
                setSources(cached);
            }
        }

        for (let attempt = 0; attempt < retries; attempt += 1) {
            try {
                const res = await axios.get(
                    `${API_BASE}/upload/list/${encodeURIComponent(sessionId)}`,
                    { timeout: 45000 },
                );
                const raw = res.data?.data?.documents;
                const docs = Array.isArray(raw) ? raw : [];
                console.log(`[LicitAI] fetchSources → ${docs.length} doc(s) para sesión: ${sessionId}`);
                if (docs.length) {
                    saveCachedSources(sessionId, docs);
                } else {
                    clearCachedSources();
                }
                setSources(docs);
                return docs;
            } catch (err) {
                console.warn(`[LicitAI] fetchSources intento ${attempt + 1}/${retries}:`, err?.message || err);
                if (attempt < retries - 1) {
                    await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
                }
            }
        }
        return null;
    }, [sessionId]);

    const fetchDictamen = useCallback(async () => {
        if (!sessionId || sessionId === "null") return;
        try {
            const res = await axios.get(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/dictamen`,
                { timeout: 120000 },
            );
            if (res.data.success && res.data.data.dictamen) {
                const d = res.data.data.dictamen;
                // Dictámenes viejos: se guardó "éxito" con 0 ítems al confundir job_id con resultados del orquestador.
                const looksLikeStaleEnqueueBug =
                    d.dictamen_schema_version !== 2 &&
                    d.dictamen_schema_version !== 3 &&
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
                const ftFromApi = res.data.data?.fast_track_document_candidates;
                if (ftFromApi && typeof ftFromApi === 'object') {
                    if (ftFromApi.sobre_1_tecnico) {
                        enriched = {
                            ...enriched,
                            documentCandidatesConsolidated: ftFromApi,
                        };
                    }
                    if (ftFromApi.candidate_document_list || Array.isArray(ftFromApi)) {
                        enriched = {
                            ...enriched,
                            fastTrackDocumentCandidates: ftFromApi,
                        };
                    } else if (!enriched.fastTrackDocumentCandidates) {
                        enriched = { ...enriched, fastTrackDocumentCandidates: ftFromApi };
                    }
                }
                const checklistFromApi = res.data.data?.submission_checklist;
                if (checklistFromApi && typeof checklistFromApi === 'object') {
                    enriched = { ...enriched, submissionChecklist: checklistFromApi };
                    setSubmissionChecklist(checklistFromApi);
                    setSubmissionChecklistError(null);
                }
                const corpFromApi = res.data.data?.corporate_physical_document_candidates;
                if (corpFromApi && typeof corpFromApi === 'object') {
                    enriched = { ...enriched, corporatePhysicalDocumentCandidates: corpFromApi };
                }
                const pliegoFromApi = res.data.data?.pliego_formats_panel;
                if (pliegoFromApi && typeof pliegoFromApi === 'object' && pliegoFromApi.sobre_1_tecnico) {
                    enriched = {
                        ...enriched,
                        pliegoFormatsPanel: pliegoFromApi,
                        documentCandidatesConsolidated: pliegoFromApi,
                        fastTrackDocumentCandidates: pliegoFromApi,
                    };
                }
                const inferredTelem = synthesizePipelineTelemetryFromDictamen(enriched);
                if (inferredTelem) {
                    enriched = { ...enriched, pipelineTelemetry: inferredTelem };
                }
                if (res.data.data?.risk_decisions_v1) {
                    enriched = { ...enriched, risk_decisions_v1: res.data.data.risk_decisions_v1 };
                }
                setAuditResults(applyInfrastructureUxOverrides(enriched));

                const persistedQualityHints = res.data.data.last_document_quality_waiting_hints;
                if (persistedQualityHints && typeof persistedQualityHints === "object") {
                    setDocumentQualityGateSnapshot({
                        reason: String(persistedQualityHints.reason || ""),
                        metrics:
                            persistedQualityHints.metrics &&
                            typeof persistedQualityHints.metrics === "object"
                                ? persistedQualityHints.metrics
                                : {},
                    });
                    setDocumentQualityBlockingSessionLatch(true);
                } else {
                    setDocumentQualityGateSnapshot(null);
                    setDocumentQualityBlockingSessionLatch(false);
                }
            } else {
                setAuditResults(null);
                setDocumentQualityGateSnapshot(null);
                setDocumentQualityBlockingSessionLatch(false);
            }

            // Panel Go/No-Go solo si quedó pendiente SIN acknowledgment (legacy o generation).
            if (res.data.success && res.data.data.go_no_go_result) {
                const gng = res.data.data.go_no_go_result;
                const stopReason = res.data.data.stop_reason;
                const gngOverride = res.data.data.go_no_go_override;
                if (gng && stopReason === 'GO_NO_GO_PENDING' && !isGoNoGoAcknowledged(gngOverride)) {
                    setGoNoGoResult(gng);
                    setShowGoNoGoPanel(true);
                } else {
                    setShowGoNoGoPanel(false);
                }
            }
        } catch (err) {
            console.error("Error fetching dictamen from Postgres:", err);
        }
    }, [sessionId]);

    const fetchSubmissionChecklist = useCallback(async () => {
        if (!sessionId || sessionId === 'null') return;
        setSubmissionChecklistLoading(true);
        try {
            const res = await axios.get(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/submission-checklist`,
                { timeout: 30000 },
            );
            if (res.data?.success && res.data?.data?.submission_checklist) {
                const cl = res.data.data.submission_checklist;
                setSubmissionChecklist(cl);
                setSubmissionChecklistError(null);
                setAuditResults((prev) =>
                    prev ? { ...prev, submissionChecklist: cl } : prev,
                );
            } else {
                setSubmissionChecklist(null);
                setSubmissionChecklistError(
                    res.data?.message || 'Sin calendario (analiza las bases primero).',
                );
            }
        } catch (err) {
            setSubmissionChecklist(null);
            setSubmissionChecklistError(
                err?.response?.data?.detail || err?.message || 'Error al cargar fechas críticas',
            );
            console.error('Error fetching submission checklist:', err);
        } finally {
            setSubmissionChecklistLoading(false);
        }
    }, [sessionId]);

    const sessionHitos = useMemo(() => {
        if (submissionChecklist?.hitos?.length) return submissionChecklist.hitos;
        if (auditResults?.submissionChecklist?.hitos?.length) {
            return auditResults.submissionChecklist.hitos;
        }
        return [];
    }, [submissionChecklist, auditResults]);

    const fetchSessionHealth = useCallback(async () => {
        if (!sessionId || sessionId === 'null') return;
        try {
            const res = await axios.get(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/health`,
                { timeout: 15000 },
            );
            if (res.data?.success && res.data?.data?.session_health) {
                setSessionHealth(res.data.data.session_health);
            } else {
                setSessionHealth(null);
            }
        } catch (err) {
            console.warn('Error fetching session health:', err?.message || err);
            setSessionHealth(null);
        }
    }, [sessionId]);

    const fetchExpedienteGuided = useCallback(async () => {
        if (!sessionId || sessionId === 'null') return;
        try {
            const hasAudit = Boolean(auditResults?.fechaAuditoria || auditResults?.dictamen);
            const res = await axios.get(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/expediente-guided`,
                { params: { analysis_done: hasAudit }, timeout: 15000 },
            );
            if (res.data?.success && res.data?.data) {
                setExpedienteGuided(res.data.data);
            }
        } catch (err) {
            console.warn('Error fetching expediente guided:', err?.message || err);
        }
    }, [sessionId, auditResults]);

    const runSessionRehydrate = useCallback(async () => {
        if (!sessionId || sessionId === 'null') return;
        setSessionHealthBusy(true);
        try {
            const res = await axios.post(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/rehydrate-analysis-artifacts`,
                {
                    ...(selectedCompanyId ? { company_id: selectedCompanyId } : {}),
                },
                { timeout: 30000, validateStatus: (s) => s === 200 || s === 202 },
            );
            const payload = res.data?.data || {};
            if (payload.async && payload.job_id) {
                const jobResult = await pollAgentsJobUntilDone(
                    payload.job_id,
                    ({ message, pct }) => {
                        if (message) {
                            setSessionHealth((prev) => ({
                                ...(prev || {}),
                                maintenance_job: {
                                    job_id: payload.job_id,
                                    status: 'RUNNING',
                                    progress: { message, pct },
                                },
                            }));
                        }
                    },
                    { timeoutMs: 120000 },
                );
                const inner = jobResult?.data || jobResult || {};
                if (inner.session_health) {
                    setSessionHealth(inner.session_health);
                }
                if (jobResult?.status === 'success' || inner.rehydrate?.success) {
                    await fetchSubmissionChecklist();
                    await fetchDictamen();
                    pushAssistantGuidance(
                        'Artefactos de análisis actualizados (calendario, documentos detectados y preguntas para la junta).',
                        false,
                    );
                } else {
                    pushAssistantGuidance(
                        inner.rehydrate?.error || 'No se pudieron reconstruir todos los artefactos.',
                        true,
                    );
                }
                return;
            }
            if (payload.session_health) {
                setSessionHealth(payload.session_health);
            }
            if (res.data?.success) {
                await fetchSubmissionChecklist();
                await fetchDictamen();
                pushAssistantGuidance(
                    'Artefactos de análisis actualizados (calendario, documentos detectados y preguntas para la junta).',
                    false,
                );
            } else {
                pushAssistantGuidance(
                    res.data?.message || 'No se pudieron reconstruir todos los artefactos. Revisa el análisis de bases.',
                    true,
                );
            }
        } catch (err) {
            pushAssistantGuidance(
                err?.response?.data?.detail || err?.message || 'Error al actualizar artefactos de la sesión.',
                true,
            );
        } finally {
            setSessionHealthBusy(false);
        }
    }, [
        sessionId,
        selectedCompanyId,
        fetchSubmissionChecklist,
        fetchDictamen,
    ]);

    // CARGA INICIAL (Solo si hay sesión)
    useEffect(() => {
        if (sessionId) {
            const cachedSources = loadCachedSources(sessionId);
            if (cachedSources?.length) {
                setSources(cachedSources);
            }
            // Limpiar estados de la sesión anterior para evitar fugas visuales (Data Leak / Hallucination UX)
            setAuditResults(null);
            setGenerationResults(null);
            setGoNoGoResult(null);
            setShowGoNoGoPanel(false);
            setChatMessages([]);
            setValidationEvents([]);
            setIntakeUiSnapshot(null);
            setDocumentQualityGateSnapshot(null);
            setDocumentQualityBlockingSessionLatch(false);
            setLatestPriceProvenance(null);
            setSubmissionChecklist(null);
            setSubmissionChecklistError(null);
            setSubmissionChecklistLoading(false);
            setSessionHealth(null);
            setSessionHealthBusy(false);

            // Carga real de la nueva sesión
            fetchCompanies();
            fetchSources();
            fetchSessionName();
            fetchDictamen();
            fetchSubmissionChecklist();
            fetchSessionHealth();
            fetchExpedienteGuided();

            const savedCompany = localStorage.getItem('licitai_selected_company');
            if (savedCompany) {
                setSelectedCompanyId(savedCompany);
            } else {
                setSelectedCompanyId('');
            }
        }
    }, [sessionId, fetchSources, fetchDictamen, fetchSubmissionChecklist, fetchSessionHealth, fetchExpedienteGuided]);

    useEffect(() => {
        if (sessionId && sessionId !== 'null') {
            fetchExpedienteGuided();
        }
    }, [auditResults, sessionId, fetchExpedienteGuided]);

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

    const applyOrchestratorResult = useCallback(async (orchestrator) => {
        if (!orchestrator?.data) {
            await fetchDictamen();
            await fetchSubmissionChecklist();
            await fetchSources();
            return;
        }
        const stopReason = orchestrator?.agent_decision?.stop_reason;
        const gngOverride =
            orchestrator?.data?.go_no_go_override
            || orchestrator?.go_no_go_override;
        if (
            (stopReason === 'GO_NO_GO_PENDING' || orchestrator?.status === 'go_no_go_pending')
            && !isGoNoGoAcknowledged(gngOverride)
        ) {
            const gngResult = orchestrator?.go_no_go_result
                || orchestrator?.data?.go_no_go_result
                || orchestrator?.data?.go_no_go;
            if (gngResult) {
                setGoNoGoResult(gngResult);
                setShowGoNoGoPanel(true);
                setAuditProgress({ percent: 0, currentFile: '' });
                pushAssistantGuidance(
                    '⚠️ Se detectaron brechas críticas entre tu perfil de empresa y los requisitos de las bases. Revisa el Semáforo Go/No-Go y decide si continuar o detener el proceso.',
                    true
                );
                return;
            }
        }

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
        if (orchestrator.dictamen && typeof orchestrator.dictamen === 'object') {
            setAuditResults(applyInfrastructureUxOverrides(enrichDictamenFromStorage(orchestrator.dictamen)));
        } else {
            const nuevosDictamen = processAuditResults(auditPayload);
            if (nuevosDictamen) {
                nuevosDictamen.fechaAuditoria = new Date().toLocaleString('es-MX');
                setAuditResults(nuevosDictamen);
            }
        }
        await fetchDictamen();
        await fetchSubmissionChecklist();
        await fetchSessionHealth();
        await fetchSources();

        const orchStatus = orchestrator?.status;
        if (orchStatus === 'success') {
            pushAssistantGuidance(
                'Análisis de bases completado. El dictamen forense está actualizado y la información ya está indexada para consultas. Si necesitas generar documentos o completar datos del expediente, te iré guiando por este chat.',
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
                    '\n\nAvisos de bases y partidas (revisar antes de cotizar):\n' +
                    gapAlerts.slice(0, 8).map((x) => `• ${x}`).join('\n');
            }
            pushAssistantGuidance(waitMsg, true);
        } else if (orchStatus === 'error') {
            pushAssistantGuidance(
                orchestrator?.chatbot_message || 'No se pudo completar el análisis de las bases. Revisa el estado de las fuentes o los logs del sistema.',
                true
            );
        }

        if (sessionId && selectedCompanyId) {
            setTimeout(() => triggerChatbotBootstrap(true), 1200);
        }
    }, [sessionId, selectedCompanyId, fetchDictamen, fetchSubmissionChecklist, fetchSessionHealth, fetchSources, triggerChatbotBootstrap]);

    const watchAuditJobInBackground = useCallback((jobId, initialProgress = {}) => {
        if (!jobId || !sessionId) return;
        if (auditJobWatchRef.current === jobId) return;
        auditJobWatchRef.current = jobId;

        setIsAnalyzing(true);
        setAnalysisOverlayVisible(true);
        savePendingAgentsJob(sessionId, jobId);
        const prog = initialProgress || {};
        setAuditProgress({
            percent: typeof prog.pct === 'number' ? Math.max(5, prog.pct) : 10,
            currentFile: prog.message || 'Análisis en servidor: sincronizando…',
        });

        void (async () => {
            try {
                const orchestrator = await pollAgentsJobUntilDone(
                    jobId,
                    (u) => {
                        setAuditProgress((prev) => {
                            const nextMsg = u.message || prev.currentFile;
                            let nextPct = prev.percent;
                            if (typeof u.pct === 'number' && !Number.isNaN(u.pct)) {
                                nextPct = Math.max(prev.percent, u.pct);
                            }
                            return { ...prev, currentFile: nextMsg, percent: nextPct };
                        });
                    },
                    { timeoutMs: AGENTS_JOB_BACKGROUND_TIMEOUT_MS },
                );
                setAuditProgress((prev) => ({ ...prev, percent: 100, currentFile: 'Análisis completado' }));
                await new Promise((r) => setTimeout(r, 700));
                await applyOrchestratorResult(orchestrator);
            } catch (bgErr) {
                if (bgErr?.name === 'AgentsJobStillRunningError') {
                    pushAssistantGuidance(
                        `El análisis sigue en el servidor (${bgErr.progress?.pct ?? '?'}% — ${bgErr.progress?.message || 'procesando'}). Mantén esta pestaña abierta o recarga en unos minutos.`,
                        false
                    );
                } else {
                    console.error('Background audit error:', bgErr);
                    pushAssistantGuidance(
                        bgErr?.message || 'El análisis en segundo plano falló. Revisa los logs del backend.',
                        true
                    );
                }
            } finally {
                auditJobWatchRef.current = null;
                clearPendingAgentsJob();
                setIsAnalyzing(false);
                setTimeout(() => setAuditProgress({ percent: 0, currentFile: '' }), 2000);
            }
        })();
    }, [sessionId, applyOrchestratorResult]);

    /** Tras F5 o timeout del browser: reanuda overlay + polling si el job sigue RUNNING. */
    useEffect(() => {
        if (!sessionId) {
            auditJobResumeAttemptedRef.current = null;
            return undefined;
        }
        if (auditJobResumeAttemptedRef.current === sessionId) {
            return undefined;
        }
        auditJobResumeAttemptedRef.current = sessionId;

        let cancelled = false;

        const pendingLocal = loadPendingAgentsJob(sessionId);
        if (pendingLocal && auditJobWatchRef.current !== pendingLocal) {
            setIsAnalyzing(true);
            setAuditProgress((prev) => {
                const nextPct = Math.max(prev.percent, 5);
                const nextFile = prev.currentFile || 'Reconectando con análisis en servidor…';
                if (prev.percent === nextPct && prev.currentFile === nextFile) {
                    return prev;
                }
                return { percent: nextPct, currentFile: nextFile };
            });
        }

        const resumeActiveAuditJob = async () => {
            let jobId = pendingLocal;
            let progress = {};

            try {
                const res = await axios.get(
                    `${API_BASE}/agents/sessions/${encodeURIComponent(sessionId)}/active-job`,
                    { timeout: 45000 },
                );
                const active = res.data?.data;
                if (active?.job_id && active?.status === 'RUNNING') {
                    jobId = active.job_id;
                    progress = active.progress || {};
                    savePendingAgentsJob(sessionId, jobId);
                } else if (!active?.job_id && pendingLocal) {
                    // Vínculo Redis limpiado: el job ya no está activo en servidor.
                    clearPendingAgentsJob();
                    jobId = null;
                    if (!cancelled) {
                        setIsAnalyzing(false);
                    }
                }
            } catch (err) {
                console.warn('[LicitAI] active-job lookup:', err?.message || err);
            }

            if (cancelled || !jobId) return;

            if (auditJobWatchRef.current === jobId) return;

            try {
                const st = await axios.get(`${API_BASE}/agents/jobs/${jobId}/status`, { timeout: 45000 });
                const job = st.data?.data;
                const terminal = new Set(['COMPLETED', 'FAILED']);
                if (job?.status === 'RUNNING') {
                    watchAuditJobInBackground(jobId, job.progress || progress);
                    const bootstrapKey = `bootstrap::${sessionId}::${selectedCompanyId || 'no-company'}`;
                    chatProactiveBootstrapDoneKeys.delete(bootstrapKey);
                    triggerChatbotBootstrap(true);
                } else if (job?.status === 'COMPLETED') {
                    clearPendingAgentsJob();
                    if (!cancelled) setIsAnalyzing(false);
                    await fetchDictamen();
                    await fetchSubmissionChecklist();
                    await fetchSessionHealth();
                    await fetchSources({ skipCache: true });
                } else if (terminal.has(String(job?.status || '').toUpperCase())) {
                    clearPendingAgentsJob();
                    if (!cancelled) setIsAnalyzing(false);
                    if (job?.status === 'FAILED' && isStaleOrInterruptedJobError(job?.error)) {
                        void tryLoadExistingDictamen(sessionId, fetchDictamen, pushAssistantGuidance);
                    }
                } else {
                    clearPendingAgentsJob();
                    if (!cancelled) setIsAnalyzing(false);
                }
            } catch {
                if (pendingLocal && auditJobWatchRef.current !== pendingLocal) {
                    try {
                        const st = await axios.get(
                            `${API_BASE}/agents/jobs/${pendingLocal}/status`,
                            { timeout: 45000 },
                        );
                        const stJob = st.data?.data;
                        if (stJob?.status === 'RUNNING') {
                            watchAuditJobInBackground(pendingLocal, { pct: 5, message: 'Reconectando…' });
                        } else {
                            clearPendingAgentsJob();
                            if (!cancelled) setIsAnalyzing(false);
                        }
                    } catch {
                        clearPendingAgentsJob();
                        if (!cancelled) setIsAnalyzing(false);
                    }
                } else if (!cancelled) {
                    clearPendingAgentsJob();
                    setIsAnalyzing(false);
                }
            }
        };

        void resumeActiveAuditJob();
        return () => { cancelled = true; };
    }, [sessionId, selectedCompanyId, watchAuditJobInBackground, triggerChatbotBootstrap, fetchDictamen, fetchSources]);

    useEffect(() => {
        if (!isAnalyzing || !sessionId) return undefined;
        const id = setInterval(() => {
            void fetchSources({ skipCache: true, retries: 2 });
        }, 15000);
        return () => clearInterval(id);
    }, [isAnalyzing, sessionId, fetchSources]);

    const fetchCompanies = async () => {
        try {
            const res = await axios.get(`${API_BASE}/companies/`);
            const companiesList = res.data.data || [];
            setCompanies(companiesList);
            
            // Validar que selectedCompanyId exista en el catálogo
            if (selectedCompanyId && companiesList.length > 0) {
                const exists = companiesList.some(c => c.id === selectedCompanyId);
                if (!exists) {
                    console.warn(`[LicitAI] Empresa "${selectedCompanyId}" no existe en catálogo; limpiando selección.`);
                    setSelectedCompanyId('');
                    localStorage.removeItem('licitai_selected_company');
                    pushAssistantGuidance(
                        '⚠️ La empresa previamente seleccionada ya no está disponible. Por favor, selecciona una empresa válida en el menú superior o créala en la vista de Empresas.',
                        true
                    );
                }
            }
        } catch (err) {
            console.error("Error fetching companies:", err);
        }
    };

    const handleFileUpload = async (e) => {
        const files = Array.from(e.target.files);
        if (files.length === 0) return;

        setIsAnalyzing(true);
        uploadAbortControllerRef.current = new AbortController();
        const signal = uploadAbortControllerRef.current.signal;

        for (const file of files) {
            // Verificar si el usuario canceló manualmente antes de procesar el siguiente archivo
            if (signal.aborted) break;

            const formData = new FormData();
            formData.append('file', file);
            formData.append('session_id', sessionId);
            
            try {
                // PASO 1: Subir archivo
                setAuditProgress({ percent: 0, currentFile: `📤 Subiendo ${file.name}… 0%` });
                const uploadRes = await axios.post(`${API_BASE}/upload/upload`, formData, {
                    signal,
                    onUploadProgress: (ev) => {
                        const total = ev.total;
                        const loaded = ev.loaded;
                        let pct = 0;
                        if (total && total > 0) {
                            pct = Math.min(99, Math.round((loaded * 100) / total));
                        } else if (file.size > 0) {
                            pct = Math.min(99, Math.round((loaded * 100) / file.size));
                        }
                        setAuditProgress({
                            percent: pct,
                            currentFile: `📤 Subiendo ${file.name}… ${pct}%`,
                        });
                    },
                });

                if (!uploadRes.data.success) {
                    console.error("Error en upload:", uploadRes.data.message);
                    continue;
                }

                const doc_id = uploadRes.data.data?.doc_id;
                if (!doc_id) {
                    console.error("No se recibió doc_id del servidor.");
                    continue;
                }

                setAuditProgress({
                    percent: 100,
                    currentFile: `📤 Subida completa: ${file.name}. Extrayendo texto…`,
                });

                // PASO 2: Disparar extracción OCR + indexación vectorial (sin progreso fino en navegador)
                setAuditProgress({ percent: 45, currentFile: `🔍 Extrayendo texto de ${file.name}…` });
                const formDataProcess = new FormData();
                formDataProcess.append('session_id', sessionId);
                
                const processRes = await axios.post(
                    `${API_BASE}/upload/process/${doc_id}`,
                    formDataProcess,
                    { 
                        signal,
                        timeout: 600000 
                    }
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
        uploadAbortControllerRef.current = null;
        setAuditProgress({ percent: 0, currentFile: "" });
        if (e?.target) {
            e.target.value = "";
        }
    };

    const handleCancelUpload = async () => {
        if (uploadAbortControllerRef.current) {
            uploadAbortControllerRef.current.abort();
        }
        try {
            // Avisar al backend para que detenga el procesamiento interno
            await axios.post(`${API_BASE}/upload/cancel/${sessionId}`);
        } catch (err) {
            console.warn("Error al notificar cancelación al backend:", err);
        }
        setIsAnalyzing(false);
        setAuditProgress({ percent: 0, currentFile: "Carga cancelada por el usuario." });
        setTimeout(() => setAuditProgress({ percent: 0, currentFile: "" }), 2000);
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
            const safeDocId = encodeURIComponent(docId);
            const safeSessionId = encodeURIComponent(sessionId);
            await axios.delete(
                `${API_BASE}/upload/${safeDocId}?session_id=${safeSessionId}`,
            );

            setAuditResults(null);
            setGenerationResults(null);

            await fetchSources({ skipCache: true });

            pushAssistantGuidance(
                'Listo: ese documento ya no forma parte de la licitación. El informe que veías dejó de mostrarse porque estaba ligado a los archivos que tenías; es normal, no significa que se haya “perdido” la licitación. Cuando tengas otra vez las bases en la lista de la izquierda, pulsa «Actualizar análisis» para obtener un informe nuevo.',
                true
            );
        } catch (err) {
            console.error("Error deleting source:", err);
            const status = err?.response?.status;
            if (status === 404) {
                clearCachedSources();
                await fetchSources({ skipCache: true });
                alert(
                    'Ese archivo ya no estaba registrado en el servidor (lista desactualizada). ' +
                        'Se actualizó la lista de fuentes; si aún ves un nombre fantasma, recarga la página (F5) y sube de nuevo el PDF correcto.',
                );
            } else {
                alert('No se pudo quitar el documento. Intenta de nuevo en unos momentos.');
            }
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
            if (selectedCompanyId) {
                formData.append('company_id', selectedCompanyId);
            }
            const resp = await axios.post(
                `${API_BASE}/upload/process/${docId}?force=true`,
                formData,
                { timeout: 600000 }
            );
            setAuditProgress({ percent: 100, currentFile: `✅ ${docName || 'Documento'} reindexado` });
            await fetchSources();
            setTimeout(() => setAuditProgress({ percent: 0, currentFile: '' }), 1600);
            const backendMsg = resp?.data?.message;
            pushAssistantGuidance(
                typeof backendMsg === 'string' && backendMsg.trim()
                    ? backendMsg
                    : `Listo: «${docName || docId}» se reprocesó (vectores y, si es Excel, partidas económicas). Pulsa «Actualizar análisis» cuando quieras refrescar el dictamen.`,
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
        // Limpiar job anterior (zombi o fallido) antes de encolar uno nuevo
        clearPendingAgentsJob();
        auditJobWatchRef.current = null;

        // Limpiar bloqueo de bootstrap para que el asistente vuelva a hablar tras el nuevo análisis
        const bootstrapKey = `bootstrap::${sessionId}::${selectedCompanyId || 'no-company'}`;
        chatProactiveBootstrapDoneKeys.delete(bootstrapKey);

        setIsAnalyzing(true);
        setAnalysisOverlayVisible(true);
        setAuditProgress({ percent: 10, currentFile: "Iniciando Auditoría..." });

        const pulseInterval = setInterval(() => {
            setAuditProgress(prev => {
                if (prev.percent < 90) return { ...prev, percent: prev.percent + 2 };
                return prev;
            });
        }, 3000);

        let deferAnalyzingReset = false;

        const continueAuditJobInBackground = (jobId, initialProgress) => {
            deferAnalyzingReset = true;
            const pct = typeof initialProgress?.pct === 'number' ? initialProgress.pct : 66;
            const msg = initialProgress?.message || 'Análisis en servidor (continúa en segundo plano)…';
            pushAssistantGuidance(
                `El análisis de bases sigue en el servidor (${pct}% — ${msg}). **No lo reinicies**; la ventana de progreso seguirá actualizándose.`,
                false
            );
            chatProactiveBootstrapDoneKeys.delete(bootstrapKey);
            setTimeout(() => triggerChatbotBootstrap(true), 1500);
            watchAuditJobInBackground(jobId, initialProgress);
        };

        try {
            const res = await axios.post(`${API_BASE}/agents/process`, {
                session_id: sessionId,
                company_id: selectedCompanyId || null,
                company_data: { "mode": "analysis_only" }
            });

            const encolado = res.data?.data;
            let orchestrator = null;

            if (encolado?.job_id) {
                clearInterval(pulseInterval);
                continueAuditJobInBackground(encolado.job_id, {
                    pct: 10,
                    message: 'Análisis en servidor (puedes seguir navegando)…',
                });
                return;
            }

            if (encolado && (encolado.analysis || encolado.compliance || encolado.economic)) {
                orchestrator = {
                    status: res.data.status,
                    data: encolado,
                    chatbot_message: res.data.chatbot_message,
                    agent_decision: res.data.agent_decision,
                    pipelineTelemetry: res.data.pipelineTelemetry,
                };
            }

            if (orchestrator?.data) {
                const orchStatus = orchestrator?.status;
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
                await applyOrchestratorResult(orchestrator);
            } else if (orchestrator?.status === 'success') {
                pushAssistantGuidance(
                    'Análisis de bases completado. El dictamen forense está actualizado y la información ya está indexada para consultas.',
                    false
                );
            }

        } catch (err) {
            if (err?.name === 'AgentsJobStillRunningError' && err?.jobId) {
                continueAuditJobInBackground(err.jobId, err.progress);
                return;
            }
            console.error("Audit error:", err);
            clearPendingAgentsJob();
            const errMsg = err?.message || '';
            if (isStaleOrInterruptedJobError(errMsg)) {
                const recovered = await tryLoadExistingDictamen(
                    sessionId,
                    fetchDictamen,
                    pushAssistantGuidance,
                );
                if (recovered) {
                    setAuditProgress({ percent: 100, currentFile: 'Dictamen ya disponible' });
                    setTimeout(() => setAuditProgress({ percent: 0, currentFile: '' }), 2000);
                    return;
                }
            }
            setAuditProgress((prev) => ({
                ...prev,
                currentFile: 'Error durante el análisis',
                percent: Math.max(prev.percent, 5),
            }));
            await new Promise((r) => setTimeout(r, 450));
            const stillRunningHint = err?.message?.includes('Tiempo de espera agotado')
                ? ' Si el backend sigue procesando, espera unos minutos y recarga la sesión (no reinicies el análisis).'
                : '';
            alert((err?.message || "Error durante la auditoría. Revisa el backend.") + stillRunningHint);
        } finally {
            clearInterval(pulseInterval);
            if (!deferAnalyzingReset) {
                setIsAnalyzing(false);
                setAuditProgress({ percent: 0, currentFile: "" });
            }
        }
    };

    const triggerGeneration = async (generationMode = 'full') => {
        if (isAnalyzing) {
            pushAssistantGuidance(
                "⏳ El análisis sigue en curso. Espera a que termine para generar propuesta y evitar inconsistencias.",
                true
            );
            return;
        }
        if (!selectedCompanyId) {
            pushAssistantGuidance(
                "⚠️ Para generar la propuesta necesito que selecciones una empresa en el menú superior. Si aún no tienes empresas registradas, ve a la vista 'Empresas' desde la pantalla principal.",
                true
            );
            return;
        }
        if (isGenerationModeButtonDisabled({
            runs: generationStreamRuns,
            modeId: generationMode,
            isAnalyzing: false,
            hasCompany: true,
        })) {
            if (isStreamActiveForMode(generationStreamRuns, generationMode)) {
                pushAssistantGuidance(
                    `⏳ Ya hay una generación **${generationModeLabelEs(generationMode)}** en curso. Espera a que termine.`,
                    true
                );
            } else if (
                generationStreamIdForMode(generationMode) !== 'full'
                && isGenerationStreamActive(generationStreamRuns, 'full')
            ) {
                pushAssistantGuidance(
                    '⏳ El modo **completo** está en curso; los modos parciales quedan en espera hasta que termine.',
                    true
                );
            } else {
                pushAssistantGuidance(
                    '⏳ Hay una generación en curso. Espera a que termine antes de iniciar otra.',
                    true
                );
            }
            return;
        }

        setGenerationResults(null);
        setEconomicBlockingSessionLatch(false);
        setDocumentQualityGateSnapshot(null);
        setActiveGenerationMode(generationMode);
        const modeForRun = generationMode;
        const modeLabel = generationModeLabelEs(generationMode);
        pushAssistantGuidance(`🚀 **${modeLabel}** — validando expediente y preparando documentos…`, false);
        setStreamActiveForMode(generationMode, true);
        setStreamProgressForMode(generationMode, {
            percent: 0,
            message: 'Encolando trabajo de generación...',
            held: false,
        });

        let finalOrchStatus = null;
        try {
            let companyPayload = companies.find((c) => c.id === selectedCompanyId) || {};
            try {
                const freshCo = await axios.get(
                    `${API_BASE}/companies/${encodeURIComponent(selectedCompanyId)}`
                );
                if (freshCo.data?.data) {
                    companyPayload = freshCo.data.data;
                }
            } catch (freshErr) {
                console.warn('[LicitAI] No se pudo refrescar empresa antes de generar:', freshErr?.message || freshErr);
            }

            const streamParam = generationStreamParamForMode(generationMode);
            const res = await axios.post(`${API_BASE}/agents/process`, {
                session_id: sessionId,
                company_id: selectedCompanyId,
                resume_generation: true,
                generation_mode: generationMode,
                ...(streamParam ? { generation_stream: streamParam } : {}),
                company_data: {
                    ...companyPayload,
                    mode: 'generation_only',
                    generation_mode: generationMode,
                    ...(streamParam ? { generation_stream: streamParam } : {}),
                },
            });

            const encolado = res.data?.data;
            let orchestrator = null;

            if (encolado?.job_id) {
                orchestrator = await pollAgentsJobUntilDone(encolado.job_id, (u) => {
                    setStreamProgressForMode(modeForRun, (prev) => {
                        const msg = u.message || prev.message || "Procesando propuesta…";
                        let pct = prev.percent;
                        if (typeof u.pct === "number" && !Number.isNaN(u.pct)) {
                            const p = Math.max(0, Math.min(100, u.pct));
                            if (u.orchestratorHeld && u.status === 'COMPLETED') {
                                pct = p;
                            } else {
                                pct = Math.max(prev.percent, p);
                            }
                        }
                        const heldLabel = u.orchestratorHeld ? ' (en pausa)' : '';
                        return {
                            percent: pct,
                            message: msg + (u.status === 'COMPLETED' && u.orchestratorHeld ? heldLabel : ''),
                            held: Boolean(u.orchestratorHeld && u.status === 'COMPLETED'),
                        };
                    });
                });
            } else if (encolado) {
                orchestrator = {
                    status: res.data.status,
                    data: encolado,
                    chatbot_message: res.data.chatbot_message,
                    missing_fields: res.data.missing_fields,
                    generation_state: res.data.generation_state,
                    agent_decision: res.data.agent_decision,
                };
            }

            const orchStatus = orchestrator?.status;
            finalOrchStatus = orchStatus;
            const stopReason = orchestrator?.agent_decision?.stop_reason;
            setGenerationQueueState(orchestrator?.generation_state || null);
            console.info('[LicitAI] Generación finalizó', {
                status: orchStatus,
                stop_reason: stopReason,
                has_data: Boolean(orchestrator?.data),
                generation_state: orchestrator?.generation_state,
            });
            if (orchStatus === 'already_running') {
                pushAssistantGuidance(
                    orchestrator?.chatbot_message
                        || 'Ya hay una generación en curso para este mismo alcance. Puedes usar el otro modo en paralelo.',
                    true,
                );
                setStreamProgressForMode(modeForRun, {
                    percent: 0,
                    message: 'Este alcance ya está en curso',
                    held: false,
                });
                return;
            } else if (stopReason === "GO_NO_GO_PENDING" || orchStatus === "go_no_go_pending") {
                const gngResult = orchestrator?.go_no_go_result
                    || orchestrator?.data?.go_no_go_result
                    || orchestrator?.data?.go_no_go;
                if (gngResult) {
                    setGoNoGoResult(gngResult);
                    setShowGoNoGoPanel(true);
                    pushAssistantGuidance(
                        "⚠️ La generación quedó en pausa por Go/No-Go. Revisa el semáforo y autoriza continuar para que se materialice el expediente descargable.",
                        true
                    );
                } else {
                    pushAssistantGuidance(
                        "La generación quedó en pausa por Go/No-Go, pero no se recibió el detalle del semáforo. Reintenta y revisa logs del backend.",
                        true
                    );
                }
                setStreamProgressForMode(modeForRun, { percent: 0, message: "Pausado: pendiente autorización Go/No-Go" });
                setValidationEvents([]);
                setValidationBlockingCount(0);
                setEconomicBlockingSessionLatch(false);
                setDocumentQualityBlockingSessionLatch(false);
                return;
            } else if (orchStatus === "waiting_for_data") {
                const baseMsg =
                    orchestrator?.chatbot_message || WAITING_FOR_DATA_FALLBACK_GENERATION_ES;
                const latchOn = orchestratorDataHasEconomicValidationBlocking(orchestrator?.data);
                const qualityLatchOn =
                    orchestratorDataHasDocumentQualityGateBlocking(orchestrator?.data)
                    || orchestratorDataHasDocumentFillQualityGateBlocking(orchestrator?.data);
                const qualitySnapshot = extractDocumentQualityGateSnapshot(orchestrator);
                setEconomicBlockingSessionLatch(!!latchOn);
                setDocumentQualityBlockingSessionLatch(!!qualityLatchOn);
                setDocumentQualityGateSnapshot(qualitySnapshot);
                setDeliveryRefreshToken((t) => t + 1);
                const freshBundle = await refreshDownloadBundle();
                focusDownloadAfterGeneration(modeForRun);
                const ecoReadyNow = Boolean(freshBundle?.economic?.ready)
                    && Number(freshBundle?.economic?.artifact_count || 0) > 0;
                const techReadyNow = Boolean(freshBundle?.technical?.ready)
                    && Number(freshBundle?.technical?.artifact_count || 0) > 0;
                const economicPause = modeForRun === 'economic'
                    || stopReason === 'ECONOMIC_PRICES_INCOMPLETE'
                    || !!latchOn;
                const downloadHint = qualityLatchOn
                    ? '\n\n**No hay archivos técnicos para descargar aún** — el bloque debajo del botón TÉCNICA muestra el motivo. Resuelve el aviso y vuelve a generar.'
                    : economicPause
                      ? '\n\n**Aún no descargues** — los archivos en ECONÓMICA pueden ser de una corrida anterior. Cierra la cotización en el chat y vuelve a generar.'
                      : ecoReadyNow
                        ? '\n\n**La cotización económica sí está lista** — usa el bloque **ECONÓMICA** debajo para descargar.'
                        : techReadyNow
                          ? '\n\n**La propuesta técnica sí está lista** — usa el bloque **TÉCNICA** debajo para descargar.'
                          : '\n\nSi ya se generó algo en otro alcance, revisa los bloques de descarga debajo de cada botón.';
                pushAssistantGuidance(
                    baseMsg + downloadHint
                        + formatGenerationWaitingExtra(orchestrator)
                        + formatGenerationStateJobsSummary(orchestrator?.generation_state),
                    true
                );
                setStreamProgressForMode(modeForRun, {
                    percent: 72,
                    message: `Pausado: ${stopReason || 'faltan datos — revisa los bloques de descarga'}`,
                    held: true,
                });
                const events = [];
                const results = orchestrator?.data;
                if (results && typeof results === "object") {
                    Object.keys(results).forEach((stage) => {
                        const r = results[stage];
                        const stageEvents = r?.data?.validation_events || r?.validation_events;
                        if (Array.isArray(stageEvents)) {
                            stageEvents.forEach((ev) => events.push({ ...ev, _stage: stage }));
                        }
                    });
                }
                buildDocumentQualityValidationEvents(results).forEach((ev) => events.push(ev));
                buildDocumentFillValidationEvents(results).forEach((ev) => events.push(ev));
                setValidationEvents(events);
                setValidationBlockingCount(events.filter((ev) => ev?.severity === "block").length);
                setValidationStartTs(Date.now());
                setValidationClicks(0);
                for (const ev of events) {
                    trackValidationEvent({
                        event: "validation_triggered",
                        session_id: sessionId,
                        error_type: ev.error_type,
                        severity: ev.severity,
                        item_id: ev?.context?.item_id,
                    }).catch(() => {});
                }
            } else if (orchStatus === "partial") {
                setGenerationResults(orchestrator.data || orchestrator);
                setDeliveryRefreshToken((t) => t + 1);
                focusDownloadAfterGeneration(modeForRun);
                pushAssistantGuidance(
                    (orchestrator?.chatbot_message || 'Generación parcial.')
                        + '\n\n**Descarga tus archivos** en el bloque verde justo debajo del botón que usaste.'
                        + formatGenerationWaitingExtra(orchestrator)
                        + formatGenerationStateJobsSummary(orchestrator?.generation_state),
                    true
                );
                setStreamProgressForMode(modeForRun, { percent: 100, message: 'Completado con advertencias', held: false });
            } else if (orchStatus === "success") {
                setGenerationResults(orchestrator.data || orchestrator);
                setDeliveryRefreshToken((t) => t + 1);
                focusDownloadAfterGeneration(modeForRun);
                // Req 6.3: No mostrar mensaje de éxito ambiguo si aún hay pending_questions activas.
                // El intakeUiSnapshot refleja si el flujo de preguntas sigue activo.
                const hasPendingIntake = intakeUiSnapshot && intakeUiSnapshot.progressTotal > 0 && intakeUiSnapshot.remainingCount > 0;
                if (hasPendingIntake) {
                    pushAssistantGuidance(
                        "✅ Documentos generados. Aún quedan datos pendientes en el chat. **Descarga lo ya generado** en los botones justo debajo del modo que elegiste.",
                        false
                    );
                } else {
                    pushAssistantGuidance(
                        "✅ Documentos generados. **Descárgalos aquí ↓** en el bloque debajo del botón que usaste (Completo, Técnica o Económica).",
                        false
                    );
                }
                setEconomicBlockingSessionLatch(false);
                setDocumentQualityBlockingSessionLatch(false);
                setDocumentQualityGateSnapshot(null);
                setValidationEvents([]);
                setValidationBlockingCount(0);
                setStreamProgressForMode(modeForRun, { percent: 100, message: "Generación completada", held: false });
            } else if (orchStatus === "hard_disqualification") {
                setDeliveryRefreshToken((t) => t + 1);
                const gateData =
                    orchestrator?.data?.compliance_gate?.data
                    || orchestrator?.data?.results?.compliance_gate?.data;
                const failed = Array.isArray(gateData?.failed_rules) ? gateData.failed_rules : [];
                const errMsg =
                    orchestrator?.message
                    || orchestrator?.chatbot_message
                    || (failed.length
                        ? `Generación detenida por reglas 12.1: ${failed.join(', ')}.`
                        : "Generación detenida por reglas deterministas de descalificación (12.1).");
                pushAssistantGuidance(errMsg, true);
                setStreamProgressForMode(modeForRun, {
                    percent: 0,
                    message: stopReason === 'COMPLIANCE_GATE_BLOCKING'
                        ? 'Detenido: gate 12.1'
                        : 'Detenido: descalificación 12.1',
                });
                setEconomicBlockingSessionLatch(false);
                setDocumentQualityBlockingSessionLatch(false);
            } else if (orchStatus === "error") {
                setDeliveryRefreshToken((t) => t + 1);
                const errMsg =
                    orchestrator?.chatbot_message
                    || orchestrator?.message
                    || "No se pudo completar la generación. Revisa el backend o vuelve a intentar.";
                const jobs = orchestrator?.generation_state?.jobs;
                const techDone = Array.isArray(jobs) && jobs.some((j) => j?.id === "technical" && j?.status === "done");
                const fmtDone = Array.isArray(jobs) && jobs.some((j) => j?.id === "formats" && j?.status === "done");
                const partialHint =
                    techDone && fmtDone
                        ? "\n\nLos documentos técnico y administrativo pueden estar en **Logística y Expedientes** — pulsa **ACTUALIZAR LISTA**."
                        : "";
                pushAssistantGuidance(
                    errMsg + partialHint + formatGenerationStateJobsSummary(orchestrator?.generation_state),
                    true
                );
                setEconomicBlockingSessionLatch(false);
                setDocumentQualityBlockingSessionLatch(false);
                setDocumentQualityGateSnapshot(null);
                setValidationEvents([]);
                setValidationBlockingCount(0);
                setStreamProgressForMode(modeForRun, {
                    percent: 0,
                    message: `Error: ${stopReason || 'generación'}`,
                });
            } else {
                setDeliveryRefreshToken((t) => t + 1);
                pushAssistantGuidance(
                    (orchestrator?.chatbot_message
                        || `La generación terminó con estado «${orchStatus || 'desconocido'}».`)
                        + formatGenerationWaitingExtra(orchestrator)
                        + formatGenerationStateJobsSummary(orchestrator?.generation_state),
                    true
                );
                setStreamProgressForMode(modeForRun, (prev) => ({
                    percent: Math.max(prev.percent, 10),
                    message: `Estado: ${stopReason || orchStatus || 'revisar'}`,
                }));
            }

        } catch (err) {
            console.error("Generation error:", err);
            setEconomicBlockingSessionLatch(false);
            setDocumentQualityBlockingSessionLatch(false);
            setDocumentQualityGateSnapshot(null);
            pushAssistantGuidance(
                err?.message?.includes("timeout")
                    ? "La generación está tardando más de lo esperado, pero el servidor puede seguir trabajando. Revisa el panel central y vuelve a intentar si no ves cambios en unos minutos."
                    : (err?.message || "Error en la generación. Revisa el backend o vuelve a intentar."),
                true
            );
        } finally {
            setStreamActiveForMode(modeForRun, false);
            fetchExpedienteGuided();
            const keepBar = finalOrchStatus && finalOrchStatus !== 'success';
            if (!keepBar) {
                setTimeout(() => {
                    setStreamProgressForMode(modeForRun, (prev) => ({ ...prev, percent: 0 }));
                }, 4000);
            }
        }
    };

    const handleValidationPrimaryAction = async (event) => {
        setValidationClicks((n) => n + 1);
        const action = event?.ux?.primary_action || {};
        const target = action?.target;
        const hint = humanNavigateHintForValidationTarget(target, event);
        pushAssistantGuidance(hint, false);
        if (target === 'chat_pricing') {
            setTimeout(() => chatInputRef.current?.focus?.(), 120);
        }
        if (target === 'companies') {
            setTimeout(() => companySelectRef.current?.focus?.(), 120);
        }
        if (target === 'economic_panel') {
            setSessionToolsTab('economico');
        }
        if (target === 'validation_policy') {
            setSessionToolsTab('calidad_docs');
        }
    };

    const refreshValidationState = async () => {
        if (!sessionId) return;
        try {
            const prevBlockingCount = validationBlockingCount;
            const res = await axios.post(
                `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/validation-events/revalidate`
            );
            const data = res?.data?.data || {};
            const events = Array.isArray(data.validation_events) ? data.validation_events : [];
            const nextBlockingCount = Number(data.blocking_count || 0);
            setValidationEvents(events);
            setValidationBlockingCount(nextBlockingCount);
            if (prevBlockingCount > 0 && nextBlockingCount === 0) {
                await trackValidationEvent({
                    event: "block_resolved",
                    session_id: sessionId,
                    error_type: "validation_blocks",
                    severity: "block",
                    resolution_time_ms: validationStartTs ? Date.now() - validationStartTs : undefined,
                    clicks_to_fix: validationClicks,
                }).catch(() => {});
            }
            if (nextBlockingCount === 0) {
                setEconomicBlockingSessionLatch(false);
                setDocumentQualityBlockingSessionLatch(false);
                if (events.length === 0) {
                    pushAssistantGuidance("Validaciones bloqueantes resueltas en backend. Puedes continuar.", false);
                }
            }
        } catch (err) {
            console.warn("No se pudo refrescar estado de validaciones:", err);
        }
    };

    const handleValidationSecondaryAction = async (event) => {
        if (!event) return;
        const action = event?.ux?.secondary_action || {};
        setValidationClicks((n) => n + 1);
        setValidationBusy(true);
        try {
            if (action?.requires_justification) {
                setPendingJustificationEvent(event);
                return;
            } else {
                await acknowledgeWarning({
                    errorType: event.error_type,
                    itemId: event?.context?.item_id,
                });
                await trackValidationEvent({
                    event: "warning_acknowledged",
                    session_id: sessionId,
                    error_type: event.error_type,
                    severity: event.severity,
                    resolution_time_ms: validationStartTs ? Date.now() - validationStartTs : undefined,
                    item_id: event?.context?.item_id,
                });
                pushAssistantGuidance("Advertencia reconocida en sesion.", false);
                await refreshValidationState();
            }
        } catch (err) {
            console.error("Error gestionando accion de validacion:", err);
            pushAssistantGuidance("No se pudo guardar la accion de validacion. Intenta de nuevo.", true);
        } finally {
            setValidationBusy(false);
        }
    };

    const handleJustificationConfirm = async (reason) => {
        const event = pendingJustificationEvent;
        if (!event) return;
        setValidationBusy(true);
        try {
            const action = event?.ux?.secondary_action || {};
            await submitJustification({
                actionId: action.type || action.label || "secondary_action",
                reason,
                itemId: event?.context?.item_id,
                errorType: event?.error_type,
            });
            await trackValidationEvent({
                event: "justification_submitted",
                session_id: sessionId,
                error_type: event.error_type,
                severity: event.severity,
                justification_length: reason.length,
                item_id: event?.context?.item_id,
            });
            pushAssistantGuidance("Justificacion guardada. Revalidando estado...", false);
            await refreshValidationState();
        } catch (err) {
            console.error("Error guardando justificacion:", err);
            pushAssistantGuidance("No se pudo guardar la justificacion.", true);
        } finally {
            setValidationBusy(false);
            setPendingJustificationEvent(null);
        }
    };

    const applyChatbotResponse = useCallback((res) => {
        const botData = res.data?.data || {};
        updateIntakeUiSnapshotFromBotData(botData);
        const botMsg = {
            sender: 'bot',
            text: botData.respuesta || res.data.reply,
            citations: botData.citas || res.data.citations || [],
            confidence: botData.confianza || res.data.confidence,
            tipo: botData.tipo,
            suggestedActions: res.data.suggested_actions || [],
            basesExcerpt: botData.bases_excerpt_v1 || null,
            evidenceV1: botData.evidence_v1 || null,
            isGlow:
                botData.tipo === 'data_saved' ||
                botData.tipo === 'pending_question' ||
                botData.tipo === 'economic_price_provenance' ||
                botData.grounded_forensic_risk === true,
        };
        setChatMessages((prev) => [...prev, botMsg]);
        if (botData.tipo === 'economic_price_provenance') {
            setLatestPriceProvenance({
                text: botData.respuesta || res.data.reply || '',
                confidence: botData.confianza || res.data.confidence || 'Media',
                capturedAt: new Date().toLocaleString('es-MX'),
            });
        }
        const updatedGng = botData.go_no_go_result || res.data?.data?.go_no_go_result;
        const gngOverride = res.data?.data?.go_no_go_override || botData.go_no_go_override;
        if (updatedGng && !isGoNoGoAcknowledged(gngOverride)) {
            setGoNoGoResult(updatedGng);
            if (!showGoNoGoPanel) setShowGoNoGoPanel(true);
        }
        setTimeout(() => {
            chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }, 100);
        fetchExpedienteGuided();
    }, [updateIntakeUiSnapshotFromBotData, showGoNoGoPanel, fetchExpedienteGuided]);

    const handleChatQuotationUpload = async (event) => {
        const file = event?.target?.files?.[0];
        if (event?.target) event.target.value = '';
        if (!file || !sessionId || !selectedCompanyId) {
            pushAssistantGuidance('Selecciona empresa y sesión antes de adjuntar la cotización.', true);
            return;
        }
        setChatMessages((prev) => [
            ...prev,
            { sender: 'user', text: `📎 Cotización económica: ${file.name}` },
        ]);
        setIsThinking(true);
        try {
            const form = new FormData();
            form.append('file', file);
            form.append('session_id', sessionId);
            const uploadRes = await axios.post(`${API_BASE}/upload/upload`, form, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            const docId = uploadRes.data?.data?.doc_id;
            if (!docId) {
                throw new Error('El servidor no devolvió identificador del archivo.');
            }
            const res = await axios.post(`${API_BASE}/chatbot/ask`, {
                query: 'Importar cotización económica desde archivo adjunto',
                session_id: sessionId,
                company_id: selectedCompanyId,
                doc_id: docId,
            });
            if (res.data?.status === 'pending') {
                pushAssistantGuidance(res.data?.message || 'Procesando archivo…', false);
            } else {
                applyChatbotResponse(res);
            }
        } catch (err) {
            console.error('Quotation upload error:', err);
            pushAssistantGuidance(
                err?.response?.data?.detail ||
                    err?.message ||
                    'No se pudo importar la cotización. Verifica que sea Excel o CSV con columnas de concepto y precio.',
                true
            );
        } finally {
            setIsThinking(false);
        }
    };

    const handleAskRiskExpert = useCallback((item) => {
        const literal = item?._literal
            || (typeof item?.texto === 'object'
                ? (item.texto?.descripcion || item.texto?.nombre)
                : item?.texto)
            || '';
        pendingForensicRiskContextRef.current = {
            force_grounded: true,
            session_id: sessionId || null,
            risk_id: item?.risk_id || item?.id,
            literal: String(literal),
            alert_subtype: item?.alert_subtype || null,
            risk_reason_ux: item?.risk_reason_ux || null,
            page: item?.page ?? null,
            snippet: item?.snippet ?? null,
            risk_kind: item?.risk_kind || null,
            risk_severity: item?.risk_severity || null,
            category: item?.category || null,
        };
        setChatInput(`Explícame este riesgo forense y qué hacer: ${literal}`);
        setTimeout(() => chatInputRef.current?.focus?.(), 120);
    }, []);

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
        const queryText = chatInput;
        const riskContext = pendingForensicRiskContextRef.current;
        pendingForensicRiskContextRef.current = null;
        setChatInput("");
        setIsThinking(true);

        const pollChatbot = async (query, isRetry = false, forensicRiskContext = null) => {
            try {
                const res = await axios.post(`${API_BASE}/chatbot/ask`, {
                    query: query,
                    session_id: sessionId,
                    company_id: selectedCompanyId,
                    forensic_risk_context: forensicRiskContext || undefined,
                }, { timeout: 600000 });
                
                // Si el backend dice 'pending', esperamos y reintentamos (Compliance Gate)
                if (res.data?.status === 'pending') {
                    const botData = res.data?.data || {};
                    const msg = res.data?.message || "Analizando bases de licitación...";
                    // Opcional: mostrar un mensaje temporal de "procesando" si es la primera vez
                    if (!isRetry) {
                        setChatMessages(prev => [...prev, { sender: 'bot', text: msg, isPending: true }]);
                    }
                    setTimeout(() => pollChatbot(query, true, forensicRiskContext), 3000);
                    return;
                }

                // Si veníamos de un retry, removemos el mensaje de "pending" previo
                if (isRetry) {
                    setChatMessages(prev => prev.filter(m => !m.isPending));
                }

                applyChatbotResponse(res);
                setIsServerDisconnected(false);

            } catch (err) {
                console.error("Chat error:", err);
                setChatMessages(prev => prev.filter(m => !m.isPending));
                const isTimeout = err?.code === 'ECONNABORTED' || String(err?.message || '').includes('timeout');
                pushAssistantGuidance(
                    isTimeout
                        ? 'La consulta a las bases está tardando más de lo habitual (primera búsqueda RAG o carga del modelo de embeddings). Espera un momento y vuelve a intentar; si acabas de reiniciar Docker, la primera pregunta literal puede tardar varios minutos.'
                        : 'Lo siento, hubo un error al procesar tu mensaje. Por favor intenta de nuevo.',
                    true,
                );
            } finally {
                setIsThinking(false);
            }
        };

        await pollChatbot(queryText, false, riskContext);
    };

    /** Tras guardar un bloque económico: sincroniza cola de pendientes y semáforo con el mismo bootstrap que el chat. */
    const handleBlockResolutionSaved = useCallback(async () => {
        if (!sessionId) return;
        try {
            const res = await axios.post(`${API_BASE}/chatbot/ask`, {
                query: '',
                session_id: sessionId,
                company_id: selectedCompanyId || null,
            });
            const text = (res.data?.reply || '').trim();
            if (text) {
                setChatMessages((prev) => {
                    const t = text.replace(/\s+/g, ' ').trim();
                    if (prev.some((m) => m.sender === 'bot' && (m.text || '').replace(/\s+/g, ' ').trim() === t)) {
                        return prev;
                    }
                    const glow = text.includes('📋') || text.includes('**') || text.includes('✨');
                    return [...prev, { sender: 'bot', text, isGlow: glow }];
                });
            }
            const botData = res.data?.data || {};
            updateIntakeUiSnapshotFromBotData(botData);
            const updatedGng = botData.go_no_go_result || res.data?.data?.go_no_go_result;
            if (updatedGng) {
                setGoNoGoResult(updatedGng);
                setShowGoNoGoPanel(true);
            }
        } catch (e) {
            console.error('refresh after block save', e);
            setChatMessages((prev) => [
                ...prev,
                {
                    sender: 'bot',
                    text: 'Precios del bloque guardados. Si no ves la cola actualizada, escribe un mensaje al asistente.',
                    isGlow: false,
                },
            ]);
        }
        setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 80);
    }, [sessionId, selectedCompanyId, updateIntakeUiSnapshotFromBotData]);

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
                    <div className="brand-logo" style={{ background: 'none', boxShadow: 'none', width: 'auto', height: 'auto' }}>
                        <img src="/images/logo_licitAI.png" alt="Logo" style={{ height: '28px', objectFit: 'contain' }} />
                    </div>
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
                            <div>OBLIGACIONES: <span className="header-stat">{auditResults.obligacionesDetectadas ?? auditResults.totalRequisitos}</span></div>
                            <div style={{ paddingLeft: '10px', borderLeft: '1px solid rgba(255,255,255,0.1)' }}>RIESGOS: <span className="header-stat risk">{auditResults.riesgos}</span></div>
                        </div>
                    )}
                    
                    <select 
                        ref={companySelectRef}
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

            {/* BANNER: Aviso cuando no hay empresa seleccionada */}
            {!selectedCompanyId && companies.length > 0 && (
                <div style={{
                    background: 'rgba(249, 212, 35, 0.1)',
                    borderBottom: '1px solid rgba(249, 212, 35, 0.3)',
                    padding: '12px 20px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                    fontSize: '13px',
                    color: 'var(--warning)'
                }}>
                    <Info size={18} />
                    <span>
                        <strong>Selecciona una empresa</strong> en el menú superior para continuar. 
                        Si aún no tienes empresas, <span 
                            style={{ textDecoration: 'underline', cursor: 'pointer' }}
                            onClick={() => setSessionId(null)}
                        >regresa al menú principal</span> y ve a la vista "Empresas".
                    </span>
                </div>
            )}

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
                        id="sources-panel"
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
                                    <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                                        {src.catalog?.label ? (
                                            <span title={src.catalog.summary || src.catalog.label}>
                                                {src.catalog.label}
                                                {' · '}
                                                {src.status}
                                            </span>
                                        ) : (
                                            src.status
                                        )}
                                    </div>
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

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <ExpedienteGuidedStepBar guided={expedienteGuided} compact />
                        <button 
                            disabled={isAnalyzing} 
                            onClick={triggerFullAudit} 
                            title={auditResults ? 'Vuelve a ejecutar agentes y actualiza el dictamen en el servidor' : 'Primera auditoría de bases para esta sesión'}
                            style={{ width: '100%', padding: '12px', borderRadius: '12px', background: 'var(--primary)', border: 'none', color: '#fff', fontWeight: 800, fontSize: '12px', cursor: isAnalyzing ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', boxShadow: '0 4px 15px var(--primary-shadow)' }}
                        >
                            {isAnalyzing ? <Loader2 className="animate-spin" size={16} /> : <FileSearch size={16} />}
                            {auditResults
                                ? panelLabels.analyze_bases
                                : panelLabels.analyze_bases_first}
                        </button>
                        {auditResults?.fechaAuditoria && (
                            <p style={{ margin: 0, fontSize: '10px', color: 'var(--text-muted)', lineHeight: 1.45, textAlign: 'center' }}>
                                Último dictamen en servidor: {auditResults.fechaAuditoria}
                                {auditResults.uxKind === 'rag_index_missing'
                                    ? ' · Falta índice vectorial para auditar de nuevo'
                                    : ''}
                            </p>
                        )}

                        {(() => {
                            const renderBtn = (modeOpt, isPrimary) => {
                                const disabled = isGenerationModeButtonDisabled({
                                    runs: generationStreamRuns,
                                    modeId: modeOpt.id,
                                    isAnalyzing,
                                    hasCompany: Boolean(selectedCompanyId),
                                });
                                const isActive = isStreamActiveForMode(generationStreamRuns, modeOpt.id);
                                return (
                                    <button
                                        key={modeOpt.id}
                                        type="button"
                                        disabled={disabled}
                                        onClick={() => triggerGeneration(modeOpt.id)}
                                        title={
                                            isAnalyzing
                                                ? 'Espera a que termine el análisis'
                                                : !selectedCompanyId
                                                  ? 'Selecciona una empresa en el menú superior'
                                                  : isActive
                                                    ? `${panelLabelForGenerationMode(modeOpt.id, panelLabels)} en curso`
                                                    : (generationHints[modeOpt.id] || modeOpt.hint)
                                        }
                                        style={{
                                            width: isPrimary ? '100%' : 'calc(50% - 4px)',
                                            padding: isPrimary ? '12px' : '10px 8px',
                                            borderRadius: '12px',
                                            background: disabled
                                                ? 'rgba(139, 92, 246, 0.2)'
                                                : isPrimary
                                                  ? 'linear-gradient(135deg, var(--primary), var(--secondary))'
                                                  : 'rgba(99,102,241,0.18)',
                                            border: isPrimary ? 'none' : '1px solid rgba(99,102,241,0.35)',
                                            color: disabled ? 'rgba(255,255,255,0.35)' : '#fff',
                                            fontWeight: 800,
                                            fontSize: isPrimary ? '12px' : '10px',
                                            cursor: disabled ? 'not-allowed' : 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            gap: '8px',
                                            boxShadow: disabled || !isPrimary ? 'none' : '0 4px 15px var(--primary-glow)',
                                        }}
                                    >
                                        {isActive ? <Loader2 className="animate-spin" size={14} /> : <DownloadCloud size={isPrimary ? 16 : 14} />}
                                        {isPrimary
                                            ? panelLabelForGenerationMode(modeOpt.id, panelLabels).toUpperCase()
                                            : panelShortForGenerationMode(modeOpt.id, panelLabels).toUpperCase()}
                                    </button>
                                );
                            };
                            const fullOpt = GENERATION_MODE_OPTIONS.find((m) => m.id === 'full');
                            const splitOpts = GENERATION_MODE_OPTIONS.filter((m) => m.id !== 'full');
                            return (
                                <>
                                    {fullOpt ? renderBtn(fullOpt, true) : null}
                                    {sessionId ? (
                                        <ScopeDownloadBlock
                                            modeId="full"
                                            sessionId={sessionId}
                                            refreshToken={deliveryRefreshToken}
                                            highlighted={downloadHighlightMode === 'full'}
                                            scopePayload={downloadBundle.full}
                                            onRefreshScope={refreshDownloadBundle}
                                        />
                                    ) : null}
                                    <div style={{ display: 'flex', gap: '8px', width: '100%', alignItems: 'stretch' }}>
                                        {splitOpts.map((opt) => (
                                            <div
                                                key={opt.id}
                                                style={{
                                                    flex: 1,
                                                    minWidth: 0,
                                                    display: 'flex',
                                                    flexDirection: 'column',
                                                }}
                                            >
                                                {renderBtn(opt, false)}
                                                {sessionId ? (
                                                    <ScopeDownloadBlock
                                                        modeId={opt.id}
                                                        sessionId={sessionId}
                                                        refreshToken={deliveryRefreshToken}
                                                        highlighted={downloadHighlightMode === opt.id}
                                                        compact
                                                        scopePayload={downloadBundle[opt.id]}
                                                        onRefreshScope={refreshDownloadBundle}
                                                    />
                                                ) : null}
                                            </div>
                                        ))}
                                    </div>
                                    <CrossScopeDownloadHint bundle={downloadBundle} />
                                    {dualStreamBanner ? (
                                        <p
                                            style={{
                                                margin: 0,
                                                fontSize: '10px',
                                                color: '#a5b4fc',
                                                lineHeight: 1.45,
                                                textAlign: 'center',
                                            }}
                                        >
                                            {dualStreamBanner}
                                        </p>
                                    ) : null}
                                    {sessionId ? (
                                        <button
                                            type="button"
                                            onClick={scrollToDeliveryPanel}
                                            style={{
                                                marginTop: '4px',
                                                background: 'none',
                                                border: 'none',
                                                color: '#64748b',
                                                fontSize: '10px',
                                                textDecoration: 'underline',
                                                cursor: 'pointer',
                                                alignSelf: 'center',
                                                padding: '2px 0',
                                            }}
                                        >
                                            Ver logística avanzada (CompraNet, ZIP completo)
                                        </button>
                                    ) : null}
                                    {downloadBundleLoading ? (
                                        <span
                                            style={{
                                                fontSize: '9px',
                                                color: '#475569',
                                                textAlign: 'center',
                                            }}
                                        >
                                            Actualizando archivos disponibles…
                                        </span>
                                    ) : null}
                                </>
                            );
                        })()}
                        <GenerationQueuePanel
                            generationState={generationQueueState}
                            streamRuns={generationStreamRuns}
                            activeMode={activeGenerationMode}
                        />
                        {(isAnalyzing || !selectedCompanyId) && (
                            <p style={{ margin: 0, fontSize: '10px', color: 'var(--warning)', lineHeight: 1.45, textAlign: 'center' }}>
                                {isAnalyzing
                                    ? '⚠️ Generación temporalmente bloqueada mientras termina el análisis'
                                    : '⚠️ Selecciona una empresa en el menú superior o créala en la vista Empresas'}
                            </p>
                        )}
                    </div>
                    
                    <div style={{ marginTop: '10px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '15px' }}>
                        {showGoNoGoPanel && goNoGoResult && auditResults?.uxKind !== 'rag_index_missing' ? (
                            <GoNoGoPanel
                                goNoGoResult={goNoGoResult}
                                onAskExpert={(q) => { setChatInput(q); }}
                                sessionId={sessionId}
                                companyId={selectedCompanyId}
                                companyData={companies.find(c => c.id === selectedCompanyId) || {}}
                                overrideTimestamp={auditResults?.go_no_go?.override_timestamp || null}
                                onDecision={(jobId) => {
                                    setShowGoNoGoPanel(false);
                                    setGoNoGoResult(null);
                                    if (jobId) {
                                        setIsAnalyzing(true);
                                        setAuditProgress({ percent: 0, currentFile: 'Reanudando pipeline tras autorización…' });
                                        pollAgentsJobUntilDone(jobId, (u) => {
                                            setAuditProgress((prev) => ({
                                                percent: u.pct ?? prev.percent,
                                                currentFile: u.message || prev.currentFile,
                                            }));
                                        }).then(async () => {
                                            await fetchDictamen();
                                        }).catch((err) => {
                                            pushAssistantGuidance(`Error al reanudar: ${err.message}`, true);
                                        }).finally(() => {
                                            setIsAnalyzing(false);
                                            setAuditProgress({ percent: 0, currentFile: '' });
                                        });
                                    } else {
                                        pushAssistantGuidance('Pipeline detenido. Puedes revisar las brechas y volver a intentarlo cuando estés listo.', false);
                                    }
                                }}
                            />
                        ) : (
                            <AnalysisResults
                                results={auditResults}
                                onAskExpert={(q) => { setChatInput(q); }}
                                onAskRiskExpert={handleAskRiskExpert}
                                sessionId={sessionId}
                                companyId={selectedCompanyId}
                                onRiskDecisionsUpdated={(data) => {
                                    if (!data?.forensic_risks_v1) return;
                                    setAuditResults((prev) => ({
                                        ...(prev || {}),
                                        forensic_risks_v1: data.forensic_risks_v1,
                                        risk_decisions_v1: data.risk_decisions_v1,
                                    }));
                                }}
                                onRiskBatchStop={() => {
                                    pushAssistantGuidance(
                                        'Detuviste el expediente tras revisar riesgos forenses. Corrige documentos o consulta al experto antes de continuar con la generación.',
                                        true,
                                    );
                                }}
                            />
                        )}
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

                    {sessionId && (
                        <div
                            style={{
                                marginTop: '-12px',
                                padding: '14px 16px',
                                borderRadius: '16px',
                                border: '1px solid rgba(255,255,255,0.08)',
                                background: 'rgba(15,23,42,0.45)',
                            }}
                        >
                            {sessionHealth?.rehydrate_recommended && (
                                <div
                                    role="alert"
                                    style={{
                                        marginBottom: '14px',
                                        padding: '12px 14px',
                                        borderRadius: '12px',
                                        border: '1px solid rgba(251,191,36,0.45)',
                                        background: 'rgba(251,191,36,0.08)',
                                        display: 'flex',
                                        flexWrap: 'wrap',
                                        alignItems: 'center',
                                        gap: '12px',
                                        justifyContent: 'space-between',
                                    }}
                                >
                                    <div style={{ flex: 1, minWidth: '200px' }}>
                                        <div
                                            style={{
                                                fontSize: '12px',
                                                fontWeight: 800,
                                                color: '#fcd34d',
                                                marginBottom: '4px',
                                            }}
                                        >
                                            Datos de análisis desactualizados o incompletos
                                        </div>
                                        <p
                                            style={{
                                                margin: 0,
                                                fontSize: '11px',
                                                color: 'rgba(226,232,240,0.85)',
                                                lineHeight: 1.45,
                                            }}
                                        >
                                            Algunos paneles (calendario, documentos, junta) pueden no coincidir con
                                            las bases actuales. Pulsa para reconstruir artefactos sin borrar tus
                                            capturas económicas ni la generación en curso.
                                        </p>
                                        {Array.isArray(sessionHealth.stale) && sessionHealth.stale.length > 0 && (
                                            <p
                                                style={{
                                                    margin: '6px 0 0',
                                                    fontSize: '10px',
                                                    color: 'rgba(226,232,240,0.55)',
                                                }}
                                            >
                                                Señales: {sessionHealth.stale.slice(0, 4).join(', ')}
                                                {sessionHealth.stale.length > 4 ? '…' : ''}
                                            </p>
                                        )}
                                    </div>
                                    <button
                                        type="button"
                                        onClick={runSessionRehydrate}
                                        disabled={sessionHealthBusy}
                                        style={{
                                            padding: '8px 14px',
                                            borderRadius: '10px',
                                            border: '1px solid #fbbf24',
                                            background: sessionHealthBusy
                                                ? 'rgba(251,191,36,0.15)'
                                                : 'rgba(251,191,36,0.22)',
                                            color: '#fef3c7',
                                            fontSize: '11px',
                                            fontWeight: 800,
                                            cursor: sessionHealthBusy ? 'wait' : 'pointer',
                                            whiteSpace: 'nowrap',
                                        }}
                                    >
                                        {sessionHealthBusy ? 'Actualizando…' : 'Actualizar artefactos'}
                                    </button>
                                </div>
                            )}
                            <div
                                role="tablist"
                                aria-label="Herramientas de sesión"
                                style={{
                                    display: 'flex',
                                    flexWrap: 'wrap',
                                    gap: '8px',
                                    marginBottom: '14px',
                                    borderBottom: '1px solid rgba(255,255,255,0.06)',
                                    paddingBottom: '12px',
                                }}
                            >
                                {[
                                    { id: 'calendario', label: 'Hitos / calendario' },
                                    { id: 'checklist_fisico', label: 'Aduana Corporativa (Checklist Físico)' },
                                    { id: 'documentos_candidatos', label: 'Documentos detectados' },
                                    { id: 'formatos_detectados', label: 'Formatos/Anexos Detectados' },
                                    { id: 'junta_preguntas', label: 'Preguntas para la Junta' },
                                    { id: 'post_junta', label: 'Actas y aclaraciones' },
                                    { id: 'economico', label: 'Validaciones económicas' },
                                    { id: 'calidad_docs', label: 'Calidad documental' },
                                    ...(import.meta.env.VITE_SHOW_VALIDATION_POLICY !== 'false'
                                        ? [{ id: 'avanzado', label: 'Política (admin)' }]
                                        : []),
                                ].map((t) => {
                                    const active = sessionToolsTab === t.id;
                                    return (
                                        <button
                                            key={t.id}
                                            type="button"
                                            role="tab"
                                            aria-selected={active}
                                            aria-expanded={active}
                                            id={`session-tool-tab-${t.id}`}
                                            aria-controls={`session-tool-panel-${t.id}`}
                                            title={active ? 'Pulsa de nuevo para ocultar' : 'Mostrar panel'}
                                            onClick={() =>
                                                setSessionToolsTab((prev) => (prev === t.id ? null : t.id))
                                            }
                                            style={{
                                                padding: '8px 12px',
                                                borderRadius: '10px',
                                                border: active ? '1px solid var(--primary)' : '1px solid rgba(255,255,255,0.1)',
                                                background: active ? 'rgba(0,212,255,0.12)' : 'rgba(0,0,0,0.25)',
                                                color: active ? '#f1f5f9' : 'rgba(226,232,240,0.75)',
                                                fontSize: '11px',
                                                fontWeight: 800,
                                                cursor: 'pointer',
                                                whiteSpace: 'nowrap',
                                            }}
                                        >
                                            {t.label}
                                        </button>
                                    );
                                })}
                            </div>
                            {sessionToolsTab == null && (
                                <>
                                    <p
                                        style={{
                                            fontSize: '11px',
                                            color: 'var(--text-muted)',
                                            margin: '0 0 12px',
                                            lineHeight: 1.45,
                                        }}
                                    >
                                        Elige una pestaña para abrir el panel. Pulsa la misma pestaña otra vez para contraerlo.
                                    </p>
                                    {submissionChecklistLoading && sessionHitos.length === 0 && (
                                        <p
                                            style={{
                                                fontSize: '11px',
                                                color: 'var(--text-muted)',
                                                margin: '0 0 12px',
                                            }}
                                        >
                                            Cargando fechas críticas…
                                        </p>
                                    )}
                                    {submissionChecklistError && sessionHitos.length === 0 && !submissionChecklistLoading && (
                                        <p
                                            style={{
                                                fontSize: '11px',
                                                color: '#fbbf24',
                                                margin: '0 0 12px',
                                                lineHeight: 1.45,
                                            }}
                                        >
                                            {submissionChecklistError}
                                        </p>
                                    )}
                                    {sessionHitos.length > 0 && (
                                        <div style={{ marginBottom: '12px' }}>
                                            <CriticalDatesList
                                                hitos={sessionHitos}
                                                compact
                                                onAskAboutHito={(h) => {
                                                    const q = `Según las bases de esta licitación, ¿qué debo cumplir respecto al hito «${h.nombre}»? Contexto: ${h.fecha_texto_raw || 'sin fecha textual'}.`;
                                                    setChatInput(q);
                                                }}
                                            />
                                            <button
                                                type="button"
                                                onClick={() => setSessionToolsTab('calendario')}
                                                style={{
                                                    marginTop: '10px',
                                                    fontSize: '10px',
                                                    fontWeight: 700,
                                                    color: 'var(--primary)',
                                                    background: 'none',
                                                    border: 'none',
                                                    cursor: 'pointer',
                                                    textDecoration: 'underline',
                                                }}
                                            >
                                                Ver calendario completo y marcar hitos →
                                            </button>
                                        </div>
                                    )}
                                </>
                            )}

                            {sessionToolsTab === 'calendario' && (
                                <div
                                    role="tabpanel"
                                    id="session-tool-panel-calendario"
                                    aria-labelledby="session-tool-tab-calendario"
                                >
                                    <SubmissionChecklistPanel
                                        sessionId={sessionId}
                                        flatList
                                        active={sessionToolsTab === 'calendario'}
                                        initialData={submissionChecklist || auditResults?.submissionChecklist}
                                        syncKey={sessionId}
                                        onChecklistUpdated={setSubmissionChecklist}
                                        onAskAboutHito={(h) => {
                                            const q = `Según las bases de esta licitación, ¿qué debo cumplir respecto al hito «${h.nombre}»? Contexto: ${h.fecha_texto_raw || 'sin fecha textual'}.`;
                                            setChatInput(q);
                                        }}
                                    />
                                </div>
                            )}
                            {sessionToolsTab === 'checklist_fisico' && (
                                <div
                                    role="tabpanel"
                                    id="session-tool-panel-checklist_fisico"
                                    aria-labelledby="session-tool-tab-checklist_fisico"
                                >
                                    <PhysicalChecklistPanel sessionId={sessionId} />
                                </div>
                            )}
                            {sessionToolsTab === 'documentos_candidatos' && (
                                <div
                                    role="tabpanel"
                                    id="session-tool-panel-documentos_candidatos"
                                    aria-labelledby="session-tool-tab-documentos_candidatos"
                                >
                                    <DocumentCandidatePanel 
                                        candidates={pickDocumentCandidatesForPanel(auditResults)}
                                        onAskExpert={(q) => { setChatInput(q); }}
                                        sessionId={sessionId}
                                        companyId={selectedCompanyId}
                                        active={sessionToolsTab === 'documentos_candidatos'}
                                    />
                                </div>
                            )}
                            {sessionToolsTab === 'formatos_detectados' && (
                                <div
                                    role="tabpanel"
                                    id="session-tool-panel-formatos_detectados"
                                    aria-labelledby="session-tool-tab-formatos_detectados"
                                >
                                    <DetectedFormatsPanel
                                        formats={pickDetectedFormatsForPanel(auditResults)}
                                        onAskExpert={(q) => { setChatInput(q); }}
                                        sessionId={sessionId}
                                        active={sessionToolsTab === 'formatos_detectados'}
                                    />
                                </div>
                            )}
                            {sessionToolsTab === 'junta_preguntas' && (
                                <div
                                    role="tabpanel"
                                    id="session-tool-panel-junta_preguntas"
                                    aria-labelledby="session-tool-tab-junta_preguntas"
                                >
                                    <JuntaAclaracionesPanel
                                        sessionId={sessionId}
                                        companyId={selectedCompanyId}
                                        active={sessionToolsTab === 'junta_preguntas'}
                                        syncKey={sessionId}
                                        onAskExpert={(q) => setChatInput(q)}
                                    />
                                </div>
                            )}
                            {sessionToolsTab === 'post_junta' && (
                                <div
                                    role="tabpanel"
                                    id="session-tool-panel-post_junta"
                                    aria-labelledby="session-tool-tab-post_junta"
                                >
                                    <PostClarificationPanel
                                        sessionId={sessionId}
                                        sources={sources}
                                        syncKey={auditResults?.fechaAuditoria || ''}
                                        onAskAboutActa={(ctx) => {
                                            const q = `Ayúdame a revisar el borrador de carta 33 Bis y las preguntas Anexo 10. Estado: ${ctx?.estado || 'N/D'}, confianza de extracción: ${ctx?.confianza_extraccion ?? 'N/D'}.`;
                                            setChatInput(q);
                                        }}
                                    />
                                </div>
                            )}
                            {sessionToolsTab === 'economico' && (
                                <div
                                    role="tabpanel"
                                    id="session-tool-panel-economico"
                                    aria-labelledby="session-tool-tab-economico"
                                >
                                    <EconomicValidationPanel
                                        sessionId={sessionId}
                                        companyId={selectedCompanyId}
                                        syncKey={auditResults?.fechaAuditoria || ''}
                                        onAskAboutValidation={(val) => {
                                            const q = `Revisemos las validaciones económicas. Perfil: ${val?.perfil_usado || 'N/D'}. Bloqueos: ${(val?.blocking_issues || []).length}. ¿Qué debo corregir primero?`;
                                            setChatInput(q);
                                        }}
                                    />
                                </div>
                            )}
                            {sessionToolsTab === 'calidad_docs' && (
                                <div
                                    role="tabpanel"
                                    id="session-tool-panel-calidad_docs"
                                    aria-labelledby="session-tool-tab-calidad_docs"
                                >
                                    <DocumentQualityDiagnosticPanel
                                        snapshot={documentQualityGateSnapshot}
                                        blocked={documentQualityBlockingSessionLatch}
                                        busy={validationBusy}
                                        onRevalidate={() => refreshValidationState()}
                                    />
                                </div>
                            )}
                            {sessionToolsTab === 'avanzado' &&
                                import.meta.env.VITE_SHOW_VALIDATION_POLICY !== 'false' && (
                                    <div
                                        role="tabpanel"
                                        id="session-tool-panel-avanzado"
                                        aria-labelledby="session-tool-tab-avanzado"
                                    >
                                        <ValidationPolicyAdmin sessionId={sessionId} />
                                    </div>
                                )}
                        </div>
                    )}

                    <div ref={deliveryPanelRef}>
                    <DeliveryPanel
                        results={generationResults || auditResults || {}}
                        sessionName={sessionName}
                        sessionId={sessionId}
                        refreshToken={deliveryRefreshToken}
                        onExpedienteCleared={() => {
                            setGenerationResults(null);
                            setDeliveryRefreshToken((t) => t + 1);
                            setDocumentQualityGateSnapshot(null);
                            setDocumentQualityBlockingSessionLatch(false);
                        }}
                    />
                    </div>
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
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', minWidth: 0, flex: '1 1 auto' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
                                <Bot size={20} color="var(--primary)" />
                                <div style={{ minWidth: 0 }}>
                                    <h3 style={{ fontSize: '15px', fontWeight: 800, margin: 0 }}>Asistente de Licitación</h3>
                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600, marginTop: '2px' }}>
                                        {economicBlockingSessionLatch
                                            ? EXPEDIENTE_CHAT_SHELL_UI.subtitleEconomicBlock
                                            : documentQualityBlockingSessionLatch
                                                ? EXPEDIENTE_CHAT_SHELL_UI.subtitleQualityBlock
                                            : EXPEDIENTE_CHAT_SHELL_UI.subtitleDefault}
                                    </div>
                                </div>
                            </div>
                            {(isAnyGenerationActive || generationProgress.percent > 0) && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: '140px' }}>
                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        {isAnyGenerationActive && !generationProgress.held && <Loader2 className="animate-spin" size={11} style={{ color: 'var(--primary)' }} />}
                                        <span style={{ fontWeight: 700, color: generationProgress.held ? '#fbbf24' : 'var(--primary)' }}>
                                            {Math.round(generationProgress.percent)}%
                                        </span>
                                        <span style={{ whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden', maxWidth: '160px' }}>
                                            {generationProgress.message || 'Preparando documentos…'}
                                        </span>
                                    </div>
                                    <div style={{ width: '100%', height: '3px', background: 'rgba(255,255,255,0.08)', borderRadius: '999px', overflow: 'hidden' }}>
                                        <div style={{
                                            height: '100%',
                                            width: `${Math.max(2, generationProgress.percent)}%`,
                                            background: generationProgress.held ? '#fbbf24' : 'var(--primary)',
                                            borderRadius: '999px',
                                            transition: 'width 0.5s ease',
                                        }} />
                                    </div>
                                </div>
                            )}
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
                        <CaptureMatrixPanel sessionId={sessionId} />
                        <BlockResolutionPanel
                            sessionId={sessionId}
                            companyId={selectedCompanyId}
                            onAfterSave={handleBlockResolutionSaved}
                        />
                        {intakeUiSnapshot && (
                            <IntakeProgressCard
                                progressCurrent={intakeUiSnapshot.progressCurrent}
                                progressTotal={intakeUiSnapshot.progressTotal}
                                progressLabel={intakeUiSnapshot.progressLabel}
                                blockingCount={intakeUiSnapshot.blockingCount}
                                remainingCount={intakeUiSnapshot.remainingCount}
                                isResumed={intakeUiSnapshot.isResumed}
                                auditMode={intakeUiSnapshot.auditMode}
                            />
                        )}
                        {validationEvents.length > 0 && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                {validationEvents.map((ev, idx) => (
                                    <ValidationAlert
                                        key={`${ev.error_type || "ev"}-${idx}`}
                                        event={ev}
                                        busy={validationBusy}
                                        onPrimaryAction={handleValidationPrimaryAction}
                                        onSecondaryAction={handleValidationSecondaryAction}
                                    />
                                ))}
                            </div>
                        )}
                        {economicBlockingSessionLatch && validationBlockingCount > 0 && (
                            <div
                                style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '8px',
                                    padding: '12px',
                                    borderRadius: '12px',
                                    border: '1px solid rgba(239,68,68,0.35)',
                                    background: 'rgba(239,68,68,0.06)',
                                }}
                            >
                                <div style={{ fontSize: '11px', fontWeight: 800, color: '#fca5a5' }}>
                                    Validación económica bloqueante
                                </div>
                                <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.45 }}>
                                    Corrige la plantilla o importes; luego recalcula validaciones en servidor. Cuando no queden bloqueos, pulsa <strong>GENERAR PROPUESTA</strong> de nuevo.
                                </div>
                                <button
                                    type="button"
                                    onClick={() => refreshValidationState()}
                                    disabled={validationBusy || !sessionId}
                                    style={{
                                        width: '100%',
                                        padding: '10px 12px',
                                        borderRadius: '10px',
                                        border: '1px solid rgba(248,113,113,0.5)',
                                        background: 'rgba(248,113,113,0.18)',
                                        color: '#fff',
                                        fontSize: '12px',
                                        fontWeight: 800,
                                        cursor: validationBusy || !sessionId ? 'not-allowed' : 'pointer',
                                        opacity: validationBusy || !sessionId ? 0.55 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        gap: '8px',
                                    }}
                                >
                                    {validationBusy ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                                    Revalidar validaciones
                                </button>
                            </div>
                        )}
                        {documentQualityBlockingSessionLatch && validationBlockingCount > 0 && (
                            <div
                                style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '8px',
                                    padding: '12px',
                                    borderRadius: '12px',
                                    border: '1px solid rgba(245,158,11,0.35)',
                                    background: 'rgba(245,158,11,0.06)',
                                }}
                            >
                                <div style={{ fontSize: '11px', fontWeight: 800, color: '#fbbf24' }}>
                                    {EXPEDIENTE_CHAT_SHELL_UI.qualityPanelTitle}
                                </div>
                                <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.45 }}>
                                    {EXPEDIENTE_CHAT_SHELL_UI.qualityPanelBody}
                                </div>
                                <button
                                    type="button"
                                    onClick={() => refreshValidationState()}
                                    disabled={validationBusy || !sessionId}
                                    style={{
                                        width: '100%',
                                        padding: '10px 12px',
                                        borderRadius: '10px',
                                        border: '1px solid rgba(245,158,11,0.5)',
                                        background: 'rgba(245,158,11,0.16)',
                                        color: '#fff',
                                        fontSize: '12px',
                                        fontWeight: 800,
                                        cursor: validationBusy || !sessionId ? 'not-allowed' : 'pointer',
                                        opacity: validationBusy || !sessionId ? 0.55 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        gap: '8px',
                                    }}
                                >
                                    {validationBusy ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                                    {EXPEDIENTE_CHAT_SHELL_UI.qualityPanelCta}
                                </button>
                            </div>
                        )}
                        {latestPriceProvenance && (
                            <div
                                style={{
                                    position: 'relative',
                                    border: provenanceCardPulse
                                        ? '1px solid rgba(34, 197, 94, 0.55)'
                                        : '1px solid rgba(56, 189, 248, 0.45)',
                                    background: 'rgba(56, 189, 248, 0.08)',
                                    borderRadius: '12px',
                                    padding: '10px 12px',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '10px',
                                    transition: 'border-color 220ms ease, box-shadow 220ms ease',
                                    boxShadow: provenanceCardPulse
                                        ? '0 0 18px rgba(34, 197, 94, 0.35)'
                                        : 'none',
                                }}
                            >
                                <div
                                    style={{
                                        display: 'flex',
                                        alignItems: 'flex-start',
                                        justifyContent: 'space-between',
                                        gap: '10px',
                                    }}
                                >
                                    <div style={{ minWidth: 0 }}>
                                        <div
                                            style={{
                                                fontSize: '11px',
                                                fontWeight: 800,
                                                color: '#7dd3fc',
                                                transition: 'transform 220ms ease',
                                                transform: provenanceCardPulse ? 'scale(1.02)' : 'scale(1)',
                                            }}
                                        >
                                            Procedencia de precio
                                        </div>
                                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                            Cascada: Chat → Documento → Catálogo · {latestPriceProvenance.capturedAt}
                                        </div>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => setShowPriceProvenanceModal(true)}
                                        onMouseEnter={() => setChatProvBadgeHover('detailBtn')}
                                        onMouseLeave={() => setChatProvBadgeHover(null)}
                                        style={{
                                            border:
                                                chatProvBadgeHover === 'detailBtn'
                                                    ? '1px solid rgba(125, 211, 252, 0.7)'
                                                    : '1px solid rgba(255,255,255,0.2)',
                                            background:
                                                chatProvBadgeHover === 'detailBtn'
                                                    ? 'rgba(125, 211, 252, 0.12)'
                                                    : 'rgba(255,255,255,0.06)',
                                            color: '#fff',
                                            borderRadius: '999px',
                                            padding: '6px 10px',
                                            fontSize: '11px',
                                            fontWeight: 700,
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '6px',
                                            flexShrink: 0,
                                            transition: 'all 220ms ease',
                                            boxShadow:
                                                chatProvBadgeHover === 'detailBtn'
                                                    ? '0 0 10px rgba(125,211,252,0.22)'
                                                    : 'none',
                                        }}
                                    >
                                        <Info size={12} />
                                        Ver detalle
                                    </button>
                                </div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                                    {[
                                        {
                                            id: 'chat',
                                            icon: '🟢',
                                            label: 'Chat',
                                            hint: 'Prioridad 1: instrucción directa del usuario en el chat (override manual).',
                                        },
                                        {
                                            id: 'doc',
                                            icon: '🟡',
                                            label: 'Documento',
                                            hint: 'Prioridad 2: partidas tabulares normalizadas (Excel/CSV de la sesión).',
                                        },
                                        {
                                            id: 'cat',
                                            icon: '⚪',
                                            label: 'Catálogo',
                                            hint: 'Prioridad 3: catálogo de empresa e inferencia del agente económico.',
                                        },
                                        {
                                            id: 'summary',
                                            icon: '📋',
                                            label: 'Resumen',
                                            hint:
                                                (latestPriceProvenance.text || '').slice(0, 360) +
                                                ((latestPriceProvenance.text || '').length > 360 ? '…' : ''),
                                        },
                                    ].map((b) => {
                                        const isH = chatProvBadgeHover === b.id;
                                        return (
                                            <div
                                                key={b.id}
                                                style={{ position: 'relative' }}
                                                onMouseEnter={() => setChatProvBadgeHover(b.id)}
                                                onMouseLeave={() => setChatProvBadgeHover(null)}
                                            >
                                                <div
                                                    style={{
                                                        display: 'inline-flex',
                                                        alignItems: 'center',
                                                        gap: '5px',
                                                        borderRadius: '999px',
                                                        border: isH
                                                            ? '1px solid rgba(125, 211, 252, 0.7)'
                                                            : '1px solid rgba(255,255,255,0.18)',
                                                        padding: '4px 8px',
                                                        fontSize: '10px',
                                                        color: '#cbd5e1',
                                                        background: isH
                                                            ? 'rgba(125, 211, 252, 0.12)'
                                                            : 'rgba(255,255,255,0.04)',
                                                        cursor: 'default',
                                                        transition: 'all 220ms ease',
                                                        boxShadow: isH
                                                            ? '0 0 10px rgba(125,211,252,0.2)'
                                                            : 'none',
                                                    }}
                                                >
                                                    <span>{b.icon}</span>
                                                    <span>{b.label}</span>
                                                </div>
                                                {isH && b.hint && (
                                                    <div
                                                        style={{
                                                            position: 'absolute',
                                                            top: 'calc(100% + 6px)',
                                                            left: 0,
                                                            width: 'min(300px, 72vw)',
                                                            zIndex: 20,
                                                            background: 'rgba(15, 23, 42, 0.96)',
                                                            border: '1px solid rgba(125,211,252,0.35)',
                                                            borderRadius: '10px',
                                                            padding: '8px 10px',
                                                            boxShadow: '0 10px 30px rgba(0,0,0,0.45)',
                                                            whiteSpace: 'pre-wrap',
                                                            textAlign: 'left',
                                                            lineHeight: 1.45,
                                                            color: '#e2e8f0',
                                                            fontSize: '11px',
                                                        }}
                                                    >
                                                        {b.hint}
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                        {chatMessages.length === 0 ? (
                            <div style={{ margin: 'auto', textAlign: 'center', opacity: 0.2 }}>
                                <Bot size={50} style={{ marginBottom: '15px' }} />
                                <p style={{ fontSize: '13px' }}>El experto forense puede ayudarte con el análisis de bases y los datos faltantes del expediente.</p>
                            </div>
                        ) : (
                            chatMessages.map((msg, i) => {
                                // --- Estilos diferenciados por tipo de mensaje ---
                                const isBlockingDenied = msg.tipo === 'skip_denied_blocking';
                                const isFieldSkipped = msg.tipo === 'field_skipped';
                                const isPendingQuestion = msg.tipo === 'pending_question';
                                const isDataSaved = msg.tipo === 'data_saved';

                                let bubbleBg = msg.sender === 'user' ? 'var(--primary)' : 'rgba(255,255,255,0.05)';
                                let bubbleBorder = msg.isGlow ? '2px solid var(--primary)' : '1px solid rgba(255,255,255,0.05)';
                                let bubbleShadow = msg.isGlow ? '0 0 20px var(--primary-glow)' : 'none';
                                let msgPrefix = null;

                                if (msg.sender === 'bot') {
                                    if (isBlockingDenied) {
                                        // Campo bloqueante: advertencia urgente (rojo/naranja)
                                        bubbleBg = 'rgba(239,68,68,0.10)';
                                        bubbleBorder = '2px solid rgba(239,68,68,0.55)';
                                        bubbleShadow = '0 0 14px rgba(239,68,68,0.18)';
                                        msgPrefix = (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', fontSize: '11px', fontWeight: 800, color: '#fca5a5' }}>
                                                <AlertTriangle size={14} />
                                                <span>Campo obligatorio — no se puede omitir</span>
                                            </div>
                                        );
                                    } else if (isFieldSkipped) {
                                        // Campo informativo omitido: tono suave (verde/azul)
                                        bubbleBg = 'rgba(34,197,94,0.07)';
                                        bubbleBorder = '1px solid rgba(34,197,94,0.35)';
                                        bubbleShadow = 'none';
                                        msgPrefix = (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', fontSize: '11px', fontWeight: 700, color: '#86efac' }}>
                                                <CheckCircle size={13} />
                                                <span>Campo omitido (opcional)</span>
                                            </div>
                                        );
                                    } else if (isPendingQuestion) {
                                        // Pregunta pendiente activa: tono informativo (azul)
                                        bubbleBg = 'rgba(56,189,248,0.07)';
                                        bubbleBorder = '1px solid rgba(56,189,248,0.35)';
                                        bubbleShadow = '0 0 12px rgba(56,189,248,0.10)';
                                    } else if (isDataSaved) {
                                        // Dato guardado: confirmación suave (verde)
                                        bubbleBg = 'rgba(34,197,94,0.07)';
                                        bubbleBorder = '1px solid rgba(34,197,94,0.30)';
                                        bubbleShadow = 'none';
                                    }
                                }

                                return (
                                    <div key={i} style={{ alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start', maxWidth: '85%' }}>
                                        <div style={{ 
                                            background: bubbleBg,
                                            color: '#fff', 
                                            padding: '12px 16px', 
                                            borderRadius: msg.sender === 'user' ? '15px 15px 0 15px' : '0 15px 15px 15px', 
                                            fontSize: '14px', 
                                            lineHeight: 1.5, 
                                            border: bubbleBorder,
                                            boxShadow: bubbleShadow,
                                            whiteSpace: 'pre-wrap'
                                        }}>
                                            {msgPrefix}
                                            {msg.text.includes('|') && msg.text.includes('---') ? (
                                                <div style={{ fontFamily: 'monospace', fontSize: '12px', overflowX: 'auto', background: 'rgba(0,0,0,0.2)', padding: '10px', borderRadius: '8px' }}>
                                                    {msg.text}
                                                </div>
                                            ) : (
                                                msg.text
                                            )}
                                        </div>
                                        {msg.evidenceV1 && (
                                            <div style={{ marginTop: '8px' }}>
                                                <ForensicEvidenceBadge evidence={msg.evidenceV1} />
                                            </div>
                                        )}
                                        {msg.basesExcerpt?.available && (
                                            <ForensicBasesExcerptCard excerpt={msg.basesExcerpt} compact />
                                        )}
                                        {Array.isArray(msg.citations) && msg.citations.length > 0 && (
                                            <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                                {msg.citations.map((cita, idx) => (
                                                    <div
                                                        key={idx}
                                                        style={{
                                                            fontSize: '11px',
                                                            color: '#94a3b8',
                                                            padding: '6px 10px',
                                                            borderRadius: '8px',
                                                            background: 'rgba(148,163,184,0.08)',
                                                            border: '1px solid rgba(148,163,184,0.2)',
                                                        }}
                                                    >
                                                        <strong style={{ color: '#cbd5e1' }}>
                                                            {cita.documento || 'Bases'}
                                                            {cita.pagina ? ` · Pág. ${cita.pagina}` : ''}
                                                        </strong>
                                                        {cita.fragmento ? (
                                                            <div style={{ marginTop: '4px', opacity: 0.9 }}>
                                                                «{String(cita.fragmento).slice(0, 160)}»
                                                            </div>
                                                        ) : null}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                        {msg.suggestedActions && msg.suggestedActions.length > 0 && (
                                            <div style={{ marginTop: '12px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                                {msg.suggestedActions.map((action, idx) => (
                                                    <button
                                                        key={idx}
                                                        type="button"
                                                        onClick={() => {
                                                            const kind = action.action_kind || 'chat';
                                                            const actionId = action.action_id || '';
                                                            if (kind === 'ui' && actionId === 'OPEN_SOURCES_PANEL') {
                                                                document
                                                                    .getElementById('sources-panel')
                                                                    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                                                                return;
                                                            }
                                                            if (kind === 'ui' && actionId === 'TRIGGER_ANALYZE_BASES') {
                                                                triggerFullAudit();
                                                                return;
                                                            }
                                                            if (kind === 'ui' && actionId === 'TRIGGER_GENERATION_ECONOMIC') {
                                                                triggerGeneration('economic');
                                                                return;
                                                            }
                                                            if (kind === 'ui' && actionId === 'TRIGGER_GENERATION_FULL') {
                                                                triggerGeneration('full');
                                                                return;
                                                            }
                                                            if (kind === 'ui' && actionId === 'TRIGGER_GENERATION_TECHNICAL') {
                                                                triggerGeneration('technical');
                                                                return;
                                                            }
                                                            if (!action.payload) return;
                                                            setChatInput(action.payload);
                                                            setTimeout(() => {
                                                                chatFormRef.current?.requestSubmit?.();
                                                            }, 50);
                                                        }}
                                                        style={{
                                                            padding: '6px 12px',
                                                            borderRadius: '20px',
                                                            fontSize: '11px',
                                                            fontWeight: 800,
                                                            background: action.style === 'primary' ? 'var(--primary)' : 'rgba(255,255,255,0.1)',
                                                            border: action.style === 'primary' ? 'none' : '1px solid rgba(255,255,255,0.2)',
                                                            color: '#fff',
                                                            cursor: 'pointer'
                                                        }}
                                                    >
                                                        {action.label}
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                );
                            })
                        )}
                        <div ref={chatEndRef} />
                        {isThinking && <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', gap: '10px' }}><Loader2 className="spin" size={14} /> Trabajando...</div>}
                        {(isAnyGenerationActive || generationProgress.held) && (
                            <div style={{
                                alignSelf: 'flex-start',
                                maxWidth: '92%',
                                width: '100%',
                                background: generationProgress.held ? 'rgba(251,191,36,0.08)' : 'rgba(99,102,241,0.08)',
                                border: generationProgress.held ? '1px solid rgba(251,191,36,0.35)' : '1px solid rgba(99,102,241,0.25)',
                                borderRadius: '0 15px 15px 15px',
                                padding: '16px 18px',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '10px',
                            }}>
                                {/* Cabecera con spinner y etapa actual */}
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                    {isAnyGenerationActive && !generationProgress.held ? (
                                        <Loader2 className="animate-spin" size={16} style={{ color: 'var(--primary)', flexShrink: 0 }} />
                                    ) : null}
                                    <span style={{ fontSize: '13px', fontWeight: 700, color: generationProgress.held ? '#fbbf24' : 'var(--primary)' }}>
                                        {generationProgress.held
                                            ? 'Generación en pausa'
                                            : dualStreamBanner || 'Generando propuesta…'}
                                    </span>
                                    <span style={{ marginLeft: 'auto', fontSize: '12px', fontWeight: 800, color: generationProgress.held ? '#fbbf24' : 'var(--primary)' }}>
                                        {Math.round(generationProgress.percent)}%
                                    </span>
                                </div>

                                {/* Barra de progreso */}
                                <div style={{
                                    width: '100%',
                                    height: '6px',
                                    background: 'rgba(255,255,255,0.08)',
                                    borderRadius: '999px',
                                    overflow: 'hidden',
                                }}>
                                    <div style={{
                                        height: '100%',
                                        width: `${Math.max(4, generationProgress.percent)}%`,
                                        background: generationProgress.held
                                            ? 'linear-gradient(90deg, #fbbf24, #f59e0b)'
                                            : 'linear-gradient(90deg, var(--primary), #818cf8)',
                                        borderRadius: '999px',
                                        transition: 'width 0.6s ease',
                                    }} />
                                </div>

                                {/* Mensaje de etapa actual */}
                                <div style={{ fontSize: '11px', color: 'rgba(226,232,240,0.65)', lineHeight: 1.4 }}>
                                    {generationProgress.message || 'Preparando documentos…'}
                                </div>

                                {/* Etapas del pipeline */}
                                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '2px' }}>
                                    {[
                                        { key: 'technical', label: '📄 Técnica', pctRange: [93, 94] },
                                        { key: 'formats', label: '📋 Formatos', pctRange: [95, 96] },
                                        { key: 'economic_writer', label: '💰 Económica', pctRange: [97, 98] },
                                        { key: 'packager', label: '📦 Sobres', pctRange: [98, 99] },
                                        { key: 'delivery', label: '✅ Entrega', pctRange: [99, 100] },
                                    ].map(({ key, label, pctRange }) => {
                                        const pct = generationProgress.percent;
                                        const done = pct >= pctRange[1];
                                        const active = pct >= pctRange[0] && pct < pctRange[1];
                                        return (
                                            <span key={key} style={{
                                                fontSize: '10px',
                                                fontWeight: 700,
                                                padding: '3px 8px',
                                                borderRadius: '999px',
                                                background: done
                                                    ? 'rgba(34,197,94,0.15)'
                                                    : active
                                                        ? 'rgba(99,102,241,0.25)'
                                                        : 'rgba(255,255,255,0.05)',
                                                color: done
                                                    ? '#4ade80'
                                                    : active
                                                        ? '#a5b4fc'
                                                        : 'rgba(226,232,240,0.35)',
                                                border: active ? '1px solid rgba(99,102,241,0.4)' : '1px solid transparent',
                                                transition: 'all 0.3s ease',
                                            }}>
                                                {done ? '✓ ' : active ? '⟳ ' : ''}{label}
                                            </span>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                    </div>

                    <form ref={chatFormRef} onSubmit={handleSendMessage} style={{ padding: '20px', borderTop: '1px solid rgba(255,255,255,0.05)', display: 'flex', gap: '10px', alignItems: 'center' }}>
                        <input
                            ref={chatQuotationFileRef}
                            type="file"
                            accept=".xlsx,.xls,.csv,.tsv,.docx"
                            style={{ display: 'none' }}
                            onChange={handleChatQuotationUpload}
                        />
                        {sessionId && selectedCompanyId && (
                            <button
                                type="button"
                                title={
                                    economicBlockingSessionLatch
                                        ? 'Adjuntar cotización (Excel, CSV o DOCX con tabla de precios)'
                                        : 'Adjuntar Excel/CSV/DOCX con cotización (precios unitarios)'
                                }
                                onClick={() => chatQuotationFileRef.current?.click()}
                                disabled={isThinking}
                                style={{
                                    background: 'rgba(34, 197, 94, 0.15)',
                                    border: '1px solid rgba(34, 197, 94, 0.35)',
                                    color: '#86efac',
                                    padding: '10px 12px',
                                    borderRadius: '10px',
                                    cursor: isThinking ? 'not-allowed' : 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                }}
                            >
                                <Paperclip size={18} />
                            </button>
                        )}
                        {(() => {
                            return (
                                <input
                                    ref={chatInputRef}
                                    type="text"
                                    value={chatInput}
                                    onChange={(e) => setChatInput(e.target.value)}
                                    placeholder={
                                        economicBlockingSessionLatch
                                            ? 'Adjunta 📎 tu Excel o DOCX de cotización, o usa Revalidar arriba'
                                            : intakeUiSnapshot
                                            ? 'Pregunta sobre las bases o adjunta 📎 tu Excel de cotización…'
                                            : 'Pregunta sobre las bases o aporta un dato del expediente…'
                                    }
                                    style={{
                                        flex: 1,
                                        background: 'rgba(255,255,255,0.05)',
                                        border: '1px solid rgba(255,255,255,0.1)',
                                        padding: '12px 15px',
                                        borderRadius: '10px',
                                        color: '#fff',
                                        outline: 'none',
                                    }}
                                />
                            );
                        })()}
                        <button
                            type="submit"
                            disabled={isThinking || !chatInput.trim()}
                            title={isThinking ? 'Espera la respuesta del asistente…' : 'Enviar mensaje'}
                            style={{
                                background: 'var(--primary)',
                                border: 'none',
                                color: '#fff',
                                padding: '10px 15px',
                                borderRadius: '10px',
                                cursor: isThinking || !chatInput.trim() ? 'not-allowed' : 'pointer',
                                opacity: isThinking || !chatInput.trim() ? 0.5 : 1,
                            }}
                        >
                            <Send size={18} />
                        </button>
                    </form>
                </aside>

            </main>

            {/* OVERLAY DE CONEXIÓN CAÍDA (NOCTURNO / REINICIO) */}
            {isServerDisconnected && (
                <div style={{
                    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                    backgroundColor: 'rgba(15, 23, 42, 0.95)', zIndex: 99999,
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    color: 'white', backdropFilter: 'blur(8px)', textAlign: 'center', padding: '20px'
                }}>
                    <AlertTriangle size={80} color="#f59e0b" style={{ marginBottom: '25px' }} />
                    <h2 style={{ fontSize: '28px', fontWeight: 900, marginBottom: '15px', letterSpacing: '-0.5px' }}>Conexión Perdida con el Servidor</h2>
                    <p style={{ fontSize: '16px', color: '#cbd5e1', marginBottom: '30px', maxWidth: '600px', lineHeight: 1.6 }}>
                        Parece que el servidor se ha reiniciado o hemos perdido la conexión, posiblemente debido a inactividad o un reinicio nocturno tras una carga masiva.
                        <br/><br/>
                        No te preocupes, el sistema está diseñado para retener tu progreso. Por favor, recarga la página para restaurar la sesión de forma segura y continuar.
                    </p>
                    <button
                        onClick={() => window.location.reload()}
                        style={{
                            padding: '14px 30px', backgroundColor: 'var(--primary)', color: '#000',
                            border: 'none', borderRadius: '12px', fontSize: '16px', fontWeight: 800, 
                            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '10px',
                            boxShadow: '0 4px 15px rgba(0, 212, 255, 0.3)', transition: 'transform 0.2s'
                        }}
                        onMouseEnter={(e) => e.target.style.transform = 'scale(1.05)'}
                        onMouseLeave={(e) => e.target.style.transform = 'scale(1)'}
                    >
                        <RefreshCw size={18} />
                        Recargar Sistema
                    </button>
                </div>
            )}

            {/* OVERLAY DE CARGA (DRAGGABLE) */}
            {isAnalyzing && analysisOverlayVisible && (
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
                        <span style={{ fontSize: '12px', fontWeight: 800 }}>{overlayMessages.bases_analysis_title}</span>
                        <span style={{ fontSize: '12px', color: 'var(--primary)' }}>{auditProgress.percent}%</span>
                    </div>
                    <div style={{ height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${auditProgress.percent}%`, background: 'var(--primary)', transition: 'width 0.3s' }}></div>
                    </div>
                    <div style={{ fontSize: '10px', marginTop: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                        {auditProgress.currentFile || overlayMessages.bases_analysis_subtitle}
                    </div>

                    <button
                        type="button"
                        onClick={() => setAnalysisOverlayVisible(false)}
                        style={{
                            width: '100%',
                            marginTop: '10px',
                            padding: '8px',
                            borderRadius: '8px',
                            border: '1px solid rgba(139, 92, 246, 0.45)',
                            background: 'transparent',
                            color: 'var(--primary)',
                            fontSize: '11px',
                            fontWeight: 700,
                            cursor: 'pointer',
                        }}
                    >
                        Seguir navegando (análisis en segundo plano)
                    </button>
                    
                    <button 
                        onClick={handleCancelUpload}
                        style={{
                            width: '100%',
                            marginTop: '15px',
                            padding: '8px',
                            background: 'rgba(239, 68, 68, 0.2)',
                            border: '1px solid rgba(239, 68, 68, 0.5)',
                            color: '#fca5a5',
                            borderRadius: '8px',
                            fontSize: '11px',
                            fontWeight: 800,
                            cursor: 'pointer',
                            transition: 'all 0.2s'
                        }}
                        onMouseEnter={(e) => e.target.style.background = 'rgba(239, 68, 68, 0.3)'}
                        onMouseLeave={(e) => e.target.style.background = 'rgba(239, 68, 68, 0.2)'}
                    >
                        CANCELAR INGESTA
                    </button>

                    <div style={{ fontSize: '9px', textAlign: 'center', marginTop: '10px', opacity: 0.5 }}>Arrastra para mover</div>
                </div>
            )}

            {isAnyGenerationActive && generationOverlayVisible && !isAnalyzing && (
                <div
                    style={{
                        position: 'fixed',
                        bottom: `${dragOffset.y + 120}px`,
                        right: `${dragOffset.x}px`,
                        background: 'rgba(0,0,0,0.95)',
                        padding: '20px',
                        borderRadius: '15px',
                        border: '2px solid #a78bfa',
                        width: '300px',
                        zIndex: 10000,
                        boxShadow: '0 20px 50px rgba(0,0,0,0.7)',
                    }}
                >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '10px' }}>
                        <span style={{ fontSize: '12px', fontWeight: 800 }}>{overlayMessages.document_generation_title}</span>
                        <span style={{ fontSize: '12px', color: '#c4b5fd' }}>{generationProgress.percent}%</span>
                    </div>
                    <div style={{ height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${generationProgress.percent}%`, background: '#a78bfa', transition: 'width 0.3s' }} />
                    </div>
                    <div style={{ fontSize: '10px', marginTop: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                        {generationProgress.message || overlayMessages.document_generation_subtitle}
                    </div>
                    <button
                        type="button"
                        onClick={() => setGenerationOverlayVisible(false)}
                        style={{
                            width: '100%',
                            marginTop: '10px',
                            padding: '8px',
                            borderRadius: '8px',
                            border: '1px solid rgba(167, 139, 250, 0.45)',
                            background: 'transparent',
                            color: '#c4b5fd',
                            fontSize: '11px',
                            fontWeight: 700,
                            cursor: 'pointer',
                        }}
                    >
                        {overlayMessages.dismiss_hint}
                    </button>
                </div>
            )}
            <JustificationModal
                open={!!pendingJustificationEvent}
                busy={validationBusy}
                title={pendingJustificationEvent?.ux?.title || "Justificacion requerida"}
                onCancel={() => setPendingJustificationEvent(null)}
                onConfirm={handleJustificationConfirm}
            />
            {showPriceProvenanceModal && latestPriceProvenance && (
                <div
                    style={{
                        position: 'fixed',
                        inset: 0,
                        background: 'rgba(0,0,0,0.65)',
                        zIndex: 12000,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: '20px',
                    }}
                    onClick={() => setShowPriceProvenanceModal(false)}
                >
                    <div
                        style={{
                            width: 'min(760px, 95vw)',
                            maxHeight: '80vh',
                            overflowY: 'auto',
                            background: '#111827',
                            border: '1px solid rgba(56,189,248,0.35)',
                            borderRadius: '14px',
                            padding: '16px',
                            boxShadow: '0 20px 60px rgba(0,0,0,0.55)',
                            transform: provenanceModalAnimIn ? 'scale(1)' : 'scale(0.96)',
                            opacity: provenanceModalAnimIn ? 1 : 0.88,
                            transition: 'transform 0.22s ease-out, opacity 0.22s ease-out',
                        }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                            <h4 style={{ margin: 0, fontSize: '14px', color: '#7dd3fc' }}>Trazabilidad de precio aplicado</h4>
                            <button
                                type="button"
                                onClick={() => setShowPriceProvenanceModal(false)}
                                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
                            >
                                Cerrar
                            </button>
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px' }}>
                            Confianza: {latestPriceProvenance.confidence} · Capturado: {latestPriceProvenance.capturedAt}
                        </div>
                        <pre
                            style={{
                                margin: 0,
                                whiteSpace: 'pre-wrap',
                                fontFamily: 'inherit',
                                fontSize: '12px',
                                lineHeight: 1.5,
                                color: '#e5e7eb',
                                background: 'rgba(255,255,255,0.03)',
                                border: '1px solid rgba(255,255,255,0.08)',
                                borderRadius: '10px',
                                padding: '12px',
                                transition: 'box-shadow 0.35s ease',
                                boxShadow: provenanceModalPrePulse
                                    ? '0 0 16px rgba(34,197,94,0.35)'
                                    : 'none',
                            }}
                        >
                            {latestPriceProvenance.text}
                        </pre>
                    </div>
                </div>
            )}
        </div>
    );
};

export default App;
