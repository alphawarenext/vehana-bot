from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select

from api.deps import CurrentUser, CurrentOrg, DBSession, OrgAdmin
from models.voice_agent import VoiceAgent

router = APIRouter(prefix="/agents", tags=["agents"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str
    call_direction: str = "outbound"
    prompt: str = ""
    examples: str = ""
    llm_model: str = "gemini-2.5-flash"
    stt_model: str = "saaras:v3"
    tts_model: str = "bulbul:v2"
    voice: str = "shreya"
    language: str = "hi-IN"
    temperature: float = 0.7
    max_tokens: int = 160
    max_call_turns: int = 20


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    call_direction: Optional[str] = None
    prompt: Optional[str] = None
    examples: Optional[str] = None
    llm_model: Optional[str] = None
    stt_model: Optional[str] = None
    tts_model: Optional[str] = None
    voice: Optional[str] = None
    language: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_call_turns: Optional[int] = None
    is_active: Optional[bool] = None


class AgentResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    call_direction: str
    prompt: str
    examples: str
    llm_model: str
    stt_model: str
    tts_model: str
    voice: str
    language: str
    temperature: float
    max_tokens: int
    max_call_turns: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[AgentResponse])
async def list_agents(org: CurrentOrg, session: DBSession):
    result = await session.exec(
        select(VoiceAgent).where(VoiceAgent.org_id == org.id).order_by(VoiceAgent.created_at.desc())
    )
    return result.all()


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(body: AgentCreate, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    agent = VoiceAgent(org_id=org.id, **body.model_dump())
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: UUID, org: CurrentOrg, session: DBSession):
    agent = await session.get(VoiceAgent, agent_id)
    if not agent or agent.org_id != org.id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: UUID, body: AgentUpdate, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    agent = await session.get(VoiceAgent, agent_id)
    if not agent or agent.org_id != org.id:
        raise HTTPException(status_code=404, detail="Agent not found")
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agent, field, value)
    agent.updated_at = datetime.utcnow()
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: UUID, org: CurrentOrg, _: OrgAdmin, session: DBSession):
    agent = await session.get(VoiceAgent, agent_id)
    if not agent or agent.org_id != org.id:
        raise HTTPException(status_code=404, detail="Agent not found")
    await session.delete(agent)
    await session.commit()
