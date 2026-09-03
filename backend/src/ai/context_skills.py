from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SkillImageEvidence:
    content: bytes
    media_type: str
    label: str


@dataclass(frozen=True)
class SkillContext:
    skill_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    images: tuple[SkillImageEvidence, ...] = ()


class ContextSkill(Protocol):
    skill_id: str

    def retrieve_if_applicable(
        self,
        content: str,
        history: Sequence[Any],
    ) -> SkillContext | None: ...
