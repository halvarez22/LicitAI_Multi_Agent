import React from 'react';
import { MessageSquare, Info } from 'lucide-react';
import { API_BASE } from '../apiBase.js';

/**
 * Componente Tarjeta Forense: El bloque visual fundamental de LicitAI.
 * Recibe: ubicación (ej. página / fuente), sección (tipo de requisito o categoría) 
 * y textoLiteral (snippet o descripción principal). 
 */
const ForensicCard = ({ 
  ubicacion, 
  seccion, 
  textoLiteral, 
  isExpanded, 
  onClick, 
  onAskExpert, 
  isRisk,
  snippet,
  /** Zona de map-reduce (compliance); opcional */
  zonaOrigen,
  /** Lista API (administrativo|tecnico|formatos); para comparar con categoriaLlm */
  bucketKey,
  /** false si la zona se infirió del bucket (sin zona_origen en API) */
  zonaExplicita = true,
  /** Categoría asignada por el LLM; opcional */
  categoriaLlm,
  // Fase 4 Props
  sessionId,
  agentId,
  entityRef,
  companyId
}) => {
  const isDesechamiento = isRisk || seccion.includes('DESECHAMIENTO') || seccion.includes('ALERTA');

  const catDiffersFromBucket =
    categoriaLlm &&
    bucketKey &&
    String(categoriaLlm).toLowerCase().trim() !== String(bucketKey).toLowerCase().trim();
  
  const [feedbackStatus, setFeedbackStatus] = React.useState(null); // 'correct', 'incorrect', 'partial'
  const [correction, setCorrection] = React.useState('');
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [submitted, setSubmitted] = React.useState(false);

  const handleFeedback = async (type) => {
    setFeedbackStatus(type);
    if (type === 'correct') {
      submitToBackend(true, "");
    }
  };

  const submitToBackend = async (wasCorrect, userCorrection) => {
    setIsSubmitting(true);
    try {
      const payload = {
        session_id: sessionId,
        company_id: companyId || null,
        agent_id: agentId || 'unknown',
        pipeline_stage: 'audit',
        entity_type: 'requirement',
        entity_ref: entityRef || 'N/A',
        extracted_value: textoLiteral,
        user_correction: userCorrection,
        was_correct: wasCorrect,
        correction_type: wasCorrect ? null : 'value_error'
      };

      await fetch(`${API_BASE}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      setSubmitted(true);
    } catch (err) {
      console.error("Error sending feedback:", err);
    } finally {
      setIsSubmitting(false);
    }
  };
  
 return (
    <div 
      onClick={onClick}
      className={`forensic-card ${isExpanded ? 'expanded' : ''} ${isDesechamiento ? 'risk-card' : ''}`}
    >
      <div className="forensic-card-header">
        <span className="forensic-section-name">{seccion}</span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center', justifyContent: 'flex-end' }}>
          {zonaOrigen && (
            <span className="forensic-page-badge" style={{ background: 'rgba(0, 212, 255, 0.12)', border: '1px solid rgba(0,212,255,0.25)' }} title="Zona de extracción (map-reduce)">
              Zona: {zonaOrigen}
              {zonaExplicita === false ? ' · inferida' : ''}
            </span>
          )}
          {catDiffersFromBucket && (
            <span className="forensic-page-badge" style={{ background: 'rgba(255,255,255,0.06)' }} title="Categoría del modelo distinta a la lista de origen">
              Cat. LLM: {categoriaLlm}
            </span>
          )}
          {ubicacion && <span className="forensic-page-badge">📄 {ubicacion}</span>}
        </div>
      </div>
      
      <div className="forensic-main-text">
        {textoLiteral}
      </div>
      
      {isExpanded && (
        <div className="forensic-details-content">
          {(zonaOrigen || catDiffersFromBucket) && (
            <div className="forensic-detail-item">
              <div className="forensic-detail-label">TRAZA:</div>
              <div className="forensic-detail-value">
                {zonaOrigen && (
                  <div>
                    Zona de extracción: {zonaOrigen}
                    {zonaExplicita === false ? ' (inferida por lista de origen — dictamen legacy o sin estampar)' : ''}
                  </div>
                )}
                {catDiffersFromBucket && <div>Categoría (LLM): {categoriaLlm}</div>}
              </div>
            </div>
          )}
          <div className="forensic-detail-item">
            <div className="forensic-detail-label">UBICACIÓN:</div>
            <div className="forensic-detail-value">{ubicacion ? `Página ${ubicacion} del documento indexado.` : 'No especificada'}</div>
          </div>
          
          <div className="forensic-detail-item">
            <div className="forensic-detail-label">TEXTO LITERAL HALLADO EN DB:</div>
            <div className="forensic-literal-box">
              "{snippet || 'No se detalló el párrafo exacto, consulta al experto para más detalle.'}"
            </div>
          </div>

          {/* FASE 4: FEEDBACK PANEL */}
          <div style={{ marginTop: '15px', padding: '12px', background: 'rgba(255,255,255,0.03)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ fontSize: '10px', fontWeight: 900, marginBottom: '10px', color: 'var(--text-muted)' }}>CONTROL DE CALIDAD (HITL)</div>
            
            {submitted ? (
              <div style={{ fontSize: '12px', color: '#2ecc71', fontWeight: 700 }}>✅ Gracias por tu feedback.</div>
            ) : (
              <>
                <div style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
                  <button 
                    disabled={isSubmitting}
                    onClick={(e) => { e.stopPropagation(); handleFeedback('correct'); }}
                    style={{ flex: 1, padding: '8px', borderRadius: '8px', background: feedbackStatus === 'correct' ? '#2ecc71' : 'rgba(255,255,255,0.05)', border: 'none', color: '#fff', fontSize: '11px', cursor: 'pointer' }}
                  >
                    SÍ ES CORRECTO
                  </button>
                  <button 
                    disabled={isSubmitting}
                    onClick={(e) => { e.stopPropagation(); setFeedbackStatus('incorrect'); }}
                    style={{ flex: 1, padding: '8px', borderRadius: '8px', background: feedbackStatus === 'incorrect' ? '#e74c3c' : 'rgba(255,255,255,0.05)', border: 'none', color: '#fff', fontSize: '11px', cursor: 'pointer' }}
                  >
                    NO ES CORRECTO
                  </button>
                </div>

                {feedbackStatus === 'incorrect' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <textarea 
                      onClick={(e) => e.stopPropagation()}
                      value={correction}
                      onChange={(e) => setCorrection(e.target.value)}
                      placeholder="Escribe la corrección o detalle del error..."
                      style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.1)', color: '#fff', padding: '10px', borderRadius: '8px', fontSize: '11px', minHeight: '60px' }}
                    />
                    <button 
                      disabled={isSubmitting || !correction.trim()}
                      onClick={(e) => { e.stopPropagation(); submitToBackend(false, correction); }}
                      style={{ background: 'var(--primary)', color: '#fff', border: 'none', padding: '8px', borderRadius: '8px', fontSize: '11px', fontWeight: 700, cursor: 'pointer' }}
                    >
                      {isSubmitting ? 'ENVIANDO...' : 'ENVIAR CORRECCIÓN'}
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
          
          <button 
            className="forensic-expert-btn"
            style={{ marginTop: '10px' }}
            onClick={(e) => { 
                e.stopPropagation(); 
                onAskExpert && onAskExpert(`Dame más detalles sobre el requisito: ${textoLiteral}`); 
            }}
          >
            <MessageSquare size={14} /> CONSULTAR AL EXPERTO SOBRE ESTE PUNTO
          </button>
        </div>
      )}
    </div>
  );
};

export default ForensicCard;
