"""api/routes/chat.py — Claude AI chat endpoint."""
from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from chat.claude_client import process_command
from core.database import get_session
from core.models import ChatMessage

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


@router.post("/api/chat")
async def chat(request: ChatRequest, db: Session = Depends(get_session)):
    loop = asyncio.get_event_loop()

    # Save user message
    db.add(ChatMessage(session_id=request.session_id, role="user", content=request.message))
    db.commit()

    # Process
    result = await process_command(request.message, loop=loop)

    # Save assistant response
    db.add(ChatMessage(
        session_id=request.session_id,
        role="assistant",
        content=result.response,
        tool_calls=json.dumps(result.actions_taken) if result.actions_taken else None,
    ))
    db.commit()

    return {
        "response":      result.response,
        "actions_taken": result.actions_taken,
        "session_id":    request.session_id,
    }


@router.get("/api/chat/history")
def chat_history(session_id: str = "default", limit: int = 50,
                 db: Session = Depends(get_session)):
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.timestamp.asc())
        .limit(limit)
        .all()
    )
    return {
        "messages": [
            {"role": m.role, "content": m.content,
             "timestamp": m.timestamp.isoformat() if m.timestamp else None,
             "tool_calls": json.loads(m.tool_calls) if m.tool_calls else []}
            for m in msgs
        ]
    }
