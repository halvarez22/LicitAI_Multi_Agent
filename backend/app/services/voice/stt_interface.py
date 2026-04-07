from abc import ABC, abstractmethod
from typing import Optional, Dict
from dataclasses import dataclass

@dataclass
class TranscriptionResult:
    text: str
    confidence: float
    language: str
    duration_seconds: float
    word_count: int
    timestamps: Optional[list] = None

class STTInterface(ABC):
    """Contrato único para todos los adaptadores STT (Speech-to-Text)"""
    
    @abstractmethod
    async def transcribe_audio(self, audio_path: str, language: str = "es") -> TranscriptionResult:
        """Transcribe archivo de audio a texto"""
        pass
    
    @abstractmethod
    async def transcribe_stream(self, audio_stream, language: str = "es") -> TranscriptionResult:
        """Transcribe stream de audio en tiempo real"""
        pass
    
    @abstractmethod
    async def get_supported_languages(self) -> list:
        """Retorna lenguajes soportados"""
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict:
        """Verifica salud del servicio STT"""
        pass
