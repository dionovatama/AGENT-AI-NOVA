"""Authenticated, account-scoped chat history endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.models import Conversation, ConversationMessage, User
from app.database.session import get_db
from app.security.dependencies import get_current_user

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=160)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class MessageCreate(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=30000)
    metadata: dict[str, Any] | None = None


def _conversation_out(item: Conversation) -> dict[str, Any]:
    return {
        "id": item.id, "title": item.title,
        "created_at": item.created_at, "updated_at": item.updated_at,
    }


def _message_out(item: ConversationMessage) -> dict[str, Any]:
    return {
        "id": item.id, "role": item.role, "content": item.content,
        "metadata": item.message_metadata, "created_at": item.created_at,
    }


def _owned_conversation(db: Session, conversation_id: uuid.UUID, owner_id: uuid.UUID) -> Conversation:
    item = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.owner_id == owner_id,
    ).first()
    if item is None:
        # 404 deliberately hides whether this ID belongs to another account.
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return item


@router.post("", status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = Conversation(owner_id=current_user.id, title=payload.title.strip() or "New chat")
    db.add(item)
    db.commit()
    db.refresh(item)
    return _conversation_out(item)


@router.get("")
def list_conversations(
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = (
        db.query(Conversation)
        .filter(Conversation.owner_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit).all()
    )
    return [_conversation_out(item) for item in items]


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _owned_conversation(db, conversation_id, current_user.id)
    items = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
        .limit(limit).all()
    )
    return [_message_out(item) for item in items]


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
def append_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _owned_conversation(db, conversation_id, current_user.id)
    item = ConversationMessage(
        conversation_id=conversation.id,
        role=payload.role,
        content=payload.content,
        message_metadata=payload.metadata,
    )
    if payload.role == "user" and conversation.title == "New chat":
        conversation.title = payload.content.strip().replace("\n", " ")[:72] or "New chat"
    conversation.updated_at = datetime.now(timezone.utc)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _message_out(item)


@router.patch("/{conversation_id}")
def rename_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationRename,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _owned_conversation(db, conversation_id, current_user.id)
    conversation.title = payload.title.strip()
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conversation)
    return _conversation_out(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _owned_conversation(db, conversation_id, current_user.id)
    db.delete(conversation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
