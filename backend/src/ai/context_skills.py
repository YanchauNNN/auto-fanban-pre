from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass(frozen=True)
class SkillContext:
    skill_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextSkill(Protocol):
    skill_id: str

    def retrieve_if_applicable(
        self,
        content: str,
        history: Sequence[Any],
    ) -> SkillContext | None: ...
