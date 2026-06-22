"""
Returns the right telephony provider for a given org.
Falls back to Vehana pool credentials if org hasn't set their own.
"""
import json
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from core.config import settings
from core.security import decrypt_secret
from models.telephony import TelephonyConfig, TelephonyProvider
from services.telephony.base import BaseTelephonyProvider
from services.telephony.ozonetel import OzonetelProvider


async def get_telephony_provider(org_id: UUID, session: AsyncSession) -> BaseTelephonyProvider:
    result = await session.exec(
        select(TelephonyConfig).where(TelephonyConfig.org_id == org_id, TelephonyConfig.is_active == True)
    )
    config = result.first()

    if config and config.provider == TelephonyProvider.OZONETEL:
        # Use first DID from org's did_numbers as the outbound caller ID
        org_did = ""
        if config.did_numbers:
            try:
                dids = json.loads(config.did_numbers)
                org_did = dids[0] if dids else ""
            except (json.JSONDecodeError, TypeError):
                pass
        return OzonetelProvider(
            api_key=decrypt_secret(config.api_key_enc),
            username=config.username or "",
            agent_id=config.agent_id or "",
            did=org_did or None,
            trunk_extension=config.trunk_extension or None,
        )

    # Fall back to Vehana pool Ozonetel account
    return OzonetelProvider(
        api_key=settings.OZONETEL_API_KEY,
        username=settings.OZONETEL_USERNAME,
        agent_id=settings.OZONETEL_AGENT_ID,
    )
