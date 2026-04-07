/**
 * Utilidad para centralizar el procesamiento de resultados de auditoría.
 * Asegura que el conteo de requisitos y hallazgos sea uniforme en toda la aplicación.
 *
 * Compliance: cada ítem puede traer zona_origen (map-reduce). Si falta (dictámenes legacy),
 * se infiere la zona a partir del bucket (administrativo/tecnico/formatos).
 */

/** Orden alineado con backend ComplianceAgent.search_zones */
export const ZONA_TAB_ORDER = [
    'ADMINISTRATIVO/LEGAL',
    'TÉCNICO/OPERATIVO',
    'FORMATOS/ANEXOS',
    'GARANTÍAS/SEGUROS',
];

const BUCKET_TO_FALLBACK_ZONA = {
    administrativo: 'ADMINISTRATIVO/LEGAL',
    tecnico: 'TÉCNICO/OPERATIVO',
    formatos: 'FORMATOS/ANEXOS',
};

/**
 * MVP documentado: si `zona_origen` falta (dictámenes antiguos o ítem sin estampar),
 * se usa el bucket de lista (administrativo/tecnico/formatos) como zona aproximada.
 * No se añade pestaña "Sin zona" separada: la zona mostrada es siempre efectiva para filtrado.
 * @param {string} [tipo]
 * @returns {'administrativo'|'tecnico'|'formatos'}
 */
export function inferBucketKeyFromTipo(tipo) {
    if (!tipo || typeof tipo !== 'string') return 'administrativo';
    if (tipo.includes('TÉCNICO') || tipo.includes('TECNICO')) return 'tecnico';
    if (tipo.includes('FORMATO') || tipo.includes('ANEXO')) return 'formatos';
    if (tipo.includes('ADMINISTRATIVO')) return 'administrativo';
    return 'administrativo';
}

/**
 * @param {string} a
 * @param {string} b
 */
function sameCategoryBucket(a, b) {
    return String(a || '')
        .toLowerCase()
        .trim() === String(b || '')
            .toLowerCase()
            .trim();
}

/**
 * @param {object|string} raw - ítem compliance
 * @param {string} tipoLabel - etiqueta UI (emoji + nombre)
 * @param {'administrativo'|'tecnico'|'formatos'} listKey - clave de lista en API
 */
function mapComplianceHallazgo(raw, tipoLabel, listKey) {
    const o = typeof raw === 'object' && raw !== null ? raw : {};
    const zo = o.zona_origen != null && String(o.zona_origen).trim() !== ''
        ? String(o.zona_origen).trim()
        : null;
    const effectiveZona = zo || BUCKET_TO_FALLBACK_ZONA[listKey] || 'ADMINISTRATIVO/LEGAL';
    const catRaw = typeof raw === 'object' && raw.categoria ? String(raw.categoria) : listKey;
    return {
        tipo: tipoLabel,
        texto: raw,
        category: 'compliance',
        snippet: typeof raw === 'object' ? raw.snippet : null,
        page: typeof raw === 'object' ? raw.page : null,
        id: typeof raw === 'object' ? raw.id : null,
        agent_id: 'compliance_001',
        zona_origen: effectiveZona,
        /** Categoría devuelta por el modelo (o bucket si no hubo categoria en API). */
        categoria_llm: catRaw,
        /** Lista de origen en API: para contrastar con categoria_llm en UI. */
        bucketKey: listKey,
        /** false si zona_origen no vino en el payload (fallback por bucket). */
        zona_explicita: zo !== null,
        /** true si la categoría del LLM difiere del bucket de lista (badge secundario en ForensicCard). */
        categoria_difiere_bucket: !sameCategoryBucket(catRaw, listKey),
    };
}

export function buildCompliancePorZona(complianceHallazgos) {
    /** @type {Record<string, typeof complianceHallazgos>} */
    const out = {};
    for (const z of ZONA_TAB_ORDER) {
        out[z] = [];
    }
    out._OTRAS_ZONAS = [];

    for (const h of complianceHallazgos) {
        const k = h.zona_origen;
        if (ZONA_TAB_ORDER.includes(k)) {
            out[k].push(h);
        } else {
            out._OTRAS_ZONAS.push(h);
        }
    }
    return out;
}

/**
 * Cadena normalizada para deduplicar hallazgos. Prioriza el texto principal que ve el usuario
 * (descripción / requisito), no el fragmento del PDF (`snippet`), que suele variar entre ítems
 * duplicados del map-reduce aunque sea el mismo requisito.
 * @param {unknown} texto
 * @returns {string}
 */
export function hallazgoFingerprintContent(texto) {
    if (texto == null || texto === '') return '';
    if (typeof texto === 'string') {
        return texto.trim().toLowerCase().replace(/\s+/g, ' ').slice(0, 1000);
    }
    if (typeof texto === 'object') {
        const o = texto;
        const raw =
            o.descripcion ||
            o.requisito ||
            o.detalle ||
            o.nombre ||
            o.texto_crudo ||
            o.snippet ||
            o.extracto ||
            o.evidencia ||
            o.literal ||
            '';
        if (raw) return String(raw).trim().toLowerCase().replace(/\s+/g, ' ').slice(0, 1000);
        try {
            return JSON.stringify(o).trim().toLowerCase().replace(/\s+/g, ' ').slice(0, 1000);
        } catch {
            return '';
        }
    }
    return String(texto).trim().toLowerCase().replace(/\s+/g, ' ').slice(0, 1000);
}

/**
 * Deduplica el listado unificado de hallazgos (misma regla que al procesar respuesta de agentes).
 * Compliance se unifica por texto literal para evitar repeticiones del map-reduce con IDs distintos.
 * @param {Array<object>} rawList
 * @returns {Array<object>}
 */
export function dedupeHallazgosList(rawList) {
    if (!Array.isArray(rawList) || rawList.length === 0) return rawList || [];
    const seenMap = new Map();

    rawList.forEach((h) => {
        if (!h.texto) return;

        const contentStr = hallazgoFingerprintContent(h.texto);

        const dedupKey =
            h.category === 'compliance'
                ? `compliance:${contentStr}`
                : h.id && !h.id.includes('risk-') && !h.id.includes('base-')
                  ? h.id
                  : `${h.category}:${contentStr}`;

        if (!seenMap.has(dedupKey)) {
            seenMap.set(dedupKey, h);
        } else {
            const prev = seenMap.get(dedupKey);
            if (h.isRisk && prev) prev.isRisk = true;
            if (h.category === 'compliance' && prev) {
                if ((prev.page == null || String(prev.page).trim() === '') && h.page != null && String(h.page).trim() !== '') {
                    prev.page = h.page;
                }
                if ((prev.snippet == null || String(prev.snippet).trim() === '') && h.snippet != null && String(h.snippet).trim() !== '') {
                    prev.snippet = h.snippet;
                }
                if (typeof prev.texto === 'object' && prev.texto && typeof h.texto === 'object' && h.texto) {
                    if (!prev.texto.page && h.texto.page) prev.texto = { ...prev.texto, page: h.texto.page };
                    if (!prev.texto.snippet && h.texto.snippet) prev.texto = { ...prev.texto, snippet: h.texto.snippet };
                }
            }
        }
    });

    return Array.from(seenMap.values());
}

/**
 * Tras deduplicar `causales`, recalcula zonas y contadores del dictamen cargado desde Postgres.
 * @param {object} dictamen
 * @returns {object}
 */
function finalizeStoredDictamenDedupe(dictamen) {
    const causales = dedupeHallazgosList(dictamen.causales || []);
    const comp = causales.filter((c) => c.category === 'compliance');
    const porZona = buildCompliancePorZona(comp);
    return {
        ...dictamen,
        causales,
        compliancePorZona: porZona,
        causalesPorZona: porZona,
        totalRequisitos: causales.length,
        riesgos: causales.filter((h) => h.isRisk).length,
        complianceHallazgosCount: comp.length,
    };
}

/**
 * Dictámenes guardados antes de `compliancePorZona`: reconstruye agrupación desde `causales`.
 * @param {object|null} dictamen
 * @returns {object|null}
 */
/**
 * Si el dictamen en Postgres es anterior al contrato `pipelineTelemetry`, infiere etapas y estado
 * del orquestador a partir de causales, zonas y `statusRaw` (sin sustituir telemetría real del servidor).
 *
 * @param {object|null} dictamen
 * @returns {object|null} Objeto compatible con `pipelineTelemetry` con `_inferred: true`, o null si no aplica.
 */
export function synthesizePipelineTelemetryFromDictamen(dictamen) {
    if (!dictamen || typeof dictamen !== 'object') return null;
    const existing = dictamen.pipelineTelemetry;
    if (
        existing &&
        typeof existing === 'object' &&
        Array.isArray(existing.stagesCompleted) &&
        existing.stagesCompleted.length > 0 &&
        !existing._inferred
    ) {
        return null;
    }

    const causales = Array.isArray(dictamen.causales) ? dictamen.causales : [];
    const hasBases = causales.some((c) => String(c.category || '').toLowerCase().includes('bases'));
    
    // Señal inequívoca de que al menos un agente procesó información:
    const hasTotalReqs = typeof dictamen.totalRequisitos === 'number' && dictamen.totalRequisitos > 0;

    const ex = dictamen.extracted_data;
    const hasExtraction = ex && typeof ex === 'object' && Object.keys(ex).length > 0;

    const compCount = dictamen.complianceHallazgosCount ?? 0;
    const hasCompItems = causales.some((c) => String(c.category || '').toLowerCase() === 'compliance');
    const zones = Array.isArray(dictamen.zones) ? dictamen.zones : [];
    const hasComplianceSignal = hasCompItems || compCount > 0 || zones.length > 0;

    const sr = String(dictamen.statusRaw || '').trim().toLowerCase();
    const srKnown = ['success', 'partial', 'fail', 'error'].includes(sr);

    /** @type {string[]} */
    const stages = [];
    
    // Si hay requisitos en general, el análisis inicial se hizo.
    if (hasBases || hasExtraction || hasTotalReqs || hasComplianceSignal || srKnown) {
        stages.push('analysis');
    }

    // Si hay señales directas forenses o un éxito reportado
    if (hasComplianceSignal || srKnown || (hasTotalReqs && !hasBases)) {
        if (!stages.includes('compliance')) stages.push('compliance');
    }

    if (causales.some((c) => String(c.category || '').toLowerCase() === 'economic')) stages.push('economic');

    if (stages.length === 0) return null;

    let orch = 'unknown';
    if (sr === 'success') orch = 'success';
    else if (sr === 'partial') orch = 'partial';
    else if (sr === 'fail' || sr === 'error') orch = 'error';

    return {
        stagesCompleted: stages,
        pausedStage: null,
        orchestratorStatus: orch,
        stopReason: null,
        _inferred: true,
    };
}

export function enrichDictamenFromStorage(dictamen) {
    if (!dictamen || typeof dictamen !== 'object') return dictamen;
    if (dictamen.compliancePorZona && Object.keys(dictamen.compliancePorZona).length > 0) {
        const withAlias = dictamen.causalesPorZona != null
            ? dictamen
            : { ...dictamen, causalesPorZona: dictamen.compliancePorZona };
        return finalizeStoredDictamenDedupe(withAlias);
    }
    const compliance = (dictamen.causales || []).filter((c) => c.category === 'compliance');
    if (compliance.length === 0) {
        return finalizeStoredDictamenDedupe({
            ...dictamen,
            compliancePorZona: buildCompliancePorZona([]),
            causalesPorZona: buildCompliancePorZona([]),
        });
    }
    const normalized = compliance.map((h) => {
        const bucket = h.bucketKey || inferBucketKeyFromTipo(h.tipo);
        const zo =
            h.zona_origen != null && String(h.zona_origen).trim() !== ''
                ? String(h.zona_origen).trim()
                : null;
        const effectiveZona = zo || BUCKET_TO_FALLBACK_ZONA[bucket] || 'ADMINISTRATIVO/LEGAL';
        const catRaw = h.categoria_llm != null ? String(h.categoria_llm) : bucket;
        return {
            ...h,
            bucketKey: bucket,
            zona_origen: effectiveZona,
            zona_explicita: zo !== null,
            categoria_llm: catRaw,
            categoria_difiere_bucket: !sameCategoryBucket(catRaw, bucket),
        };
    });
    let ni = 0;
    const causalesMerged = (dictamen.causales || []).map((c) =>
        c.category === 'compliance' ? normalized[ni++] : c
    );
    const porZona = buildCompliancePorZona(normalized);
    return finalizeStoredDictamenDedupe({ ...dictamen, causales: causalesMerged, compliancePorZona: porZona, causalesPorZona: porZona });
}

/**
 * Indica si el fallo de compliance se debe a falta de contexto en el índice vectorial (Chroma),
 * no a un hallazgo de incumplimiento en las bases.
 * @param {Array<{status?: string, reason?: string}>|undefined} zones
 * @param {string} [statusRaw]
 * @param {string} [errorText]
 */
export function detectRagInfrastructureIssue(zones, statusRaw, errorText) {
    if (statusRaw !== 'fail' && statusRaw !== 'error') return false;
    const ragInText = (s) => {
        const t = String(s || '').toLowerCase();
        return t.includes('rag') && (t.includes('vacío') || t.includes('vacio') || t.includes('empty'));
    };
    if (ragInText(errorText)) return true;
    if (!Array.isArray(zones) || zones.length === 0) return false;
    return zones.every(
        (z) =>
            z &&
            z.status &&
            String(z.status).toLowerCase() !== 'pass' &&
            ragInText(z.reason)
    );
}

/**
 * Ajusta título y color del dictamen cuando el problema es de índice RAG, para no confundir con
 * "no se guardó nada" ni con incumplimiento contractual.
 * @param {object|null} dictamen - objeto ya procesado (processAuditResults o cargado de Postgres)
 * @returns {object|null}
 */
export function applyInfrastructureUxOverrides(dictamen) {
    if (!dictamen || typeof dictamen !== 'object') return dictamen;
    const rag = detectRagInfrastructureIssue(
        dictamen.zones,
        dictamen.statusRaw,
        dictamen.errorText
    );
    if (!rag) {
        return dictamen.uxKind ? dictamen : { ...dictamen, uxKind: 'normal' };
    }
    return {
        ...dictamen,
        status: '⚠️ Índice de búsqueda no disponible',
        statusColor: '#38bdf8',
        uxKind: 'rag_index_missing',
        uxGuiaUsuario:
            'Tus datos de expediente y el último dictamen siguen guardados en el servidor. Aquí falló la consulta al índice vectorial (Chroma): no hay fragmentos útiles para esta sesión o se vació tras un reinicio. No es un “borrón” de la base de datos. Sube o reprocesa los PDF y pulsa «Analizar bases» solo para reindexar y volver a auditar.',
    };
}

export const processAuditResults = (resultsData) => {
    if (!resultsData) return null;
    // Evita falso "COMPLETADO" si se pasa la respuesta de encolado (job_id) en lugar del payload del orquestador.
    if (resultsData.job_id && !resultsData.compliance && !resultsData.analysis && !resultsData.economic) {
        console.warn('[auditSummary] processAuditResults: payload es de encolado (job_id), no resultados de agentes.');
        return null;
    }

    const { analysis, compliance, economic } = resultsData;

    const complianceAdmin = (compliance?.data?.administrativo || []).map((c) =>
        mapComplianceHallazgo(c, '📁 ADMINISTRATIVO', 'administrativo')
    );
    const complianceTec = (compliance?.data?.tecnico || []).map((t) =>
        mapComplianceHallazgo(t, '🛠️ TÉCNICO', 'tecnico')
    );
    const complianceFmt = (compliance?.data?.formatos || []).map((f) =>
        mapComplianceHallazgo(f, '📄 FORMATO / ANEXO', 'formatos')
    );
    const complianceHallazgos = [...complianceAdmin, ...complianceTec, ...complianceFmt];

    // --- LISTADO UNIFICADO DE HALLAZGOS (Contrato 1:1; orden estable) ---
    const reqParticipacion = analysis?.data?.requisitos_participacion || analysis?.requisitos_participacion || [];
    const reqParticipacionItems = reqParticipacion.map((it, i) => {
        const inc = typeof it?.inciso === 'string' ? it.inciso.trim() : '';
        const txt = typeof it?.texto_literal === 'string' ? it.texto_literal.trim() : '';
        const label = inc && txt ? `${inc}) ${txt}`.replace(/^\)\s*/, '') : txt || String(it || '');
        return {
            tipo: '📋 REQUISITO PARA PARTICIPAR',
            texto: label,
            category: 'bases_participacion',
            id: `base-part-${i}`,
            agent_id: 'analyst_001',
            zona_origen: null,
            categoria_llm: null,
        };
    }).filter((x) => x.texto);
    const analysisPayload = analysis?.data || analysis || {};
    const reglasEconomicasItems = Object.entries(analysisPayload.reglas_economicas || {})
        .filter(([, v]) => typeof v === 'string' && v.trim() && v.trim() !== 'No especificado')
        .map(([k, v], i) => ({
            tipo: '💶 REGLA ECONÓMICA (BASES)',
            texto: `${k}: ${v}`,
            category: 'bases_reglas_economicas',
            id: `base-regla-${i}`,
            agent_id: 'analyst_001',
            zona_origen: null,
            categoria_llm: null,
        }));
    const alcanceOperativoItems = (analysisPayload.alcance_operativo || [])
        .map((row, i) => {
            const lit =
                typeof row?.texto_literal_fila === 'string' ? row.texto_literal_fila.trim() : '';
            const fallback = [
                row?.ubicacion_o_area,
                row?.puesto_funcion_o_servicio,
                row?.turno,
                row?.cantidad_o_elementos,
                row?.dias_aplicables,
            ]
                .filter(Boolean)
                .join(' | ');
            const texto = lit || fallback;
            return {
                tipo: '📊 ALCANCE / DOTACIÓN (BASES)',
                texto,
                category: 'bases_alcance',
                id: `base-alcance-${i}`,
                agent_id: 'analyst_001',
                zona_origen: null,
                categoria_llm: null,
            };
        })
        .filter((x) => x.texto);
    const datosTabAlert = analysisPayload.datos_tabulares?.alerta_faltante
        ? [
              {
                  tipo: '⚠️ ALERTA PARTIDAS / ANEXOS',
                  texto: analysisPayload.datos_tabulares.alerta_faltante,
                  category: 'bases_datos_tabulares',
                  id: 'base-tabular-alert',
                  agent_id: 'analyst_001',
                  zona_origen: null,
                  categoria_llm: null,
              },
          ]
        : [];
    const rawList = [
        ...reqParticipacionItems,
        ...(analysis?.data?.requisitos_filtro || analysis?.requisitos_filtro || []).map((r, i) => ({
            tipo: '⚖️ FILTRO / DESCALIFICACIÓN (BASES)',
            texto: r,
            category: 'bases_filtro',
            id: `base-filtro-${i}`,
            agent_id: 'analyst_001',
            zona_origen: null,
            categoria_llm: null,
        })),
        ...reglasEconomicasItems,
        ...alcanceOperativoItems,
        ...datosTabAlert,
        ...complianceHallazgos,
        ...(compliance?.summary?.causas_desechamiento || []).map((d, i) => ({
            tipo: '🚫 DESECHAMIENTO',
            texto: d,
            isRisk: true,
            category: 'risk',
            snippet: typeof d === 'object' ? d.snippet : null,
            page: typeof d === 'object' ? d.page : null,
            id: typeof d === 'object' ? d.id : `risk-${i}`,
            agent_id: 'compliance_001',
            zona_origen: null,
            categoria_llm: null,
        })),
        ...(economic?.data?.analisis_precios?.alertas || []).map((a, i) => ({
            tipo: '💰 ALERTA ECONÓMICA',
            texto: a,
            isRisk: true,
            category: 'economic',
            id: `econ-${i}`,
            agent_id: 'economic_001',
            zona_origen: null,
            categoria_llm: null,
        })),
        ...(Array.isArray(economic?.data?.alertas_contexto_bases)
            ? economic.data.alertas_contexto_bases
            : []
        ).map((a, i) => ({
            tipo: '📌 PAUSA ECONÓMICA / CONTEXTO DE BASES',
            texto: a,
            isRisk: true,
            category: 'economic_gap_context',
            id: `econ-gap-${i}`,
            agent_id: 'economic_001',
            zona_origen: null,
            categoria_llm: null,
        })),
    ];

    const listadoHallazgos = dedupeHallazgosList(rawList);

    const compliancePorZona = buildCompliancePorZona(
        listadoHallazgos.filter(h => h.category === 'compliance')
    );

    const auditZones =
        compliance?.data?.audit_summary?.zones ||
        compliance?.metrics?.zones ||
        [];

    // --- CÁLCULO DE MÉTRICAS ---
    const totalHallazgos = listadoHallazgos.length;
    const totalRiesgos = listadoHallazgos.filter((h) => h.isRisk).length;

    // --- DETERMINACIÓN DE ESTADO ---
    const status_backend = compliance?.status || 'success';
    let displayStatus = '✅ COMPLETADO';
    let statusColor = '#2ecc71';

    if (status_backend === 'error') {
        displayStatus = '❌ ERROR EN AUDITORÍA DE CUMPLIMIENTO';
        statusColor = '#e74c3c';
    } else if (status_backend === 'partial') {
        displayStatus = '⚠️ COMPLETADO CON INCIDENCIAS';
        statusColor = '#f39c12';
    } else if (status_backend === 'fail') {
        displayStatus = '❌ FALLO EN AUDITORÍA';
        statusColor = '#e74c3c';
    }

    const base = {
        status: displayStatus,
        statusColor: statusColor,
        statusRaw: status_backend,
        errorText: compliance?.error || compliance?.message || '',
        zones: auditZones,
        veredicto: compliance?.summary?.veredicto || 'Auditoría Técnica completada.',
        riesgos: totalRiesgos,
        totalRequisitos: totalHallazgos,
        causales: listadoHallazgos,
        compliancePorZona,
        /** Alias explícito del plan (mismo objeto que compliancePorZona). */
        causalesPorZona: compliancePorZona,
        complianceHallazgosCount: listadoHallazgos.filter(h => h.category === 'compliance').length,
        extracted_data: analysis,
        fechaAuditoria: new Date().toLocaleString('es-MX'),
    };
    if (resultsData.pipelineTelemetry && typeof resultsData.pipelineTelemetry === 'object') {
        base.pipelineTelemetry = resultsData.pipelineTelemetry;
    }
    if (resultsData.metadata && typeof resultsData.metadata === 'object') {
        base.orchestratorMetadata = resultsData.metadata;
    }
    const wh = resultsData.orchestrator_decision?.waiting_hints;
    if (wh && typeof wh === 'object') {
        base.economicWaitingHints = wh;
    }
    return applyInfrastructureUxOverrides(base);
};
