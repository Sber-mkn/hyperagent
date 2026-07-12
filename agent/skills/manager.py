"""Learn reusable procedures from completed tool-heavy tasks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.llminterface.client.llm_chat import LLMChat
from agent.llminterface.client.llm_client import LLMClient
from agent.memory.store import Turn


MIN_TOOL_CALLS = 3
MIN_DISTINCT_TOOLS = 2
MAX_LOADED_SKILL_CHARS = 16_000
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class LearnedSkill:
    name: str
    path: Path


class SkillManager:
    def __init__(self, client: LLMClient, model: str, data_dir: Path):
        self.client = client
        self.model = model
        self.data_dir = Path(data_dir)

    @classmethod
    def open(cls, client: LLMClient, model: str, data_dir: Path) -> "SkillManager":
        manager = cls(client, model, data_dir)
        manager.data_dir.mkdir(parents=True, exist_ok=True)
        return manager

    def consider(self, turns: list[Turn]) -> LearnedSkill | None:
        """Save one reusable skill when a completed task is complex enough."""
        tool_names = _tool_names(turns)
        if (
            len(tool_names) < MIN_TOOL_CALLS
            or len(set(tool_names)) < MIN_DISTINCT_TOOLS
        ):
            return None

        try:
            skill = self._generate(turns, tool_names)
            return self._save(skill) if skill else None
        except Exception:
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
        response = self.client.send(chat, model=self.model, temperature=0)
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


def load_skills(data_dir: Path) -> str:
    """Load persisted skills with a bounded context cost."""
    skills_dir = Path(data_dir) / "skills"
    if not skills_dir.is_dir():
        return ""

    loaded: list[str] = []
    size = 0
    for path in sorted(skills_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if not content or size + len(content) > MAX_LOADED_SKILL_CHARS:
            continue
        loaded.append(content)
        size += len(content)
    return "\n\n".join(loaded)


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
    name = str(data.get("name") or "").strip()
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
