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
    
    # Redis for communication
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }

settings = Settings()
