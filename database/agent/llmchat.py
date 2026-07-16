from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.functions import current_timestamp


class Base(DeclarativeBase):
    pass


class Chat(Base):
    __tablename__ = "chats"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'New Chat'"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=current_timestamp()
    )


class ClientChat(Base):
    __tablename__ = "client_chat"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, ForeignKey("chats.id"), nullable=False)
    message_type: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[Any] = mapped_column(JSONB, nullable=False)
    dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=current_timestamp()
    )


class LLMMessage(Base):
    __tablename__ = "llmchat"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, ForeignKey("chats.id"), nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    done_reason: Mapped[str] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    thinking: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_calls: Mapped[Any] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model: Mapped[str] = mapped_column(Text, default="", nullable=False)

    tokens_prompt: Mapped[int] = mapped_column(Integer, nullable=True)
    tokens_response: Mapped[int] = mapped_column(Integer, nullable=True)

    duration_load: Mapped[int] = mapped_column(Integer, nullable=True)
    duration_prompt: Mapped[int] = mapped_column(Integer, nullable=True)
    duration_response: Mapped[int] = mapped_column(Integer, nullable=True)

    dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=current_timestamp()
    )
    __table_args__ = (
        CheckConstraint("role in ('assistant', 'system', 'user', 'tool')", name="check_role"),
    )


class L3Memory(Base):
    __tablename__ = "l3_memory"
    chat_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=current_timestamp()
    )
    last_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
