from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

from .context_skills import SkillContext


ANSYS_MAPDL_SKILL_ID = "ansys_mapdl_18_2"
ANSYS_MAPDL_SKILL_DIR = "ansys-mapdl-18-2"
ANSYS_MAPDL_RELEASE = "18.2"
ANSYS_MAPDL_SKILL_ROOT_ENV = "FANBAN_ANSYS_MAPDL_SKILL_ROOT"

_DEFAULT_TRIGGER_TERMS = (
    "ansys",
    "mapdl",
    "apdl",
    "mechanical apdl",
    "keyopt",
    "antype",
    "/solu",
    "/prep7",
    "/post1",
    "/post26",
    "*get",
    "*dim",
    "*do",
    "tbdata",
)
_FOLLOWUP_TERMS = (
    "它",
    "这个",
    "该命令",
    "该单元",
    "参数",
    "选项",
    "继续",
    "再解释",
    "什么意思",
    "怎么设置",
    "怎么用",
)
_ELEMENT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"((?:SOLID|SHELL|BEAM|LINK|MASS|COMBIN|CONTA|TARGE|SURF|FLUID|PLANE|PIPE|CIRCUIT)\d{2,4})"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])([/*]?[A-Za-z][A-Za-z0-9]{1,15})(?![A-Za-z0-9_])",
)
_IGNORED_IDENTIFIERS = {
    "ANSYS",
    "APDL",
    "MAPDL",
    "MECHANICAL",
}
_REQUIRED_FILES = (
    Path("SKILL.md"),
    Path("scripts") / "mapdl_query.py",
    Path("assets") / "data" / "mapdl_help.sqlite",
    Path("assets") / "data" / "mapdl_commands.jsonl",
    Path("assets") / "data" / "manifest.json",
)


class AnsysMapdlSkillError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnsysMapdlSkillConfig:
    skill_id: str = ANSYS_MAPDL_SKILL_ID
    auto_trigger: bool = True
    trigger_terms: tuple[str, ...] = _DEFAULT_TRIGGER_TERMS
    max_results: int = 4
    max_context_chars: int = 16_000
    query_timeout_seconds: int = 20
    history_followup_messages: int = 6


QueryRunner = Callable[..., dict[str, Any]]


class AnsysMapdlSkill:
    def __init__(
        self,
        *,
        root: Path,
        config: AnsysMapdlSkillConfig,
        query_runner: QueryRunner | None = None,
    ) -> None:
        self.root = root.resolve()
        self.config = config
        self.skill_id = config.skill_id
        self._query_runner = query_runner or self._run_query

    @property
    def available(self) -> bool:
        return all((self.root / relative).is_file() for relative in _REQUIRED_FILES)

    def matches(self, content: str, history: Sequence[Any]) -> bool:
        if not self.config.auto_trigger:
            return False
        normalized = content.casefold()
        if any(term.casefold() in normalized for term in self.config.trigger_terms):
            return True
        if _ELEMENT_PATTERN.search(content):
            return True
        if self._history_used_skill(history) and (
            not content.strip()
            or any(term in normalized for term in _FOLLOWUP_TERMS)
        ):
            return True
        return False

    def retrieve_if_applicable(
        self,
        content: str,
        history: Sequence[Any],
    ) -> SkillContext | None:
        if not self.matches(content, history):
            return None
        if not self.available:
            return SkillContext(
                skill_id=self.skill_id,
                content=(
                    "ANSYS MAPDL 18.2 离线 Skill 已触发，但本地语料不完整。"
                    "不得根据记忆猜测版本相关命令、参数、KEYOPT 或单元行为；请明确告知用户语料不可用。"
                ),
                metadata={
                    "available": False,
                    "error": "skill_payload_incomplete",
                    "operations": [],
                    "evidence_count": 0,
                },
            )

        evidence: list[dict[str, Any]] = []
        operations: list[str] = []
        errors: list[dict[str, str]] = []

        elements = _unique(token.upper() for token in _ELEMENT_PATTERN.findall(content))
        identifiers = _extract_command_candidates(content, excluded=set(elements))
        for operation, queries in (("command", identifiers[:4]), ("element", elements[:4])):
            for query in queries:
                result = self._safe_query(operation, query, errors)
                if not result:
                    continue
                if operation == "command" and not result.get("exact"):
                    continue
                records = result.get("results") or []
                if not records:
                    continue
                operations.append(operation)
                evidence.append(
                    {
                        "operation": operation,
                        "query": query,
                        "records": [_compact_value(item) for item in records[: self.config.max_results]],
                    }
                )

        search_result = self._safe_query("search", content, errors)
        if search_result and search_result.get("results"):
            operations.append("search")
            evidence.append(
                {
                    "operation": "search",
                    "query": content,
                    "expanded_queries": search_result.get("expanded_queries", []),
                    "matched_terms": _compact_value(search_result.get("matched_terms", [])),
                    "records": [
                        _compact_value(item)
                        for item in (search_result.get("results") or [])[: self.config.max_results]
                    ],
                }
            )

        operations = _unique(operations)
        payload = {
            "skill": "ANSYS Mechanical APDL 18.2",
            "release": ANSYS_MAPDL_RELEASE,
            "policy": (
                "以下内容是后端从本地授权语料只读检索得到的证据。"
                "版本相关结论必须以证据为准；保留 APDL 标识符，并引用 manual/title/doc_id 或 source_file。"
            ),
            "evidence": evidence,
            "errors": errors,
        }
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(rendered) > self.config.max_context_chars:
            rendered = rendered[: self.config.max_context_chars] + "\n[context truncated]"
        return SkillContext(
            skill_id=self.skill_id,
            content=rendered,
            metadata={
                "available": True,
                "release": ANSYS_MAPDL_RELEASE,
                "operations": operations,
                "evidence_count": sum(len(item.get("records", [])) for item in evidence),
                "errors": errors,
            },
        )

    def _history_used_skill(self, history: Sequence[Any]) -> bool:
        for message in list(history)[-max(self.config.history_followup_messages, 0) :]:
            metadata = getattr(message, "metadata", None) or {}
            if self.skill_id in metadata.get("auto_skill_ids", []):
                return True
        return False

    def _safe_query(
        self,
        operation: str,
        query: str,
        errors: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        try:
            result = self._query_runner(operation, query, limit=self.config.max_results)
        except Exception as exc:
            errors.append({"operation": operation, "query": query, "error": str(exc)})
            return None
        return result if isinstance(result, dict) else None

    def _run_query(self, operation: str, query: str, *, limit: int) -> dict[str, Any]:
        script = self.root / "scripts" / "mapdl_query.py"
        arguments = [sys.executable, str(script), operation, query]
        if operation in {"search", "command"}:
            arguments.extend(["--limit", str(max(int(limit), 1))])
        completed = subprocess.run(
            arguments,
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(int(self.config.query_timeout_seconds), 1),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[:1000]
            raise AnsysMapdlSkillError(
                f"MAPDL query failed ({operation}, exit={completed.returncode}): {detail}"
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AnsysMapdlSkillError("MAPDL query returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AnsysMapdlSkillError("MAPDL query returned a non-object JSON payload")
        return payload


def resolve_skill_root(server_root: Path, configured_root: str, env_var: str) -> Path:
    env_value = os.getenv(env_var) if env_var else None
    root = Path(env_value or configured_root)
    if not root.is_absolute():
        root = server_root / root
    return root.resolve()


def install_skill_archive(archive: Path, destination: Path) -> Path:
    archive = archive.resolve()
    destination = destination.resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"ANSYS MAPDL Skill archive does not exist: {archive}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ansys-mapdl-skill-", dir=destination.parent) as temp_dir:
        staged = Path(temp_dir) / ANSYS_MAPDL_SKILL_DIR
        staged.mkdir(parents=True)
        found_payload = False
        with ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                normalized = entry.filename.replace("\\", "/")
                parts = PurePosixPath(normalized).parts
                if normalized.startswith("/") or ".." in parts:
                    raise AnsysMapdlSkillError(f"unsafe ZIP entry: {entry.filename}")
                try:
                    skill_index = parts.index(ANSYS_MAPDL_SKILL_DIR)
                except ValueError:
                    continue
                relative_parts = parts[skill_index + 1 :]
                if not relative_parts or entry.is_dir():
                    continue
                target = staged.joinpath(*relative_parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                found_payload = True

        if not found_payload:
            raise AnsysMapdlSkillError("archive does not contain ansys-mapdl-18-2 payload")
        missing = [str(relative) for relative in _REQUIRED_FILES if not (staged / relative).is_file()]
        if missing:
            raise AnsysMapdlSkillError(f"skill payload is incomplete: {', '.join(missing)}")

        backup = destination.with_name(f"{destination.name}.backup")
        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            destination.replace(backup)
        try:
            shutil.copytree(staged, destination)
        except Exception:
            if destination.exists():
                shutil.rmtree(destination)
            if backup.exists():
                backup.replace(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    return destination


def _extract_command_candidates(content: str, *, excluded: set[str]) -> list[str]:
    candidates: list[str] = []
    for token in _IDENTIFIER_PATTERN.findall(content):
        canonical = token.upper()
        if canonical in _IGNORED_IDENTIFIERS or canonical in excluded:
            continue
        if token.startswith(("/", "*")) or token == canonical:
            candidates.append(canonical)
    return _unique(candidates)


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "[nested content omitted]"
    if isinstance(value, str):
        return value if len(value) <= 2500 else value[:2500] + " [truncated]"
    if isinstance(value, list):
        return [_compact_value(item, depth=depth + 1) for item in value[:10]]
    if isinstance(value, dict):
        return {
            str(key): _compact_value(item, depth=depth + 1)
            for key, item in list(value.items())[:30]
        }
    return value


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _main() -> int:
    parser = argparse.ArgumentParser(description="Install the ANSYS MAPDL 18.2 offline Skill")
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    installed = install_skill_archive(args.archive, args.destination)
    print(json.dumps({"ok": True, "skill_root": str(installed)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
