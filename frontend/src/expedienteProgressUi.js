/**
 * Etiquetas HRU de progreso del expediente (alineado con document_quality_ux_messages.json).
 */

export const EXPEDIENTE_PROGRESS_UI = Object.freeze({
    cardTitle: 'Avance del expediente',
    progressStep: (current, total) => `Paso ${current} de ${total}`,
    blockingHint: 'Completa primero lo marcado como urgente para poder generar.',
    steadyHint: 'Vamos bien. Siguiente: completa los datos que te pido abajo.',
    blockingLabel: 'Urgente',
    pendingLabel: 'Por completar',
    resumedBadge: 'Retomado',
    auditBadge: 'Vista técnica',
});

export const EXPEDIENTE_CHAT_SHELL_UI = Object.freeze({
    subtitleQualityBlock:
        'Falta confirmar qué documentos armamos en el sistema — responde en el chat y vuelve a generar.',
    subtitleEconomicBlock:
        'Hay un detalle en la cotización — corrige en el chat o en Excel y vuelve a generar.',
    subtitleDefault: 'Pregunta por fechas, requisitos o dudas de las bases — aquí abajo',
    qualityPanelTitle: 'Confirmar documentos del pliego',
    qualityPanelBody:
        'Antes de generar, necesitamos aclarar qué anexos redacta el sistema. Responde en el chat y pulsa revalidar.',
    qualityPanelCta: 'Revisar y continuar',
});
