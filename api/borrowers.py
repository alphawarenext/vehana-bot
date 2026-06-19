from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from api.deps import CurrentOrg, DBSession, OrgAdmin
from models.borrower import Borrower

router = APIRouter(prefix="/borrowers", tags=["borrowers"])


class BorrowerCreate(BaseModel):
    name: str
    phone: str
    loan_account_last4: str = ""
    emi_amount: float = 0.0
    overdue_amount: float = 0.0
    days_past_due: int = 0
    bucket: str = "pre_due"
    lender_name: str = ""
    upi_id: Optional[str] = None
    payment_link: Optional[str] = None


class BorrowerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    emi_amount: Optional[float] = None
    overdue_amount: Optional[float] = None
    days_past_due: Optional[int] = None
    bucket: Optional[str] = None
    upi_id: Optional[str] = None
    payment_link: Optional[str] = None


class BorrowerResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    phone: str
    loan_account_last4: str
    emi_amount: float
    overdue_amount: float
    days_past_due: int
    bucket: str
    lender_name: str
    upi_id: Optional[str]
    payment_link: Optional[str]
    last_call_date: Optional[str]
    last_call_outcome: Optional[str]
    total_calls_this_cycle: int
    created_at: datetime


@router.get("", response_model=List[BorrowerResponse])
async def list_borrowers(org: CurrentOrg, session: DBSession, bucket: Optional[str] = None):
    query = select(Borrower).where(Borrower.org_id == org.id)
    if bucket:
        query = query.where(Borrower.bucket == bucket)
    result = await session.exec(query.order_by(Borrower.days_past_due.desc()))
    return result.all()


@router.post("", response_model=BorrowerResponse, status_code=status.HTTP_201_CREATED)
async def create_borrower(body: BorrowerCreate, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    borrower = Borrower(org_id=org.id, **body.model_dump())
    session.add(borrower)
    await session.commit()
    await session.refresh(borrower)
    return borrower


@router.get("/{borrower_id}", response_model=BorrowerResponse)
async def get_borrower(borrower_id: UUID, org: CurrentOrg, session: DBSession):
    borrower = await session.get(Borrower, borrower_id)
    if not borrower or borrower.org_id != org.id:
        raise HTTPException(status_code=404, detail="Borrower not found")
    return borrower


@router.patch("/{borrower_id}", response_model=BorrowerResponse)
async def update_borrower(borrower_id: UUID, body: BorrowerUpdate, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    borrower = await session.get(Borrower, borrower_id)
    if not borrower or borrower.org_id != org.id:
        raise HTTPException(status_code=404, detail="Borrower not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(borrower, field, value)
    borrower.updated_at = datetime.utcnow()
    session.add(borrower)
    await session.commit()
    await session.refresh(borrower)
    return borrower


@router.delete("/{borrower_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_borrower(borrower_id: UUID, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    borrower = await session.get(Borrower, borrower_id)
    if not borrower or borrower.org_id != org.id:
        raise HTTPException(status_code=404, detail="Borrower not found")
    await session.delete(borrower)
    await session.commit()
