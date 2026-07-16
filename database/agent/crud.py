from datetime import UTC, datetime

from sqlalchemy import desc, select

from database.agent.llmchat import L3Memory, LLMMessage
from database.agent.session import AgentSession


def _message_to_dict(message: LLMMessage) -> dict:
    return {
        "id": message.id,
        "done": message.done,
        "done_reason": message.done_reason,
        "role": message.role,
        "thinking": message.thinking,
        "content": message.content,
        "tool_calls": message.tool_calls,
        "tool_call_id": message.tool_call_id,
        "provider": message.provider,
        "model": message.model,
        "tokens_prompt": message.tokens_prompt,
        "tokens_response": message.tokens_response,
        "duration_load": message.duration_load,
        "duration_prompt": message.duration_prompt,
        "duration_response": message.duration_response,
        "dt": message.dt.isoformat() if message.dt else None,
    }


def _l3_memory_to_dict(memory: L3Memory) -> dict:
    return {
        "summary": memory.summary,
        "created_at": memory.created_at.isoformat(),
        "last_message_id": memory.last_message_id,
    }


def add_message(message: dict, chat_id: int):
    with AgentSession() as session:
        try:
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
