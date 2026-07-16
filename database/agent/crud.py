from datetime import UTC, datetime

from sqlalchemy import asc, desc, exists, select

from database.agent.llmchat import Chat, ClientChat, L3Memory, LLMMessage
from database.agent.session import AgentSession

# NEW_CHAT_TITLE = "New "


def _l3_memory_to_dict(memory: L3Memory) -> dict:
    return {
        "summary": memory.summary,
        "created_at": memory.created_at.isoformat(),
        "last_message_id": memory.last_message_id,
    }


def _chat_to_dict(chat: Chat) -> dict:
    return {
        "id": chat.id,
        "title": chat.title,
        "updated_at": chat.updated_at.isoformat(),
    }


def _client_message_to_dict(message: ClientChat) -> dict:
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "message_type": message.message_type,
        "message": message.message,
        "dt": message.dt.isoformat(),
    }


def _message_to_dict(message: LLMMessage) -> dict:
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "done": message.done,
        "done_reason": message.done_reason,
        "role": message.role,
        "thinking": message.thinking,
        "content": message.content,
        "tool_calls": message.tool_calls,
        "tool_call_id": message.tool_call_id,
        "name": message.name,
        "provider": message.provider,
        "model": message.model,
        "tokens_prompt": message.tokens_prompt,
        "tokens_response": message.tokens_response,
        "duration_load": message.duration_load,
        "duration_prompt": message.duration_prompt,
        "duration_response": message.duration_response,
        "dt": message.dt.isoformat(),
    }


def list_chats() -> list[dict]:
    with AgentSession() as session:
        chats = select(Chat).order_by(desc(Chat.updated_at), desc(Chat.id))
        result = []
        for chat in session.scalars(chats).all():
            item = _chat_to_dict(chat)
            item["has_messages"] = _has_client_messages(session, chat.id)
            result.append(item)
        return result


def create_chat(title: str) -> dict:
    clean_title = title.strip()
    with AgentSession() as session:
        try:
            chat = Chat(title=clean_title, updated_at=datetime.now(UTC))
            session.add(chat)
            session.flush()
            result = _chat_to_dict(chat)
            result["has_messages"] = False
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()
            return result


def rename_chat(chat_id: int, title: str) -> dict:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("Chat title cannot be empty")

    with AgentSession() as session:
        try:
            chat = session.get(Chat, chat_id)
            chat.title = clean_title
            chat.updated_at = datetime.now(UTC)
            session.flush()
            result = _chat_to_dict(chat)
            result["has_messages"] = _has_client_messages(session, chat.id)
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()
            return result


def get_chat_history(chat_id: int) -> list[dict]:
    with AgentSession() as session:
        messages = (
            select(ClientChat)
            .where(ClientChat.chat_id == chat_id)
            .order_by(asc(ClientChat.dt), asc(ClientChat.id))
        )
        return [_client_message_to_dict(message) for message in session.scalars(messages).all()]


def add_client_message(chat_id: int, message_type: str, message) -> int:
    with AgentSession() as session:
        try:
            chat = session.get(Chat, chat_id)
            client_message = ClientChat(
                chat_id=chat_id,
                message_type=message_type,
                message=message,
                dt=datetime.now(UTC),
            )
            chat.updated_at = datetime.now(UTC)
            session.add(client_message)
            session.flush()
            message_id = client_message.id
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()
            return message_id


def add_message(message: dict, chat_id: int):
    with AgentSession() as session:
        try:
            chat = session.get(Chat, chat_id)
            llm_message = LLMMessage(
                chat_id=chat_id,
                done=message.get("done"),
                done_reason=message.get("done_reason"),
                role=message.get("role"),
                thinking=message.get("thinking"),
                content=message.get("content"),
                tool_calls=message.get("tool_calls"),
                tool_call_id=message.get("tool_call_id"),
                name=message.get("name"),
                provider=message.get("provider"),
                model=message.get("model"),
                tokens_prompt=message.get("tokens_prompt"),
                tokens_response=message.get("tokens_response"),
                duration_load=message.get("duration_load"),
                duration_prompt=message.get("duration_prompt"),
                duration_response=message.get("duration_response"),
                dt=message.get("dt"),
            )
            chat.updated_at = datetime.now(UTC)
            session.add(llm_message)
            session.flush()
            message_id = llm_message.id
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()
            return message_id


def get_llmchat(chat_id: int):
    with AgentSession() as session:
        messages = (
            select(LLMMessage).where(LLMMessage.chat_id == chat_id).order_by(desc(LLMMessage.dt))
        )
        return [_message_to_dict(message) for message in session.scalars(messages).all()]


def get_l3_memory(chat_id: int):
    with AgentSession() as session:
        memory = session.get(L3Memory, chat_id)
        return _l3_memory_to_dict(memory) if memory else None


def add_l3_memory(memory: dict, chat_id: int):
    with AgentSession() as session:
        try:
            l3_memory = session.get(L3Memory, chat_id)
            if l3_memory is None:
                l3_memory = L3Memory(chat_id=chat_id)
                session.add(l3_memory)

            l3_memory.summary = memory.get("summary")
            l3_memory.last_message_id = memory.get("last_message_id")
            l3_memory.created_at = datetime.now(UTC)
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()


def _has_client_messages(session, chat_id: int) -> bool:
    return bool(session.scalar(select(exists().where(ClientChat.chat_id == chat_id))))
