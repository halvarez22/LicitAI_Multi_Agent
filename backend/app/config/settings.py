import os
import re

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "default-insecure-key"
    JWT_EXPIRY_MINUTES: int = 15
    
    MEMORY_BACKEND: str = "postgres"
    DATABASE_URL: Optional[str] = None
    
    OCR_URL: Optional[str] = None
    LLM_URL: Optional[str] = None
    VECTOR_DB_URL: Optional[str] = None
    
    # --- Fase 1 Confidence ---
    CONFIDENCE_ENABLED: bool = False
    CONFIDENCE_SHADOW_MODE: bool = True
    CONFIDENCE_THRESHOLD_DEFAULT: float = 0.70
    CONFIDENCE_THRESHOLD_CRITICAL: float = 0.80
    
    # --- Fase 2 Adaptive Orchestrator ---
    ADAPTIVE_ORCHESTRATOR_ENABLED: bool = False
    ADAPTIVE_PIPELINE_SAFE_MODE: bool = True
    ADAPTIVE_MAX_SKIPS: int = 1
    ADAPTIVE_LOW_CONF_THRESHOLD: float = 0.70
    ADAPTIVE_LOW_CONF_MAX_ITEMS: int = 3
    
    # --- Fase 3 Backtracking & Validation ---
    BACKTRACKING_ENABLED: bool = False
    BACKTRACK_MAX_ITERATIONS: int = 2
    BACKTRACK_REDIS_CHANNEL_PREFIX: str = "licitai:agents"
    VALIDATOR_LLM_ASSIST: bool = False
    CRITIC_ENABLED: bool = True
    
    # --- Fase 4 Feedback HITL ---
    FEEDBACK_API_ENABLED: bool = False
    FEEDBACK_UI_ENABLED: bool = False
    FEEDBACK_REQUIRE_AUTH: bool = True

    # --- Fase 5: Experiencia y Casos Similares ---
    EXPERIENCE_LAYER_ENABLED: bool = False
    EXPERIENCE_PROMPT_INJECTION: bool = False
    EXPERIENCE_SHADOW_MODE: bool = True
    EXPERIENCE_TOP_K: int = 5
    EXPERIENCE_MIN_CASES: int = 1
    EXPERIENCE_API_ENABLED: bool = False
    EXPERIENCE_DEBUG: bool = False

    # --- Inventario de documentos (amplía compliance antes de generar Word) ---
    DOCUMENT_INVENTORY_MERGE_ENABLED: bool = True
    DOCUMENT_INVENTORY_MAX_ADD: int = 55
    DOCUMENT_INVENTORY_CONTEXT_CHARS: int = 90000
    DOCUMENT_INVENTORY_SERVICE_ENABLED: bool = True
    DOCUMENT_INVENTORY_SERVICE_USE_LLM: bool = True
    DOCUMENT_INVENTORY_SYNC_ENABLED: bool = True

    # --- Gate duro de calidad documental ---
    DOCUMENT_QUALITY_HARD_GATE_ENABLED: bool = True
    DOCUMENT_QUALITY_GATE_MIN_ITEMS: int = 3
    DOCUMENT_QUALITY_GATE_MAX_UNKNOWN_RATIO: float = 0.6
    DOCUMENT_QUALITY_GATE_MIN_EVIDENCE_MATCH_RATIO: float = 0.5
    DOCUMENT_FILL_QUALITY_GATE_ENABLED: bool = True
    DOCUMENT_FILL_QUALITY_GATE_MODE: str = "enforce"
    DOCUMENT_FILL_QUALITY_MIN_CONFIDENCE_CRITICAL: float = 0.75
    # Cola de generación: conteo congruente (umbrales globales, no por licitación).
    GENERATION_FILTER_ENABLED: bool = True
    # Borra /data/outputs/{sesión} antes de writers en cada corrida de generación (evita duplicados viejos).
    GENERATION_WIPE_OUTPUTS_BEFORE_WRITERS: bool = True
    # Tras CompraNetPackager exitoso, elimina copias en SOBRE_* y carpetas de generación.
    GENERATION_PRUNE_DUPLICATE_OUTPUTS_AFTER_PACK: bool = True
    # Permite preguntar precios en chat aunque falte página/snippet estricto en el pliego.
    ECONOMIC_RELAX_PRICE_ANCHORS_FOR_CHAT: bool = True
    TECH_WRITER_MAX_GENERABLE_DOCS: int = 12
    FORMATS_MAX_GENERABLE_DOCS: int = 18
    INTAKE_PLANNER_ENABLED: bool = True
    INTAKE_PLANNER_SHADOW_MODE: bool = False
    FAST_TRACK_DOC_CANDIDATES_ENABLED: bool = True
    FAST_TRACK_REQUIRE_HUMAN_CONFIRM: bool = True
    FAST_TRACK_LOW_CONF_THRESHOLD: float = 0.70

    # --- Enhanced Analyst Agent (Solvencia Técnica y Condiciones Contractuales) ---
    ENHANCED_EXTRACTION_ENABLED: bool = True
    EXTRACTION_CONFIDENCE_THRESHOLD: float = 0.5
    DEFAULT_CLASSIFICATION: str = "obligatorio"

    # --- Tender Router & Legal Audit — Prompt Hardening v2 ---
    # Rollback: setear ROUTER_PROMPT_VERSION=v1 para revertir a prompts originales
    ROUTER_PROMPT_VERSION: str = "v2"          # "v1" | "v2"
    TRIAGE_SIGNALS_ENABLED: bool = True        # Incluir signals_detected en triage
    AUDIT_DUAL_OBLIGATION_ENABLED: bool = True # obligatorio_por_bases + por_marco_normativo
    AUDIT_JUSTIFICATION_ENABLED: bool = True   # justificacion_clasificacion por item
    TRIAGE_ENABLED: bool = True                # Master switch del triage normativo
    # Post-proceso: anclar label_taxonomica desde texto + vocabulario cerrado en prompt de auditoría
    COMPLIANCE_TAXONOMY_ANCHOR_ENABLED: bool = True

    # --- EvidenceProfile Bridge (Go/No-Go con evidencia de sesión) ---
    ENABLE_EVIDENCE_PROFILE_BRIDGE: bool = False

    # En analysis_only/full: registra semáforo y brechas sin GO_NO_GO_PENDING ni panel UI.
    GO_NO_GO_SILENT_IN_ANALYSIS: bool = True

    # Espejo de plantillas Office ingestadas (fase 2 universal).
    TEMPLATE_MIRROR_ENABLED: bool = True
    TEMPLATE_MIRROR_MAX_ADMIN: int = 40
    TEMPLATE_MIRROR_MAX_ECONOMIC: int = 20

    # --- Resolución por bloques (Hito A1) ---
    ENABLE_BLOCK_RESOLUTION: bool = Field(
        default=True,
        validation_alias=AliasChoices("LICITAI_ENABLE_BLOCK_RESOLUTION", "ENABLE_BLOCK_RESOLUTION"),
        description="Si True, expone preview/guardado masivo de InteractionBlock para pendientes económicos agrupados.",
    )
    BLOCK_RESOLUTION_MIN_ITEMS: int = Field(
        default=3,
        validation_alias=AliasChoices("LICITAI_BLOCK_RESOLUTION_MIN_ITEMS", "BLOCK_RESOLUTION_MIN_ITEMS"),
        description="Mínimo de ítems economic_price en un mismo grupo para formar un InteractionBlock.",
    )

    # Redis for communication
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }

    @model_validator(mode="after")
    def _normalize_docker_service_hosts_on_local_api(self) -> "Settings":
        """
        Si el proceso del API corre en el host (fuera de Docker) pero el .env
        está alineado a docker-compose (hostnames ``database``, ``vector-db``,
        ``queue-redis``), apuntar a localhost donde los puertos suelen estar publicados.
        Dentro del contenedor ``/.dockerenv`` existe y no se altera nada.
        """
        if os.path.exists("/.dockerenv"):
            return self

        if self.DATABASE_URL and "@database:" in self.DATABASE_URL:
            self.DATABASE_URL = self.DATABASE_URL.replace("@database:", "@127.0.0.1:")

        if self.VECTOR_DB_URL and "vector-db" in self.VECTOR_DB_URL:
            self.VECTOR_DB_URL = re.sub(
                r"//vector-db([:/])",
                r"//127.0.0.1\1",
                self.VECTOR_DB_URL,
                count=1,
            )

        if self.REDIS_HOST in ("queue-redis", "redis"):
            self.REDIS_HOST = "127.0.0.1"

        return self


settings = Settings()
