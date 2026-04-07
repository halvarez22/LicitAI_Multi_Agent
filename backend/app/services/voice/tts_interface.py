from abc import ABC, abstractmethod
from typing import Optional, Dict, List
from dataclasses import dataclass

@dataclass
class SynthesisResult:
    success: bool
    audio_path: Optional[str] = None
    audio_data: Optional[bytes] = None
    duration_seconds: float = 0
    character_count: int = 0
    error: Optional[str] = None

class TTSInterface(ABC):
    """Contrato único para todos los adaptadores TTS (Text-to-Speech)"""
    
    @abstractmethod
    async def synthesize(self, text: str, voice_id: Optional[str] = None, 
                        output_path: str = None) -> SynthesisResult:
        """Sintetiza texto a audio"""
        pass
    
    @abstractmethod
    async def get_available_voices(self) -> List[Dict]:
        """Retorna voces disponibles por el adaptador externo/local"""
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict:
        """Verifica salud del servicio TTS"""
        pass
