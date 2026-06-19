"""
Campaign dialing tasks — run by Celery workers, not the FastAPI process.

Flow:
  run_campaign(campaign_id)
    → for each contact: dial_contact.apply_async(...)
    → dial_contact: DND check → concurrency check → make_call → log CallLog
"""
import asyncio
import json
from uuid import UUID
from datetime import datetime, timezone

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlmodel import select

from core.database import AsyncSessionLocal
from models.campaign import Campaign, CampaignStatus
from models.borrower import Borrower, CallLog, CallOutcome
from services.telephony.base import CallStatus
from models.organization import Organization
from services.telephony.factory import get_telephony_provider
from services.telephony.registry import call_registry
from services.dnd import is_dnd

logger = get_task_logger(__name__)


def _run(coro):
    """Run an async coroutine from a sync Celery task."""
    return asyncio.get_event_loop().run_until_complete(coro)


@shared_task(bind=True, max_retries=0, name="workers.campaign_tasks.run_campaign")
def run_campaign(self, campaign_id: str):
    """
    Top-level campaign task. Fans out individual dial_contact tasks
    respecting the org's calls_per_minute_limit.
    """
    async def _inner():
        async with AsyncSessionLocal() as session:
            campaign = await session.get(Campaign, UUID(campaign_id))
            if not campaign or campaign.status != CampaignStatus.RUNNING:
                logger.warning(f"Campaign {campaign_id} not found or not running — aborting")
                return

            org = await session.get(Organization, campaign.org_id)
            contacts: list = campaign.contacts or []

            logger.info(f"[Campaign {campaign_id}] Starting {len(contacts)} contacts for org {org.slug}")

            delay_seconds = 60 / max(org.calls_limit_monthly // 30, 1)  # rough rate limit

            for i, phone in enumerate(contacts):
                if isinstance(phone, dict):
                    phone = phone.get("phone") or phone.get("number") or ""
                if not phone:
                    continue
                dial_contact.apply_async(
                    args=[campaign_id, str(campaign.org_id), phone],
                    countdown=i * delay_seconds,
                )

    _run(_inner())


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=300,  # retry after 5 min
    name="workers.campaign_tasks.dial_contact",
)
def dial_contact(self, campaign_id: str, org_id: str, phone: str):
    """
    Dials a single contact. Handles:
    - DND check
    - Concurrency limit check
    - Actual Ozonetel/Twilio API call
    - CallLog creation
    """
    async def _inner():
        async with AsyncSessionLocal() as session:
            org_uuid = UUID(org_id)
            campaign_uuid = UUID(campaign_id)

            # DND check
            if await is_dnd(org_uuid, phone, session):
                logger.info(f"[DND] Skipping {phone} for org {org_id}")
                return

            # Concurrency check — get org's limit from telephony config
            from models.telephony import TelephonyConfig
            tc_result = await session.exec(
                select(TelephonyConfig).where(TelephonyConfig.org_id == org_uuid)
            )
            tc = tc_result.first()
            max_concurrent = tc.max_concurrent_calls if tc else 5

            allowed, reason = await call_registry.can_accept_call(org_uuid, phone, max_concurrent)
            if not allowed:
                logger.warning(f"[Rate limit] {phone}: {reason} — will retry")
                raise self.retry(countdown=60)

            # Find borrower
            borrower_result = await session.exec(
                select(Borrower).where(Borrower.org_id == org_uuid, Borrower.phone == phone)
            )
            borrower = borrower_result.first()

            # Make the call via Ozonetel CPaaS outbound.php.
            # We pass the WebSocket URL directly in extra_data — Ozonetel connects
            # to it when the customer answers (no answer webhook callback needed).
            from core.config import settings
            campaign = await session.get(Campaign, campaign_uuid)
            provider = await get_telephony_provider(org_uuid, session)

            # Build the WebSocket URL with context so the pipeline knows the org/borrower
            ws_params: dict[str, str] = {"call_direction": "outbound"}
            if borrower:
                ws_params["borrower_id"] = str(borrower.id)
            ws_params["campaign_id"] = campaign_id

            wss_base = settings.BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
            ws_url = (
                f"{wss_base}/api/v2/webhooks/{campaign.agent_id}/stream"
                + "?" + "&".join(f"{k}={v}" for k, v in ws_params.items())
            )

            from_did = ""
            if tc and tc.did_numbers:
                dids = json.loads(tc.did_numbers)
                from_did = dids[0] if dids else ""

            result = await provider.make_call(
                to=phone,
                from_did=from_did,
                webhook_url=ws_url,   # this becomes extra_data stream XML in OzonetelProvider
            )

            if result.status == CallStatus.FAILED:
                logger.error(f"[Dial failed] {phone}: {result.error}")
                raise self.retry(countdown=300)

            # Create CallLog (borrower_id optional for non-EMI campaigns)
            call_log = CallLog(
                org_id=org_uuid,
                borrower_id=borrower.id if borrower else UUID("00000000-0000-0000-0000-000000000000"),
                campaign_id=campaign_uuid,
                call_sid=result.call_sid,
                outcome=CallOutcome.IN_PROGRESS,
            )
            session.add(call_log)

            # Increment org call counter
            org = await session.get(Organization, org_uuid)
            org.calls_used_this_month += 1
            session.add(org)

            # Update campaign stats
            campaign = await session.get(Campaign, campaign_uuid)
            campaign.calls_made += 1
            session.add(campaign)

            await session.commit()
            logger.info(f"[Dialed] {phone} → call_sid={result.call_sid}")

    _run(_inner())
