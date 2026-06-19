"""
Async conversation logger for v2.
Writes Conversation + Message rows to Postgres via SQLModel async sessions.
"""
from __future__ import annotations

import time
from typing import Optional
from uuid import UUID

from loguru import logger
from sqlmodel import select

from core.database import AsyncSessionLocal as async_session_factory
from models.conversation import Conversation, Message


class ConversationLogger:
    """
    Lifecycle:
        logger = ConversationLogger(org_id, agent_id, phone_number)
        await logger.start()
        await logger.add_message("user", "text here")
        await logger.add_message("agent", "reply here")
        await logger.cleanup()          # marks conversation complete
        await logger.cleanup("failed")  # marks conversation failed
    """

    def __init__(
        self,
        org_id: UUID,
        agent_id: UUID,
        phone_number: Optional[str] = None,
        call_direction: str = "outbound",
        campaign_id: Optional[UUID] = None,
        borrower_id: Optional[UUID] = None,
        call_sid: Optional[str] = None,
    ):
        self.org_id = org_id
        self.agent_id = agent_id
        self.phone_number = phone_number
        self.call_direction = call_direction
        self.campaign_id = campaign_id
        self.borrower_id = borrower_id
        self.call_sid = call_sid

        self._conversation_id: Optional[UUID] = None
        self._sequence: int = 0
        self._started = False

    @property
    def conversation_id(self) -> Optional[UUID]:
        return self._conversation_id

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            async with async_session_factory() as session:
                conv = Conversation(
                    org_id=self.org_id,
                    agent_id=self.agent_id,
                    borrower_id=self.borrower_id,
                    campaign_id=self.campaign_id,
                    phone_number=self.phone_number,
                    call_direction=self.call_direction,
                    status="active",
                    meta_data={"call_sid": self.call_sid} if self.call_sid else None,
                )
                session.add(conv)
                await session.commit()
                await session.refresh(conv)
                self._conversation_id = conv.id
                logger.debug(f"[conv-logger] started conversation {conv.id} for {self.phone_number}")
        except Exception as exc:
            logger.error(f"[conv-logger] failed to create conversation: {exc}")

    async def add_message(self, sender: str, text: str) -> None:
        if not text or not text.strip():
            return
        if not self._conversation_id:
            logger.warning("[conv-logger] add_message called before start()")
            return
        try:
            async with async_session_factory() as session:
                self._sequence += 1
                msg = Message(
                    conversation_id=self._conversation_id,
                    org_id=self.org_id,
                    sender=sender,
                    text=text.strip(),
                    sequence_no=self._sequence,
                )
                session.add(msg)
                await session.commit()
        except Exception as exc:
            logger.error(f"[conv-logger] failed to save message: {exc}")

    async def cleanup(self, status: str = "completed") -> None:
        if not self._conversation_id:
            return
        try:
            from datetime import datetime
            async with async_session_factory() as session:
                conv = await session.get(Conversation, self._conversation_id)
                if conv:
                    conv.status = status
                    conv.ended_at = datetime.utcnow()
                    session.add(conv)
                    await session.commit()
                    logger.debug(f"[conv-logger] conversation {self._conversation_id} marked {status}")
        except Exception as exc:
            logger.error(f"[conv-logger] failed to close conversation: {exc}")
