from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

import fitz

from .context_skills import SkillContext, SkillImageEvidence
from .standards_source_resolver import ResolvedStandardSource, StandardsSourceResolver

BUILDING_STANDARDS_SKILL_ID = "building_structure_standards"
BUILDING_STANDARDS_SKILL_DIR = "building-structure-standards"
BUILDING_STANDARDS_SKILL_ROOT_ENV = "FANBAN_BUILDING_STANDARDS_SKILL_ROOT"

_DEFAULT_TRIGGER_TERMS = (
    "规范",
    "标准",
    "条款",
    "图集",
    "建筑结构",
    "总图",
    "抗震",
    "防火",
    "厂址评价",
    "gb/t",
    "gb ",
    "nb/t",
    "jgj",
    "haf",
)
_FOLLOWUP_TERMS = (
    "这个条款",
    "该条款",
    "这个规范",
    "该规范",
    "继续",
    "版本",
    "页码",
    "依据",
    "还要注意",
    "设计建议",
)
_STANDARD_CODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])("
    r"(?:GB(?:/T)?|NB/T|JGJ|HAF)\s*[A-Za-z]?\s*\d+(?:\.\d+)?"
    r"(?:-\d{4})?(?:[（(][^）)]*[）)])?"
    r"|(?:19|20)\d{2}JT\d+"
    r"|CP\s+\d{2}JT\d+"
    r"|\d{2}[A-Z]{1,3}\d+(?:-\d+)?"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_CLAUSE_PATTERN = re.compile(r"第?\s*(\d+(?:\.\d+)+)\s*条?")
_TABLE_PATTERN = re.compile(r"(?:表|table\s*)\s*(\d+(?:\.\d+)+(?:-\d+)?)", re.IGNORECASE)
_REQUIRED_FILES = (
    Path("SKILL.md"),
    Path("scripts") / "standards_query.py",
    Path("scripts") / "validate_full_corpus.py",
    Path("assets") / "data" / "standards.sqlite",
    Path("assets") / "data" / "audit_catalog.json",
    Path("assets") / "data" / "manifest.json",
    Path("assets") / "data" / "validation_report.json",
)


class BuildingStandardsSkillError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildingStandardsSkillConfig:
    skill_id: str = BUILDING_STANDARDS_SKILL_ID
    auto_trigger: bool = True
    trigger_terms: tuple[str, ...] = _DEFAULT_TRIGGER_TERMS
    max_results: int = 6
    max_context_chars: int = 20_000
    query_timeout_seconds: int = 20
    history_followup_messages: int = 6
    source_root: Path | None = None
    fallback_source_roots: tuple[Path, ...] = ()
    per_file_fallback: bool = True
    preview_enabled: bool = False
    download_enabled: bool = False
    model_page_images_enabled: bool = False
    page_render_dpi: int = 144
    max_model_page_images: int = 2
    verify_source_sha256: bool = False


QueryRunner = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class StandardSourceRecord:
    source_id: int
    standard_code: str
    standard_name: str
    version: str
    source_path: str
    source_sha256: str


class BuildingStandardsSkill:
    def __init__(
        self,
        *,
        root: Path,
        config: BuildingStandardsSkillConfig,
        query_runner: QueryRunner | None = None,
    ) -> None:
        self.root = root.resolve()
        self.config = config
        self.skill_id = config.skill_id
        self._query_runner = query_runner or self._run_query
        self.source_resolver = (
            StandardsSourceResolver(
                primary_root=config.source_root,
                fallback_roots=config.fallback_source_roots,
                per_file_fallback=config.per_file_fallback,
                verify_sha256=config.verify_source_sha256,
            )
            if config.source_root is not None
            else None
        )

    @property
    def available(self) -> bool:
        return all((self.root / relative).is_file() for relative in _REQUIRED_FILES)

    @property
    def database_path(self) -> Path:
        return self.root / "assets" / "data" / "standards.sqlite"

    def get_source_record(self, source_id: int) -> StandardSourceRecord | None:
        if not self.database_path.is_file():
            return None
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """
                SELECT
                    source_id, standard_code, standard_name, version,
                    source_path, source_sha256
                FROM sources
                WHERE source_id = ?
                """,
                (int(source_id),),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return StandardSourceRecord(**dict(row))

    def resolve_source(self, source_id: int) -> ResolvedStandardSource | None:
        record = self.get_source_record(source_id)
        if record is None:
            return None
        if self.source_resolver is None:
            raise BuildingStandardsSkillError("standards source resolver is not configured")
        return self.source_resolver.resolve(
            record.source_path,
            expected_sha256=record.source_sha256,
        )

    def matches(self, content: str, history: Sequence[Any]) -> bool:
        if not self.config.auto_trigger:
            return False
        normalized = content.casefold()
        if _STANDARD_CODE_PATTERN.search(content):
            return True
        if any(term.casefold() in normalized for term in self.config.trigger_terms):
            return True
        return self._history_used_skill(history) and (
            not content.strip() or any(term in normalized for term in _FOLLOWUP_TERMS)
        )

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
                    "建筑结构总图规范离线 Skill 已触发，但本地语料包不完整。"
                    "不得凭记忆猜测规范条款、数值、表格、版本或替代关系；"
                    "请明确告知用户当前不能提供可靠规范依据。"
                ),
                metadata={
                    "available": False,
                    "error": "skill_payload_incomplete",
                    "operations": [],
                    "evidence_count": 0,
                    "evidence_insufficient": True,
                    "design_advice_allowed": False,
                },
            )

        codes = _unique(_normalize_code(match) for match in _STANDARD_CODE_PATTERN.findall(content))
        table_match = _TABLE_PATTERN.search(content)
        table_id = table_match.group(1) if table_match else ""
        clause_match = _CLAUSE_PATTERN.search(_STANDARD_CODE_PATTERN.sub("", content)) if not table_id else None
        clause_id = clause_match.group(1) if clause_match else ""
        evidence: list[dict[str, Any]] = []
        operations: list[str] = []
        errors: list[dict[str, str]] = []

        if codes and (clause_id or table_id):
            operation = "table" if table_id else "clause"
            identifier = {"table_id": table_id} if table_id else {"clause_id": clause_id}
            for code in codes:
                result = self._safe_query(
                    operation, code, errors, **identifier, limit=self.config.max_results,
                )
                if result is not None:
                    operations.append(operation)
                    evidence.append({**result, "operation": operation, "standard_code": code, **identifier})
        elif codes:
            query_text = _STANDARD_CODE_PATTERN.sub("", content).strip(" \t\r\n,，、;；")
            for code in codes:
                result = self._safe_query(
                    "search",
                    query_text,
                    errors,
                    standard_code=code,
                    limit=self.config.max_results,
                )
                if result and result.get("results"):
                    operations.append("search")
                    evidence.append(
                        {
                            "operation": "search",
                            "standard_code": code,
                            **result,
                        }
                    )
                    continue
                catalog = self._safe_query(
                    "catalog",
                    code,
                    errors,
                    limit=self.config.max_results,
                )
                if catalog is not None:
                    operations.append("catalog")
                    evidence.append(
                        {
                            "operation": "catalog",
                            "standard_code": code,
                            **catalog,
                        }
                    )
        else:
            result = self._safe_query(
                "search",
                content,
                errors,
                limit=self.config.max_results,
            )
            if result is not None:
                operations.append("search")
                evidence.append(
                    {
                        "operation": "search",
                        **result,
                    }
                )

        gate = _evidence_gate(evidence, codes, errors)
        payload = {
            "skill": "建筑结构总图规范离线库",
            **gate,
            "policy": {
                "catalog_is_not_fulltext": True,
                "no_memory_guessing": True,
                "citations_required": True,
                "design_advice_requires_sufficient_evidence": True,
                "evidence_gate": (
                    "严格服从顶层及每项 evidence_insufficient/design_advice_allowed 门禁。"
                    "检索命中、目录元数据或原页图片不等于合格正文；只有每个指定规范都命中"
                    "相关正文，且覆盖全部页的质量和风险检查通过，才可给出最终设计建议。"
                    "旧质量 schema、未知质量、待复核、目录、公告、条文说明不能放行；"
                    "visual_required 表格只供原页定位，不得从扁平文字猜测行列、数值或单位。"
                    "门禁关闭时说明缺少的证据，允许引用并明确标记待复核的检索结果。"
                ),
                "confidential_sources_must_remain_local": True,
                "link_usage": (
                    "引用条款后，可使用 evidence.links 中的地址生成 Markdown 链接："
                    "[查看原页](page)、[打开规范](document)、[下载规范](download)；"
                    "不得输出本地磁盘路径或 UNC 路径。"
                ),
            },
            "requested_codes": codes,
            "requested_clause": clause_id,
            "requested_table": table_id,
            "evidence": evidence,
            "errors": errors,
        }
        rendered = _render_context(payload, self.config.max_context_chars)
        retained_evidence = payload.get("evidence", [])
        evidence_count = sum(
            len(item.get("results") or []) or int(bool(item.get("table") or item.get("record") or item.get("standard")))
            for item in retained_evidence
        )
        page_images = self._render_model_page_images(retained_evidence, errors)
        return SkillContext(
            skill_id=self.skill_id,
            content=rendered,
            metadata={
                "available": True,
                "operations": _unique(operations),
                "evidence_count": evidence_count,
                "requested_codes": codes,
                "requested_clause": clause_id,
                "requested_table": table_id,
                "evidence_insufficient": payload["evidence_insufficient"],
                "design_advice_allowed": payload["design_advice_allowed"],
                "context_truncated": payload.get("context_truncated", False),
                "errors": errors,
                "page_image_count": len(page_images),
            },
            images=page_images,
        )

    def _render_model_page_images(
        self,
        evidence: list[dict[str, Any]],
        errors: list[dict[str, str]],
    ) -> tuple[SkillImageEvidence, ...]:
        limit = max(0, int(self.config.max_model_page_images))
        if not self.config.model_page_images_enabled or limit == 0 or self.source_resolver is None:
            return ()

        candidates: list[tuple[int, int, str]] = []
        seen: set[tuple[int, int]] = set()
        for item in evidence:
            results = item.get("results") or ([item["table"]] if item.get("table") else [])
            if not isinstance(results, list):
                continue
            for result in results:
                if not isinstance(result, dict):
                    continue
                try:
                    source_id = int(result["source_id"])
                    page_number = int(result.get("page_start") or result["page_number"])
                except (KeyError, TypeError, ValueError):
                    continue
                key = (source_id, page_number)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    (
                        source_id,
                        page_number,
                        str(result.get("standard_code") or "规范"),
                    )
                )
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break

        images: list[SkillImageEvidence] = []
        for source_id, page_number, standard_code in candidates:
            try:
                resolved = self.resolve_source(source_id)
                if resolved is None:
                    raise BuildingStandardsSkillError("source record was not found")
                with fitz.open(resolved.path) as document:
                    if page_number < 1 or page_number > document.page_count:
                        raise BuildingStandardsSkillError("page was not found")
                    page = document.load_page(page_number - 1)
                    scale = self.config.page_render_dpi / 72.0
                    pixel_count = page.rect.width * scale * page.rect.height * scale
                    if pixel_count > 40_000_000:
                        raise BuildingStandardsSkillError("page is too large")
                    pixmap = page.get_pixmap(
                        matrix=fitz.Matrix(scale, scale),
                        alpha=False,
                    )
                    content = pixmap.tobytes("png")
            except Exception as exc:
                errors.append(
                    {
                        "operation": "page_image",
                        "query": f"source_id={source_id},page={page_number}",
                        "error": str(exc),
                    }
                )
                continue
            images.append(
                SkillImageEvidence(
                    content=content,
                    media_type="image/png",
                    label=f"{standard_code} PDF第{page_number}页",
                )
            )
        return tuple(images)

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
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        try:
            result = self._query_runner(operation, query, **kwargs)
        except Exception as exc:
            errors.append({"operation": operation, "query": query, "error": str(exc)})
            return None
        return result if isinstance(result, dict) else None

    def _run_query(
        self,
        operation: str,
        query: str,
        *,
        limit: int,
        clause_id: str = "",
        table_id: str = "",
        standard_code: str = "",
    ) -> dict[str, Any]:
        script = self.root / "scripts" / "standards_query.py"
        arguments = [sys.executable, str(script)]
        if operation == "clause":
            arguments.extend(["clause", query, clause_id])
        elif operation == "table":
            arguments.extend(["table", query, table_id])
        elif operation == "search":
            arguments.extend(["search", query, "--limit", str(max(1, limit))])
            if standard_code:
                arguments.extend(["--code", standard_code])
        elif operation == "catalog":
            arguments.extend(["catalog", query])
        else:
            raise BuildingStandardsSkillError(f"unsupported query operation: {operation}")
        completed = subprocess.run(
            arguments,
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(self.config.query_timeout_seconds)),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[:1000]
            raise BuildingStandardsSkillError(
                f"standards query failed ({operation}, exit={completed.returncode}): {detail}"
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise BuildingStandardsSkillError("standards query returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise BuildingStandardsSkillError("standards query returned a non-object JSON payload")
        return payload


def install_skill_archive(archive: Path, destination: Path) -> Path:
    archive = archive.resolve()
    destination = destination.resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"standards skill archive does not exist: {archive}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="building-standards-skill-",
        dir=destination.parent,
    ) as temp_dir:
        staged = Path(temp_dir) / BUILDING_STANDARDS_SKILL_DIR
        staged.mkdir(parents=True)
        found_payload = False
        with ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                normalized = entry.filename.replace("\\", "/")
                parts = PurePosixPath(normalized).parts
                if normalized.startswith("/") or ".." in parts:
                    raise BuildingStandardsSkillError(f"unsafe ZIP entry: {entry.filename}")
                try:
                    skill_index = parts.index(BUILDING_STANDARDS_SKILL_DIR)
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
            raise BuildingStandardsSkillError(
                "archive does not contain building-structure-standards payload"
            )
        missing = [
            str(relative) for relative in _REQUIRED_FILES if not (staged / relative).is_file()
        ]
        if missing:
            raise BuildingStandardsSkillError(f"skill payload is incomplete: {', '.join(missing)}")
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


def _normalize_code(value: str) -> str:
    normalized = value.replace("\u00a0", " ").strip().upper()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"^(GB(?:/T)?|NB/T|JGJ|HAF)(?=\d)", r"\1 ", normalized)
    return normalized


def _evidence_gate(
    evidence: list[dict[str, Any]], codes: list[str], errors: list[dict[str, str]],
) -> dict[str, Any]:
    available: list[str] = []
    matched: list[str] = []
    for item in evidence:
        rows = item.get("results") or ([item["table"]] if item.get("table") else [])
        qualified = []
        for row in rows:
            code = row.get("standard_code")
            if code:
                matched.append(code)
            if (
                item.get("operation") in {"clause", "search", "table"}
                and item.get("evidence_insufficient") is False
                and item.get("design_advice_allowed") is True
                and row.get("evidence_insufficient") is False
                and row.get("design_advice_allowed") is True
                and row.get("quality_status") == "usable"
                and row.get("quality_flags") == []
                and row.get("content_role") == "normative"
                and (not item.get("standard_code") or item["standard_code"] == code)
            ):
                qualified.append(code)
        # Older query packages lack these gates and remain usable only for lookup.
        item["design_advice_allowed"] = bool(qualified)
        item["evidence_insufficient"] = not qualified
        available.extend(qualified)
    available = _unique(available)
    required = codes or _unique(matched)
    missing = [code for code in required if code not in matched]
    insufficient = [code for code in required if code in matched and code not in available]
    allowed = bool(available) and not missing and not insufficient and not errors
    return {
        "evidence_insufficient": not allowed,
        "design_advice_allowed": allowed,
        "evidence_level": "sufficient" if allowed else ("partial" if matched else "none"),
        "available_codes": available,
        "missing_content_codes": missing,
        "insufficient_quality_codes": insufficient,
    }


def _render_context(payload: dict[str, Any], limit: int) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(rendered) <= limit:
        return rendered
    # Never cut serialized quality fields or retain an approval for omitted evidence.
    payload.update(
        context_truncated=True, evidence_insufficient=True, design_advice_allowed=False,
        evidence_level="partial", available_codes=[],
    )
    while payload["evidence"]:
        rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(rendered) <= limit:
            return rendered
        payload["evidence"].pop()
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(rendered) > limit:
        minimal = {
            "evidence_insufficient": True, "design_advice_allowed": False,
            "context_truncated": True, "evidence": [],
        }
        payload.clear()
        payload.update(minimal)
        rendered = json.dumps(payload, separators=(",", ":"))
    return rendered


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the building/structure/site standards offline Skill"
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    installed = install_skill_archive(args.archive, args.destination)
    print(
        json.dumps(
            {"ok": True, "skill_root": str(installed)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
