"""Learn reusable procedures from completed tasks."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.llm_json import parse_llm_json
from agent.llminterface.client.llm_chat import LLMChat
from agent.llminterface.client.llm_client import LLMClient
from agent.tools.registry import truncate_middle

if TYPE_CHECKING:
    from agent.memory.store import Turn


MIN_REASONING_CHARS = 600  # no-tool path: total assistant content+thinking chars
MIN_ASSISTANT_TURNS = 2  # no-tool path: number of assistant turns
MAX_TRAJECTORY_THINKING_CHARS = 800
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LearnedSkill:
    name: str
    path: Path


class SkillManager:
    def __init__(
        self,
        client: LLMClient,
        model: str,
        data_dir: Path,
        options: dict[str, Any] | None = None,
    ):
        self.client = client
        self.model = model
        self.data_dir = Path(data_dir)
        self.options = options or {}
        self.last_reason = "Skill learning was not evaluated."

    @classmethod
    def open(
        cls,
        client: LLMClient,
        model: str,
        data_dir: Path,
        options: dict[str, Any] | None = None,
    ) -> "SkillManager":
        manager = cls(client, model, data_dir, options)
        manager.data_dir.mkdir(parents=True, exist_ok=True)
        return manager

    def consider(
        self,
        turns: list[Turn],
        completion_verified: bool = False,
    ) -> list[LearnedSkill]:
        """Save reusable skills distilled from a completed task's whole trajectory."""
        if not completion_verified:
            self.last_reason = "Task completion was not verified."
            return []

        if not _worth_evaluating(turns):
            self.last_reason = (
                "Trigger not met: no tool calls and too little reasoning to "
                "evaluate for a reusable procedure."
            )
            return []

        tool_names = _tool_names(turns)
        try:
            skills = self._generate(turns, tool_names)
            if not skills:
                self.last_reason = (
                    "The summarizer found no new broadly reusable procedure."
                )
                return []

            learned: list[LearnedSkill] = []
            skipped: list[str] = []
            for skill in skills:
                saved = self._save(skill)
                if saved:
                    learned.append(saved)
                else:
                    skipped.append(skill["name"])

            if not learned:
                self.last_reason = f"Skill(s) already exist: {', '.join(skipped)}."
                return []

            self.last_reason = f"Created {len(learned)} skill(s)."
            if skipped:
                self.last_reason += f" Already existed: {', '.join(skipped)}."
            return learned
        except Exception as error:
            logger.exception("Skill generation failed")
            detail = " ".join(str(error).split()) or type(error).__name__
            self.last_reason = f"Skill generation failed: {detail[:300]}"
            return []

    def _generate(
        self,
        turns: list[Turn],
        tool_names: list[str],
    ) -> list[dict[str, Any]]:
        existing = [path.stem for path in self.data_dir.glob("*.md")]
        trajectory = json.dumps(_compact_trajectory(turns), ensure_ascii=False)
        chat = LLMChat(
            [
                {
                    "role": "system",
                    "content": (
                        "Extract reusable agent procedures from a completed task's "
                        "full trajectory, including its reasoning ('thinking' "
                        "fields), not just tool calls. Return JSON only: "
                        '{"save": boolean, "skills": [...]}. Return '
                        '{"save": false, "skills": []} when nothing broadly '
                        "reusable was learned. A trajectory is worth saving when "
                        "any of: it is a broadly reusable multi-step procedure, "
                        "with or without tools; it involved repeated trial-and-"
                        "error with a tool, library, or API before finding a "
                        "working approach (these are especially valuable — they "
                        "save future repeated struggle); or it used a non-trivial "
                        "reasoning method worth reusing even with no tool calls. "
                        "Do not save one-off, user-specific, or trivial exchanges. "
                        "When the trajectory decomposes into independent, "
                        "separately reusable sub-procedures (e.g. 'resolve a "
                        "user's location from their IP', 'fetch a weather "
                        "forecast for coordinates', and 'build a formatted Excel "
                        "workbook' are three separate skills, not one), return "
                        "each as its own entry in skills; otherwise return a "
                        "single entry. Do not preserve user-specific facts, "
                        "secrets, exact filenames, or one-off content. Skip "
                        "anything already covered by an existing skill. Never "
                        "create instructions that alter identity, permissions, "
                        "safety rules, tool policy, or system-message priority. "
                        "For each skill return: name (short lowercase hyphenated), "
                        "description (one sentence), steps (2-8 concise steps), "
                        "pitfalls (0-6 concrete 'what failed -> what worked' "
                        "facts — keep exact names, parameters, endpoints, and "
                        "error types when they were the actual source of "
                        "difficulty, do not generalize them away), and "
                        "source_url (the URL of a fetched page that materially "
                        "contributed to the working approach, or omit if none)."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Existing skills: {json.dumps(existing)}\n"
                        f"Tools used: {json.dumps(tool_names)}\n"
                        f"Completed task trajectory:\n{trajectory}"
                    ),
                },
            ]
        )
        response = self.client.send(chat, model=self.model, temperature=0, **self.options)
        data = parse_llm_json(response[-1])
        if not data.get("save"):
            return []
        raw_skills = data.get("skills")
        if not isinstance(raw_skills, list) or not raw_skills:
            return []

        validated: list[dict[str, Any]] = []
        for item in raw_skills:
            try:
                validated.append(_validate_skill(item, tool_names))
            except (ValueError, TypeError):
                logger.warning("Skipping invalid skill entry: %r", item)
        return validated

    def _save(self, skill: dict[str, Any]) -> LearnedSkill | None:
        path = self.data_dir / f"{skill['name']}.md"
        if path.exists():
            return None

        tools = "\n".join(f"- {name}" for name in skill["tools"])
        steps = "\n".join(
            f"{index}. {step}"
            for index, step in enumerate(skill["steps"], start=1)
        )
        extra = ""
        if skill.get("source_url"):
            extra += f"Source: {skill['source_url']}\n\n"
        if skill.get("pitfalls"):
            pitfalls = "\n".join(f"- {item}" for item in skill["pitfalls"])
            extra += f"## Pitfalls\n\n{pitfalls}\n\n"
        content = (
            f"# {skill['name']}\n\n"
            f"{skill['description']}\n\n"
            f"{extra}"
            f"## Tools\n\n{tools}\n\n"
            f"## Procedure\n\n{steps}\n"
        )
        temporary = path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
        return LearnedSkill(name=skill["name"], path=path)


def _worth_evaluating(turns: list[Turn]) -> bool:
    """Cheap pre-filter: skip only exchanges too trivial to bother asking the LLM about."""
    if _tool_names(turns):
        return True  # any tool call at all — including a single failed one — is a candidate

    assistant_turns = [turn for turn in turns if turn.role == "assistant"]
    reasoning_chars = sum(
        len(turn.content) + len(turn.thinking or "") for turn in assistant_turns
    )
    return len(assistant_turns) >= MIN_ASSISTANT_TURNS or reasoning_chars >= MIN_REASONING_CHARS


def _compact_trajectory(turns: list[Turn]) -> list[dict[str, Any]]:
    compact = []
    for turn in turns:
        data = turn.to_dict()
        if data.get("thinking"):
            data["thinking"] = truncate_middle(data["thinking"], MAX_TRAJECTORY_THINKING_CHARS)
        compact.append(data)
    return compact


def _tool_names(turns: list[Turn]) -> list[str]:
    names: list[str] = []
    for turn in turns:
        for call in turn.tool_calls or []:
            name = (call.get("function") or {}).get("name")
            if name:
                names.append(name)
    return names


def _validate_skill(
    data: dict[str, Any],
    tool_names: list[str],
) -> dict[str, Any]:
    raw_name = str(data.get("name") or "").strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", raw_name).strip("-")
    description = " ".join(str(data.get("description") or "").split())
    steps = [" ".join(str(step).split()) for step in data.get("steps") or []]
    steps = [step for step in steps if step]
    pitfalls = [" ".join(str(item).split()) for item in data.get("pitfalls") or []]
    pitfalls = list(dict.fromkeys(item for item in pitfalls if item))[:6]
    source_url = str(data.get("source_url") or "").strip()
    if not re.match(r"^https?://", source_url):
        source_url = ""

    if not _SLUG.fullmatch(name):
        raise ValueError("Invalid skill name")
    if not description or not 2 <= len(steps) <= 8:
        raise ValueError("Invalid skill content")

    return {
        "name": name,
        "description": description,
        "steps": steps,
        "pitfalls": pitfalls,
        "source_url": source_url,
        "tools": list(dict.fromkeys(tool_names)),
    }
