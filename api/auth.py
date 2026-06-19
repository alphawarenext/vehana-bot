from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from core.database import get_session
from core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_refresh_token,
)
from core.redis import get_redis
from models.user import User, UserRole
from models.organization import Organization, PlanType
from api.deps import CurrentUser, DBSession, SuperAdmin

router = APIRouter(prefix="/auth", tags=["auth"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegisterOrgRequest(BaseModel):
    org_name: str
    org_slug: str
    admin_email: EmailStr
    admin_password: str
    plan: PlanType = PlanType.STARTER


class RefreshRequest(BaseModel):
    refresh_token: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: DBSession):
    result = await session.exec(select(User).where(User.email == body.email))
    user = result.first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    # Update last login
    user.last_login = datetime.utcnow()
    session.add(user)
    await session.commit()

    access = create_access_token(user.id, user.org_id, user.role)
    refresh = create_refresh_token(user.id)

    # Store refresh token in Redis (key: refresh:{user_id}, TTL 30 days)
    redis = await get_redis()
    await redis.setex(f"refresh:{user.id}", 60 * 60 * 24 * 30, refresh)

    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, session: DBSession):
    payload = decode_refresh_token(body.refresh_token)
    user_id = UUID(payload["sub"])

    redis = await get_redis()
    stored = await redis.get(f"refresh:{user_id}")
    if stored != body.refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked or invalid")

    user = await session.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access = create_access_token(user.id, user.org_id, user.role)
    new_refresh = create_refresh_token(user.id)
    await redis.setex(f"refresh:{user.id}", 60 * 60 * 24 * 30, new_refresh)

    return TokenResponse(access_token=access, refresh_token=new_refresh)


@router.post("/logout")
async def logout(user: CurrentUser):
    redis = await get_redis()
    await redis.delete(f"refresh:{user.id}")
    return {"message": "Logged out"}


@router.post("/register-org", status_code=status.HTTP_201_CREATED)
async def register_org(body: RegisterOrgRequest, _: SuperAdmin, session: DBSession):
    """Super-admin only — onboard a new client organization."""
    existing = await session.exec(select(Organization).where(Organization.slug == body.org_slug))
    if existing.first():
        raise HTTPException(status_code=400, detail="Org slug already taken")

    org = Organization(name=body.org_name, slug=body.org_slug, plan=body.plan)
    session.add(org)
    await session.flush()  # get org.id before creating user

    existing_user = await session.exec(select(User).where(User.email == body.admin_email))
    if existing_user.first():
        raise HTTPException(status_code=400, detail="Email already registered")

    admin = User(
        org_id=org.id,
        email=body.admin_email,
        password_hash=hash_password(body.admin_password),
        role=UserRole.ORG_ADMIN,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(org)

    return {"org_id": str(org.id), "org_slug": org.slug, "admin_email": admin.email}


@router.get("/me")
async def get_me(user: CurrentUser):
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "org_id": str(user.org_id),
    }
