"""
Per-org telephony configuration (Ozonetel / Twilio credentials + DID pool).
Only ORG_ADMIN and SUPER_ADMIN can read or write this.
"""
import json
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from api.deps import CurrentOrg, DBSession, OrgAdmin
from core.security import encrypt_secret, decrypt_secret
from models.telephony import TelephonyConfig, TelephonyProvider

router = APIRouter(prefix="/telephony", tags=["telephony"])


class TelephonyConfigCreate(BaseModel):
    provider: TelephonyProvider = TelephonyProvider.OZONETEL
    api_key: str
    username: Optional[str] = None
    agent_id: Optional[str] = None
    agent_email: Optional[str] = None
    agent_password: Optional[str] = None
    # Twilio
    account_sid: Optional[str] = None
    auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    # DID pool
    did_numbers: Optional[List[str]] = None
    max_concurrent_calls: int = 5
    calls_per_minute_limit: int = 10


class TelephonyConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    agent_password: Optional[str] = None
    auth_token: Optional[str] = None
    did_numbers: Optional[List[str]] = None
    max_concurrent_calls: Optional[int] = None
    calls_per_minute_limit: Optional[int] = None
    is_active: Optional[bool] = None


class TelephonyConfigResponse(BaseModel):
    id: UUID
    org_id: UUID
    provider: TelephonyProvider
    username: Optional[str]
    agent_id: Optional[str]
    agent_email: Optional[str]
    account_sid: Optional[str]
    twilio_phone_number: Optional[str]
    did_numbers: List[str]
    max_concurrent_calls: int
    calls_per_minute_limit: int
    is_active: bool
    updated_at: datetime
    # NOTE: encrypted fields (api_key, passwords) are never returned


@router.get("", response_model=TelephonyConfigResponse)
async def get_telephony_config(org: CurrentOrg, _: OrgAdmin, session: DBSession):
    result = await session.exec(select(TelephonyConfig).where(TelephonyConfig.org_id == org.id))
    config = result.first()
    if not config:
        raise HTTPException(status_code=404, detail="No telephony config found. Create one first.")
    return _to_response(config)


@router.post("", response_model=TelephonyConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_telephony_config(body: TelephonyConfigCreate, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    existing = await session.exec(select(TelephonyConfig).where(TelephonyConfig.org_id == org.id))
    if existing.first():
        raise HTTPException(status_code=400, detail="Telephony config already exists. Use PATCH to update.")

    config = TelephonyConfig(
        org_id=org.id,
        provider=body.provider,
        api_key_enc=encrypt_secret(body.api_key),
        username=body.username,
        agent_id=body.agent_id,
        agent_email=body.agent_email,
        agent_password_enc=encrypt_secret(body.agent_password) if body.agent_password else None,
        account_sid=body.account_sid,
        auth_token_enc=encrypt_secret(body.auth_token) if body.auth_token else None,
        twilio_phone_number=body.twilio_phone_number,
        did_numbers=json.dumps(body.did_numbers or []),
        max_concurrent_calls=body.max_concurrent_calls,
        calls_per_minute_limit=body.calls_per_minute_limit,
    )
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return _to_response(config)


@router.patch("", response_model=TelephonyConfigResponse)
async def update_telephony_config(body: TelephonyConfigUpdate, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    result = await session.exec(select(TelephonyConfig).where(TelephonyConfig.org_id == org.id))
    config = result.first()
    if not config:
        raise HTTPException(status_code=404, detail="No telephony config found")

    if body.api_key is not None:
        config.api_key_enc = encrypt_secret(body.api_key)
    if body.agent_password is not None:
        config.agent_password_enc = encrypt_secret(body.agent_password)
    if body.auth_token is not None:
        config.auth_token_enc = encrypt_secret(body.auth_token)
    if body.did_numbers is not None:
        config.did_numbers = json.dumps(body.did_numbers)
    if body.max_concurrent_calls is not None:
        config.max_concurrent_calls = body.max_concurrent_calls
    if body.calls_per_minute_limit is not None:
        config.calls_per_minute_limit = body.calls_per_minute_limit
    if body.is_active is not None:
        config.is_active = body.is_active

    config.updated_at = datetime.utcnow()
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return _to_response(config)


def _to_response(config: TelephonyConfig) -> TelephonyConfigResponse:
    return TelephonyConfigResponse(
        id=config.id,
        org_id=config.org_id,
        provider=config.provider,
        username=config.username,
        agent_id=config.agent_id,
        agent_email=config.agent_email,
        account_sid=config.account_sid,
        twilio_phone_number=config.twilio_phone_number,
        did_numbers=json.loads(config.did_numbers or "[]"),
        max_concurrent_calls=config.max_concurrent_calls,
        calls_per_minute_limit=config.calls_per_minute_limit,
        is_active=config.is_active,
        updated_at=config.updated_at,
    )
