"""
Super-admin dashboard — Vehana internal only.
Lists all orgs, their usage, costs, and allows manual controls.
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select, func

from api.deps import DBSession, SuperAdmin
from models.organization import Organization, PlanType
from models.user import User
from models.usage import UsageEvent

router = APIRouter(prefix="/admin", tags=["admin"])


class OrgAdminView(BaseModel):
    id: UUID
    name: str
    slug: str
    plan: PlanType
    is_active: bool
    calls_used_this_month: int
    calls_limit_monthly: int
    monthly_cost_usd: float
    user_count: int
    created_at: datetime


class OrgStatusUpdate(BaseModel):
    is_active: Optional[bool] = None
    calls_limit_monthly: Optional[int] = None
    plan: Optional[PlanType] = None


@router.get("/orgs", response_model=List[OrgAdminView])
async def list_all_orgs(_: SuperAdmin, session: DBSession):
    result = await session.exec(select(Organization).order_by(Organization.created_at.desc()))
    orgs = result.all()

    # Get user counts per org in one query
    counts_result = await session.exec(
        select(User.org_id, func.count(User.id).label("cnt")).group_by(User.org_id)
    )
    user_counts = {str(row.org_id): row.cnt for row in counts_result.all()}

    return [
        OrgAdminView(
            id=org.id,
            name=org.name,
            slug=org.slug,
            plan=org.plan,
            is_active=org.is_active,
            calls_used_this_month=org.calls_used_this_month,
            calls_limit_monthly=org.calls_limit_monthly,
            monthly_cost_usd=org.monthly_cost_usd,
            user_count=user_counts.get(str(org.id), 0),
            created_at=org.created_at,
        )
        for org in orgs
    ]


@router.patch("/orgs/{org_id}")
async def update_org_status(org_id: UUID, body: OrgStatusUpdate, _: SuperAdmin, session: DBSession):
    org = await session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Org not found")
    if body.is_active is not None:
        org.is_active = body.is_active
    if body.calls_limit_monthly is not None:
        org.calls_limit_monthly = body.calls_limit_monthly
    if body.plan is not None:
        org.plan = body.plan
    session.add(org)
    await session.commit()
    return {"message": "Updated", "org_id": str(org_id)}


@router.get("/orgs/{org_id}/cost")
async def get_org_cost_detail(_: SuperAdmin, org_id: UUID, session: DBSession):
    """Drill into one org's cost breakdown by provider."""
    result = await session.exec(
        select(
            UsageEvent.provider,
            UsageEvent.model,
            func.sum(UsageEvent.cost_usd).label("total"),
            func.count(UsageEvent.id).label("events"),
        )
        .where(UsageEvent.org_id == org_id)
        .where(func.date_trunc("month", UsageEvent.timestamp) == func.date_trunc("month", func.now()))
        .group_by(UsageEvent.provider, UsageEvent.model)
    )
    rows = result.all()
    return [{"provider": r.provider, "model": r.model, "total_usd": round(r.total or 0, 4), "events": r.events} for r in rows]
