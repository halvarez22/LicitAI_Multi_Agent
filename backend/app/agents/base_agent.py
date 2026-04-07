from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from app.agents.mcp_context import MCPContextManager

class BaseAgent(ABC):
    """Clase base abstracta para todos los agentes del sistema Licitaciones AI"""
    
    def __init__(self, agent_id: str, name: str, description: str, context_manager: MCPContextManager):
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.context_manager = context_manager
        
    @abstractmethod
    async def process(self, session_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Método principal de ejecución del agente.
        Debe recuperar el contexto usando self.context_manager,
        ejecutar su lógica específica (llamar al LLM, herramientas, etc.),
        y actualizar el estado.
        """
        pass

    async def get_state(self, session_id: str) -> Optional[Dict]:
        """Obtiene el estado interno del agente desde la memoria."""
        return await self.context_manager.memory.get_agent_state(self.agent_id, session_id)

    async def save_state(self, session_id: str, state_data: Dict) -> bool:
        """Guarda el estado del agente en la memoria persistente."""
        return await self.context_manager.memory.save_agent_state(self.agent_id, session_id, state_data)

    async def smart_search(self, session_id: str, query: str, n_results: int = 15, expand_context: bool = True, vector_db: Optional[Any] = None) -> str:
        """
        Realiza una búsqueda inteligente 'tirando del hilo'.
        Si expand_context=True, busca fragmentos adyacentes de las mismas páginas encontradas.
        
        Args:
            session_id: ID de la sesión.
            query: Texto a buscar.
            n_results: Número de fragmentos iniciales.
            expand_context: Si True, recupera páginas completas donde hubo hits.
            vector_db: Cliente vectorial opcional (para inyección de dependencias).
        """
        if not vector_db:
            from app.services.vector_service import VectorDbServiceClient
            vector_db = VectorDbServiceClient()
        
        # 1. Búsqueda Vectorial Inicial
        print(f"DEBUG: SmartSearch Query -> {query}")
        initial_res = vector_db.query_texts(session_id, query, n_results=n_results)
        docs = initial_res.get("documents", [])
        metadatas = initial_res.get("metadatas", [])
        
        print(f"DEBUG: SmartSearch Inicial encontró {len(docs)} fragmentos.")
        if not docs:
            return ""

        if not expand_context:
            return "\n---\n".join(docs)

        # 2. 'Tirar del Hilo': Identificar páginas clave y recuperar bloques continuos
        pages_to_fetch = {} # {source: [pages]}
        for meta in metadatas:
            src = meta.get("source")
            pg = meta.get("page")
            if src and pg is not None:
                if src not in pages_to_fetch: pages_to_fetch[src] = set()
                pages_to_fetch[src].add(pg) 
                
                # Expandir agresivamente para licitaciones: página anterior y siguiente
                try:
                    p_num = int(pg)
                    if p_num > 1: pages_to_fetch[src].add(p_num - 1)
                    pages_to_fetch[src].add(p_num + 1)
                except: pass

        # 3. Recuperar contexto extendido (misma colección que la búsqueda inicial; soporta cross-collection)
        expanded_docs = []

        for src, pgs in pages_to_fetch.items():
            sorted_pgs = sorted(list(pgs), key=lambda x: int(x) if str(x).isdigit() else 0)
            print(f"DEBUG: Recuperando páginas completas: {sorted_pgs} de {src}")
            for pg in sorted_pgs:
                docs = vector_db.fetch_page_documents(session_id, src, pg)
                if docs:
                    page_text = f"--- PÁGINA {pg} ({src}) ---\n" + "\n".join(docs)
                    expanded_docs.append(page_text)
        
        final_context = "\n\n".join(expanded_docs)
        print(f"DEBUG: SmartSearch Contexto final construido: {len(final_context)} caracteres.")
        return final_context

    def classify_moment(self, text: str) -> str:
        """
        Clasifica un hallazgo según el momento procesal de la licitación.
        Universal: Válido para cualquier país o sector.
        """
        t = text.lower()
        # 1. Fase de Presentación / Sobre
        if any(w in t for w in ["digitalizar", "pdf", "plataforma", "comprasmx", "compranet", "sobre técnico", "sobre administrativo", "propuesta", "digital", "adjuntar"]):
            return "PARTICIPACION (SOBRE)"
        
        # 2. Fase de Evaluación / Desempate
        if any(w in t for w in ["puntos y porcentajes", "binario", "desempate", "evaluación", "solvencia"]):
            return "EVALUACION"

        # 3. Fase de Contratación / Cotejo (Ganador)
        if any(w in t for w in ["cotejo", "original", "copia certificada", "ganador", "adjudicado", "previo a la firma", "contrato"]):
            return "CONTRATACION (COTEJO)"

        return "GENERAL"

    def _truncate_context_for_llm(self, context_text: str, max_tokens: int = 16000) -> str:
        """Utilidad para evitar context overflow antes de enviar al LLM. Configurado para 8GB VRAM."""
        max_chars = max_tokens * 4
        if len(context_text) > max_chars:
            print(f"⚠️ ADVERTENCIA: Contexto demasiado largo ({len(context_text)} chars). Truncando a {max_chars}.")
            return context_text[:max_chars] + "... [TRUNCADO POR OVERFLOW DE SEGURIDAD OPERATIVA]"
        return context_text
