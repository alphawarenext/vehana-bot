"""Abstract telephony provider — Ozonetel and Twilio both implement this."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CallStatus(str, Enum):
    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"


@dataclass
class CallResult:
    call_sid: str
    status: CallStatus
    error: Optional[str] = None


class BaseTelephonyProvider(ABC):

    @abstractmethod
    async def make_call(self, to: str, from_did: str, webhook_url: str) -> CallResult:
        """Initiate an outbound call. Returns call_sid on success."""
        ...

    @abstractmethod
    async def get_call_status(self, call_sid: str) -> CallStatus:
        ...

    @abstractmethod
    async def end_call(self, call_sid: str) -> bool:
        ...

    @abstractmethod
    def build_stream_response(self, websocket_url: str) -> str:
        """Return the XML/response body that connects Twilio/Ozonetel to our WebSocket."""
        ...
