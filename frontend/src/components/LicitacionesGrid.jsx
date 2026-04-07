import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Plus, Search, Loader2, Info } from 'lucide-react';
import LicitacionCard from './LicitacionCard';
import CompaniesManager from './CompaniesManager';
import { LICITAI_APP_VERSION } from '../appVersion.js';
import { API_BASE } from '../apiBase.js';

const LicitacionesGrid = ({ onSelectSession }) => {
    const [licitaciones, setLicitaciones] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState("");
    const [isCreating, setIsCreating] = useState(false);
    const [newName, setNewName] = useState("");

    const fetchLicitaciones = async () => {
        setLoading(true);
        try {
            const res = await axios.get(`${API_BASE}/sessions`);
            if (res.data.success) {
                // Ordenar por fecha de actualización descendente
                const sorted = res.data.data.licitaciones.sort((a, b) => 
                    new Date(b.updated_at) - new Date(a.updated_at)
                );
                setLicitaciones(sorted);
            }
        } catch (err) {
            console.error("Error cargando licitaciones:", err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchLicitaciones();
    }, []);

    const handleCreate = async (e) => {
        if (e) e.preventDefault();
        if (!newName.trim()) return;
        
        try {
            const res = await axios.post(`${API_BASE}/sessions/create?name=${encodeURIComponent(newName)}`);
            if (res.data.success) {
                const newId = res.data.data.session_id;
                setNewName("");
                setIsCreating(false);
                // Ir directamente a la nueva licitación para emular fluidez de NotebookLM
                onSelectSession(newId);
            } else {
                alert(res.data.message);
            }
        } catch (err) {
            alert("Error al crear la licitación.");
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm("¿Seguro que deseas eliminar esta licitación y todos sus documentos?")) return;
        try {
            await axios.delete(`${API_BASE}/sessions/${id}`);
            fetchLicitaciones();
        } catch (err) {
            alert("Error al eliminar.");
        }
    };

    const [view, setView] = useState("licitaciones"); // "licitaciones" o "empresas"
    const filtered = licitaciones.filter(l => l.name.toLowerCase().includes(searchTerm.toLowerCase()));

    return (
        <div className="landing-container" style={{ padding: '60px 40px', maxWidth: '1280px', margin: '0 auto', animation: 'fadeIn 0.6s ease-out' }}>
            <div style={{ textAlign: 'center', marginBottom: '40px' }}>
                <h1 style={{ 
                    fontSize: '48px', 
                    fontWeight: 900, 
                    marginBottom: '16px', 
                    fontFamily: 'var(--font-heading)',
                    background: 'linear-gradient(to right, #fff, #94a3b8)', 
                    WebkitBackgroundClip: 'text', 
                    WebkitTextFillColor: 'transparent',
                    letterSpacing: '-1.5px'
                }}>
                    Qlicitaciones <span style={{ color: 'var(--primary)', WebkitTextFillColor: 'var(--primary)' }}>Empresas</span>
                </h1>
                
                {/* Tab Switcher Estilo Moderno */}
                <div style={{ 
                    display: 'inline-flex', 
                    background: 'rgba(255,255,255,0.03)', 
                    padding: '6px', 
                    borderRadius: '14px', 
                    border: '1px solid var(--border-glass)',
                    marginTop: '24px'
                }}>
                    <button 
                        onClick={() => setView("licitaciones")}
                        style={{ 
                            padding: '10px 24px', 
                            borderRadius: '10px', 
                            border: 'none', 
                            background: view === "licitaciones" ? 'var(--primary)' : 'transparent',
                            color: view === "licitaciones" ? 'white' : 'var(--text-muted)',
                            fontWeight: 700,
                            fontSize: '13px',
                            cursor: 'pointer',
                            transition: 'all 0.3s'
                        }}
                    >
                        LICITACIONES
                    </button>
                    <button 
                        onClick={() => setView("empresas")}
                        style={{ 
                            padding: '10px 24px', 
                            borderRadius: '10px', 
                            border: 'none', 
                            background: view === "empresas" ? 'var(--secondary)' : 'transparent',
                            color: view === "empresas" ? 'white' : 'var(--text-muted)',
                            fontWeight: 700,
                            fontSize: '13px',
                            cursor: 'pointer',
                            transition: 'all 0.3s'
                        }}
                    >
                        EMPRESAS
                    </button>
                </div>
                <p
                    style={{
                        marginTop: '20px',
                        fontSize: '13px',
                        fontWeight: 700,
                        letterSpacing: '2px',
                        color: 'var(--primary)',
                        fontFamily: 'monospace',
                    }}
                    title="Si no coincide tras actualizar, fuerza recarga (Ctrl+F5) o reconstruye el contenedor frontend."
                >
                    LicitAI v{LICITAI_APP_VERSION}
                </p>
            </div>

            {view === "licitaciones" ? (
                <>
                    <div style={{ marginBottom: '48px', position: 'relative', maxWidth: '800px', margin: '0 auto 48px auto' }}>
                        <Search style={{ position: 'absolute', left: '20px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} size={20} />
                        <input 
                            type="text"
                            placeholder="Buscar licitación por nombre..."
                            className="glass-panel"
                            style={{ 
                                width: '100%', 
                                padding: '20px 20px 20px 60px', 
                                borderRadius: '16px',
                                background: 'rgba(255,255,255,0.03)',
                                border: '1px solid var(--border-glass)',
                                color: 'white',
                                fontSize: '18px',
                                outline: 'none',
                                transition: 'box-shadow 0.3s'
                            }}
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                    </div>

                    {loading ? (
                        <div style={{ display: 'flex', justifyContent: 'center', padding: '100px' }}>
                            <Loader2 className="animate-spin" size={48} color="var(--primary)" />
                        </div>
                    ) : (
                        <div style={{ 
                            display: 'grid', 
                            gridTemplateColumns: 'repeat(4, 1fr)', 
                            gap: '24px' 
                        }}>
                            {/* Tarjeta de Creación Estilo NotebookLM */}
                            {!searchTerm && (
                                <div 
                                    className="glass-panel" 
                                    onClick={() => setIsCreating(true)}
                                    style={{
                                        cursor: 'pointer',
                                        padding: '32px',
                                        borderRadius: 'var(--radius-l)',
                                        border: '2px dashed var(--border-glass)',
                                        background: 'rgba(59, 130, 246, 0.03)',
                                        display: 'flex',
                                        flexDirection: 'column',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        gap: '16px',
                                        transition: 'all 0.3s ease',
                                        height: '240px'
                                    }}
                                    onMouseOver={(e) => {
                                        e.currentTarget.style.borderColor = 'var(--primary)';
                                        e.currentTarget.style.background = 'rgba(59, 130, 246, 0.08)';
                                    }}
                                    onMouseOut={(e) => {
                                        e.currentTarget.style.borderColor = 'var(--border-glass)';
                                        e.currentTarget.style.background = 'rgba(59, 130, 246, 0.03)';
                                    }}
                                >
                                    <div style={{ 
                                        width: '56px', 
                                        height: '56px', 
                                        borderRadius: '50%', 
                                        background: 'var(--primary)', 
                                        display: 'flex', 
                                        alignItems: 'center', 
                                        justifyContent: 'center',
                                        color: 'white',
                                        boxShadow: '0 0 20px var(--primary-glow)'
                                    }}>
                                        <Plus size={32} strokeWidth={3} />
                                    </div>
                                    <span style={{ fontSize: '18px', fontWeight: 700, color: '#fff' }}>Nueva Licitación</span>
                                    <span style={{ fontSize: '13px', color: 'var(--text-muted)', textAlign: 'center' }}>Define un nuevo espacio de auditoría</span>
                                </div>
                            )}

                            {filtered.map(l => (
                                <LicitacionCard key={l.id} licitacion={l} onSelect={onSelectSession} onDelete={handleDelete} />
                            ))}
                        </div>
                    )}
                </>
            ) : (
                <CompaniesManager />
            )}

            {isCreating && (
                <div style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'rgba(0,0,0,0.85)',
                    backdropFilter: 'blur(12px)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 2000,
                    animation: 'fadeIn 0.3s ease'
                }}>
                    <div className="glass-panel" style={{ 
                        padding: '40px', 
                        width: '450px', 
                        borderRadius: '24px',
                        border: '1px solid var(--border-active)',
                        boxShadow: '0 20px 50px rgba(0,0,0,0.5)'
                    }}>
                        <h2 style={{ fontSize: '24px', fontWeight: 800, marginBottom: '24px', fontFamily: 'var(--font-heading)' }}>Nombre del Workspace</h2>
                        <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                            <input 
                                autoFocus
                                type="text" 
                                placeholder="Ej: ISSSTE Vigilancia 2024"
                                style={{ 
                                    padding: '16px', 
                                    background: 'rgba(0,0,0,0.3)', 
                                    border: '1px solid var(--border-glass)', 
                                    borderRadius: '12px', 
                                    color: 'white',
                                    fontSize: '16px',
                                    outline: 'none'
                                }}
                                value={newName}
                                onChange={(e) => setNewName(e.target.value)}
                            />
                            <div style={{ display: 'flex', gap: '16px' }}>
                                <button type="button" className="btn-secondary" onClick={() => setIsCreating(false)} style={{ 
                                    flex: 1, 
                                    background: 'rgba(255,255,255,0.05)', 
                                    border: '1px solid var(--border-glass)',
                                    color: 'white',
                                    padding: '12px',
                                    borderRadius: '8px',
                                    cursor: 'pointer'
                                }}>Cancelar</button>
                                <button type="submit" className="btn-primary" style={{ flex: 1, padding: '12px' }}>Crear Licitación</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};


export default LicitacionesGrid;
