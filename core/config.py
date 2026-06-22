from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    # App
    APP_NAME: str = "Vehana"
    ENVIRONMENT: str = "development"
    BASE_URL: str = "http://localhost:8001"
    SECRET_KEY: str
    ENCRYPTION_KEY: str  # Fernet key for encrypting API keys in DB

    # Database
    DATABASE_URL: str  # postgresql+asyncpg://...

    # Redis
    REDIS_URL: str = "redis://localhost:6379/1"

    # JWT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Vehana pool keys — used when a tenant hasn't set their own (BYOK)
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    SARVAM_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""

    # Gemini Live pipeline defaults
    GEMINI_LIVE_MODEL: str = "gemini-2.0-flash-live-001"
    GEMINI_VOICE: str = "Aoede"
    GEMINI_CALL_VAD_RMS_THRESHOLD: int = 200  # Noise gate — zero out frames below this RMS

    # Vehana's own Ozonetel account (for tenants who don't supply their own)
    OZONETEL_API_KEY: str = ""
    OZONETEL_USERNAME: str = ""
    OZONETEL_AGENT_ID: str = ""
    OZONETEL_BASE_URL: str = "in1-ccaas-api.ozonetel.com"
    OZONETEL_DID: str = ""  # DID / trunk ID for this account (e.g. 525836 or +918045613563)

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/2"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:8080,http://localhost:3000"

    def get_allowed_origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]


settings = Settings()
