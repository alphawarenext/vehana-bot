"""
Calculates USD cost for each LLM/STT/TTS API call and writes a UsageEvent row.
Prices are approximate — update from provider billing pages monthly.
"""
from uuid import UUID
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from models.usage import UsageEvent, LLMProvider

# ─── Price table ─────────────────────────────────────────────────────────────
# LLM: (input_usd_per_1m_tokens, output_usd_per_1m_tokens)
# STT: usd_per_second
# TTS: usd_per_character

_LLM_PRICES: dict[tuple, tuple[float, float]] = {
    ("gemini", "gemini-2.5-flash"):             (0.075,  0.30),
    ("gemini", "gemini-2.5-flash-lite"):        (0.0375, 0.15),
    ("gemini", "gemini-2.0-flash-live-001"):    (0.075,  0.30),
    ("openai", "gpt-4.1-mini"):                 (0.075,  0.30),
    ("openai", "gpt-4.1-nano"):                 (0.015,  0.06),
    ("groq",   "llama-3.3-70b-versatile"):      (0.59,   0.79),
    ("groq",   "llama-3.1-8b-instant"):         (0.05,   0.08),
}

_STT_PRICES: dict[str, float] = {
    "saaras:v3":              0.004,   # per second
    "whisper-large-v3-turbo": 0.003,
}

_TTS_PRICES: dict[str, float] = {
    "bulbul:v2":              0.000012,  # per character
    "eleven_turbo_v2_5":      0.000030,
    "eleven_multilingual_v2": 0.000030,
}


def _calc_llm_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    key = (provider, model)
    if key not in _LLM_PRICES:
        # Unknown model — use a safe default estimate
        input_price, output_price = 0.5, 1.0
    else:
        input_price, output_price = _LLM_PRICES[key]
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def _calc_stt_cost(model: str, audio_seconds: float) -> float:
    return audio_seconds * _STT_PRICES.get(model, 0.005)


def _calc_tts_cost(model: str, character_count: int) -> float:
    return character_count * _TTS_PRICES.get(model, 0.00003)


async def log_llm_usage(
    session: AsyncSession,
    org_id: UUID,
    provider: LLMProvider,
    model: str,
    input_tokens: int,
    output_tokens: int,
    call_log_id: Optional[UUID] = None,
    conversation_id: Optional[UUID] = None,
):
    cost = _calc_llm_cost(provider.value, model, input_tokens, output_tokens)
    event = UsageEvent(
        org_id=org_id,
        call_log_id=call_log_id,
        conversation_id=conversation_id,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )
    session.add(event)
    await session.commit()
    return cost


async def log_stt_usage(
    session: AsyncSession,
    org_id: UUID,
    model: str,
    audio_seconds: float,
    call_log_id: Optional[UUID] = None,
):
    cost = _calc_stt_cost(model, audio_seconds)
    event = UsageEvent(
        org_id=org_id,
        call_log_id=call_log_id,
        provider=LLMProvider.SARVAM_STT,
        model=model,
        audio_seconds=audio_seconds,
        cost_usd=cost,
    )
    session.add(event)
    await session.commit()
    return cost


async def log_tts_usage(
    session: AsyncSession,
    org_id: UUID,
    model: str,
    character_count: int,
    provider: LLMProvider = LLMProvider.SARVAM_TTS,
    call_log_id: Optional[UUID] = None,
):
    cost = _calc_tts_cost(model, character_count)
    event = UsageEvent(
        org_id=org_id,
        call_log_id=call_log_id,
        provider=provider,
        model=model,
        character_count=character_count,
        cost_usd=cost,
    )
    session.add(event)
    await session.commit()
    return cost
