"""
Bootstrap the database with a Vehana super-admin org and user.
Run once after first migration: python seed_db.py
"""
import asyncio
from datetime import date, timedelta

from sqlmodel import select

from core.database import create_db_and_tables, AsyncSessionLocal
from core.security import hash_password
from models.organization import Organization, PlanType
from models.user import User, UserRole


async def seed():
    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        # Check if already seeded
        existing = await session.exec(select(Organization).where(Organization.slug == "vehana-internal"))
        if existing.first():
            print("Already seeded — skipping")
            return

        # Create Vehana's own internal org (super-admin home)
        org = Organization(
            name="Vehana Internal",
            slug="vehana-internal",
            plan=PlanType.ENTERPRISE,
            calls_limit_monthly=999_999,
            billing_reset_date=date.today() + timedelta(days=30),
        )
        session.add(org)
        await session.flush()

        # Create super-admin user
        admin = User(
            org_id=org.id,
            email="admin@vehana.ai",
            password_hash=hash_password("change-me-on-first-login"),
            role=UserRole.SUPER_ADMIN,
        )
        session.add(admin)
        await session.commit()

        print(f"Seeded org: {org.name} ({org.slug})")
        print(f"Seeded super-admin: {admin.email}")
        print("IMPORTANT: Change the admin password immediately after first login.")


if __name__ == "__main__":
    asyncio.run(seed())
