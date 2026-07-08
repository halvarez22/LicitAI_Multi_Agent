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
    DOCUMENT_CONTAMINATION_GATE_ENABLED: bool = True
    CORPORATE_PHYSICAL_CONTAMINATION_GATE_ENABLED: bool = True
    FORMATS_PANEL_CONTAMINATION_GATE_ENABLED: bool = True
    JUNTA_CONTAMINATION_GATE_ENABLED: bool = True
    DELIVERY_CONTAMINATION_ENFORCE_AT_PACK: bool = True
    DOCUMENT_DATE_OFFSET_BUSINESS_DAYS: int = 2
    DOCUMENT_FORMAL_CLOSING_ENABLED: bool = True
    DOCUMENT_MIN_SUBSTANTIVE_WORDS: int = 40
    DOCUMENT_REQUIRE_LEGAL_MARKER: bool = True
    # Cola de generación: conteo congruente (umbrales globales, no por licitación).
    GENERATION_FILTER_ENABLED: bool = True
    # Borra /data/outputs/{sesión} antes de writers en cada corrida de generación (evita duplicados viejos).
    GENERATION_WIPE_OUTPUTS_BEFORE_WRITERS: bool = True
    # Tras CompraNetPackager exitoso, elimina copias en SOBRE_* y carpetas de generación.
    GENERATION_PRUNE_DUPLICATE_OUTPUTS_AFTER_PACK: bool = False
    # Permite preguntar precios en chat aunque falte página/snippet estricto en el pliego.
    ECONOMIC_RELAX_PRICE_ANCHORS_FOR_CHAT: bool = True
    # Operación: habilita/deshabilita la política versionada en
    # app/contracts/document_fill_deferral_policy.json (reglas HRU canónicas).
    ADMIN_ECONOMIC_DEFERRAL: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "ADMIN_ECONOMIC_DEFERRAL",
            "LICITAI_ADMIN_ECONOMIC_DEFERRAL",
        ),
    )
    # F1: copiloto económico proactivo post-análisis + prioridad chat sobre Excel.
    ECONOMIC_CHAT_FIRST: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "ECONOMIC_CHAT_FIRST",
            "LICITAI_ECONOMIC_CHAT_FIRST",
        ),
    )
    ECONOMIC_POST_ANALYSIS_HOOK_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "ECONOMIC_POST_ANALYSIS_HOOK_ENABLED",
            "LICITAI_ECONOMIC_POST_ANALYSIS_HOOK_ENABLED",
        ),
    )
    # F8: recalcular y mostrar subtotal/IVA/total en chat tras cada captura de precio.
    ECONOMIC_CHAT_CALC_ON_CAPTURE: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "ECONOMIC_CHAT_CALC_ON_CAPTURE",
            "LICITAI_ECONOMIC_CHAT_CALC_ON_CAPTURE",
        ),
    )
    # F2: generación desacoplada (técnica / económica / completa). Política en generation_mode_policy.json.
    DECOUPLED_GENERATION_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "DECOUPLED_GENERATION_ENABLED",
            "LICITAI_DECOUPLED_GENERATION_ENABLED",
        ),
    )
    # F6 (ADR-001): streams técnico/económico concurrentes en una sesión.
    DUAL_STREAM_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "DUAL_STREAM_ENABLED",
            "LICITAI_DUAL_STREAM_ENABLED",
        ),
    )
    # F9: copiloto técnico — canónico antes de redactar con LLM.
    TECHNICAL_CHAT_FIRST: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "TECHNICAL_CHAT_FIRST",
            "LICITAI_TECHNICAL_CHAT_FIRST",
        ),
    )
    TECHNICAL_POST_ANALYSIS_HOOK_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "TECHNICAL_POST_ANALYSIS_HOOK_ENABLED",
            "LICITAI_TECHNICAL_POST_ANALYSIS_HOOK_ENABLED",
        ),
    )
    COPILOT_UNIFIED_STATUS: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "COPILOT_UNIFIED_STATUS",
            "LICITAI_COPILOT_UNIFIED_STATUS",
        ),
    )
    # F3.3: empaquetado estricto (todos los sobres) vs parcial piloto.
    PACKAGING_REQUIRE_ALL_SOBRES: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "PACKAGING_REQUIRE_ALL_SOBRES",
            "LICITAI_PACKAGING_REQUIRE_ALL_SOBRES",
        ),
    )
    # F5: descarga contextual bajo botones de generación. Política en delivery_scope_policy.json.
    CONTEXTUAL_DOWNLOAD_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "CONTEXTUAL_DOWNLOAD_ENABLED",
            "LICITAI_CONTEXTUAL_DOWNLOAD_ENABLED",
        ),
    )
    # F11: briefing canónico del pliego (tres bloques + primer paso).
    CONVOCATORIA_BRIEFING_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "CONVOCATORIA_BRIEFING_ENABLED",
            "LICITAI_CONVOCATORIA_BRIEFING_ENABLED",
        ),
    )
    # F11: orquestador único de apertura del chat (sin carreras proactive_*).
    CHAT_OPENING_ORCHESTRATOR_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "CHAT_OPENING_ORCHESTRATOR_ENABLED",
            "LICITAI_CHAT_OPENING_ORCHESTRATOR_ENABLED",
        ),
    )
    # F12.1: anclas de evidencia fail-closed en claims del asistente.
    EVIDENCE_ANCHOR_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "EVIDENCE_ANCHOR_ENABLED",
            "LICITAI_EVIDENCE_ANCHOR_ENABLED",
        ),
    )
    EXPEDIENTE_GUIDED_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "EXPEDIENTE_GUIDED_ENABLED",
            "LICITAI_EXPEDIENTE_GUIDED_ENABLED",
        ),
    )
    READINESS_GATES_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "READINESS_GATES_ENABLED",
            "LICITAI_READINESS_GATES_ENABLED",
        ),
    )
    TECH_WRITER_MAX_GENERABLE_DOCS: int = 12
    FORMATS_MAX_GENERABLE_DOCS: int = 18
    # Mínimo de anexos administrativos materializados vs panel/cola (0–1).
    FORMATS_MIN_DELIVERABLE_RATIO: float = 0.85
    # Cobertura mínima plantillas de oferta en _compranet_validated antes de FINAL_OK.
    DELIVERY_MIN_COVERAGE_RATIO: float = 0.85
    INTAKE_PLANNER_ENABLED: bool = True
    INTAKE_PLANNER_SHADOW_MODE: bool = False
    # Oferta «plan guiado» en chat (confunde si hay inventario en panel). False = solo resumen/acciones claras.
    INTAKE_PROACTIVE_CHAT_OFFER_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "LICITAI_INTAKE_PROACTIVE_CHAT_OFFER",
            "INTAKE_PROACTIVE_CHAT_OFFER_ENABLED",
        ),
    )
    # Intake autónomo conversacional (Fase 1): coordinador delgado post-análisis.
    AUTONOMOUS_INTAKE_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "LICITAI_AUTONOMOUS_INTAKE_ENABLED",
            "AUTONOMOUS_INTAKE_ENABLED",
        ),
    )
    FAST_TRACK_DOC_CANDIDATES_ENABLED: bool = True
    FAST_TRACK_REQUIRE_HUMAN_CONFIRM: bool = True
    FAST_TRACK_LOW_CONF_THRESHOLD: float = 0.70

    # --- Estabilización UI: enrichment cronograma (P0-03) ---
    CRONOGRAMA_ENRICHMENT_TIMEOUT_S: float = 12.0

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

    # Machotes oficiales en bases: sin LLM sustituto en obra|T/E; shell [Consignar] si falla espejo.
    OFFICIAL_MIRROR_STRICT: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "OFFICIAL_MIRROR_STRICT",
            "LICITAI_OFFICIAL_MIRROR_STRICT",
        ),
    )
    OFFICIAL_MIRROR_DELIVERY_GATE_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "OFFICIAL_MIRROR_DELIVERY_GATE_ENABLED",
            "LICITAI_OFFICIAL_MIRROR_DELIVERY_GATE_ENABLED",
        ),
    )

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

    DICTAMEN_CURATION_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices("DICTAMEN_CURATION_ENABLED", "LICITAI_DICTAMEN_CURATION_ENABLED"),
        description="Curación vista licitante en Dictamen Forense.",
    )
    DICTAMEN_VIEW_MODE: str = Field(
        default="licitante",
        validation_alias=AliasChoices("DICTAMEN_VIEW_MODE", "LICITAI_DICTAMEN_VIEW_MODE"),
        description="licitante | forense_completo",
    )

    # Redis for communication
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    AGENTS_JOB_STALE_SECONDS: int = Field(
        default=5400,
        validation_alias=AliasChoices("AGENTS_JOB_STALE_SECONDS", "LICITAI_AGENTS_JOB_STALE_SECONDS"),
        description=(
            "Segundos sin heartbeat (updated_at) para marcar un job RUNNING/QUEUED como FAILED "
            "al consultar active-job (p. ej. tras reinicio del contenedor). "
            "No aplica al polling de /jobs/{id}/status durante análisis activo."
        ),
    )
    
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
