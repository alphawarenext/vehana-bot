"""
Ozonetel webhook + WebSocket routes.

Inbound call flow (configure ONE URL in Ozonetel dashboard per DID):
  GET /api/v2/webhooks/inbound?dnis=<called_DID>&cid=<caller_number>
  → look up which org owns that DID (from TelephonyConfig.did_numbers)
  → find that org's active inbound VoiceAgent
  → return stream XML with WebSocket URL for that agent

Outbound call flow (no Ozonetel dashboard config needed):
  campaign_tasks.py calls OzonetelProvider.make_call(to, from_did, ws_url)
  → GET outbound.php?extra_data=<stream XML with ws_url>
  → Ozonetel dials customer; when they answer, opens WebSocket directly
"""
import json
import time
from uuid import UUID

from fastapi import APIRouter, Request, Response, WebSocket
from loguru import logger
from sqlmodel import select

from core.config import settings
from core.database import AsyncSessionLocal
from models.voice_agent import VoiceAgent
from models.telephony import TelephonyConfig
from services.pipeline.gemini_live import run_gemini_live_stream
from services.telephony.registry import call_registry

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

DEFAULT_MAX_CONCURRENT = 10  # used if org has no TelephonyConfig


def _wss_base() -> str:
    if settings.BASE_URL.startswith("https://"):
        return settings.BASE_URL.replace("https://", "wss://")
    return settings.BASE_URL.replace("http://", "ws://")


def _get_qp(qp: dict, key: str) -> str | None:
    """Ozonetel sometimes XML-escapes & to amp; in query params."""
    return qp.get(key) or qp.get(f"amp;{key}")


def _resolve_did(qp: dict) -> str:
    did = (
        _get_qp(qp, "dnis")
        or _get_qp(qp, "did")
        or _get_qp(qp, "called_number")
        or settings.OZONETEL_DID
        or "525836"
    )
    did = str(did).replace("+", "").strip()
    if len(did) > 8:
        did = settings.OZONETEL_DID or "525836"
    return did


# ─── Shared helpers ──────────────────────────────────────────────────────────

def _lifecycle_response(event: str | None, status: str | None) -> Response | None:
    """Return early for Ozonetel lifecycle events that don't need a stream."""
    if event == "Stream":
        return Response(content="<?xml version='1.0'?><response></response>", media_type="text/xml")
    if event == "Dial":
        return Response(content="<?xml version='1.0'?><response><hangup/></response>", media_type="text/xml")
    if event in ("Hangup", "Disconnect") or status in ("not_answered", "failed"):
        return Response(content="OK", media_type="text/plain")
    return None


def _build_stream_xml(agent_id: UUID, qp: dict, call_direction: str = "inbound") -> Response:
    """Build the Ozonetel <stream> XML for a given agent, forwarding call context."""
    from_num = _get_qp(qp, "cid") or _get_qp(qp, "caller_id") or ""
    to_num   = _get_qp(qp, "dnis") or _get_qp(qp, "called_number") or _get_qp(qp, "did") or ""
    borrower_id  = _get_qp(qp, "borrower_id") or ""
    campaign_id  = _get_qp(qp, "campaign_id") or ""

    ws_params: dict[str, str] = {"call_direction": call_direction}
    if from_num:
        ws_params["from_number"] = from_num
    if to_num:
        ws_params["to_number"] = to_num
    if borrower_id:
        ws_params["borrower_id"] = borrower_id
    if campaign_id:
        ws_params["campaign_id"] = campaign_id

    ws_url = _wss_base() + f"/api/v2/webhooks/{agent_id}/stream"
    if ws_params:
        ws_url += "?" + "&amp;".join(f"{k}={v}" for k, v in ws_params.items())

    did = _resolve_did(qp)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<response>
  <stream is_sip="true" bidirectional="true" url="{ws_url}">{did}</stream>
</response>"""
    logger.info(f"[ozonetel] stream XML → {ws_url} (DID={did})")
    return Response(content=xml, media_type="text/xml")


# ─── DID-based inbound webhook (configure THIS in Ozonetel dashboard) ─────────

@router.api_route("/inbound", methods=["GET", "POST"])
async def ozonetel_inbound(request: Request):
    """
    Single URL configured in Ozonetel dashboard for ALL inbound DIDs.

    Ozonetel passes `dnis` = the DID that was called.
    We look up which org owns that DID → find their active inbound VoiceAgent
    → return stream XML with that agent's WebSocket URL.

    Ozonetel dashboard config:
        https://v2.vehana.ai/api/v2/webhooks/inbound
    """
    qp = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            for k, v in form.items():
                qp[k] = str(v)
        except Exception:
            pass

    event  = _get_qp(qp, "event")
    status = _get_qp(qp, "status")
    called_did = (
        _get_qp(qp, "dnis") or _get_qp(qp, "did") or _get_qp(qp, "called_number") or ""
    ).replace("+", "").strip()

    logger.info(f"[ozonetel] inbound webhook dnis={called_did} event={event} status={status}")

    early = _lifecycle_response(event, status)
    if early:
        return early

    # Find which org owns this DID
    agent = None
    async with AsyncSessionLocal() as session:
        # Fetch all telephony configs and check did_numbers in Python
        # (did_numbers is a JSON array stored as string)
        result = await session.exec(select(TelephonyConfig))
        all_configs = result.all()

        matched_org_id = None
        for cfg in all_configs:
            if not cfg.did_numbers:
                continue
            try:
                dids = json.loads(cfg.did_numbers)
                # Normalise: strip + and spaces for comparison
                clean_dids = [str(d).replace("+", "").strip() for d in dids]
                if called_did in clean_dids:
                    matched_org_id = cfg.org_id
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        if matched_org_id:
            # Find the org's active inbound (or "both") VoiceAgent
            agent_result = await session.exec(
                select(VoiceAgent).where(
                    VoiceAgent.org_id == matched_org_id,
                    VoiceAgent.is_active == True,
                    VoiceAgent.call_direction.in_(["inbound", "both"]),
                )
            )
            agent = agent_result.first()

    if not agent:
        logger.warning(f"[ozonetel] No active inbound agent found for DID {called_did} — returning hangup")
        return Response(
            content="<?xml version='1.0'?><response><hangup/></response>",
            media_type="text/xml",
        )

    return _build_stream_xml(agent.id, qp, call_direction="inbound")


# ─── Agent-specific answer webhook (used by outbound extra_data flow) ─────────

@router.api_route("/{agent_id}/answer", methods=["GET", "POST"])
async def ozonetel_answer(agent_id: UUID, request: Request):
    """
    Agent-specific answer webhook.
    Used as fallback — primarily the /inbound endpoint is configured in Ozonetel.
    """
    qp = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            for k, v in form.items():
                qp[k] = str(v)
        except Exception:
            pass

    event  = _get_qp(qp, "event")
    status = _get_qp(qp, "status")
    logger.info(f"[ozonetel] answer webhook agent={agent_id} event={event} status={status}")

    early = _lifecycle_response(event, status)
    if early:
        return early

    call_direction = _get_qp(qp, "call_direction") or "outbound"
    return _build_stream_xml(agent_id, qp, call_direction=call_direction)


# ─── WebSocket audio stream ───────────────────────────────────────────────────

@router.websocket("/{agent_id}/stream")
async def ozonetel_stream(
    agent_id: UUID,
    websocket: WebSocket,
    from_number: str | None = None,
    to_number: str | None = None,
    borrower_id: str | None = None,
    campaign_id: str | None = None,
    call_direction: str = "outbound",
):
    """
    Bidirectional audio WebSocket. Ozonetel connects here after the answer webhook.
    Runs a Gemini Live pipeline for the duration of the call.
    """
    await websocket.accept()

    # Load agent + org from DB (no JWT auth — this is called by Ozonetel server)
    async with AsyncSessionLocal() as session:
        agent = await session.get(VoiceAgent, agent_id)
        telephony_cfg = None
        if agent:
            result = await session.exec(
                select(TelephonyConfig).where(TelephonyConfig.org_id == agent.org_id)
            )
            telephony_cfg = result.first()

    if not agent or not agent.is_active:
        logger.warning(f"[ws] agent {agent_id} not found or inactive — closing")
        await websocket.close(code=1008)
        return

    org_id = agent.org_id
    max_concurrent = (telephony_cfg.max_concurrent_calls if telephony_cfg else DEFAULT_MAX_CONCURRENT)

    # Generate a unique call_sid immediately — the pipeline reads all WebSocket
    # messages itself (including Ozonetel's 'start' event with ucid).
    # We don't consume any message here so nothing is lost.
    call_sid = f"call-{agent_id}-{int(time.time())}"

    caller_phone = from_number or ""
    logger.info(f"[ws] call starting agent={agent_id} org={org_id} sid={call_sid} from={caller_phone}")

    # Check concurrency limits
    allowed, reason = await call_registry.can_accept_call(org_id, caller_phone, max_concurrent)
    if not allowed:
        logger.warning(f"[ws] call blocked: {reason}")
        await websocket.close(code=1008)
        return

    # Register active call
    await call_registry.register(
        org_id=org_id,
        call_sid=call_sid,
        phone=caller_phone,
        agent_id=str(agent_id),
    )

    # Resolve optional UUID params
    _borrower_id: UUID | None = None
    _campaign_id: UUID | None = None
    try:
        if borrower_id:
            _borrower_id = UUID(borrower_id)
        if campaign_id:
            _campaign_id = UUID(campaign_id)
    except ValueError:
        pass

    # Load borrower data as contact_data if available
    contact_data: dict | None = None
    if _borrower_id:
        async with AsyncSessionLocal() as session:
            from models.borrower import Borrower
            borrower = await session.get(Borrower, _borrower_id)
            if borrower:
                contact_data = {
                    "Name": borrower.name,
                    "Due_Amount": str(borrower.emi_amount),
                    "Due_Date": str(borrower.emi_due_date or ""),
                }

    try:
        await run_gemini_live_stream(
            websocket=websocket,
            call_sid=call_sid,
            agent=agent,
            org_id=org_id,
            caller_number=from_number,
            callee_number=to_number,
            contact_data=contact_data,
            campaign_id=_campaign_id,
            borrower_id=_borrower_id,
        )
    finally:
        await call_registry.release(org_id=org_id, call_sid=call_sid, phone=caller_phone)
        logger.info(f"[ws] call {call_sid} released from registry")
