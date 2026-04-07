import React, { useMemo } from 'react';
import { Activity, ShieldCheck, FileSpreadsheet, CheckCircle, Info, AlertTriangle } from 'lucide-react';

/**
 * Infiere qué etapa del pipeline está activa según el texto de progreso del job (español).
 * @param {{ currentFile?: string, percent?: number }|null|undefined} auditProgress
 * @returns {'ingestion'|'analysis'|'compliance'|'economic'|'orchestration'}
 */
function inferActiveStageFromProgress(auditProgress) {
    const f = String(auditProgress?.currentFile || '').toLowerCase();
    if (f.includes('económ') || f.includes('econom')) return 'economic';
    if (f.includes('compliance') || f.includes('forense') || f.includes('zona')) return 'compliance';
    if (f.includes('analista') || f.includes('extrayendo requisitos')) return 'analysis';
    if (f.includes('ocr') || f.includes('ingest') || f.includes('ingesta') || f.includes('procesando ocr')) {
        return 'ingestion';
    }
    if (f.includes('orquest')) return 'orchestration';
    const p = typeof auditProgress?.percent === 'number' ? auditProgress.percent : 0;
    if (p < 28) return 'ingestion';
    if (p < 88) return 'compliance';
    return 'economic';
}

/**
 * @param {object} p
 * @param {string} [p.sessionId]
 * @param {object|null} [p.auditResults]
 * @param {boolean} [p.isAnalyzing]
 * @param {{ currentFile?: string, percent?: number }} [p.auditProgress]
 */
const Dashboard = ({ sessionId, auditResults, isAnalyzing = false, auditProgress = null }) => {
    const telem = auditResults?.pipelineTelemetry;
    const stages = Array.isArray(telem?.stagesCompleted) ? telem.stagesCompleted : null;
    const hasTelemetry = !!(telem && stages && stages.length > 0);
    const telemetryInferred = !!(telem && telem._inferred === true);
    const orchSt = telem?.orchestratorStatus;
    const pausedStage = telem?.pausedStage ?? null;
    const stopReason = telem?.stopReason ?? null;
    const plannedStages = auditResults?.orchestratorMetadata?.pipeline_config?.stages_planned;
    const economicPlanned = Array.isArray(plannedStages) ? plannedStages.includes('economic') : null;

    const sr = auditResults?.statusRaw;
    const ragUx = auditResults?.uxKind === 'rag_index_missing';
    const hasDictamen = !!auditResults;
    const isFinishedCompliance = auditResults && auditResults.statusRaw === 'success';
    const hasAnalysisSignal =
        hasDictamen &&
        ((auditResults.totalRequisitos ?? 0) > 0 || !!auditResults.extracted_data);

    const activeStage = isAnalyzing ? inferActiveStageFromProgress(auditProgress) : null;

    const orchestratorSuccess = hasTelemetry ? orchSt === 'success' : isFinishedCompliance;
    const orchestratorWaiting = hasTelemetry && orchSt === 'waiting_for_data';
    const orchestratorError = hasTelemetry && orchSt === 'error';

    const agentStates = useMemo(() => {
        const s = (id) => (hasTelemetry ? stages.includes(id) : false);

        /** @type {'PENDING'|'IN_PROGRESS'|'DONE'|'ATENCIÓN'|'EN PAUSA'|'REVISAR'|'ÍNDICE'} */
        let analyst;
        /** @type {string} */
        let analystHint = '';

        if (isAnalyzing && (activeStage === 'ingestion' || activeStage === 'analysis' || activeStage === 'orchestration')) {
            analyst = 'IN_PROGRESS';
            analystHint = auditProgress?.currentFile || 'Procesando documentos y extracción de bases…';
        } else if (hasTelemetry) {
            analyst = s('analysis') ? 'DONE' : 'PENDING';
            analystHint = s('analysis') ? 'Requisitos y cronograma extraídos en esta corrida.' : 'Aún no consta la etapa de análisis en la telemetría.';
        } else {
            if (!hasDictamen) analyst = 'PENDING';
            else if (hasAnalysisSignal || isFinishedCompliance) analyst = 'DONE';
            else analyst = 'REVISAR';
            analystHint =
                analyst === 'DONE'
                    ? 'Hay señal de análisis en el dictamen (modo compatibilidad).'
                    : 'Sin telemetría de pipeline: estado inferido por datos del dictamen.';
        }

        let compliance;
        let complianceHint = '';
        if (isAnalyzing && activeStage === 'compliance') {
            compliance = 'IN_PROGRESS';
            complianceHint = auditProgress?.currentFile || 'Auditoría forense (map-reduce) en curso…';
        } else if (!hasDictamen && !hasTelemetry) {
            compliance = 'PENDING';
            complianceHint = 'Ejecuta «Actualizar análisis» para obtener compliance.';
        } else if (hasTelemetry) {
            if (!s('compliance')) {
                compliance = 'PENDING';
                complianceHint = 'Compliance aún no figura como completado en el servidor.';
            } else if (sr === 'success') {
                compliance = 'DONE';
                complianceHint = 'Cumplimiento evaluado sin estado de error en el agente.';
            } else if (ragUx) {
                compliance = 'ÍNDICE';
                complianceHint = 'Problema de índice vectorial; el dictamen puede estar conservado.';
            } else if (sr === 'partial') {
                compliance = 'ATENCIÓN';
                complianceHint = 'El agente compliance reportó incidencias parciales (zonas o calidad). Revisa el dictamen.';
            } else if (sr === 'fail' || sr === 'error') {
                compliance = 'REVISAR';
                complianceHint = auditResults?.errorText || 'Revisa hallazgos y mensaje de error en compliance.';
            } else {
                compliance = 'REVISAR';
                complianceHint = 'Compliance ejecutado; estado del agente no es success estándar.';
            }
        } else {
            if (sr === 'success') compliance = 'DONE';
            else if (ragUx) compliance = 'ÍNDICE';
            else if (sr === 'partial') compliance = 'ATENCIÓN';
            else if (sr === 'fail' || sr === 'error') compliance = 'REVISAR';
            else compliance = 'REVISAR';
            complianceHint = 'Estado derivado del dictamen sin telemetría de orquestador.';
        }

        let legal;
        let legalHint = '';
        if (isAnalyzing && activeStage === 'compliance') {
            legal = 'IN_PROGRESS';
            legalHint = 'Revisión administrativa/legal integrada en el pase de compliance (zonas y listas).';
        } else if (hasTelemetry) {
            if (!s('compliance')) {
                legal = 'PENDING';
                legalHint = 'Pendiente de completar compliance (no hay etapa legal autónoma en el backend).';
            } else if (orchestratorSuccess && sr === 'success') {
                legal = 'DONE';
                legalHint = 'Pipeline exitoso; revisa hallazgos en zona ADMINISTRATIVO/LEGAL en el dictamen.';
            } else if (orchestratorWaiting && pausedStage === 'economic') {
                legal = 'EN PAUSA';
                legalHint = 'El flujo se detuvo por datos económicos; la revisión legal queda en espera del cierre de pipeline.';
            } else if (sr === 'partial' || sr === 'fail') {
                legal = 'ATENCIÓN';
                legalHint = 'Hay incidencias en compliance que suelen afectar la vertiente administrativa/legal.';
            } else if (orchestratorWaiting) {
                legal = 'EN PAUSA';
                legalHint = 'Orquestador en espera de datos; revisa el mensaje del asistente.';
            } else if (orchestratorError) {
                legal = 'REVISAR';
                legalHint = 'El orquestador reportó error; revisa logs y dictamen parcial si existe.';
            } else {
                legal = 'EN PAUSA';
                legalHint = 'Compliance listo pero el resultado global no es éxito pleno.';
            }
        } else {
            legal = !hasDictamen ? 'PENDING' : isFinishedCompliance ? 'DONE' : 'EN PAUSA';
            legalHint =
                legal === 'DONE'
                    ? 'Modo compatibilidad: compliance en success.'
                    : 'Sin telemetría: estado aproximado por dictamen.';
        }

        let eco;
        let ecoHint = '';
        if (isAnalyzing && activeStage === 'economic') {
            eco = 'IN_PROGRESS';
            ecoHint = auditProgress?.currentFile || 'Evaluación económica en curso…';
        } else if (hasTelemetry) {
            if (!s('compliance')) {
                eco = 'PENDING';
                ecoHint = 'Primero debe completarse compliance.';
            } else if (s('economic')) {
                eco = 'DONE';
                ecoHint = 'Etapa económica registrada como completada en telemetría.';
            } else if (
                pausedStage === 'economic' ||
                stopReason === 'ECONOMIC_GAP' ||
                (orchestratorWaiting && pausedStage === 'economic')
            ) {
                eco = 'EN PAUSA';
                ecoHint =
                    'Esperando catálogo o precios (p. ej. unidad de medida, anexos). Completa datos y vuelve a analizar o responde al asistente.';
            } else if (orchestratorSuccess && !s('economic')) {
                if (economicPlanned === false) {
                    eco = 'DONE';
                    ecoHint = 'En este modo el orquestador no planificó la etapa económica.';
                } else {
                    eco = 'EN PAUSA';
                    ecoHint = 'Pipeline exitoso pero la etapa económica no figura en telemetría; revisa configuración o última corrida.';
                }
            } else if (orchestratorWaiting) {
                eco = 'EN PAUSA';
                ecoHint = 'Pipeline en pausa antes de cerrar la parte económica.';
            } else {
                eco = 'PENDING';
                ecoHint = 'Económico aún no consta como completado.';
            }
        } else {
            eco = !hasDictamen ? 'PENDING' : isFinishedCompliance ? 'DONE' : 'EN PAUSA';
            ecoHint = 'Modo compatibilidad: ligado al estado global del dictamen.';
        }

        return {
            analyst: { status: analyst, hint: analystHint },
            compliance: { status: compliance, hint: complianceHint },
            legal: { status: legal, hint: legalHint },
            eco: { status: eco, hint: ecoHint },
        };
    }, [
        hasTelemetry,
        stages,
        hasDictamen,
        hasAnalysisSignal,
        isFinishedCompliance,
        isAnalyzing,
        activeStage,
        auditProgress,
        sr,
        ragUx,
        orchestratorSuccess,
        orchestratorWaiting,
        orchestratorError,
        pausedStage,
        stopReason,
        auditResults?.errorText,
        economicPlanned,
    ]);

    const statusStyle = (code) => {
        if (code === 'DONE') return { bg: 'var(--success)', glow: 'var(--success-glow)' };
        if (code === 'IN_PROGRESS') return { bg: 'var(--primary)', glow: 'var(--primary-glow)' };
        if (code === 'ÍNDICE') return { bg: '#38bdf8', glow: 'rgba(56,189,248,0.5)' };
        if (code === 'ATENCIÓN') return { bg: '#f59e0b', glow: 'rgba(245,158,11,0.45)' };
        if (code === 'REVISAR') return { bg: '#f43f5e', glow: 'rgba(244,63,94,0.4)' };
        if (code === 'EN PAUSA') return { bg: 'rgba(148, 163, 184, 0.55)', glow: 'transparent' };
        return { bg: 'var(--text-muted)', glow: 'transparent' };
    };

    const agents = [
        {
            id: 'ocr',
            name: 'Analista de Bases',
            icon: <Activity />,
            ...agentStates.analyst,
            desc: 'Extrae cronograma, evaluación y fallos.',
            colorClass: 'glass-card-blue',
        },
        {
            id: 'compliance',
            name: 'Validador Compliance',
            icon: <ShieldCheck />,
            ...agentStates.compliance,
            desc: 'Coteja Opiniones del SAT, actas y matrices.',
            colorClass: 'glass-card-green',
        },
        {
            id: 'legal',
            name: 'Revisor Legal',
            icon: <ShieldCheck />,
            ...agentStates.legal,
            desc: 'Garantiza solvencia legal y fianzas (vista sobre compliance administrativo).',
            colorClass: 'glass-card-yellow',
        },
        {
            id: 'eco',
            name: 'Analista Económico',
            icon: <FileSpreadsheet />,
            ...agentStates.eco,
            desc: 'Desglosa precios unitarios y formato en Excel.',
            colorClass: 'glass-card-red',
        },
    ];

    return (
        <div style={{ padding: '20px' }}>
            <div style={{ marginBottom: '32px' }}>
                <h2 style={{ fontSize: '28px', fontWeight: 900, fontFamily: 'var(--font-heading)', background: 'linear-gradient(to right, #fff, #94a3b8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Orquestación de Agentes</h2>
                <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '4px' }}>Control de flujo inteligente · Sesión: <span style={{ color: 'var(--primary)', fontWeight: 700 }}>{sessionId}</span></p>
                {hasTelemetry && (
                    <p style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: '8px', lineHeight: 1.45 }}>
                        Telemetría{telemetryInferred ? ' (inferida del dictamen guardado)' : ''}: orquestador{' '}
                        <strong style={{ color: '#e2e8f0' }}>{orchSt || '—'}</strong>
                        {pausedStage ? (
                            <> · pausa en <strong style={{ color: '#f59e0b' }}>{pausedStage}</strong></>
                        ) : null}
                        {stopReason ? (
                            <> · <span style={{ opacity: 0.85 }}>{stopReason}</span></>
                        ) : null}
                        {telemetryInferred ? (
                            <span style={{ display: 'block', marginTop: '6px', opacity: 0.92 }}>
                                Tras «Actualizar análisis» con el backend actual, aquí verás telemetría enviada por el orquestador (sin inferencia).
                            </span>
                        ) : null}
                    </p>
                )}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '20px' }}>
                {agents.map((agent) => (
                    <div
                        key={agent.id}
                        className={agent.colorClass}
                        title={agent.hint}
                        style={{
                            padding: '24px',
                            borderRadius: 'var(--radius-xl)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '20px',
                            transition: 'transform 0.3s ease',
                            cursor: 'default',
                        }}
                        onMouseOver={(e) => {
                            e.currentTarget.style.transform = 'translateY(-5px)';
                        }}
                        onMouseOut={(e) => {
                            e.currentTarget.style.transform = 'translateY(0)';
                        }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div
                                style={{
                                    width: '50px',
                                    height: '50px',
                                    borderRadius: '16px',
                                    background: 'rgba(255,255,255,0.05)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    color: 'white',
                                }}
                            >
                                {agent.icon}
                            </div>
                            <div
                                style={{
                                    width: '10px',
                                    height: '10px',
                                    borderRadius: '50%',
                                    background: statusStyle(agent.status).bg,
                                    boxShadow: `0 0 10px ${statusStyle(agent.status).glow}`,
                                }}
                            />
                        </div>

                        <div>
                            <h3 style={{ fontSize: '18px', fontWeight: 700, marginBottom: '4px', color: '#fff' }}>{agent.name}</h3>
                            <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.6)', lineHeight: '1.4' }}>{agent.desc}</p>
                        </div>

                        <div
                            style={{
                                marginTop: 'auto',
                                fontSize: '11px',
                                fontWeight: 900,
                                letterSpacing: '1px',
                                color:
                                    agent.status === 'DONE'
                                        ? 'var(--success)'
                                        : agent.status === 'PENDING' || agent.status === 'EN PAUSA'
                                          ? 'rgba(255,255,255,0.45)'
                                          : agent.status === 'IN_PROGRESS'
                                            ? 'var(--primary)'
                                            : statusStyle(agent.status).bg,
                                background: 'rgba(255,255,255,0.03)',
                                padding: '8px',
                                borderRadius: '10px',
                                textAlign: 'center',
                                textTransform: 'uppercase',
                            }}
                        >
                            {agent.status === 'IN_PROGRESS' ? 'EN PROGRESO' : agent.status}
                        </div>

                        {agent.hint && (agent.status === 'ATENCIÓN' || agent.status === 'EN PAUSA' || agent.status === 'IN_PROGRESS' || agent.status === 'REVISAR') && (
                            <p
                                style={{
                                    margin: 0,
                                    fontSize: '10px',
                                    lineHeight: 1.45,
                                    color: 'rgba(226, 232, 240, 0.72)',
                                    borderTop: '1px solid rgba(255,255,255,0.06)',
                                    paddingTop: '10px',
                                }}
                            >
                                {agent.hint}
                            </p>
                        )}
                    </div>
                ))}
            </div>

            {hasDictamen && orchestratorWaiting && (
                <div
                    style={{
                        marginTop: '32px',
                        background: 'rgba(245, 158, 11, 0.08)',
                        border: '1px solid rgba(245, 158, 11, 0.35)',
                        padding: '20px',
                        borderRadius: '20px',
                        display: 'flex',
                        gap: '20px',
                        alignItems: 'flex-start',
                    }}
                >
                    <AlertTriangle size={36} color="#f59e0b" style={{ flexShrink: 0 }} />
                    <div>
                        <h3 style={{ color: '#fde68a', fontWeight: 800, marginBottom: '6px' }}>Análisis en pausa: faltan datos</h3>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '14px', lineHeight: 1.55 }}>
                            El orquestador detuvo el pipeline
                            {pausedStage ? ` en la etapa «${pausedStage}»` : ''}
                            {stopReason ? ` (${stopReason}).` : '.'} Revisa el chat del experto o completa lo solicitado y vuelve a ejecutar cuando corresponda.
                        </p>
                    </div>
                </div>
            )}

            {hasDictamen && !orchestratorSuccess && !orchestratorWaiting && hasTelemetry && orchestratorError && (
                <div
                    style={{
                        marginTop: '32px',
                        background: 'rgba(244, 63, 94, 0.08)',
                        border: '1px solid rgba(244, 63, 94, 0.35)',
                        padding: '20px',
                        borderRadius: '20px',
                        display: 'flex',
                        gap: '20px',
                        alignItems: 'flex-start',
                    }}
                >
                    <AlertTriangle size={36} color="#f43f5e" style={{ flexShrink: 0 }} />
                    <div>
                        <h3 style={{ color: '#fda4af', fontWeight: 800, marginBottom: '6px' }}>El orquestador reportó error</h3>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '14px', lineHeight: 1.55 }}>
                            {stopReason ? `Motivo registrado: ${stopReason}. ` : ''}
                            Revisa logs del backend y el dictamen parcial si está disponible.
                        </p>
                    </div>
                </div>
            )}

            {hasDictamen && !orchestratorSuccess && !orchestratorWaiting && !(hasTelemetry && orchestratorError) && (
                <div
                    style={{
                        marginTop: '32px',
                        background: 'rgba(148, 163, 184, 0.08)',
                        border: '1px solid rgba(148, 163, 184, 0.25)',
                        padding: '20px',
                        borderRadius: '20px',
                        display: 'flex',
                        gap: '20px',
                        alignItems: 'flex-start',
                    }}
                >
                    {ragUx ? <AlertTriangle size={36} color="#38bdf8" style={{ flexShrink: 0 }} /> : <Info size={36} color="var(--text-muted)" style={{ flexShrink: 0 }} />}
                    <div>
                        <h3 style={{ color: '#e2e8f0', fontWeight: 800, marginBottom: '6px' }}>
                            {ragUx ? 'Dictamen guardado: falta índice para auditar otra vez' : 'Dictamen recuperado del servidor'}
                        </h3>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '14px', lineHeight: 1.55 }}>
                            {ragUx
                                ? 'El último resultado sigue en base de datos; el bloqueo es el motor de búsqueda vectorial (sin fragmentos para esta sesión). Reindexa fuentes y usa «Actualizar análisis» cuando quieras un dictamen nuevo, no es obligatorio rehacer todo el expediente.'
                                : 'No estás empezando desde cero: ya hay un último análisis persistido. Revisa el panel «Dictamen Forense» a la izquierda. Pulsa «Actualizar análisis» solo si subiste documentos o quieres refrescar el resultado.'}
                        </p>
                    </div>
                </div>
            )}

            {orchestratorSuccess && (
                <div
                    style={{
                        marginTop: '32px',
                        background: 'rgba(0, 242, 254, 0.05)',
                        border: '1px solid var(--success-glow)',
                        padding: '20px',
                        borderRadius: '20px',
                        display: 'flex',
                        gap: '20px',
                        alignItems: 'center',
                        animation: 'fadeIn 0.5s ease-out',
                    }}
                >
                    <CheckCircle size={40} color="var(--success)" />
                    <div>
                        <h3 style={{ color: 'var(--success)', fontWeight: 800, marginBottom: '4px' }}>
                            {hasTelemetry ? 'Pipeline del orquestador completado' : 'Auditoría completada con éxito'}
                        </h3>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                            {hasTelemetry
                                ? 'Los agentes consolidaron el resultado según la telemetría del servidor. El dictamen está en el panel lateral.'
                                : 'Los agentes consolidaron el conocimiento según el dictamen cargado. Revisa el panel lateral.'}
                        </p>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Dashboard;
