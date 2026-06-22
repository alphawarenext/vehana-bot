"""
Ozonetel telephony provider — CPaaS outbound.php API.

How outbound works (CPaaS mode):
  1. We call outbound.php with phone_no + extra_data (the stream XML)
  2. Ozonetel dials the customer
  3. When customer answers, Ozonetel uses the XML in extra_data directly
     to open a bidirectional WebSocket to our server — NO callback URL needed
  4. Audio flows through the WebSocket

This means the WebSocket URL must be publicly accessible when the customer answers.
There is no "answer webhook" for outbound — the stream URL is baked into the dial request.

Inbound is different — Ozonetel calls our answer webhook (configured in their dashboard)
which returns the same XML dynamically.
"""
from urllib.parse import urlparse

import httpx

from core.config import settings
from services.telephony.base import BaseTelephonyProvider, CallResult, CallStatus


class OzonetelProvider(BaseTelephonyProvider):

    def __init__(
        self,
        api_key: str,
        username: str = "",
        agent_id: str = "",
        base_url: str | None = None,
        did: str | None = None,
        trunk_extension: str | None = None,
    ):
        self.api_key = api_key
        self.username = username
        self.agent_id = agent_id
        self.did = did or settings.OZONETEL_DID

        # trunk_extension is the SHORT Ozonetel SIP trunk ID (e.g. "525836") that goes
        # inside the <stream> body.  It is DIFFERENT from the full E.164 DID phone number.
        # All DIDs on the same Ozonetel account share one trunk extension.
        self.trunk_extension = trunk_extension or settings.OZONETEL_DID

        raw = base_url or settings.OZONETEL_BASE_URL or "in1-cpaas.ozonetel.com"
        parsed = urlparse(raw)
        voice_host = parsed.netloc or parsed.path
        if "/" in voice_host:
            voice_host = voice_host.split("/")[0]
        self._voice_host = voice_host

    def _outbound_url(self) -> str:
        return f"https://{self._voice_host}/outbound/outbound.php"

    def _clean_did(self) -> str:
        """Return the short SIP trunk extension for the <stream> body.

        Uses trunk_extension if configured (preferred).  Falls back to the DID
        phone number stripped of '+', and if that is still a full E.164 number
        (>8 digits) falls back to the hardcoded legacy Vehana trunk '525836'.
        """
        ext = str(self.trunk_extension or self.did or "525836").replace("+", "").strip()
        if len(ext) > 8:
            ext = "525836"
        return ext

    def _build_stream_xml(self, websocket_url: str) -> str:
        """The XML Ozonetel uses to connect the answered call to our WebSocket."""
        did = self._clean_did()
        return f'<response><stream is_sip="true" bidirectional="true" url="{websocket_url}">{did}</stream></response>'

    async def make_call(self, to: str, from_did: str, webhook_url: str) -> CallResult:
        """
        Initiate an outbound call via Ozonetel CPaaS outbound.php.

        `webhook_url` here is actually the WebSocket URL (wss://...) — we embed it
        in extra_data as stream XML. Ozonetel connects to it directly when the
        customer answers, no callback to our server.
        """
        clean_phone = to.replace("+", "").strip()
        caller_id = (from_did or self.did or "").replace("+", "").strip()

        # Build the WebSocket stream URL for this call
        # webhook_url is wss://your-domain/api/v2/webhooks/{agent_id}/stream
        extra_data = self._build_stream_xml(webhook_url)

        params: dict[str, str] = {
            "api_key": self.api_key,
            "phone_no": clean_phone,
            "extra_data": extra_data,
            "outbound_version": "2",
        }
        if caller_id:
            params["caller_id"] = caller_id

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(self._outbound_url(), params=params)
            body = resp.text.strip()

        success_tokens = ("queued", "success", "initiated", "callid", "ucid")
        error_tokens = ("error", "failed", "failure", "invalid")

        body_lower = body.lower()
        if any(t in body_lower for t in error_tokens):
            return CallResult(call_sid="", status=CallStatus.FAILED, error=body)
        if any(t in body_lower for t in success_tokens) or resp.status_code == 200:
            # Extract call ID if present (format: "QUEUED|<id>" or JSON)
            call_sid = body
            if "|" in body:
                parts = body.split("|", 1)
                if parts[0].upper() in ("QUEUED", "SUCCESS"):
                    call_sid = parts[1]
            return CallResult(call_sid=call_sid, status=CallStatus.QUEUED)

        return CallResult(call_sid="", status=CallStatus.FAILED, error=body)

    async def get_call_status(self, call_sid: str) -> CallStatus:
        return CallStatus.IN_PROGRESS

    async def end_call(self, call_sid: str) -> bool:
        return True

    def build_stream_response(self, websocket_url: str) -> str:
        """Used by the inbound answer webhook to return XML to Ozonetel."""
        return self._build_stream_xml(websocket_url)
