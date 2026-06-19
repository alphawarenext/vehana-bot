"""
Gemini Live real-time voice pipeline for Ozonetel WebSocket streams.
Ported from v1 gemini_live_stream.py — adapted for v2 multi-tenant context.

Audio protocol:
  Ozonetel → PCM int16 list at 8kHz → upsample to 16kHz → Gemini (audio/pcm;rate=16000)
  Gemini → PCM bytes at 24kHz → downsample to 8kHz → PCM int16 list → Ozonetel
"""
import asyncio
import audioop
import json
import struct
import time
import traceback
from typing import Any, Optional
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState

from core.config import settings
from models.voice_agent import VoiceAgent
from services.pipeline.conversation_logger import ConversationLogger
from services.pipeline.prompt_builder import build_agent_system_prompt


# ─── Audio conversion helpers ─────────────────────────────────────────────────

def _ozonetel_samples_to_pcm16_16k(samples: list[int]) -> bytes:
    linear_8k = struct.pack(f"<{len(samples)}h", *samples)
    linear_16k, _ = audioop.ratecv(linear_8k, 2, 1, 8000, 16000, None)
    return linear_16k


def _pcm16_24k_to_ozonetel_samples(pcm_bytes: bytes) -> list[int]:
    linear_8k, _ = audioop.ratecv(pcm_bytes, 2, 1, 24000, 8000, None)
    num_samples = len(linear_8k) // 2
    return list(struct.unpack(f"<{num_samples}h", linear_8k))


# ─── Main pipeline ────────────────────────────────────────────────────────────

async def run_gemini_live_stream(
    websocket: WebSocket,
    call_sid: str,
    agent: VoiceAgent,
    org_id: UUID,
    caller_number: Optional[str] = None,
    callee_number: Optional[str] = None,
    contact_data: Optional[dict[str, Any]] = None,
    campaign_id: Optional[UUID] = None,
    borrower_id: Optional[UUID] = None,
) -> None:
    """
    Drive a full Gemini Live call session over an Ozonetel WebSocket.
    Runs until the Ozonetel 'stop' event or WebSocket disconnect.
    """
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as exc:
        logger.error(f"[{call_sid}] Gemini SDK missing: {exc}")
        await websocket.close()
        return

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        logger.error(f"[{call_sid}] GEMINI_API_KEY not configured")
        await websocket.close()
        return

    system_prompt = build_agent_system_prompt(agent, contact_data=contact_data)

    conv_logger = ConversationLogger(
        org_id=org_id,
        agent_id=agent.id,
        phone_number=caller_number,
        call_direction="inbound" if callee_number else "outbound",
        campaign_id=campaign_id,
        borrower_id=borrower_id,
        call_sid=call_sid,
    )
    await conv_logger.start()

    call_started_at = time.perf_counter()
    _elapsed = lambda: f"+{time.perf_counter() - call_started_at:.2f}s"

    vad = SileroVADAnalyzer(
        sample_rate=16000,
        params=VADParams(
            stop_secs=0.35,
            start_secs=0.08,
            confidence=0.6,
            min_volume=0.1,
        ),
    )
    vad.set_sample_rate(16000)

    client = genai.Client(api_key=api_key)
    live_model = agent.llm_model or settings.GEMINI_LIVE_MODEL
    voice_name = agent.voice or settings.GEMINI_VOICE
    vad_threshold = settings.GEMINI_CALL_VAD_RMS_THRESHOLD

    live_config = genai_types.LiveConnectConfig(
        response_modalities=[genai_types.Modality.AUDIO],
        realtime_input_config=genai_types.RealtimeInputConfig(
            automatic_activity_detection=genai_types.AutomaticActivityDetection(
                disabled=False,
                silence_duration_ms=400,
            )
        ),
        speech_config=genai_types.SpeechConfig(
            voice_config=genai_types.VoiceConfig(
                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
        system_instruction=genai_types.Content(parts=[genai_types.Part(text=system_prompt)]),
        input_audio_transcription=genai_types.AudioTranscriptionConfig(),
        output_audio_transcription=genai_types.AudioTranscriptionConfig(),
    )

    try:
        async with client.aio.live.connect(model=live_model, config=live_config) as session:
            logger.info(f"[{call_sid}] Gemini Live session opened (model={live_model} voice={voice_name}) {_elapsed()}")

            # Trigger initial greeting
            contact_name = (contact_data or {}).get("Name", "").strip() if contact_data else ""
            if contact_name:
                greeting_trigger = f"The user {contact_name} just picked up the call. Start the conversation by greeting them by name."
            else:
                greeting_trigger = "The user just picked up the call. Start the conversation by greeting them."

            await session.send_client_content(
                turns=genai_types.Content(role="user", parts=[genai_types.Part(text=greeting_trigger)]),
                turn_complete=True,
            )

            input_queue: asyncio.Queue[dict] = asyncio.Queue()
            caller_parts: list[str] = []
            gemini_parts: list[str] = []

            user_speaking = False
            bot_responding = False
            interrupted = False
            is_first_turn = True

            first_caller_audio_logged = False
            first_gemini_audio_logged = False

            def _append_part(parts: list[str], text: str) -> None:
                clean = (text or "").strip()
                if not clean:
                    return
                if parts and parts[-1] == clean:
                    return
                parts.append(clean)

            async def _flush_caller():
                if not caller_parts:
                    return
                text = " ".join(caller_parts).strip()
                caller_parts.clear()
                if text:
                    await conv_logger.add_message("user", text)

            async def _flush_gemini():
                if not gemini_parts:
                    return
                text = " ".join(gemini_parts).strip()
                gemini_parts.clear()
                if text:
                    await conv_logger.add_message("agent", text)

            # ── Task 1: receive audio from Ozonetel ──────────────────────────
            async def receive_from_ozonetel():
                nonlocal first_caller_audio_logged, user_speaking, interrupted, is_first_turn
                try:
                    while True:
                        raw = await websocket.receive_text()
                        payload = json.loads(raw)
                        event = payload.get("event")

                        if event == "start":
                            # Ozonetel sends ucid (call ID) in the start event
                            ucid = payload.get("ucid") or payload.get("sid")
                            if ucid:
                                logger.info(f"[{call_sid}] Ozonetel start event received ucid={ucid}")
                            continue

                        if event == "media":
                            if not first_caller_audio_logged:
                                first_caller_audio_logged = True
                                logger.info(f"[{call_sid}] First caller audio frame {_elapsed()}")

                            samples = payload.get("data", {}).get("samples", [])
                            if not samples:
                                continue

                            pcm_bytes = _ozonetel_samples_to_pcm16_16k(samples)
                            vad_state = await vad.analyze_audio(pcm_bytes)
                            rms = audioop.rms(pcm_bytes, 2)

                            if vad_state == VADState.QUIET and rms < vad_threshold:
                                pcm_bytes = b"\x00" * len(pcm_bytes)

                            await input_queue.put({"type": "audio", "data": pcm_bytes})

                            if vad_state == VADState.SPEAKING:
                                if not user_speaking:
                                    user_speaking = True
                                    if bot_responding and not is_first_turn:
                                        logger.debug(f"[{call_sid}] VAD: user interrupted bot")
                                        interrupted = True
                            elif vad_state == VADState.QUIET and user_speaking:
                                user_speaking = False
                                logger.debug(f"[{call_sid}] VAD: user stopped speaking")

                        elif event == "stop":
                            await _flush_caller()
                            await _flush_gemini()
                            await input_queue.put({"type": "stop"})
                            logger.info(f"[{call_sid}] Ozonetel stop event {_elapsed()}")
                            break

                except WebSocketDisconnect:
                    await _flush_caller()
                    await _flush_gemini()
                    await input_queue.put({"type": "stop"})
                    logger.info(f"[{call_sid}] Ozonetel WebSocket disconnected {_elapsed()}")
                except Exception as exc:
                    await _flush_caller()
                    await _flush_gemini()
                    await input_queue.put({"type": "stop"})
                    logger.error(f"[{call_sid}] Ozonetel receive error: {exc}")

            # ── Task 2: forward buffered PCM to Gemini ───────────────────────
            async def send_audio_to_gemini():
                audio_buffer = bytearray()
                try:
                    while True:
                        msg = await input_queue.get()
                        if msg["type"] == "audio":
                            audio_buffer.extend(msg["data"])
                            if input_queue.empty() or len(audio_buffer) >= 3200:
                                await session.send_realtime_input(
                                    audio=genai_types.Blob(
                                        data=bytes(audio_buffer),
                                        mime_type="audio/pcm;rate=16000",
                                    )
                                )
                                audio_buffer.clear()
                        elif msg["type"] == "stop":
                            if audio_buffer:
                                await session.send_realtime_input(
                                    audio=genai_types.Blob(
                                        data=bytes(audio_buffer),
                                        mime_type="audio/pcm;rate=16000",
                                    )
                                )
                            break
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.error(f"[{call_sid}] send_audio_to_gemini error: {exc}")

            # ── Task 3: receive Gemini responses, send audio to Ozonetel ─────
            async def receive_from_gemini():
                nonlocal first_gemini_audio_logged, bot_responding, interrupted, is_first_turn
                try:
                    while True:
                        async for response in session.receive():
                            sc = response.server_content
                            if not sc:
                                continue

                            if getattr(sc, "interrupted", False):
                                if not is_first_turn:
                                    logger.debug(f"[{call_sid}] Gemini server-VAD interrupted signal")
                                    interrupted = True
                                    bot_responding = False

                            if sc.output_transcription and sc.output_transcription.text and not interrupted:
                                _append_part(gemini_parts, sc.output_transcription.text)

                            if sc.input_transcription and sc.input_transcription.text:
                                _append_part(caller_parts, sc.input_transcription.text)

                            if sc.model_turn:
                                bot_responding = True
                                if not interrupted:
                                    for part in sc.model_turn.parts:
                                        if not part.inline_data or interrupted:
                                            break

                                        if not first_gemini_audio_logged:
                                            first_gemini_audio_logged = True
                                            logger.info(f"[{call_sid}] First Gemini audio chunk sent {_elapsed()}")

                                        samples = _pcm16_24k_to_ozonetel_samples(part.inline_data.data)
                                        await websocket.send_text(
                                            json.dumps({
                                                "event": "media",
                                                "type": "media",
                                                "ucid": call_sid,
                                                "data": {
                                                    "samples": samples,
                                                    "bitsPerSample": 16,
                                                    "sampleRate": 8000,
                                                    "channelCount": 1,
                                                    "numberOfFrames": len(samples),
                                                    "type": "data",
                                                },
                                            })
                                        )

                            if getattr(sc, "turn_complete", False):
                                bot_responding = False
                                await _flush_caller()
                                if not interrupted:
                                    await _flush_gemini()
                                else:
                                    gemini_parts.clear()
                                interrupted = False
                                if is_first_turn:
                                    logger.info(f"[{call_sid}] Initial greeting complete — interruptions now enabled {_elapsed()}")
                                    is_first_turn = False

                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    await _flush_gemini()
                    logger.error(f"[{call_sid}] Gemini receive error: {exc}\n{traceback.format_exc()}")

            ozonetel_task = asyncio.create_task(receive_from_ozonetel())
            send_task = asyncio.create_task(send_audio_to_gemini())
            gemini_task = asyncio.create_task(receive_from_gemini())

            await ozonetel_task

            for t in (send_task, gemini_task):
                t.cancel()
            await asyncio.gather(send_task, gemini_task, return_exceptions=True)

            await _flush_caller()
            await _flush_gemini()
            await conv_logger.cleanup("completed")
            logger.info(f"[{call_sid}] Call ended cleanly {_elapsed()}")

    except Exception as exc:
        await conv_logger.cleanup("failed")
        logger.error(f"[{call_sid}] Gemini Live session error: {exc}\n{traceback.format_exc()}")
        try:
            await websocket.close()
        except Exception:
            pass
