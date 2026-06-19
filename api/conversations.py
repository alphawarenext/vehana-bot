from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from api.deps import CurrentOrg, DBSession
from models.conversation import Conversation, Message

router = APIRouter(prefix="/conversations", tags=["conversations"])


class MessageOut(BaseModel):
    id: UUID
    sender: str
    text: str
    sequence_no: int
    confidence: Optional[float]
    timestamp: str


class ConversationOut(BaseModel):
    id: UUID
    phone_number: Optional[str]
    call_direction: str
    status: str
    summary: Optional[str]
    started_at: str
    ended_at: Optional[str]


@router.get("", response_model=List[ConversationOut])
async def list_conversations(org: CurrentOrg, session: DBSession, limit: int = 50, offset: int = 0):
    result = await session.exec(
        select(Conversation)
        .where(Conversation.org_id == org.id)
        .order_by(Conversation.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    convos = result.all()
    return [
        ConversationOut(
            id=c.id,
            phone_number=c.phone_number,
            call_direction=c.call_direction,
            status=c.status,
            summary=c.summary,
            started_at=c.started_at.isoformat(),
            ended_at=c.ended_at.isoformat() if c.ended_at else None,
        )
        for c in convos
    ]


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: UUID, org: CurrentOrg, session: DBSession):
    convo = await session.get(Conversation, conversation_id)
    if not convo or convo.org_id != org.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = await session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.sequence_no)
    )
    messages = result.all()

    return {
        "conversation": ConversationOut(
            id=convo.id,
            phone_number=convo.phone_number,
            call_direction=convo.call_direction,
            status=convo.status,
            summary=convo.summary,
            started_at=convo.started_at.isoformat(),
            ended_at=convo.ended_at.isoformat() if convo.ended_at else None,
        ),
        "messages": [
            MessageOut(
                id=m.id,
                sender=m.sender,
                text=m.text,
                sequence_no=m.sequence_no,
                confidence=m.confidence,
                timestamp=m.timestamp.isoformat(),
            )
            for m in messages
        ],
    }
