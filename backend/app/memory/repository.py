from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class MemoryRepository(ABC):
    """Contrato único para todos los adaptadores de memoria"""
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establece conexión con el backend de memoria"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """Cierra conexión limpiamente"""
        pass
    
    @abstractmethod
    async def save_session(self, session_id: str, data: Dict) -> bool:
        """Guarda estado de sesión"""
        pass
    
    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[Dict]:
        """Recupera estado de sesión"""
        pass
    
    @abstractmethod
    async def save_document(self, doc_id: str, session_id: str, content: Dict, metadata: Dict) -> bool:
        """Guarda documento procesado con metadata"""
        pass
    
    @abstractmethod
    async def get_documents(self, session_id: str) -> List[Dict]:
        """Recupera todos los documentos de una sesión"""
        pass

    @abstractmethod
    async def get_document(self, doc_id: str) -> Optional[Dict]:
        """Recupera un documento específico por su ID"""
        pass

    @abstractmethod
    async def delete_document(self, doc_id: str) -> bool:
        """Elimina un documento específico por su ID"""
        pass
    
    @abstractmethod
    async def save_conversation(self, session_id: str, messages: List[Dict]) -> bool:
        """Guarda historial de conversación (chatbot)"""
        pass
    
    @abstractmethod
    async def get_conversation(self, session_id: str, limit: int = 50) -> List[Dict]:
        """Recupera historial de conversación"""
        pass
    
    @abstractmethod
    async def save_agent_state(self, agent_id: str, session_id: str, state: Dict) -> bool:
        """Guarda estado de agente para recuperación"""
        pass
    
    @abstractmethod
    async def get_agent_state(self, agent_id: str, session_id: str) -> Optional[Dict]:
        """Recupera estado de agente"""
        pass
    
    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        """Elimina sesión y datos asociados (GDPR compliant)"""
        pass
    
    @abstractmethod
    async def backup(self, destination: str) -> bool:
        """Crea backup encriptado"""
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict:
        """Verifica salud del backend de memoria"""
        pass

    @abstractmethod
    async def list_sessions(self) -> List[Dict]:
        """Lista todas las sesiones (Licitaciones) registradas"""
        pass

    @abstractmethod
    async def save_company(self, company_id: str, data: Dict) -> bool:
        """Guarda o actualiza una empresa"""
        pass

    @abstractmethod
    async def get_companies(self) -> List[Dict]:
        """Lista todas las empresas"""
        pass

    @abstractmethod
    async def get_company(self, company_id: str) -> Optional[Dict]:
        """Obtiene una empresa"""
        pass

    @abstractmethod
    async def delete_company(self, company_id: str) -> bool:
        """Elimina una empresa"""
        pass
    @abstractmethod
    async def save_feedback(self, data: Dict) -> bool:
        """Guarda feedback de una extracción"""
        pass

    @abstractmethod
    async def get_feedback(self, session_id: str = None, company_id: str = None) -> List[Dict]:
        """Obtiene feedback por sesión o empresa"""
        pass

    @abstractmethod
    async def save_outcome(self, session_id: str, data: Dict) -> bool:
        """Guarda el resultado final de una licitación"""
        pass

    @abstractmethod
    async def get_outcome(self, session_id: str) -> Optional[Dict]:
        """Obtiene el resultado de una licitación"""
        pass

    @abstractmethod
    async def replace_line_items_for_document(
        self, session_id: str, document_id: str, line_items: List[Dict]
    ) -> bool:
        """Borra partidas previas del documento e inserta las nuevas filas (ingesta idempotente)."""

    @abstractmethod
    async def get_line_items_for_session(self, session_id: str) -> List[Dict]:
        """Lista todas las partidas tabulares persistidas para la sesión."""
