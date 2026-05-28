from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.entities import DXFEntity

from ..audit_check.bridge import AuditDotNetScanner
from ..audit_check.lexicon import AuditLexiconLoader
from ..audit_check.matcher import AuditMatchEngine
from ..audit_check.roi_mapper import AuditFieldContextMapper
from ..cad import A4MultipageGrouper, FrameDetector, ODAConverter, TitleblockExtractor
from ..config import get_config
from ..models import Job
from ..pipeline.shared_prep import SharedPrepService
from .factory_index_bridge import FactoryIndexMapReplacementService
from .mapping import ReplaceMapping, ReplaceMappingBuilder
from .reporting import write_replace_report_json, write_replace_report_xlsx


def derive_replaced_dwg_filename(
    *,
    source_name: str,
    source_project_no: str,
    target_project_no: str,
) -> str:
    path = Path(str(source_name or "").strip() or "replaced.dwg")
    suffix = path.suffix or ".dwg"
    stem = path.stem or "replaced"
    source_project_no = str(source_project_no or "").strip()
    target_project_no = str(target_project_no or "").strip()

    if source_project_no and source_project_no in stem:
        return f"{stem.replace(source_project_no, target_project_no, 1)}{suffix}"
    return f"{stem}——{target_project_no}{suffix}"


class AuditReplaceExecutor:
    _EXTERNAL_CODE_CONTEXT = "titleblock_external_code"
    _EXTERNAL_CODE_MIN_LEN = 19

    def __init__(self) -> None:
        self.config = get_config()
        self.oda = ODAConverter()
        self.frame_detector = FrameDetector()
        self.titleblock_extractor = TitleblockExtractor()
        self.a4_grouper = A4MultipageGrouper()
        self.lexicon_loader = AuditLexiconLoader()
        self.dotnet_scanner = AuditDotNetScanner()
        self.mapping_builder = ReplaceMappingBuilder()
        self.factory_index_maps = FactoryIndexMapReplacementService()

    def execute(self, job: Job) -> None:
        if not job.input_files:
            raise ValueError("audit_replace requires one uploaded dwg file")

        source_dwg = Path(job.input_files[0]).resolve()
        source_display_name = Path(str(job.source_filename or source_dwg.name)).name or source_dwg.name
        source_project_no = str(job.params.get("source_project_no") or "").strip()
        target_project_no = str(job.params.get("target_project_no") or "").strip()
        if not source_project_no or not target_project_no:
            raise ValueError("source_project_no and target_project_no are required for replace")

        job.mark_running(stage="AUDIT_REPLACE")
        job.progress.message = "replacing"
        job.work_dir = self.config.get_job_dir(job.job_id)
        job.work_dir.mkdir(parents=True, exist_ok=True)

        shared_prep_dir = str(job.params.get("shared_prep_dir") or "").strip()
        if shared_prep_dir:
            prep = SharedPrepService.load(Path(shared_prep_dir))
            source_dxf = prep.source_converted_dxf
            remaining_frames = prep.frames
            sheet_sets = prep.sheet_sets
        else:
            dxf_dir = job.work_dir / "work" / "replace_dxf"
            dxf_dir.mkdir(parents=True, exist_ok=True)
            source_dxf = self.oda.dwg_to_dxf(source_dwg, dxf_dir)
            self.frame_detector.set_project_no(source_project_no)
            self.titleblock_extractor.set_project_no(source_project_no)
            frames = self.frame_detector.detect_frames(source_dxf)
            for frame in frames:
                frame.runtime.cad_source_file = source_dwg
                self.titleblock_extractor.extract_fields(source_dxf, frame)
            remaining_frames, sheet_sets = self.a4_grouper.group_a4_pages(frames)

        lexicon = self.lexicon_loader.load(self.config.audit_check.lexicon_path)
        mapping = self.mapping_builder.build(
            workbook_path=self.config.audit_check.lexicon_path,
            source_project_no=source_project_no,
            target_project_no=target_project_no,
        )
        mapper = AuditFieldContextMapper(remaining_frames, sheet_sets)
        slot_runtime = job.params.get("cad_slot_runtime")
        scan_items = self.dotnet_scanner.scan(
            job_id=job.job_id,
            source_dwg=source_dwg,
            workspace_dir=job.work_dir / "work",
            slot_runtime=slot_runtime if isinstance(slot_runtime, dict) else None,
        )
        annotated_items = [mapper.annotate(item) for item in scan_items]
        findings = AuditMatchEngine(lexicon).evaluate(
            project_no=target_project_no,
            unit_no=str(job.params.get("unit_no") or "").strip() or None,
            items=annotated_items,
        )

        replace_entries = self._build_replace_entries(findings, mapping)
        replace_entries.extend(
            self._build_external_code_prefix_entries(
                items=annotated_items,
                mapping=mapping,
                existing_entries=replace_entries,
            )
        )
        replace_dir = job.work_dir / "work" / "replace"
        replace_dir.mkdir(parents=True, exist_ok=True)
        replaced_dxf = replace_dir / "replaced.dxf"
        self._apply_replacements(
            source_dxf=source_dxf,
            output_dxf=replaced_dxf,
            entries=replace_entries,
        )

        converted_dir = replace_dir / "converted"
        converted_dwg = self.oda.dxf_to_dwg(replaced_dxf, converted_dir)
        factory_result = self.factory_index_maps.replace_if_configured(
            job_id=job.job_id,
            source_project_no=source_project_no,
            target_project_no=target_project_no,
            source_filename=source_display_name,
            source_variant=self._factory_index_source_variant(job.params),
            target_variant=self._factory_index_target_variant(job.params),
            source_dxf=replaced_dxf,
            source_dwg=converted_dwg,
            output_dwg=replace_dir / "factory_index" / "replaced_factory_index.dwg",
            workspace_dir=replace_dir / "factory_index",
            slot_runtime=slot_runtime if isinstance(slot_runtime, dict) else None,
        )
        final_dwg = factory_result.output_dwg if factory_result.applied else converted_dwg
        replaced_dwg = job.work_dir / derive_replaced_dwg_filename(
            source_name=source_display_name,
            source_project_no=source_project_no,
            target_project_no=target_project_no,
        )
        replaced_dwg.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(final_dwg, replaced_dwg)

        reports_dir = job.work_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_json = reports_dir / "report.json"
        report_xlsx = reports_dir / "report.xlsx"

        summary = write_replace_report_json(
            report_json,
            source_filename=source_display_name,
            source_project_no=source_project_no,
            target_project_no=target_project_no,
            entries=replace_entries,
            no_op_tokens=mapping.no_op_tokens,
            missing_target_tokens=mapping.missing_target_tokens,
        )
        write_replace_report_xlsx(
            report_xlsx,
            source_filename=source_display_name,
            source_project_no=source_project_no,
            target_project_no=target_project_no,
            entries=replace_entries,
            summary=summary,
            no_op_tokens=mapping.no_op_tokens,
            missing_target_tokens=mapping.missing_target_tokens,
        )

        job.artifacts.reports_dir = reports_dir
        job.artifacts.report_json = report_json
        job.artifacts.report_xlsx = report_xlsx
        job.artifacts.replaced_dwg = replaced_dwg
        job.progress.details["replacement_count"] = int(summary["replacement_count"])
        job.progress.details["affected_drawings_count"] = int(summary["affected_drawings_count"])
        job.progress.details["top_replaced_texts"] = list(summary["top_replaced_texts"])
        job.progress.details["top_internal_codes"] = list(summary["top_internal_codes"])
        job.progress.details["factory_index_map"] = factory_result.to_progress_dict()
        job.mark_succeeded()

    def _factory_index_source_variant(self, params: dict[str, Any]) -> str | None:
        return self._factory_index_variant_from_params(
            params,
            self.config.factory_index_maps.source_variant_param_names,
        )

    def _factory_index_target_variant(self, params: dict[str, Any]) -> str | None:
        names = list(self.config.factory_index_maps.target_variant_param_names)
        for legacy_name in self.config.factory_index_maps.variant_param_names:
            if legacy_name not in names:
                names.append(legacy_name)
        return self._factory_index_variant_from_params(params, names)

    @staticmethod
    def _factory_index_variant_from_params(
        params: dict[str, Any],
        names: list[str],
    ) -> str | None:
        for name in names:
            value = params.get(name)
            if value is not None and str(value).strip():
                return FactoryIndexMapReplacementService._normalize_variant(str(value))
        return None

    @staticmethod
    def _build_replace_entries(findings: list[Any], mapping: ReplaceMapping) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str | None, str]] = set()
        no_op_tokens = set(mapping.no_op_tokens)
        missing_target_tokens = set(mapping.missing_target_tokens)

        for finding in findings:
            identity = (finding.entity_handle, finding.matched_text)
            if identity in seen_pairs:
                continue
            seen_pairs.add(identity)

            status = "pending"
            replacement_text: str | None = None
            message = ""
            if finding.matched_text in no_op_tokens:
                status = "skipped_no_op"
                message = "source_and_target_identical"
            elif finding.matched_text in missing_target_tokens:
                status = "skipped_missing_target"
                message = "target_term_missing"
            elif finding.matched_text not in mapping.replacements:
                status = "skipped_unmapped"
                message = "replacement_not_configured"
            elif not finding.entity_handle:
                status = "skipped_missing_handle"
                message = "entity_handle_missing"
            else:
                replacement_text = mapping.replacements[finding.matched_text]

            entries.append(
                {
                    "status": status,
                    "matched_text": finding.matched_text,
                    "replacement_text": replacement_text,
                    "raw_text": finding.raw_text,
                    "new_text": finding.raw_text,
                    "source_project_no": mapping.source_project_no,
                    "target_project_no": mapping.target_project_no,
                    "matched_project_nos": list(finding.matched_project_nos),
                    "internal_code": finding.internal_code,
                    "layout_name": finding.layout_name,
                    "entity_type": finding.entity_type,
                    "entity_handle": finding.entity_handle,
                    "field_context": finding.field_context,
                    "block_path": finding.block_path,
                    "position_x": finding.position_x,
                    "position_y": finding.position_y,
                    "message": message,
                }
            )
        return entries

    @classmethod
    def _build_external_code_prefix_entries(
        cls,
        *,
        items: list[Any],
        mapping: ReplaceMapping,
        existing_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prefix_pairs = cls._external_code_prefix_pairs(mapping)
        if not prefix_pairs:
            return []

        existing_handles = {
            str(entry.get("entity_handle"))
            for entry in existing_entries
            if entry.get("entity_handle") and entry.get("status") == "pending"
        }
        entries: list[dict[str, Any]] = []
        for group in cls._cluster_external_code_char_items(items):
            ordered = sorted(group, key=cls._item_x)
            chars = [cls._single_alnum(item.raw_text) for item in ordered]
            code = "".join(chars)
            if not cls._looks_like_external_code(code):
                continue

            upper_code = code.upper()
            for source_prefix, target_prefix in prefix_pairs:
                if not upper_code.startswith(source_prefix):
                    continue
                for index, target_char in enumerate(target_prefix):
                    item = ordered[index]
                    source_char = chars[index].upper()
                    handle = str(item.entity_handle or "")
                    if not handle or handle in existing_handles or source_char == target_char:
                        continue
                    existing_handles.add(handle)
                    entries.append(
                        {
                            "status": "pending",
                            "matched_text": source_char,
                            "replacement_text": target_char,
                            "raw_text": item.raw_text,
                            "new_text": item.raw_text,
                            "source_project_no": mapping.source_project_no,
                            "target_project_no": mapping.target_project_no,
                            "matched_project_nos": [mapping.source_project_no],
                            "internal_code": item.internal_code,
                            "layout_name": item.layout_name,
                            "entity_type": item.entity_type,
                            "entity_handle": item.entity_handle,
                            "field_context": item.field_context,
                            "block_path": item.block_path,
                            "position_x": item.position_x,
                            "position_y": item.position_y,
                            "message": "external_code_prefix",
                        }
                    )
                break
        return entries

    @staticmethod
    def _external_code_prefix_pairs(mapping: ReplaceMapping) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for source, target in mapping.replacements.items():
            source_text = str(source or "").strip().upper()
            target_text = str(target or "").strip().upper()
            if (
                1 < len(source_text) <= 4
                and len(source_text) == len(target_text)
                and source_text.isalpha()
                and target_text.isalpha()
            ):
                pairs.append((source_text, target_text))
        pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
        return pairs

    @classmethod
    def _cluster_external_code_char_items(cls, items: list[Any]) -> list[list[Any]]:
        keyed: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for item in items:
            if item.field_context != cls._EXTERNAL_CODE_CONTEXT:
                continue
            if not item.entity_handle:
                continue
            if cls._single_alnum(item.raw_text) is None:
                continue
            y = cls._item_y(item)
            x = cls._item_x(item)
            if y is None or x is None:
                continue
            keyed[
                (
                    str(item.internal_code or ""),
                    str(item.layout_name or ""),
                )
            ].append(item)

        groups: list[list[Any]] = []
        for bucket in keyed.values():
            current: list[Any] = []
            current_y: float | None = None
            for item in sorted(bucket, key=lambda row: (cls._item_y(row) or 0.0, cls._item_x(row) or 0.0)):
                y = cls._item_y(item)
                tolerance = cls._line_y_tolerance(item)
                if current and current_y is not None and y is not None and abs(y - current_y) > tolerance:
                    groups.append(current)
                    current = []
                    current_y = None
                current.append(item)
                item_y = y or 0.0
                current_y = item_y if current_y is None else (current_y * (len(current) - 1) + item_y) / len(current)
            if current:
                groups.append(current)
        return groups

    @classmethod
    def _looks_like_external_code(cls, value: str) -> bool:
        text = str(value or "").strip().upper()
        if len(text) < cls._EXTERNAL_CODE_MIN_LEN:
            return False
        return text[0].isalpha() and sum(1 for char in text if char.isdigit()) >= 3

    @staticmethod
    def _single_alnum(value: str) -> str | None:
        text = re.sub(r"[^A-Za-z0-9]", "", str(value or "").strip().upper())
        return text if len(text) == 1 else None

    @staticmethod
    def _item_x(item: Any) -> float | None:
        if item.text_bbox is not None:
            return float(item.text_bbox.xmin)
        if item.position_x is not None:
            return float(item.position_x)
        return None

    @staticmethod
    def _item_y(item: Any) -> float | None:
        if item.text_bbox is not None:
            return float((item.text_bbox.ymin + item.text_bbox.ymax) / 2.0)
        if item.position_y is not None:
            return float(item.position_y)
        return None

    @staticmethod
    def _line_y_tolerance(item: Any) -> float:
        if item.text_bbox is not None and item.text_bbox.height > 0:
            return max(5.0, float(item.text_bbox.height) * 0.75)
        return 5.0

    def _apply_replacements(
        self,
        *,
        source_dxf: Path,
        output_dxf: Path,
        entries: list[dict[str, Any]],
    ) -> None:
        doc = ezdxf.readfile(source_dxf)
        pending_by_handle: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in entries:
            if entry["status"] == "pending" and entry.get("entity_handle"):
                pending_by_handle[str(entry["entity_handle"])].append(entry)

        for handle, handle_entries in pending_by_handle.items():
            entity = doc.entitydb.get(handle)
            if entity is None:
                for entry in handle_entries:
                    entry["status"] = "skipped_missing_entity"
                    entry["message"] = "entity_not_found_in_dxf"
                continue

            current_text = self._get_entity_text(entity)
            if current_text is None:
                for entry in handle_entries:
                    entry["status"] = "skipped_unsupported_entity"
                    entry["message"] = f"unsupported_entity:{entity.dxftype()}"
                continue

            updated_text = current_text
            for entry in sorted(handle_entries, key=lambda item: len(str(item["matched_text"])), reverse=True):
                replacement_text = str(entry.get("replacement_text") or "")
                updated_text = self._replace_token(updated_text, str(entry["matched_text"]), replacement_text)

            if updated_text == current_text:
                for entry in handle_entries:
                    entry["status"] = "skipped_not_changed"
                    entry["new_text"] = current_text
                    entry["message"] = "replacement_made_no_change"
                continue

            self._set_entity_text(entity, updated_text)
            for entry in handle_entries:
                entry["status"] = "replaced"
                entry["new_text"] = updated_text
                entry["message"] = ""

        output_dxf.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(output_dxf)

    @staticmethod
    def _get_entity_text(entity: DXFEntity) -> str | None:
        entity_type = entity.dxftype().upper()
        if entity_type in {"TEXT", "ATTRIB", "ATTDEF"}:
            return str(entity.dxf.text)
        if entity_type == "MTEXT":
            return str(getattr(entity, "text", ""))
        return None

    @staticmethod
    def _set_entity_text(entity: DXFEntity, value: str) -> None:
        entity_type = entity.dxftype().upper()
        if entity_type in {"TEXT", "ATTRIB", "ATTDEF"}:
            entity.dxf.text = value
            return
        if entity_type == "MTEXT":
            entity.text = value
            return
        raise ValueError(f"unsupported entity type: {entity.dxftype()}")

    @staticmethod
    def _replace_token(text: str, source: str, target: str) -> str:
        pattern = re.compile(re.escape(source), re.IGNORECASE)
        replaced = pattern.sub(target, text)
        if replaced != text or not re.search(r"\s", source):
            return replaced

        compact_pattern = re.compile(
            r"\s*".join(re.escape(char) for char in source if not char.isspace()),
            re.IGNORECASE,
        )
        return compact_pattern.sub(target, text)
