import asyncio
import base64
import contextlib
import io
import json
import struct
import re
import urllib.parse
import wave
from collections.abc import AsyncGenerator

import httpx
import websockets
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    StartFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.stt_service import STTService, SegmentedSTTService
from pipecat.services.tts_service import TTSService, TextAggregationMode
from pipecat.services.settings import TTSSettings
from pipecat.utils.time import time_now_iso8601

def detect_language(text: str, default: str = "hi-IN") -> str:
    # Check Tamil
    if any("\u0b80" <= c <= "\u0bff" for c in text):
        return "ta-IN"
    # Check Telugu
    if any("\u0c00" <= c <= "\u0c7f" for c in text):
        return "te-IN"
    # Check Kannada
    if any("\u0c80" <= c <= "\u0cff" for c in text):
        return "kn-IN"
    # Check Bengali
    if any("\u0980" <= c <= "\u09ff" for c in text):
        return "bn-IN"
    # Check Gujarati
    if any("\u0a80" <= c <= "\u0aff" for c in text):
        return "gu-IN"
    # Check Malayalam
    if any("\u0d00" <= c <= "\u0d7f" for c in text):
        return "ml-IN"
    # Check Devanagari (Hindi/Marathi)
    # Marathi specifically uses the Devanagari character 'ळ' (\u0933)
    if any("\u0900" <= c <= "\u097f" for c in text):
        if "\u0933" in text:
            return "mr-IN"
        return "hi-IN"
    # If it contains English/Latin letters, return en-IN
    if any(c.isalpha() and c.isascii() for c in text):
        return "en-IN"
    return default

class SarvamStreamingSTTService(STTService):
    """Continuously streams every incoming audio frame to Sarvam STT."""

    def __init__(
        self,
        api_key: str,
        model: str = "saaras:v3",
        language_code: str = "hi-IN",
        sample_rate: int = 16000,
        mode: str = "transcribe",
        input_audio_codec: str = "audio/wav",
        high_vad_sensitivity: bool = True,
    ):
        super().__init__(
            audio_passthrough=True,
            sample_rate=sample_rate,
        )
        self.api_key = api_key
        self._model = model
        self._language_code = language_code
        self._sample_rate = sample_rate
        self._mode = mode
        self._input_audio_codec = input_audio_codec
        self._high_vad_sensitivity = high_vad_sensitivity
        self._websocket = None
        self._receiver_task: asyncio.Task | None = None
        self._server_user_speaking = False
        self._last_reconnect_time = 0
        self._sent_audio_packets = 0
        self._disabled = False
        self._stopping = False
        print(f"[sarvam-stt] continuous streaming initialized model={model}")

    async def start(self, frame: StartFrame | None = None):
        self._stopping = False
        if frame is not None:
            await super().start(frame)
        await self._ensure_started()

    async def stop(self, frame: Frame | None = None):
        self._stopping = True
        self._disabled = True
        await self._disconnect()
        if frame is not None:
            await super().stop(frame)

    async def _connect(self):
        if self._stopping or self._disabled:
            return
        # Prevent rapid reconnection loops to avoid rate limits
        now = asyncio.get_event_loop().time()
        if now - self._last_reconnect_time < 2.0:
            await asyncio.sleep(2.0)
            if self._stopping or self._disabled:
                return
        self._last_reconnect_time = asyncio.get_event_loop().time()

        query = urllib.parse.urlencode(
            {
                "language-code": self._language_code,
                "model": self._model,
                "mode": self._mode,
                "sample_rate": str(self._sample_rate),
                "input_audio_codec": self._input_audio_codec,
                "high_vad_sensitivity": str(self._high_vad_sensitivity).lower(),
                "vad_signals": "true",
                "flush_signal": "true",
            }
        )
        url = f"wss://api.sarvam.ai/speech-to-text/ws?{query}"
        headers = {"Api-Subscription-Key": self.api_key}
        print("[sarvam-stt] opening continuous websocket")
        self._websocket = await websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=10,
        )
        self._receiver_task = asyncio.create_task(self._receive_loop())
        print("[sarvam-stt] continuous websocket ready")

    async def _disconnect(self):
        if self._receiver_task:
            self._receiver_task.cancel()
            with contextlib.suppress(BaseException):
                await self._receiver_task
            self._receiver_task = None
        if self._websocket:
            await self._websocket.close()
            self._websocket = None

    async def _ensure_started(self):
        if self._disabled or self._stopping:
            return
        if self._websocket is None or getattr(self._websocket, "closed", False):
            await self._connect()

    async def run_stt(self, audio: bytes, *args, **kwargs) -> AsyncGenerator[Frame | None, None]:
        # This is handled by process_audio_frame in continuous mode
        if False: yield None

    async def process_audio_frame(self, frame: AudioRawFrame, direction: FrameDirection):
        await self._ensure_started()
        if self._disabled or self._websocket is None:
            return
        pcm_bytes, effective_sample_rate = self._normalize_audio(frame.audio, frame.sample_rate, frame.num_channels)
        payload_bytes = self._encode_audio_payload(pcm_bytes, effective_sample_rate, frame.num_channels)
        self._sent_audio_packets += 1
        if self._sent_audio_packets <= 3 or self._sent_audio_packets % 100 == 0:
            print(
                f"[sarvam-stt] send audio #{self._sent_audio_packets}: "
                f"bytes={len(payload_bytes)} sample_rate={effective_sample_rate} codec={self._input_audio_codec}"
            )
        message = {
            "audio": {
                "data": base64.b64encode(payload_bytes).decode("ascii"),
                "sample_rate": effective_sample_rate,
                "encoding": self._input_audio_codec,
            }
        }
        try:
            await self._websocket.send(json.dumps(message))
        except Exception as exc:
            if self._stopping:
                return
            print(f"[sarvam-stt] send error: {exc}")
            await self._disconnect()

    async def _receive_loop(self):
        try:
            async for response in self._websocket:
                data = json.loads(response)
                await self._handle_server_message(data)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if self._stopping:
                return
            print(f"[sarvam-stt] receive loop error: {exc}")

    async def _handle_server_message(self, data: dict):
        msg_type = str(data.get("type") or "").lower()
        if msg_type == "error":
            print(f"[sarvam-stt] api error: {data}")
            message = str((data.get("data") or {}).get("message") or "")
            if "audio.encoding" in message or "rate limit exceeded" in message.lower():
                self._disabled = True
                await self._disconnect()
            return
            
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        event_name = str(payload.get("event_type") or payload.get("signal_type") or "").lower()
        
        if "speech_start" in event_name:
            await self._handle_speech_start()
        elif "speech_end" in event_name:
            await self._handle_speech_end()
        
        transcript = payload.get("transcript", "").strip()
        if transcript:
            print(f"[sarvam-stt] final transcript: {transcript}")
            await self.push_frame(TranscriptionFrame(transcript, "", time_now_iso8601()))

    async def _handle_speech_start(self):
        if not self._server_user_speaking:
            self._server_user_speaking = True
            print("[sarvam-stt] sarvam speech_start")
            await self.push_frame(VADUserStartedSpeakingFrame())
            await self.push_frame(UserStartedSpeakingFrame())
            await self.push_frame(InterruptionFrame(), FrameDirection.UPSTREAM)

    async def _handle_speech_end(self):
        if self._server_user_speaking:
            self._server_user_speaking = False
            print("[sarvam-stt] sarvam speech_end")
            await self.push_frame(VADUserStoppedSpeakingFrame())
            await self.push_frame(UserStoppedSpeakingFrame())

    async def _send_flush(self):
        if self._disabled or self._stopping or self._websocket is None:
            return
        try:
            print("[sarvam-stt] sending flush")
            await self._websocket.send(json.dumps({"type": "flush"}))
        except Exception as exc:
            if self._stopping:
                return
            print(f"[sarvam-stt] flush error: {exc}")
            await self._disconnect()

    async def flush(self):
        await self._send_flush()

    @staticmethod
    def _encode_audio_payload(audio: bytes, sample_rate: int, num_channels: int) -> bytes:
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wav_file:
                wav_file.setnchannels(num_channels)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(audio)
            return buffer.getvalue()

    def _normalize_audio(self, audio: bytes, sample_rate: int, num_channels: int) -> tuple[bytes, int]:
        if self._sample_rate == sample_rate:
            return audio, sample_rate

        if num_channels != 1:
            return audio, sample_rate

        if sample_rate == 8000 and self._sample_rate == 16000:
            sample_count = len(audio) // 2
            samples = struct.unpack(f"<{sample_count}h", audio)
            upsampled = bytearray()
            for sample in samples:
                upsampled.extend(struct.pack("<h", sample))
                upsampled.extend(struct.pack("<h", sample))
            return bytes(upsampled), 16000

        return audio, sample_rate

class SarvamStreamingTTSService(TTSService):
    def __init__(self, api_key: str, speaker: str = "shreya", model: str = "bulbul:v3", sample_rate: int = 8000, min_buffer_size: int = 30, language_code: str = "hi-IN"):
        super().__init__(
            text_aggregation_mode=TextAggregationMode.SENTENCE,
            sample_rate=sample_rate,
            settings=TTSSettings(model=model, voice=speaker, language=language_code),
        )
        self.api_key = api_key
        self._speaker = speaker
        self._model = model
        self._sample_rate = sample_rate
        self._min_buffer_size = min_buffer_size
        self._language_code = language_code
        self._websocket = None
        print(f"[sarvam-tts] streaming initialized speaker={speaker} min_buffer={min_buffer_size} lang={language_code}")

    async def start(self, frame: StartFrame | None = None):
        if frame is not None: await super().start(frame)
        initial_lang = "hi-IN" if self._language_code == "multilingual" else self._language_code
        await self._ensure_started(initial_lang)

    async def stop(self, frame: Frame | None = None):
        await self._disconnect()
        if frame is not None: await super().stop(frame)

    async def _connect(self, language_code: str):
        self._language_code = language_code
        url = f"wss://api.sarvam.ai/text-to-speech/ws?model={self._model}&send_completion_event=true"
        headers = {"Api-Subscription-Key": self.api_key}
        print("[sarvam-tts] opening websocket")
        self._websocket = await websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=10,
        )

        config = {
            "model": self._model,
            "speaker": self._speaker,
            "target_language_code": self._language_code,
            "speech_sample_rate": self._sample_rate,
            "output_audio_codec": "linear16",
            "min_buffer_size": self._min_buffer_size,
        }
        await self._websocket.send(json.dumps({"type": "config", "data": config}))
        print(f"[sarvam-tts] websocket ready (speaker={self._speaker}, sr={self._sample_rate}, lang={self._language_code})")

        # Pre-warm TTS to eliminate first-turn cold start penalty
        await self._warm_up()

    async def _warm_up(self):
        try:
            await asyncio.sleep(0.1)
            await self._websocket.send(json.dumps({"type": "text", "data": {"text": "ह"}}))
            await self._websocket.send(json.dumps({"type": "flush"}))
            while True:
                response = await asyncio.wait_for(self._websocket.recv(), timeout=5.0)
                data = json.loads(response)
                if data.get("type") == "event" and data.get("data", {}).get("event_type") == "final":
                    break
            print("[sarvam-tts] warm-up complete")
        except Exception as e:
            print(f"[sarvam-tts] warm-up skipped: {e}")

    async def _disconnect(self):
        if self._websocket:
            with contextlib.suppress(Exception):
                await self._websocket.close()
            self._websocket = None

    async def _ensure_started(self, language_code: str):
        if self._websocket is None or getattr(self._websocket, "closed", False):
            await self._connect(language_code)
        elif language_code != self._language_code:
            self._language_code = language_code
            config = {
                "model": self._model,
                "speaker": self._speaker,
                "target_language_code": self._language_code,
                "speech_sample_rate": self._sample_rate,
                "output_audio_codec": "linear16",
                "min_buffer_size": self._min_buffer_size,
            }
            try:
                print(f"[sarvam-tts] dynamically switching websocket language config to {language_code}")
                await self._websocket.send(json.dumps({"type": "config", "data": config}))
            except Exception as e:
                print(f"[sarvam-tts] failed to send config update: {e}, reconnecting...")
                await self._disconnect()
                await self._connect(language_code)

    async def run_tts(self, text: str, *args, **kwargs) -> AsyncGenerator[Frame | None, None]:
        if not text.strip():
            return
        
        target_lang = self._language_code
        if target_lang == "multilingual":
            target_lang = detect_language(text, default="hi-IN")
            print(f"[sarvam-tts] detected language '{target_lang}' for text: {text!r}")
            
        try:
            await self._ensure_started(target_lang)
            # Send the text
            await self._websocket.send(json.dumps({"type": "text", "data": {"text": text}}))
            # Signal end-of-input so Sarvam produces audio
            await self._websocket.send(json.dumps({"type": "flush"}))

            audio_chunks = 0
            while True:
                response = await asyncio.wait_for(self._websocket.recv(), timeout=10.0)
                data = json.loads(response)
                msg_type = data.get("type", "")

                if msg_type == "error":
                    print(f"[sarvam-tts] API error: {data}")
                    break

                payload = data.get("data", {})
                if "audio" in payload:
                    audio_bytes = base64.b64decode(payload["audio"])
                    audio_chunks += 1
                    yield TTSAudioRawFrame(audio_bytes, self._sample_rate, 1)

                if msg_type == "event" and payload.get("event_type") == "final":
                    break

            print(f"[sarvam-tts] done: {audio_chunks} chunks yielded")
        except asyncio.TimeoutError:
            print(f"[sarvam-tts] timeout waiting for audio, reconnecting...")
            await self._disconnect()
        except Exception as e:
            print(f"[sarvam-tts] stream error: {e}, reconnecting...")
            await self._disconnect()

class SarvamSTTService(SegmentedSTTService):
    # Standard legacy implementation for fallback or other agents
    def __init__(self, api_key: str, model: str = "saaras:v3", language_code: str = "hi-IN"):
        super().__init__()
        self.api_key = api_key
        self._model = model
        self._language_code = language_code
        self._http_client = httpx.AsyncClient(base_url="https://api.sarvam.ai", headers={"api-subscription-key": api_key})

    async def run_stt(self, audio: bytes, *args, **kwargs) -> AsyncGenerator[Frame, None]:
        if not audio: return
        response = await self._http_client.post("/speech-to-text", files={"file": ("audio.wav", audio, "audio/wav")}, data={"model": self._model, "language_code": self._language_code, "input_audio_codec": "pcm_s16le"})
        transcript = response.json().get("transcript", "").strip()
        if transcript: yield TranscriptionFrame(transcript, "", time_now_iso8601())

class SarvamTTSService(TTSService):
    # Standard legacy implementation
    def __init__(self, api_key: str, speaker: str = "shreya", model: str = "bulbul:v3", sample_rate: int = 8000, language_code: str = "hi-IN"):
        super().__init__(
            settings=TTSSettings(model=model, voice=speaker, language=language_code),
        )
        self.api_key = api_key
        self._speaker = speaker
        self._model = model
        self._sample_rate = sample_rate
        self._language_code = language_code
        self._http_client = httpx.AsyncClient(base_url="https://api.sarvam.ai", headers={"api-subscription-key": api_key})

    async def run_tts(self, text: str, *args, **kwargs) -> AsyncGenerator[Frame, None]:
        if not text.strip(): return
        
        target_lang = self._language_code
        if target_lang == "multilingual":
            target_lang = detect_language(text, default="hi-IN")
            print(f"[sarvam-tts][rest] detected language '{target_lang}' for text: {text!r}")
            
        payload = {
            "inputs": [text],
            "target_language_code": target_lang,
            "model": self._model,
            "speaker": self._speaker,
            "speech_sample_rate": self._sample_rate,
            "enable_preprocessing": True,
            "pace": 1.1,
            "temperature": 0.4
        }
        
        try:
            response = await self._http_client.post("/text-to-speech", json=payload)
            if response.status_code != 200:
                print(f"[sarvam-tts] REST API returned error status {response.status_code}: {response.text}")
                return
                
            data = response.json()
            if "audios" not in data or not data["audios"]:
                print(f"[sarvam-tts] REST API did not return audios: {data}")
                return
                
            import io
            import wave
            
            wav_bytes = base64.b64decode(data["audios"][0])
            with wave.open(io.BytesIO(wav_bytes)) as wf:
                pcm_bytes = wf.readframes(wf.getnframes())
                
            yield TTSAudioRawFrame(pcm_bytes, self._sample_rate, 1)
            print(f"[sarvam-tts] Successfully generated bulbul:v3 REST TTS audio chunk ({len(pcm_bytes)} bytes)")
            
        except Exception as e:
            print(f"[sarvam-tts] REST API exception during synthesis: {e}")
