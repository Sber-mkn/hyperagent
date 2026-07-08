from sqlalchemy import desc, select

from database.agent.llmchat import LLMMessage
from session import AgentSession

def add_message(message: dict):
    llm_message = LLMMessage(done=message.get("done"),
                             done_reason=message.get("done_reason"),
                             role=message.get("role"),
                             thinking=message.get("thinking"),
                             content=message.get("content"),
                             tool_calls=message.get("tool_calls"),
                             tool_call_id=message.get("tool_call_id"),
                             name = message.get("name"),
                             provider = message.get("provider"),
                             model = message.get("model"),
                             tokens_prompt=message.get("tokens_prompt"),
                             tokens_response=message.get("tokens_response"),
                             duration_load=message.get("duration_load"),
                             duration_prompt=message.get("duration_prompt"),
                             duration_response=message.get("duration_response"),
                             dt = message.get("dt"),
                            )
    with AgentSession() as session:
        try:
            session.add(llm_message)
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()

def get_llmchat():
    with AgentSession() as session:
        messages = (
            select(LLMMessage).order_by(desc(LLMMessage.dt))
        )
        llmchat = session.scalars(messages).all()
        return llmchat