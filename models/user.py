from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4
from enum import Enum

from sqlmodel import SQLModel, Field


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"  # Vehana internal — can see all orgs
    ORG_ADMIN = "org_admin"      # Client's admin — full access to their org
    ORG_MEMBER = "org_member"    # Client's team — read-only dashboard access


class User(SQLModel, table=True):
    __tablename__ = "user"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)

    email: str = Field(unique=True, index=True)
    password_hash: str
    role: UserRole = Field(default=UserRole.ORG_MEMBER)
    is_active: bool = Field(default=True)

    last_login: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = Field(default_factory=lambda: datetime.utcnow())
