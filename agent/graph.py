"""The agent graph (LangGraph).

Structure:

    start -> namer -> orchestrator <-> toolNode -> reflector -> (orchestrator | end)

- namer: creates a short chat title (topic only).
- orchestrator: decides next action and emits tool calls.
- tools: executes tools and returns outputs.
- reflector: checks whether the final answer is good enough; can request one retry.
"""

import json
import uuid
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from llm import namer_llm, orchestrator_llm, reflector_llm
from tools import BASE_TOOLS

MAX_ITERATIONS = 20
MAX_REFLECTIONS = 2

# Prompts kept close to the no-framework version for a fair comparison.
NAMER_SYSTEM_PROMPT = (
    "Ты не должен отвечать на поставляемые пользователем вопросы. "
    "Ты должен только выделить тему всего диалога с помощью нескольких слов."
)
REFLECTOR_SYSTEM_PROMPT = (
    "Твоя задача объективно оценивать решение проблемы представленное в диалоге. "
    "Ответь строго в формате JSON: approved=true если решение правильное, "
    "approved=false если нужно исправление, и comment с объяснением."
)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int
    conversation_title: str
    approved: bool
    reflection: str
    reflections: int


# orchestrator with tools bound (it can now emit tool calls)
orchestrator_with_tools = orchestrator_llm.bind_tools(BASE_TOOLS)

# Names of the real tools — used to reject hallucinated tool calls from small models.
KNOWN_TOOL_NAMES = {t.name for t in BASE_TOOLS}

# How many times the SAME (name, args) call may repeat before we force termination.
MAX_SAME_CALL = 2


def _extract_tool_call_from_content(content: str) -> list[dict]:
    """Fallback parser for models that output tool calls as JSON text.
    Only returns calls whose name is a real registered tool, so a model that
    invents a tool (or emits a plain JSON answer) is treated as a final answer."""
    if isinstance(content, str):
        text = content.strip()
    else:
        text = str(content or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    decoder = json.JSONDecoder()
    idx = 0
    payloads: list[dict] = []
    while idx < len(text):
        brace = text.find("{", idx)
        if brace == -1:
            break
        try:
            obj, end_idx = decoder.raw_decode(text[brace:])
            idx = brace + end_idx
            if isinstance(obj, dict):
                payloads.append(obj)
        except json.JSONDecodeError:
            idx = brace + 1

    tool_calls: list[dict] = []
    for payload in payloads:
        name = payload.get("name")
        args = payload.get("arguments", {})
        if not name or not isinstance(name, str):
            continue
        if name not in KNOWN_TOOL_NAMES:
            continue
        if not isinstance(args, dict):
            args = {}
        tool_calls.append(
            {
                "name": name,
                "args": args,
                "id": f"manual_{uuid.uuid4().hex[:10]}",
                "type": "tool_call",
            }
        )
    return tool_calls


def namer_node(state: AgentState) -> AgentState:
    """Generate a short title for the current user request."""
    user_text = ""
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage):
            user_text = m.content
            break
    response = namer_llm.invoke(
        [
            SystemMessage(content=NAMER_SYSTEM_PROMPT),
            HumanMessage(content=f"Dialog:\n{user_text}\n\nReturn only a short title."),
        ]
    )
    raw_title = getattr(response, "content", "")
    title = raw_title.strip() if isinstance(raw_title, str) else str(raw_title or "").strip()
    return {"conversation_title": title or "Untitled conversation"}


def _count_prior_call(messages: list[BaseMessage], name: str, args: dict) -> int:
    """How many times this exact (name, args) tool call already appears in history."""
    count = 0
    for m in messages:
        for tc in getattr(m, "tool_calls", None) or []:
            if tc.get("name") == name and tc.get("args") == args:
                count += 1
    return count


def orchestrator_node(state: AgentState) -> AgentState:
    """The brain: looks at the conversation + tool results, decides the next step."""
    response = orchestrator_with_tools.invoke(state["messages"])

    tool_calls = list(getattr(response, "tool_calls", None) or [])
    if not tool_calls:
        tool_calls = _extract_tool_call_from_content(getattr(response, "content", ""))

    # Drop calls that have already been made too many times (breaks repeat loops).
    fresh_calls = [
        tc for tc in tool_calls
        if _count_prior_call(state["messages"], tc["name"], tc.get("args", {})) < MAX_SAME_CALL
    ]

    if fresh_calls:
        response = AIMessage(content=response.content, tool_calls=fresh_calls)
    else:
        # No new tool work to do -> treat as the final answer (no tool calls).
        response = AIMessage(content=response.content)

    return {"messages": [response], "iteration": state.get("iteration", 0) + 1}


def reflector_node(state: AgentState) -> AgentState:
    """Review final answer quality and decide if one retry is needed."""
    messages = [
        SystemMessage(content=REFLECTOR_SYSTEM_PROMPT),
        HumanMessage(content="\n".join(getattr(m, "content", "") or "" for m in state["messages"])),
    ]
    response = reflector_llm.invoke(messages)
    raw_content = getattr(response, "content", "")
    raw = raw_content.strip() if isinstance(raw_content, str) else str(raw_content or "").strip()
    normalized = raw
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3:
            normalized = "\n".join(lines[1:-1]).strip()
    approved = False
    comment = raw
    try:
        parsed = json.loads(normalized)
        approved = bool(parsed.get("approved", False))
        comment = str(parsed.get("comment", ""))
    except json.JSONDecodeError:
        approved = False
    return {
        "approved": approved,
        "reflection": comment,
        "reflections": state.get("reflections", 0) + 1,
    }


def route_after_orchestrator(state: AgentState) -> str:
    """If orchestrator asked for tools -> run tools, else -> reflector."""
    if state.get("iteration", 0) >= MAX_ITERATIONS:
        return END
    return tools_condition(state)  # returns "tools" or END


def route_after_reflector(state: AgentState) -> str:
    if state.get("approved", False):
        return END
    if state.get("reflections", 0) >= MAX_REFLECTIONS:
        return END
    return "orchestrator"


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("namer", namer_node)
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("tools", ToolNode(BASE_TOOLS))
    builder.add_node("reflector", reflector_node)

    builder.add_edge(START, "namer")
    builder.add_edge("namer", "orchestrator")
    builder.add_conditional_edges(
        "orchestrator", route_after_orchestrator, {"tools": "tools", END: "reflector"}
    )
    builder.add_edge("tools", "orchestrator")  # after a tool, ALWAYS back to the brain
    builder.add_conditional_edges(
        "reflector", route_after_reflector, {"orchestrator": "orchestrator", END: END}
    )
    return builder.compile()


graph = build_graph()
