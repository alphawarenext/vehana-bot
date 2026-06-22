"""
One-time script to create a test VoiceAgent + TelephonyConfig in the Vehana Internal org.
Run after seed_db.py:
    python setup_test_agent.py

Prints the agent UUID and curl test commands.
"""
import asyncio
import json
from sqlmodel import select

from core.database import create_db_and_tables, AsyncSessionLocal
from core.security import encrypt_secret
from models.organization import Organization
from models.voice_agent import VoiceAgent
from models.telephony import TelephonyConfig, TelephonyProvider
from core.config import settings

# ── Configure your Ozonetel DIDs ─────────────────────────────────────────────
# DID phone numbers (E.164 or digits only, + stripped automatically)
DID_1 = settings.OZONETEL_DID.replace("+", "").strip() if settings.OZONETEL_DID else "918045613563"
DID_2 = "918045613564"   # second DID — update if different

# Ozonetel SIP trunk extension — the SHORT ID (e.g. "525836") that goes inside
# the <stream> XML body.  Find it in Ozonetel dashboard → Manage DIDs → Extension.
# All DIDs on the same Ozonetel account typically share ONE trunk extension.
TRUNK_EXTENSION = "525836"
# ─────────────────────────────────────────────────────────────────────────────


async def setup():
    await create_db_and_tables()

    async with AsyncSessionLocal() as session:
        # Find the Vehana Internal org (created by seed_db.py)
        result = await session.exec(
            select(Organization).where(Organization.slug == "vehana-internal")
        )
        org = result.first()
        if not org:
            print("ERROR: Run python seed_db.py first")
            return

        # ── VoiceAgent ────────────────────────────────────────────────────────
        existing = await session.exec(
            select(VoiceAgent).where(
                VoiceAgent.org_id == org.id,
                VoiceAgent.name == "Test EMI Agent"
            )
        )
        agent = existing.first()
        if not agent:
            agent = VoiceAgent(
                org_id=org.id,
                name="Test EMI Agent",
                call_direction="both",
                llm_model=settings.GEMINI_LIVE_MODEL,
                voice=settings.GEMINI_VOICE,
                language="hi-IN",
                prompt=(
                    "You are Rohan, a helpful EMI collections assistant from Alphaware. "
                    "Greet the caller in Hindi and ask if they are calling about their EMI payment. "
                    "Keep responses under 15 words. Use natural conversational Hindi."
                ),
            )
            session.add(agent)
            await session.commit()
            await session.refresh(agent)
            print(f"✅ Created agent: {agent.name}")
        else:
            print(f"✅ Agent already exists: {agent.name}")

        # ── TelephonyConfig ───────────────────────────────────────────────────
        tc_result = await session.exec(
            select(TelephonyConfig).where(TelephonyConfig.org_id == org.id)
        )
        tc = tc_result.first()

        dids = [d for d in [DID_1, DID_2] if d]
        did_json = json.dumps(dids)

        if not tc:
            # Encrypt pool credentials so the factory can decrypt them
            api_key_enc = encrypt_secret(settings.OZONETEL_API_KEY or "placeholder")
            tc = TelephonyConfig(
                org_id=org.id,
                provider=TelephonyProvider.OZONETEL,
                api_key_enc=api_key_enc,
                username=settings.OZONETEL_USERNAME or "",
                agent_id=settings.OZONETEL_AGENT_ID or "",
                did_numbers=did_json,
                trunk_extension=TRUNK_EXTENSION,
                max_concurrent_calls=10,
                calls_per_minute_limit=5,
            )
            session.add(tc)
            await session.commit()
            await session.refresh(tc)
            print(f"✅ Created TelephonyConfig with DIDs: {dids}, trunk: {TRUNK_EXTENSION}")
        else:
            # Update DIDs and trunk extension in existing config
            tc.did_numbers = did_json
            tc.trunk_extension = TRUNK_EXTENSION
            session.add(tc)
            await session.commit()
            print(f"✅ Updated TelephonyConfig DIDs: {dids}, trunk: {TRUNK_EXTENSION}")

        # ── Print results ─────────────────────────────────────────────────────
        print(f"\n{'─'*60}")
        print(f"  Org UUID   : {org.id}")
        print(f"  Agent UUID : {agent.id}")
        print(f"  DIDs       : {dids}")
        print(f"{'─'*60}")
        print(f"\n📋 Configure in Ozonetel dashboard:")
        print(f"   Answer URL : http://localhost:8001/api/v2/webhooks/inbound")
        print(f"   (on server): https://v2.vehana.ai/api/v2/webhooks/inbound")
        print(f"\n🧪 Test inbound routing with curl:")
        for did in dids:
            print(f"   curl 'http://localhost:8001/api/v2/webhooks/inbound?dnis={did}&cid=919999999999'")
        print(f"\n   Expected response: <stream> XML with wss://... WebSocket URL")
        print(f"\n🧪 Test with agent UUID directly:")
        print(f"   curl 'http://localhost:8001/api/v2/webhooks/{agent.id}/answer?dnis={dids[0] if dids else 'YOUR_DID'}&cid=919999999999'")


if __name__ == "__main__":
    asyncio.run(setup())
