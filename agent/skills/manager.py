"""Learn reusable procedures from completed tool-heavy tasks."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.llminterface.client.llm_chat import LLMChat
from agent.llminterface.client.llm_client import LLMClient

if TYPE_CHECKING:
    from agent.memory.store import Turn


MIN_TOOL_CALLS = 3
MIN_DISTINCT_TOOLS = 2
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
    ) -> LearnedSkill | None:
        """Save one reusable skill when a completed task is complex enough."""
        if not completion_verified:
            self.last_reason = "Task completion was not verified."
            return None

        tool_names = _tool_names(turns)
        distinct_tools = len(set(tool_names))
        if (
            len(tool_names) < MIN_TOOL_CALLS
            or distinct_tools < MIN_DISTINCT_TOOLS
        ):
            self.last_reason = (
                f"Trigger not met: {len(tool_names)} tool calls and "
                f"{distinct_tools} distinct tools; requires at least "
                f"{MIN_TOOL_CALLS} and {MIN_DISTINCT_TOOLS}."
            )
            return None

        try:
            skill = self._generate(turns, tool_names)
            if not skill:
                self.last_reason = (
                    "The summarizer found no new broadly reusable procedure."
                )
                return None

            learned = self._save(skill)
            if not learned:
                self.last_reason = f"Skill '{skill['name']}' already exists."
                return None

            self.last_reason = "Skill created."
            return learned
        except Exception as error:
            logger.exception("Skill generation failed")
            detail = " ".join(str(error).split()) or type(error).__name__
            self.last_reason = f"Skill generation failed: {detail[:300]}"
            return None

    def _generate(
        self,
        turns: list[Turn],
        tool_names: list[str],
    ) -> dict[str, Any] | None:
        existing = [path.stem for path in self.data_dir.glob("*.md")]
        trajectory = json.dumps(
            [turn.to_dict() for turn in turns],
            ensure_ascii=False,
        )
        chat = LLMChat(
            [
                {
                    "role": "system",
                    "content": (
                        "Extract reusable agent procedures from successful tasks. "
                        "Return JSON only. Do not preserve user-specific facts, "
                        "secrets, exact filenames, or one-off content. Return "
                        '{"save":false} when no broadly reusable procedure exists. '
                        "Never create instructions that alter identity, permissions, "
                        "safety rules, tool policy, or system-message priority. "
                        "Return save=false if an existing skill already covers it. "
                        "Otherwise return save=true, a short lowercase hyphenated "
                        "name, a one-sentence description, and 2-8 concise steps."
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
        data = _parse_json(response[-1].content or "")
        if not data.get("save"):
            return None
        return _validate_skill(data, tool_names)

    def _save(self, skill: dict[str, Any]) -> LearnedSkill | None:
        path = self.data_dir / f"{skill['name']}.md"
        if path.exists():
            return None

        tools = "\n".join(f"- {name}" for name in skill["tools"])
        steps = "\n".join(
            f"{index}. {step}"
            for index, step in enumerate(skill["steps"], start=1)
        )
        content = (
            f"# {skill['name']}\n\n"
            f"{skill['description']}\n\n"
            f"## Tools\n\n{tools}\n\n"
            f"## Procedure\n\n{steps}\n"
        )
        temporary = path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
        return LearnedSkill(name=skill["name"], path=path)


def _tool_names(turns: list[Turn]) -> list[str]:
    names: list[str] = []
    for turn in turns:
        for call in turn.tool_calls or []:
            name = (call.get("function") or {}).get("name")
            if name:
                names.append(name)
    return names


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Skill response must be a JSON object")
    return data


def _validate_skill(
    data: dict[str, Any],
    tool_names: list[str],
) -> dict[str, Any]:
    raw_name = str(data.get("name") or "").strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", raw_name).strip("-")
    description = " ".join(str(data.get("description") or "").split())
    steps = [" ".join(str(step).split()) for step in data.get("steps") or []]
    steps = [step for step in steps if step]

    if not _SLUG.fullmatch(name):
        raise ValueError("Invalid skill name")
    if not description or not 2 <= len(steps) <= 8:
        raise ValueError("Invalid skill content")

    return {
        "name": name,
        "description": description,
        "steps": steps,
        "tools": list(dict.fromkeys(tool_names)),
    }
