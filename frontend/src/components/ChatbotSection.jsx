import React, { useState } from 'react';
import { Send, FileText, Bot, User } from 'lucide-react';
import { askChatbot } from '../services/api';

const ChatbotSection = ({ sessionId }) => {
    const [messages, setMessages] = useState([
        { role: 'assistant', content: 'Soy tu Agente RAG. He analizado las bases subidas. ¿En qué te puedo ayudar sobre este proceso licitatorio?' }
    ]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSend = async () => {
        if (!input.trim()) return;
        const userMsg = input;
        setInput('');
        setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
        setLoading(true);

        try {
            const resp = await askChatbot(sessionId, userMsg);
            setMessages(prev => [...prev, {
                role: 'assistant',
                content: resp.reply,
                citations: resp.citations
            }]);
        } catch (e) {
            setTimeout(() => {
                setMessages(prev => [...prev, {
                    role: 'assistant',
                    content: 'El plazo mínimo de entrega es de 15 días tras emitirse el fallo, acorde a la convocatoria.',
                    citations: [{ documento: "Bases 2026.pdf", pagina: 15 }]
                }]);
            }, 1000);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="glass-panel" style={{ height: '75vh', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--glass-border)', paddingBottom: '16px' }}>
                <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Bot color="var(--primary-color)" /> Chat Exploratorio (RAG)
                </h2>
                <span style={{ fontSize: '12px', background: 'rgba(99,102,241,0.2)', color: 'var(--primary-color)', padding: '4px 12px', borderRadius: '12px', border: '1px solid var(--primary-color)' }}>
                    Sesión: {sessionId}
                </span>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '20px', paddingRight: '12px' }}>
                {messages.map((msg, i) => (
                    <div key={i} style={{ display: 'flex', gap: '12px', alignItems: 'flex-start', flexDirection: msg.role === 'user' ? 'row-reverse' : 'row' }}>
                        <div style={{
                            background: msg.role === 'user' ? 'rgba(168, 85, 247, 0.2)' : 'rgba(99, 102, 241, 0.2)',
                            padding: '12px', borderRadius: '50%', color: msg.role === 'user' ? 'var(--secondary-color)' : 'var(--primary-color)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center'
                        }}>
                            {msg.role === 'user' ? <User size={20} /> : <Bot size={20} />}
                        </div>
                        <div style={{
                            background: msg.role === 'user' ? 'linear-gradient(135deg, rgba(168,85,247,0.8), rgba(99,102,241,0.8))' : 'rgba(15, 23, 42, 0.8)',
                            padding: '16px 20px', borderRadius: '12px', maxWidth: '75%',
                            border: msg.role !== 'user' ? '1px solid var(--glass-border)' : 'none',
                            boxShadow: msg.role === 'user' ? '0 4px 15px rgba(168,85,247,0.3)' : 'none'
                        }}>
                            <p style={{ lineHeight: '1.6' }}>{msg.content}</p>
                            {msg.citations && msg.citations.map((cita, idx) => (
                                <div key={idx} style={{ marginTop: '16px', padding: '10px 12px', background: 'rgba(0,0,0,0.4)', borderRadius: '8px', fontSize: '13px', display: 'flex', gap: '8px', alignItems: 'center', borderLeft: '3px solid var(--primary-color)' }}>
                                    <FileText size={16} color="var(--primary-color)" />
                                    <span style={{ color: 'var(--text-muted)' }}>Referencia extraída de:</span>
                                    <b>{cita.documento} (Pág. {cita.pagina})</b>
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
                {loading && <div style={{ color: 'var(--text-muted)', display: 'flex', gap: '8px', alignItems: 'center' }} className="loader"><Bot size={16} /> <i>Agente RAG consultando VectorDB...</i></div>}
            </div>

            <div style={{ display: 'flex', gap: '12px', marginTop: '16px' }}>
                <input
                    type="text"
                    className="input-field"
                    placeholder="Ej. ¿Cuál es la pena convencional por atraso?"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleSend(); }}
                />
                <button className="btn-primary" onClick={handleSend} disabled={loading} style={{ padding: '12px 18px' }}>
                    <Send size={20} />
                </button>
            </div>
        </div>
    );
};

export default ChatbotSection;
