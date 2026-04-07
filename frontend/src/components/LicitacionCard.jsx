import React from 'react';
import { FileText, Calendar, Trash2, ChevronRight } from 'lucide-react';

const LicitacionCard = ({ licitacion, onSelect, onDelete }) => {
    return (
        <div 
            className="glass-panel" 
            onClick={() => onSelect(licitacion.id)} 
            style={{
                cursor: 'pointer',
                padding: '28px',
                borderRadius: 'var(--radius-xl)',
                display: 'flex',
                flexDirection: 'column',
                gap: '20px',
                minHeight: '260px',
                transition: 'all 0.5s cubic-bezier(0.23, 1, 0.32, 1)',
            }}
            onMouseOver={(e) => {
                e.currentTarget.style.transform = 'translateY(-8px)';
                e.currentTarget.style.borderColor = 'var(--border-active)';
                e.currentTarget.style.boxShadow = '0 20px 40px rgba(0,0,0,0.4)';
            }}
            onMouseOut={(e) => {
                e.currentTarget.style.transform = 'translateY(0)';
                e.currentTarget.style.borderColor = 'var(--border-glass)';
                e.currentTarget.style.boxShadow = 'none';
            }}
        >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ 
                    width: '48px', 
                    height: '48px', 
                    borderRadius: '12px', 
                    background: 'linear-gradient(135deg, var(--primary), var(--secondary))', 
                    display: 'flex', 
                    alignItems: 'center', 
                    justifyContent: 'center',
                    color: 'white',
                    fontWeight: 800,
                    fontSize: '20px',
                    boxShadow: '0 8px 16px rgba(59, 130, 246, 0.2)'
                }}>
                    {licitacion.name[0].toUpperCase()}
                </div>
                <button 
                   className="icon-btn" 
                   onClick={(e) => { e.stopPropagation(); onDelete(licitacion.id); }}
                   style={{ 
                       color: 'var(--text-muted)',
                       padding: '8px',
                       borderRadius: '8px',
                       transition: 'all 0.2s'
                   }}
                   onMouseOver={(e) => e.currentTarget.style.color = 'var(--error)'}
                   onMouseOut={(e) => e.currentTarget.style.color = 'var(--text-muted)'}
                >
                    <Trash2 size={18} />
                </button>
            </div>

            <div style={{ flex: 1 }}>
                <h3 style={{ 
                    fontSize: '20px', 
                    fontWeight: 700, 
                    marginBottom: '8px', 
                    color: 'white',
                    fontFamily: 'var(--font-heading)'
                }}>{licitacion.name}</h3>
                <div style={{ 
                    display: 'inline-block', 
                    padding: '4px 10px', 
                    borderRadius: '20px', 
                    background: 'rgba(59, 130, 246, 0.1)', 
                    color: 'var(--primary)', 
                    fontSize: '10px', 
                    fontWeight: 800,
                    textTransform: 'uppercase',
                    letterSpacing: '1px'
                }}>
                    Licitación Activa
                </div>
            </div>

            <div style={{ 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'space-between',
                paddingTop: '16px',
                borderTop: '1px solid rgba(255,255,255,0.05)'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '12px' }}>
                    <Calendar size={14} />
                    <span>{new Date(licitacion.updated_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}</span>
                </div>
                <div style={{ color: 'var(--primary)', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 600, fontSize: '13px' }}>
                    Abrir <ChevronRight size={16} />
                </div>
            </div>
            
            {/* Efecto de fondo sutil */}
            <div style={{
                position: 'absolute',
                bottom: '-20%',
                left: '-10%',
                width: '120px',
                height: '120px',
                background: 'var(--primary)',
                filter: 'blur(80px)',
                opacity: 0.05,
                zIndex: -1
            }}></div>
        </div>
    );
};


export default LicitacionCard;
