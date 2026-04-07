import React from 'react';
import { FileDown } from 'lucide-react';
import { ZONA_TAB_ORDER } from '../utils/auditSummary';

/**
 * Escapa texto para insertarlo en HTML de impresión (evita rotura de layout / XSS).
 * @param {unknown} s
 */
function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/** Misma lógica que ForensicCard para el cuerpo del hallazgo. */
function literalTextoHallazgo(c) {
    const t = c?.texto;
    if (typeof t === 'object' && t !== null) {
        return t.descripcion || t.nombre || JSON.stringify(t);
    }
    return t != null ? String(t) : '';
}

/**
 * Genera bloques HTML de ítems compliance con traza de zona y categoría LLM.
 * @param {Array<object>} items
 */
function complianceItemsHtml(items) {
    return (items || [])
        .map((c) => {
            const tipo = escapeHtml(c.tipo || 'Compliance');
            const literal = escapeHtml(literalTextoHallazgo(c));
            const zonaInf =
                c.zona_explicita === false && c.zona_origen ? ' <em>(inferida)</em>' : '';
            const zona = c.zona_origen
                ? `<div class="item-meta"><strong>Zona extracción:</strong> ${escapeHtml(c.zona_origen)}${zonaInf}</div>`
                : '';
            const catDiffers =
                c.categoria_llm &&
                c.bucketKey &&
                String(c.categoria_llm).toLowerCase().trim() !== String(c.bucketKey).toLowerCase().trim();
            const cat = catDiffers
                ? `<div class="item-meta"><strong>Cat. LLM:</strong> ${escapeHtml(c.categoria_llm)}</div>`
                : '';
            const page =
                c.page != null && String(c.page).trim() !== ''
                    ? `<div class="item-meta"><strong>Página:</strong> ${escapeHtml(String(c.page))}</div>`
                    : '';
            const sn = c.snippet;
            const snippet =
                sn != null && String(sn).trim() !== ''
                    ? `<div class="snippet"><strong>Fragmento:</strong> ${escapeHtml(typeof sn === 'string' ? sn : JSON.stringify(sn))}</div>`
                    : '';
            return `<div class="item compliance">
            <div class="item-tipo">${tipo}</div>
            ${zona}${cat}${page}
            <div class="literal">${literal}</div>
            ${snippet}
        </div>`;
        })
        .join('');
}

/**
 * Secciones de compliance ordenadas por ZONA_TAB_ORDER + otras zonas.
 * @param {Record<string, object[]>} porZona
 */
function compliancePorZonaHtml(porZona) {
    if (!porZona || typeof porZona !== 'object') return '';
    let html = '';
    for (const z of ZONA_TAB_ORDER) {
        const items = porZona[z] || [];
        if (items.length === 0) continue;
        html += `<h2>Compliance — ${escapeHtml(z)}</h2>`;
        html += complianceItemsHtml(items);
    }
    const otras = porZona._OTRAS_ZONAS || [];
    if (otras.length > 0) {
        html += `<h2>Compliance — Otras zonas</h2>`;
        html += complianceItemsHtml(otras);
    }
    return html;
}

/** Clase visual según categoría de hallazgo no-compliance. */
function itemClassOtros(c) {
    const tipo = c.tipo || '';
    if (c.isRisk || tipo.includes('DESECHAMIENTO')) return 'causa';
    if (tipo.includes('ECONÓM')) return 'causa';
    if (tipo.includes('BASES') || tipo.includes('REQUISITO')) return 'requisito';
    return 'requisito';
}

function otrosHallazgosHtml(items) {
    return (items || [])
        .map((c) => {
            const cls = itemClassOtros(c);
            const tipo = escapeHtml(c.tipo || '');
            const literal = escapeHtml(literalTextoHallazgo(c));
            const page =
                c.page != null && String(c.page).trim() !== ''
                    ? `<div class="item-meta"><strong>Página:</strong> ${escapeHtml(String(c.page))}</div>`
                    : '';
            const sn = c.snippet;
            const snippet =
                sn != null && String(sn).trim() !== ''
                    ? `<div class="snippet"><strong>Fragmento:</strong> ${escapeHtml(typeof sn === 'string' ? sn : JSON.stringify(sn))}</div>`
                    : '';
            return `<div class="item ${cls}">
            <div class="item-tipo">${tipo}</div>
            ${page}
            <div class="literal">${literal}</div>
            ${snippet}
        </div>`;
        })
        .join('');
}

const ExportPDF = ({ auditResults, sessionId }) => {
    const handleExport = () => {
        if (!auditResults) return;

        const {
            veredicto,
            riesgos,
            totalRequisitos,
            causales,
            compliancePorZona,
            extracted_data: analysis,
            fechaAuditoria,
            status,
            statusColor,
            errorText,
            zones,
            reqAdmin = [],
            reqTecnico = [],
            reqFormatos = [],
        } = auditResults;

        const porZona = compliancePorZona || {};
        const allCompliance = (causales || []).filter((c) => c.category === 'compliance');
        const otrosHallazgos = (causales || []).filter((c) => c.category !== 'compliance');

        // FUENTE DE VERDAD ÚNICA: Usamos el status procesado por auditSummary (backend + lógica de negocio)
        const displayStatus = status || (riesgos > 0 ? '🔴 RIESGO DETECTADO' : '🟢 CUMPLE');
        const displayColor = statusColor || (riesgos > 0 ? '#ff4757' : '#00ff88');

        const zonesBlock =
            zones && zones.filter((z) => z.status !== 'pass').length > 0
                ? `<h2>Incidencias por zona (resumen auditoría)</h2>
            ${zones
                .filter((z) => z.status !== 'pass')
                .map(
                    (z) =>
                        `<div class="zone-flag" style="border-left-color:${z.status === 'partial' ? '#f39c12' : '#e74c3c'}">
                <strong>${escapeHtml(z.zone || '')}</strong> (${escapeHtml(String(z.status || '')).toUpperCase()}): ${escapeHtml(z.reason || '')}
            </div>`
                )
                .join('')}`
                : '';

        const complianceBlock =
            allCompliance.length > 0
                ? `<h2>Compliance por zona de extracción</h2>
            <p class="section-lead">Mismo criterio que el panel lateral: agrupación por <code>zona_origen</code> con traza de categoría LLM.</p>
            ${compliancePorZonaHtml(porZona)}`
                : '';

        const otrosBlock =
            otrosHallazgos.length > 0
                ? `<h2>Otros hallazgos (bases, desechamiento, económico)</h2>
            ${otrosHallazgosHtml(otrosHallazgos)}`
                : '';

        const legacyAdmin =
            reqAdmin.length > 0
                ? `<h2>Documentación administrativa (tabla legacy)</h2>
        <table class="section-table">
            <tr><th>ID</th><th>Documento</th><th>Descripción</th><th>Crítico</th></tr>
            ${reqAdmin
                .map(
                    (r) => `<tr>
            <td>${escapeHtml(r.id || '—')}</td>
            <td>${escapeHtml(r.nombre != null ? r.nombre : String(r))}</td>
            <td>${escapeHtml(r.descripcion || '—')}</td>
            <td>${r.es_causal_desechamiento ? '🚫 SÍ' : 'No'}</td>
        </tr>`
                )
                .join('')}
        </table>`
                : '';

        const legacyTec =
            reqTecnico.length > 0
                ? `<h2>Propuesta técnica (tabla legacy)</h2>
        <table class="section-table">
            <tr><th>ID</th><th>Requisito</th><th>Descripción</th><th>Crítico</th></tr>
            ${reqTecnico
                .map(
                    (r) => `<tr>
            <td>${escapeHtml(r.id || '—')}</td>
            <td>${escapeHtml(r.nombre != null ? r.nombre : String(r))}</td>
            <td>${escapeHtml(r.descripcion || '—')}</td>
            <td>${r.es_causal_desechamiento ? '🚫 SÍ' : 'No'}</td>
        </tr>`
                )
                .join('')}
        </table>`
                : '';

        const legacyFmt =
            reqFormatos.length > 0
                ? `<h2>Formatos oficiales (tabla legacy)</h2>
        <table class="section-table">
            <tr><th>Formato</th><th>Nombre</th><th>Descripción</th></tr>
            ${reqFormatos
                .map(
                    (r) => `<tr>
            <td><strong>${escapeHtml(r.formato || r.id || '—')}</strong></td>
            <td>${escapeHtml(r.nombre != null ? r.nombre : String(r))}</td>
            <td>${escapeHtml(r.descripcion || '—')}</td>
        </tr>`
                )
                .join('')}
        </table>`
                : '';

        const printContent = `
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Dictamen LicitAI — ${escapeHtml(sessionId)}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Arial, sans-serif; color: #1a1a2e; background: #fff; }
        
        .header {
            background: linear-gradient(135deg, #0a0f1a 0%, #1a1f2e 100%);
            color: white;
            padding: 32px 48px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .brand { font-size: 28px; font-weight: 900; letter-spacing: -1px; }
        .brand span { color: #00d4ff; }
        .meta { font-size: 11px; color: #94a3b8; text-align: right; line-height: 1.8; }
        
        .status-bar {
            background: ${displayColor}18;
            border-left: 6px solid ${displayColor};
            padding: 16px 48px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .status-label { font-size: 18px; font-weight: 800; color: ${displayColor}; }
        .status-meta { font-size: 12px; color: #64748b; }
        
        .content { padding: 32px 48px; }
        
        h2 { font-size: 14px; font-weight: 800; text-transform: uppercase; 
             letter-spacing: 2px; color: #64748b; margin: 28px 0 12px; 
             padding-bottom: 6px; border-bottom: 1px solid #e2e8f0; }
        
        .section-lead { font-size: 12px; color: #64748b; margin-bottom: 14px; line-height: 1.5; }
        .section-lead code { font-size: 11px; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; }
        
        .veredicto-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-left: 4px solid #00d4ff;
            border-radius: 8px;
            padding: 16px 20px;
            font-size: 14px;
            line-height: 1.6;
            margin-bottom: 20px;
        }
        
        .audit-status-banner {
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 16px;
            font-size: 13px;
            font-weight: 700;
            border: 1px solid #e2e8f0;
        }
        
        .zone-flag {
            padding: 10px 14px;
            margin-bottom: 8px;
            background: #f8fafc;
            border-radius: 8px;
            font-size: 12px;
            border-left: 4px solid #e74c3c;
        }
        
        .stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
        .stat-box {
            flex: 1;
            min-width: 140px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
        }
        .stat-label { font-size: 9px; font-weight: 800; text-transform: uppercase; 
                      letter-spacing: 1.5px; color: #94a3b8; margin-bottom: 4px; }
        .stat-value { font-size: 32px; font-weight: 900; color: #1a1a2e; }
        .stat-value.danger { color: #ff4757; }
        .stat-value.safe { color: #00ff88; }
        
        .item {
            padding: 10px 14px;
            border-radius: 8px;
            margin-bottom: 8px;
            font-size: 13px;
            line-height: 1.5;
        }
        .item.requisito { background: #eff6ff; border-left: 3px solid #3b82f6; }
        .item.causa { background: #fff5f5; border-left: 3px solid #ff4757; }
        .item.compliance { background: #f0fdf4; border-left: 3px solid #22c55e; }
        
        .item-tipo { font-size: 9px; font-weight: 800; text-transform: uppercase; 
                     letter-spacing: 1px; margin-bottom: 6px; color: #64748b; }
        .item-meta { font-size: 11px; color: #475569; margin-bottom: 4px; }
        .literal { margin-top: 4px; }
        .snippet { margin-top: 8px; font-size: 11px; color: #64748b; font-style: italic; border-top: 1px dashed #e2e8f0; padding-top: 8px; }
        
        .section-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 12px; }
        .section-table th { background: #f1f5f9; text-align: left; padding: 8px 12px; 
                            font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; }
        .section-table td { padding: 8px 12px; border-bottom: 1px solid #e2e8f0; }
        .section-table tr:hover td { background: #f8fafc; }
        
        .footer {
            background: #f8fafc;
            border-top: 1px solid #e2e8f0;
            padding: 20px 48px;
            font-size: 11px;
            color: #94a3b8;
            display: flex;
            justify-content: space-between;
        }
        
        @media print {
            body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
            .no-print { display: none; }
        }
    </style>
</head>
<body>

<div class="header">
    <div>
        <div class="brand">Licit<span>AI</span></div>
        <div style="font-size:12px; color:#94a3b8; margin-top:4px;">Sistema de Auditoría Inteligente para Licitaciones</div>
    </div>
    <div class="meta">
        <div><strong>Licitación:</strong> ${escapeHtml(sessionId)}</div>
        <div><strong>Fecha:</strong> ${escapeHtml(fechaAuditoria || new Date().toLocaleString('es-MX'))}</div>
        <div><strong>Generado por:</strong> LicitAI v2026</div>
    </div>
</div>

<div class="status-bar">
    <div class="status-label">${displayStatus}</div>
    <div class="status-meta">
        Dictamen generado por agentes IA &nbsp;|&nbsp;
        ${totalRequisitos} requisitos analizados &nbsp;|&nbsp;
        ${riesgos} hallazgos de riesgo detectados
    </div>
</div>

<div class="content">

    <div class="veredicto-box">
        <h3 style="font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; color: #64748b; margin-bottom: 8px;">Veredicto del sistema</h3>
        ${escapeHtml(veredicto || '')}
    </div>
    
    ${errorText ? `<div class="zone-flag" style="border-left-color:#e74c3c;"><strong>Detalle del error:</strong> ${escapeHtml(errorText)}</div>` : ''}

    <div class="stats">
        <div class="stat-box">
            <div class="stat-label">Total hallazgos</div>
            <div class="stat-value">${totalRequisitos}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Ítems de riesgo</div>
            <div class="stat-value ${riesgos > 0 ? 'danger' : 'safe'}">${riesgos}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Criterio evaluación</div>
            <div class="stat-value" style="font-size:14px; margin-top: 6px;">${escapeHtml(analysis?.criterios_evaluacion || '—')}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Hallazgos compliance</div>
            <div class="stat-value" style="font-size:22px; margin-top: 6px;">${allCompliance.length}</div>
        </div>
    </div>

    <h2>Cronograma</h2>
    <table class="section-table">
        <tr><th>Evento</th><th>Fecha</th></tr>
        <tr><td>Junta de Aclaraciones</td><td>${escapeHtml(analysis?.cronograma?.junta_aclaraciones || '—')}</td></tr>
        <tr><td>Presentación de Propuestas</td><td>${escapeHtml(analysis?.cronograma?.presentacion_proposiciones || '—')}</td></tr>
        <tr><td>Acto de Fallo</td><td>${escapeHtml(analysis?.cronograma?.fallo || '—')}</td></tr>
    </table>

    <h2>Garantías requeridas</h2>
    <table class="section-table">
        <tr><th>Tipo</th><th>Monto</th></tr>
        <tr><td>Seriedad de Oferta</td><td>${escapeHtml(analysis?.garantias?.seriedad_oferta || '—')}</td></tr>
        <tr><td>Cumplimiento de Contrato</td><td>${escapeHtml(analysis?.garantias?.cumplimiento || '—')}</td></tr>
    </table>

    ${zonesBlock}

    ${complianceBlock}

    ${otrosBlock}

    ${legacyAdmin}
    ${legacyTec}
    ${legacyFmt}

</div>

<div class="footer">
    <div>LicitAI — Plataforma de Auditoría Automatizada para Licitaciones Públicas © 2026</div>
    <div>Dictamen generado automáticamente. Verificar con asesor legal antes de presentar propuesta.</div>
</div>

</body>
</html>`;

        const printWin = window.open('', '_blank', 'width=900,height=700');
        printWin.document.write(printContent);
        printWin.document.close();
        printWin.focus();
        setTimeout(() => {
            printWin.print();
        }, 500);
    };

    return (
        <button
            type="button"
            onClick={handleExport}
            disabled={!auditResults}
            title="Exportar dictamen a PDF (vista de impresión)"
            style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                borderRadius: '8px',
                border: '1px solid var(--primary)',
                background: auditResults ? 'rgba(0, 212, 255, 0.08)' : 'rgba(255,255,255,0.02)',
                color: auditResults ? 'var(--primary)' : 'var(--text-muted)',
                cursor: auditResults ? 'pointer' : 'not-allowed',
                fontSize: '11px',
                fontWeight: 800,
                letterSpacing: '0.5px',
                transition: 'all 0.2s',
                flexShrink: 0,
            }}
            onMouseOver={(e) => {
                if (auditResults) e.currentTarget.style.background = 'rgba(0,212,255,0.15)';
            }}
            onMouseOut={(e) => {
                if (auditResults) e.currentTarget.style.background = 'rgba(0,212,255,0.08)';
            }}
        >
            <FileDown size={14} />
            EXPORTAR PDF
        </button>
    );
};

export default ExportPDF;
