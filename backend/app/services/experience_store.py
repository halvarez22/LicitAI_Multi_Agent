import hashlib
import json
import logging
from typing import List, Optional, Dict
from pydantic import BaseModel
from app.services.vector_service import VectorDbServiceClient
from app.memory.factory import MemoryAdapterFactory
from app.config.settings import settings

logger = logging.getLogger(__name__)

class ExperienceCase(BaseModel):
    session_id: str
    sector: Optional[str] = None
    tipo_licitacion: Optional[str] = None
    summary: str
    outcome: str
    score: float = 0.0
    fingerprint: Optional[str] = None
    disclaimer: Optional[str] = None

class ExperienceStore:
    def __init__(self):
        self.vector_db = VectorDbServiceClient()
        self.repo = None
        self.collection_name = "experience_cases"

    async def _get_repo(self):
        if not self.repo:
            self.repo = MemoryAdapterFactory.create_adapter()
            await self.repo.connect()
        return self.repo

    def generate_fingerprint(self, requirements: List[str]) -> str:
        """Genera un hash normalizado de la lista de requisitos."""
        if not requirements:
            return ""
        # Normalización básica: strip, lower, sort
        clean_reqs = sorted([r.strip().lower() for r in requirements if r.strip()])
        combined = "|".join(clean_reqs)
        # Unicode normalización no es estrictamente necesaria para hash pero ayuda en colisiones visuales
        # Por simplicidad usamos sha256
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()

    async def upsert_case_summary(self, session_id: str, sector: str, tipo: str, requirements: List[str], outcome: str) -> bool:
        """Sincroniza un caso con ChromaDB y Postgres."""
        if not settings.EXPERIENCE_LAYER_ENABLED:
            return False

        repo = await self._get_repo()
        fingerprint = self.generate_fingerprint(requirements)
        
        # 1. Persistir Outcome en Postgres (Fuente de Verdad)
        outcome_data = {
            "sector": sector,
            "tipo_licitacion": tipo,
            "resultado": outcome,
            "fingerprint": fingerprint
        }
        await repo.save_outcome(session_id, outcome_data)

        # 2. Indexar en ChromaDB para búsqueda semántica
        # Contenido indexado: requisitos resumidos + sector + tipo
        summary_text = f"Sector: {sector} | Tipo: {tipo} | Requisitos: {' '.join(requirements[:15])}"
        
        metadata = {
            "session_id": session_id,
            "sector": sector,
            "tipo": tipo,
            "outcome": outcome,
            "fingerprint": fingerprint
        }
        
        # Usamos add_texts de VectorDbServiceClient pero con la colección fija de experiencia
        collection = self.vector_db.get_or_create_collection(self.collection_name)
        if collection:
            collection.add(
                documents=[summary_text],
                metadatas=[metadata],
                ids=[session_id] # Usamos session_id como ID para evitar duplicados
            )
            logger.info(f"experience_case_indexed: session_id={session_id}")
            return True
        return False

    async def find_similar(self, query_text: str, sector: Optional[str] = None, tipo: Optional[str] = None, top_k: int = 5) -> List[ExperienceCase]:
        """Busca casos similares en el histórico."""
        if not settings.EXPERIENCE_LAYER_ENABLED:
            return []

        collection = self.vector_db.get_or_create_collection(self.collection_name)
        if not collection:
            return []

        results = collection.query(
            query_texts=[query_text],
            n_results=top_k
        )
        
        cases = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i in range(len(docs)):
            m = metas[i]
            # Convertir distancia a "score" (simplificado)
            score = 1.0 / (1.0 + distances[i])
            cases.append(ExperienceCase(
                session_id=m.get("session_id"),
                sector=m.get("sector"),
                tipo_licitacion=m.get("tipo"),
                summary=docs[i],
                outcome=m.get("outcome"),
                score=round(score, 4),
                fingerprint=m.get("fingerprint")
            ))

        if not cases:
            return [ExperienceCase(
                session_id="none",
                summary="No se encontraron casos previos relevantes.",
                outcome="unknown",
                disclaimer="Baja señal: No hay suficiente experiencia acumulada para este perfil."
            )]

        return cases
