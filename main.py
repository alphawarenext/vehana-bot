import ssl
import certifi
import os

# Must be set before any outbound HTTPS (Sarvam, Gemini, etc.)
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from contextlib import asynccontextmanager
from loguru import logger

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import create_db_and_tables
from core.redis import get_redis, close_redis

from api.auth import router as auth_router
from api.agents import router as agents_router
from api.campaigns import router as campaigns_router
from api.borrowers import router as borrowers_router
from api.conversations import router as conversations_router
from api.telephony import router as telephony_router
from api.usage import router as usage_router
from api.admin import router as admin_router
from api.webhooks import router as webhooks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting Vehana v2 [{settings.ENVIRONMENT}]")

    # Warm up DB connection pool
    await create_db_and_tables()

    # Warm up Redis connection
    await get_redis()

    # Pre-load Silero VAD model so the first call doesn't pay the model-load penalty
    try:
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        SileroVADAnalyzer()
        logger.info("Silero VAD pre-loaded")
    except Exception as exc:
        logger.warning(f"Silero VAD pre-load skipped: {exc}")

    logger.info("Startup complete")
    yield

    await close_redis()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Vehana API v2",
    version="2.0.0",
    lifespan=lifespan,
    # Disable docs in production
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routes ───────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v2"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(agents_router, prefix=API_PREFIX)
app.include_router(campaigns_router, prefix=API_PREFIX)
app.include_router(borrowers_router, prefix=API_PREFIX)
app.include_router(conversations_router, prefix=API_PREFIX)
app.include_router(telephony_router, prefix=API_PREFIX)
app.include_router(usage_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(webhooks_router, prefix=API_PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0", "env": settings.ENVIRONMENT}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=settings.ENVIRONMENT == "development",
        log_level="info",
    )
