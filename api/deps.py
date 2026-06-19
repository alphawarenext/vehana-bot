"""
Shared FastAPI dependencies — injected into every route that needs auth or DB.
"""
from uuid import UUID
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from core.database import get_session
from core.security import decode_access_token
from models.user import User, UserRole
from models.organization import Organization

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    payload = decode_access_token(credentials.credentials)
    user = await session.get(User, UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


async def get_current_org(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Organization:
    org = await session.get(Organization, user.org_id)
    if not org or not org.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization inactive or not found")
    return org


def require_role(*roles: UserRole):
    """Dependency factory — raises 403 if user's role is not in the allowed set."""
    async def check(user: Annotated[User, Depends(get_current_user)]):
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return check


async def check_call_quota(org: Annotated[Organization, Depends(get_current_org)]):
    """Raise 429 if org has exceeded its monthly call quota."""
    if org.calls_used_this_month >= org.calls_limit_monthly:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Monthly call quota of {org.calls_limit_monthly} exceeded. Upgrade your plan."
        )
    return org


# Typed aliases for route signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentOrg = Annotated[Organization, Depends(get_current_org)]
DBSession = Annotated[AsyncSession, Depends(get_session)]
OrgAdmin = Annotated[User, Depends(require_role(UserRole.ORG_ADMIN, UserRole.SUPER_ADMIN))]
SuperAdmin = Annotated[User, Depends(require_role(UserRole.SUPER_ADMIN))]
