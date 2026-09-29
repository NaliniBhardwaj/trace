"""
Application configuration, loaded from environment variables (.env).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "SENTINEL API"
    ENV: str = "development"

    DATABASE_URL: str = "sqlite:///./sentinel_dev.db"

    JWT_SECRET_KEY: str = "CHANGE_ME_INSECURE_DEV_SECRET"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12

    DEFAULT_DOSE_ELEVATED_PPM_MIN: float = 15.0
    DEFAULT_DOSE_HIGH_PPM_MIN: float = 100.0
    DEFAULT_DOSE_CRITICAL_PPM_MIN: float = 800.0
    DEFAULT_PPM_ELEVATED: float = 1.0
    DEFAULT_PPM_HIGH: float = 10.0
    DEFAULT_PPM_CRITICAL: float = 100.0
    MIN_CONFIDENCE_FOR_ESTIMATE: float = 0.55

    CORS_ORIGINS: str = "*"

    ML_ENABLED: bool = True
    ML_MODEL_PATH: str = "model.pkl"
    ML_DELTA_E_MAX: float = 88.0

    # Phase 10 — WhatsApp support (optional; app runs without these)
    WHATSAPP_PROVIDER: str = "demo"
    WHATSAPP_DEMO_MODE: bool = True
    WHATSAPP_VERIFY_TOKEN: str = "sentinel-demo-verify"
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_SUPPORT_NUMBER: str = ""
    WHATSAPP_APP_SECRET: str = ""
    WHATSAPP_GRAPH_API_VERSION: str = "v19.0"

    # Phase 16 — LLM Decision Support (read-only explanation layer)
    LLM_MODE: str = "demo"  # demo | live
    LLM_PROVIDER: str = "openai_compatible"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_TIMEOUT: float = 30.0
    LLM_MAX_TOKENS: int = 1024
    LLM_TEMPERATURE: float = 0.2

    # Phase 17 — release / demo
    APP_VERSION: str = "1.0.0"
    RELEASE_NAME: str = "SENTINEL v1.0 — Final SIH Demo Release"
    SEED_DEMO_DATA: bool = False  # opt-in only; never reset DB on normal startup
    LOG_LEVEL: str = "INFO"


settings = Settings()
