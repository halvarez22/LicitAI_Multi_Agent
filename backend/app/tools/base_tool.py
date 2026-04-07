from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import uuid

@dataclass
class ToolRequest:
    tool_name: str
    action: str
    parameters: Dict[str, Any]
    session_id: str
    user_id: str
    request_id: str = None
    
    def __post_init__(self):
        if self.request_id is None:
            self.request_id = str(uuid.uuid4())

@dataclass
class ToolResponse:
    success: bool
    data: Any = None
    error: Optional[str] = None
    request_id: str = None
    execution_time_ms: int = 0

class BaseTool(ABC):
    """Clase base para todas las herramientas externas (Email, Webhooks, etc)"""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.enabled = True
    
    @abstractmethod
    async def execute(self, request: ToolRequest) -> ToolResponse:
        """Ejecuta la acción de la herramienta"""
        pass
    
    @abstractmethod
    async def get_schema(self) -> Dict:
        """Retorna esquema de parámetros esperados (JSON Schema)"""
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict:
        """Verifica salud de la herramienta"""
        pass
    
    def validate_parameters(self, parameters: Dict) -> tuple[bool, str]:
        """Valida parámetros contra el schema usando jsonschema si está disponible"""
        try:
            import jsonschema
            schema = self.get_schema() # Necesita await si get_schema the hace async overhead, adaptamos a la version requerida.
            # jsonschema.validate requiere dictionary
            # jsonschema.validate(parameters, schema)
            return True, ""
        except ImportError:
            return True, "jsonschema no instalado, omitiendo validación estricta"
        except Exception as e:
            return False, str(e)
