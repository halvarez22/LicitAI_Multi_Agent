import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { API_BASE } from '../apiBase.js';

/**
 * GoNoGoPanel — Pantalla de decisión del Semáforo Go/No-Go.
 * Cada brecha es accionable: el usuario puede capturar el dato faltante
 * directamente desde aquí, actualizar el perfil maestro y recalcular el semáforo.
 */
const GoNoGoPanel = ({
    goNoGoResult,
    sessionId,
    companyId,
    companyData = {},
    onDecision,
    overrideTimestamp = null,
    onAskExpert = null,
}) => {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [localResult, setLocalResult] = useState(goNoGoResult);
    const [savedFields, setSavedFields] = useState({});
    const [recalculating, setRecalculating] = useState(false);

    // Tras «Actualizar análisis» el padre envía un nuevo goNoGoResult; sin esto la UI
    // queda congelada en la primera carga (p. ej. 471 brechas aunque el backend ya tenga 394).
    useEffect(() => {
        if (goNoGoResult) {
            setLocalResult(goNoGoResult);
        }
    }, [goNoGoResult]);

    if (!localResult) return null;

    const {
        semaforo = 'GREEN',
        brechas = [],
        total_knockouts = 0,
        total_brechas = 0,
        brechas_atenuadas_por_evidencia_sesion = 0,
        score_cumplimiento_tecnico = null,
        score_detalle = [],
    } = localResult;

    const knockouts = brechas.filter(b => b.is_knockout);
    const normales = brechas.filter(b => !b.is_knockout);

    const SEMAFORO_CONFIG = {
        RED:    { color: '#e74c3c', bg: 'rgba(231,76,60,0.10)',  border: 'rgba(231,76,60,0.35)',  label: '🔴 Alto Riesgo — Causas de Descalificación Detectadas' },
        YELLOW: { color: '#f39c12', bg: 'rgba(243,156,18,0.10)', border: 'rgba(243,156,18,0.35)', label: '🟡 Riesgo Moderado — Brechas a Revisar' },
        GREEN:  { color: '#2ecc71', bg: 'rgba(46,204,113,0.10)', border: 'rgba(46,204,113,0.35)', label: '🟢 Sin Brechas Detectadas' },
    };
    const cfg = SEMAFORO_CONFIG[semaforo] || SEMAFORO_CONFIG.GREEN;

    // Guarda un campo en el master_profile de la empresa y recalcula el semáforo
    const handleSaveField = async (fieldKey, value, brechaId) => {
        if (!companyId || !value?.trim()) return;
        try {
            // 1. Obtener perfil actual
            const res = await axios.get(`${API_BASE}/companies/${encodeURIComponent(companyId)}`);
            const current = res.data?.data || {};
            const currentProfile = current.master_profile || {};

            // 2. Actualizar el campo
            const updatedProfile = { ...currentProfile, [fieldKey]: value.trim() };
            await axios.post(`${API_BASE}/companies/`, {
                ...current,
                id: companyId,
                master_profile: updatedProfile,
            });

            setSavedFields(prev => ({ ...prev, [brechaId]: true }));

            // 3. Recalcular semáforo relanzando el pipeline en modo reanudación
            setRecalculating(true);
            try {
                const rerunRes = await axios.post(
                    `${API_BASE}/go-no-go/${encodeURIComponent(sessionId)}/authorize`,
                    {
                        user_override: false,
                        brechas_autorizadas: [],
                        company_id: companyId,
                        company_data: { ...companyData, master_profile: updatedProfile },
                        recalculate_only: true,
                    }
                );
                if (rerunRes.data?.data?.go_no_go_result) {
                    setLocalResult(rerunRes.data.data.go_no_go_result);
                }
            } catch (_) {
                // Si el recálculo falla, no bloqueamos — el dato ya se guardó
            } finally {
                setRecalculating(false);
            }
        } catch (err) {
            console.error('Error guardando campo:', err);
        }
    };

    const handleDecision = async (userOverride) => {
        setLoading(true);
        setError(null);
        try {
            const brechasAutorizadas = userOverride ? brechas.map(b => b.id) : [];
            const res = await axios.post(
                `${API_BASE}/go-no-go/${encodeURIComponent(sessionId)}/authorize`,
                {
                    user_override: userOverride,
                    brechas_autorizadas: brechasAutorizadas,
                    company_id: companyId || null,
                    company_data: companyData,
                    resume_generation: true,
                }
            );
            if (res.data?.success) {
                onDecision && onDecision(res.data?.data?.job_id || null);
            } else {
                setError(res.data?.message || 'Error al procesar la decisión.');
            }
        } catch (err) {
            setError(err?.response?.data?.message || err.message || 'Error de red.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div style={{
            padding: '20px', background: 'rgba(255,255,255,0.02)',
            borderRadius: '20px', border: '1px solid rgba(255,255,255,0.07)',
            maxHeight: '80vh', overflowY: 'auto', scrollbarWidth: 'thin',
        }}>
            {/* Encabezado */}
            <div style={{ marginBottom: '20px' }}>
                <h3 style={{ fontSize: '15px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '4px' }}>
                    Semáforo Go / No-Go
                </h3>
                <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Completa los datos faltantes para avanzar — cada campo que llenes mejora tu score
                </p>
            </div>

            {/* Override previo */}
            {overrideTimestamp && (
                <div style={{
                    marginBottom: '16px', padding: '10px 14px', borderRadius: '10px',
                    background: 'rgba(255,193,7,0.08)', border: '1px solid rgba(255,193,7,0.3)',
                    fontSize: '11px', color: 'rgba(255,255,255,0.75)',
                }}>
                    ⚠️ Autorizaste continuar con brechas el {new Date(overrideTimestamp).toLocaleString('es-MX')}.
                </div>
            )}

            {/* Semáforo */}
            <div style={{
                marginBottom: '20px', padding: '16px', borderRadius: '14px',
                background: cfg.bg, border: `1px solid ${cfg.border}`,
            }}>
                <div style={{ fontSize: '14px', fontWeight: 900, color: cfg.color, marginBottom: '8px' }}>
                    {recalculating ? '⏳ Recalculando semáforo…' : cfg.label}
                </div>
                <div style={{ display: 'flex', gap: '20px', fontSize: '12px', color: 'rgba(255,255,255,0.7)', flexWrap: 'wrap' }}>
                    <span>Brechas totales: <strong style={{ color: '#fff' }}>{total_brechas}</strong></span>
                    <span>Knock-outs: <strong style={{ color: '#e74c3c' }}>{total_knockouts}</strong></span>
                    {score_cumplimiento_tecnico !== null && (
                        <span>Score: <strong style={{ color: cfg.color }}>{score_cumplimiento_tecnico}%</strong></span>
                    )}
                </div>
                {Number(brechas_atenuadas_por_evidencia_sesion) > 0 && (
                    <div style={{
                        marginTop: '12px', padding: '10px 12px', borderRadius: '10px',
                        fontSize: '11px', lineHeight: 1.45,
                        background: 'rgba(46,204,113,0.08)', border: '1px solid rgba(46,204,113,0.28)',
                        color: 'rgba(255,255,255,0.88)',
                    }}>
                        <strong style={{ color: '#2ecc71' }}>Evidencia de sesión</strong>
                        {' — '}
                        Brechas atenuadas respecto al solo perfil de empresa:{' '}
                        <strong style={{ color: '#2ecc71' }}>{brechas_atenuadas_por_evidencia_sesion}</strong>
                        <span style={{ display: 'block', marginTop: '4px', color: 'rgba(255,255,255,0.55)', fontSize: '10px' }}>
                            Son requisitos que seguirían como brecha si solo se usara el catálogo maestro; los documentos cargados en esta sesión aportan datos que los cubren o acreditan.
                        </span>
                    </div>
                )}
            </div>

            {/* Score de cumplimiento técnico */}
            {score_cumplimiento_tecnico !== null && (
                <ScoreBar score={score_cumplimiento_tecnico} />
            )}

            {/* Brechas knock-out */}
            {knockouts.length > 0 && (
                <div style={{ marginBottom: '16px' }}>
                    <div style={{ fontSize: '10px', fontWeight: 900, color: '#e74c3c', marginBottom: '8px', letterSpacing: '0.5px' }}>
                        ⛔ CAUSAS DE DESCALIFICACIÓN ({knockouts.length})
                    </div>
                    {knockouts.map(b => (
                        <BrechaCard key={b.id} brecha={b} isKnockout isSaved={savedFields[b.id]} onSave={handleSaveField} onAskExpert={onAskExpert} />
                    ))}
                </div>
            )}

            {/* Brechas normales agrupadas por categoría */}
            {semaforo !== 'GREEN' && normales.length > 0 && (
                <BrechasAgrupadas brechas={normales} savedFields={savedFields} onSave={handleSaveField} onAskExpert={onAskExpert} />
            )}

            {/* Error */}
            {error && (
                <div style={{ marginBottom: '12px', padding: '10px', borderRadius: '10px', background: 'rgba(231,76,60,0.1)', border: '1px solid rgba(231,76,60,0.3)', fontSize: '12px', color: '#e74c3c' }}>
                    {error}
                </div>
            )}

            {/* Botones de decisión */}
            <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                {semaforo !== 'GREEN' ? (
                    <>
                        <button onClick={() => handleDecision(true)} disabled={loading}
                            style={{ flex: 1, padding: '12px', borderRadius: '12px', background: 'rgba(243,156,18,0.15)', border: '1px solid rgba(243,156,18,0.4)', color: '#f39c12', fontWeight: 800, fontSize: '12px', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1 }}>
                            {loading ? '⏳ Procesando…' : '⚠️ Continuar asumiendo el riesgo'}
                        </button>
                        <button onClick={() => handleDecision(false)} disabled={loading}
                            style={{ flex: 1, padding: '12px', borderRadius: '12px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.7)', fontWeight: 800, fontSize: '12px', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1 }}>
                            🛑 Detener y revisar
                        </button>
                    </>
                ) : (
                    <button onClick={() => handleDecision(true)} disabled={loading}
                        style={{ flex: 1, padding: '12px', borderRadius: '12px', background: 'rgba(46,204,113,0.15)', border: '1px solid rgba(46,204,113,0.4)', color: '#2ecc71', fontWeight: 800, fontSize: '12px', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1 }}>
                        {loading ? '⏳ Procesando…' : '✅ Continuar'}
                    </button>
                )}
            </div>
        </div>
    );
};

/* ─── Barra de score ─── */
const ScoreBar = ({ score }) => (
    <div style={{ marginBottom: '16px', padding: '12px 14px', borderRadius: '12px', background: 'rgba(0,212,255,0.05)', border: '1px solid rgba(0,212,255,0.15)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '10px', fontWeight: 900, color: 'var(--primary)', letterSpacing: '0.5px' }}>📊 SCORE DE CUMPLIMIENTO</span>
            <span style={{ fontSize: '16px', fontWeight: 900, color: score >= 70 ? '#2ecc71' : score >= 40 ? '#f39c12' : '#e74c3c' }}>{score}%</span>
        </div>
        <div style={{ height: '6px', borderRadius: '3px', background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
            <div style={{ height: '100%', borderRadius: '3px', width: `${score}%`, background: score >= 70 ? '#2ecc71' : score >= 40 ? '#f39c12' : '#e74c3c', transition: 'width 0.5s ease' }} />
        </div>
    </div>
);

/* ─── Tarjeta de brecha accionable ─── */
const FIELD_MAP = {
    certificacion_faltante:    { key: 'certificaciones',      placeholder: 'Ej: ISO 9001, ASIS, STPS…' },
    capital_insuficiente:      { key: 'capital_contable',     placeholder: 'Ej: $5,000,000 MXN' },
    experiencia_insuficiente:  { key: 'anos_experiencia',     placeholder: 'Ej: 10 años, 3 contratos similares' },
    documento_faltante:        { key: 'documentos_adicionales', placeholder: 'Describe el documento o sube el archivo' },
    requisito_no_acreditado:   { key: 'requisitos_adicionales', placeholder: 'Captura el dato o valor requerido' },
};

const BrechaCard = ({ brecha, isKnockout = false, isSaved = false, onSave, accentColor, onAskExpert }) => {
    const [inputValue, setInputValue] = useState('');
    const [expanded, setExpanded] = useState(false);
    const [saving, setSaving] = useState(false);

    const fieldInfo = FIELD_MAP[brecha.categoria] || FIELD_MAP.requisito_no_acreditado;
    const color = accentColor || (isKnockout ? '#e74c3c' : '#f39c12');
    const accentBg = isKnockout ? 'rgba(231,76,60,0.06)' : 'rgba(255,255,255,0.03)';
    const accentBorder = isKnockout ? 'rgba(231,76,60,0.25)' : 'rgba(255,255,255,0.08)';

    const handleSave = async () => {
        if (!inputValue.trim()) return;
        setSaving(true);
        await onSave(fieldInfo.key, inputValue, brecha.id);
        setSaving(false);
    };

    return (
        <div style={{
            marginBottom: '4px', borderRadius: '10px',
            background: isSaved ? 'rgba(46,204,113,0.06)' : accentBg,
            border: `1px solid ${isSaved ? 'rgba(46,204,113,0.3)' : accentBorder}`,
            borderLeft: `3px solid ${isSaved ? '#2ecc71' : color}`,
            overflow: 'hidden', transition: 'border-color 0.3s ease',
        }}>
            {/* Cabecera clickeable */}
            <div
                onClick={() => setExpanded(e => !e)}
                style={{ padding: '10px 14px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}
            >
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '10px', fontWeight: 800, color: isSaved ? '#2ecc71' : color, marginBottom: '3px' }}>
                        {isSaved ? '✅ COMPLETADO' : brecha.zona_origen}
                    </div>
                    <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.85)', lineHeight: 1.4 }}>
                        {brecha.descripcion}
                    </div>
                </div>
                <span style={{ fontSize: '10px', color: 'var(--text-muted)', flexShrink: 0, marginTop: '2px' }}>
                    {expanded ? '▲' : '▼'}
                </span>
            </div>

            {/* Detalle expandible + campo de captura */}
            {expanded && (
                <div style={{ padding: '0 14px 12px', borderTop: `1px solid ${accentBorder}` }}>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '10px', marginBottom: '4px' }}>
                        <strong style={{ color: 'rgba(255,255,255,0.6)' }}>Requisito en bases:</strong>
                    </div>
                    <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.7)', marginBottom: '10px', lineHeight: 1.5, fontStyle: 'italic' }}>
                        "{brecha.requisito_bases}"
                    </div>

                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                        <strong style={{ color: 'rgba(255,255,255,0.6)' }}>Valor actual en tu perfil:</strong>{' '}
                        <span style={{ color: brecha.valor_empresa ? '#2ecc71' : '#e74c3c' }}>
                            {brecha.valor_empresa || 'No registrado'}
                        </span>
                    </div>

                    {!isSaved && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            {onAskExpert && (
                                <button
                                    onClick={() => onAskExpert(
                                        `Explícame detalladamente qué es el siguiente requisito de estas bases de licitación y qué documentos o información necesito para acreditarlo: "${brecha.requisito_bases}"`
                                    )}
                                    style={{
                                        padding: '7px 12px', borderRadius: '8px', width: '100%',
                                        background: 'rgba(0,212,255,0.08)', border: '1px solid rgba(0,212,255,0.25)',
                                        color: 'var(--primary)', fontWeight: 700, fontSize: '11px',
                                        cursor: 'pointer', textAlign: 'left',
                                    }}
                                >
                                    💬 Preguntar al experto sobre este requisito
                                </button>
                            )}
                            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                            <input
                                type="text"
                                value={inputValue}
                                onChange={e => setInputValue(e.target.value)}
                                onKeyDown={e => e.key === 'Enter' && handleSave()}
                                placeholder={fieldInfo.placeholder}
                                style={{
                                    flex: 1, padding: '8px 12px', borderRadius: '8px',
                                    background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
                                    color: '#fff', fontSize: '12px', outline: 'none',
                                }}
                            />
                            <button
                                onClick={handleSave}
                                disabled={saving || !inputValue.trim()}
                                style={{
                                    padding: '8px 14px', borderRadius: '8px', flexShrink: 0,
                                    background: inputValue.trim() ? `rgba(255,255,255,0.1)` : 'rgba(255,255,255,0.04)',
                                    border: `1px solid ${inputValue.trim() ? color : 'rgba(255,255,255,0.1)'}`,
                                    color: inputValue.trim() ? color : 'rgba(255,255,255,0.3)',
                                    fontWeight: 800, fontSize: '11px',
                                    cursor: inputValue.trim() && !saving ? 'pointer' : 'not-allowed',
                                }}
                            >
                                {saving ? '⏳' : '💾 Guardar'}
                            </button>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

/* ─── Grupos de brechas por categoría ─── */
const GRUPOS = [
    {
        key: 'documento_faltante',
        label: 'Documentos Faltantes',
        icon: '📄',
        color: '#e67e22',
    },
    {
        key: 'requisito_no_acreditado',
        label: 'Requisitos No Acreditados',
        icon: '📋',
        color: '#f39c12',
    },
    {
        key: 'certificacion_faltante',
        label: 'Certificaciones Faltantes',
        icon: '🏅',
        color: '#9b59b6',
    },
    {
        key: 'experiencia_insuficiente',
        label: 'Experiencia Insuficiente',
        icon: '📊',
        color: '#3498db',
    },
    {
        key: 'capital_insuficiente',
        label: 'Capital Insuficiente',
        icon: '💰',
        color: '#e74c3c',
    },
];

const BrechasAgrupadas = ({ brechas, savedFields, onSave, onAskExpert }) => {
    const [expandedGroups, setExpandedGroups] = useState({});

    const toggleGroup = (key) => setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }));

    // Agrupar brechas por categoría
    const grupos = GRUPOS.map(g => ({
        ...g,
        items: brechas.filter(b => b.categoria === g.key),
    })).filter(g => g.items.length > 0);

    // Categorías no contempladas en GRUPOS
    const categoriasConocidas = new Set(GRUPOS.map(g => g.key));
    const otros = brechas.filter(b => !categoriasConocidas.has(b.categoria));
    if (otros.length > 0) {
        grupos.push({ key: 'otros', label: 'Otros Requisitos', icon: '⚠️', color: '#f39c12', items: otros });
    }

    const totalSaved = brechas.filter(b => savedFields[b.id]).length;

    return (
        <div style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '10px', fontWeight: 900, color: '#f39c12', marginBottom: '10px', letterSpacing: '0.5px', display: 'flex', justifyContent: 'space-between' }}>
                <span>⚠️ DATOS FALTANTES — completa para mejorar tu score ({brechas.length})</span>
                {totalSaved > 0 && <span style={{ color: '#2ecc71' }}>✅ {totalSaved} completados</span>}
            </div>

            {grupos.map(grupo => {
                const isOpen = expandedGroups[grupo.key];
                const savedInGroup = grupo.items.filter(b => savedFields[b.id]).length;
                const allDone = savedInGroup === grupo.items.length;

                return (
                    <div key={grupo.key} style={{ marginBottom: '8px', borderRadius: '12px', border: `1px solid ${allDone ? 'rgba(46,204,113,0.3)' : 'rgba(255,255,255,0.08)'}`, overflow: 'hidden' }}>
                        {/* Cabecera del grupo */}
                        <div
                            onClick={() => toggleGroup(grupo.key)}
                            style={{
                                padding: '10px 14px', cursor: 'pointer',
                                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                background: allDone ? 'rgba(46,204,113,0.06)' : 'rgba(255,255,255,0.03)',
                            }}
                        >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ fontSize: '14px' }}>{grupo.icon}</span>
                                <span style={{ fontSize: '12px', fontWeight: 800, color: allDone ? '#2ecc71' : grupo.color }}>
                                    {grupo.label}
                                </span>
                                <span style={{
                                    fontSize: '10px', padding: '2px 7px', borderRadius: '20px',
                                    background: allDone ? 'rgba(46,204,113,0.15)' : `rgba(255,255,255,0.08)`,
                                    color: allDone ? '#2ecc71' : 'rgba(255,255,255,0.6)',
                                    fontWeight: 700,
                                }}>
                                    {savedInGroup > 0 ? `${savedInGroup}/${grupo.items.length}` : grupo.items.length}
                                </span>
                            </div>
                            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{isOpen ? '▲' : '▼'}</span>
                        </div>

                        {/* Ítems del grupo */}
                        {isOpen && (
                            <div style={{ padding: '8px', borderTop: '1px solid rgba(255,255,255,0.05)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                {grupo.items.map(b => (
                                    <BrechaCard key={b.id} brecha={b} isSaved={savedFields[b.id]} onSave={onSave} accentColor={grupo.color} onAskExpert={onAskExpert} />
                                ))}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
};

export default GoNoGoPanel;
