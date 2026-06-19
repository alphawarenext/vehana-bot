from datetime import datetime, timezone
from typing import Optional, List, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel
from sqlmodel import select

from api.deps import CurrentOrg, DBSession, OrgAdmin, check_call_quota
from models.campaign import Campaign, CampaignStatus
from models.voice_agent import VoiceAgent

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str
    agent_id: UUID
    objective: str = ""
    notes: Optional[str] = None
    schedule_at: Optional[datetime] = None
    contacts: Optional[List[str]] = None  # list of phone numbers


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    agent_id: Optional[UUID] = None
    objective: Optional[str] = None
    notes: Optional[str] = None
    schedule_at: Optional[datetime] = None
    contacts: Optional[List[str]] = None
    status: Optional[CampaignStatus] = None


class CampaignResponse(BaseModel):
    id: UUID
    org_id: UUID
    agent_id: UUID
    name: str
    status: CampaignStatus
    audience_count: int
    calls_made: int
    calls_connected: int
    calls_failed: int
    schedule_at: Optional[datetime]
    objective: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[CampaignResponse])
async def list_campaigns(org: CurrentOrg, session: DBSession):
    result = await session.exec(
        select(Campaign).where(Campaign.org_id == org.id).order_by(Campaign.created_at.desc())
    )
    return result.all()


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(body: CampaignCreate, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    # Verify agent belongs to this org
    agent = await session.get(VoiceAgent, body.agent_id)
    if not agent or agent.org_id != org.id:
        raise HTTPException(status_code=404, detail="Agent not found")

    campaign = Campaign(
        org_id=org.id,
        **body.model_dump(),
        audience_count=len(body.contacts or []),
    )
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    return campaign


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: UUID, org: CurrentOrg, session: DBSession):
    campaign = await session.get(Campaign, campaign_id)
    if not campaign or campaign.org_id != org.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(campaign_id: UUID, body: CampaignUpdate, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    campaign = await session.get(Campaign, campaign_id)
    if not campaign or campaign.org_id != org.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == CampaignStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Cannot edit a running campaign. Pause it first.")

    update_data = body.model_dump(exclude_unset=True)
    if "contacts" in update_data and update_data["contacts"] is not None:
        update_data["audience_count"] = len(update_data["contacts"])
    for field, value in update_data.items():
        setattr(campaign, field, value)
    campaign.updated_at = datetime.utcnow()
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/launch")
async def launch_campaign(campaign_id: UUID, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    """Enqueue the campaign into Celery for execution."""
    from workers.campaign_tasks import run_campaign

    campaign = await session.get(Campaign, campaign_id)
    if not campaign or campaign.org_id != org.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED, CampaignStatus.SCHEDULED):
        raise HTTPException(status_code=400, detail=f"Cannot launch campaign in '{campaign.status}' state")
    if not campaign.contacts:
        raise HTTPException(status_code=400, detail="Campaign has no contacts")

    # Check quota
    if org.calls_used_this_month + len(campaign.contacts) > org.calls_limit_monthly:
        raise HTTPException(
            status_code=429,
            detail=f"Launching this campaign would exceed your monthly quota of {org.calls_limit_monthly} calls."
        )

    task = run_campaign.delay(str(campaign_id))
    campaign.status = CampaignStatus.RUNNING
    campaign.celery_task_id = task.id
    campaign.started_at = datetime.utcnow()
    campaign.updated_at = datetime.utcnow()
    session.add(campaign)
    await session.commit()

    return {"message": "Campaign launched", "task_id": task.id}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: UUID, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    from workers.celery_app import celery_app

    campaign = await session.get(Campaign, campaign_id)
    if not campaign or campaign.org_id != org.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status != CampaignStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Campaign is not running")

    if campaign.celery_task_id:
        celery_app.control.revoke(campaign.celery_task_id, terminate=True)

    campaign.status = CampaignStatus.PAUSED
    campaign.updated_at = datetime.utcnow()
    session.add(campaign)
    await session.commit()

    return {"message": "Campaign paused"}


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(campaign_id: UUID, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    campaign = await session.get(Campaign, campaign_id)
    if not campaign or campaign.org_id != org.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == CampaignStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Pause the campaign before deleting")
    await session.delete(campaign)
    await session.commit()
