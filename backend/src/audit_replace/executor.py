from __future__ import annotations

import re
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.document import Drawing
from ezdxf.entities import DXFEntity

from ..audit_check.bridge import AuditDotNetScanner
from ..audit_check.lexicon import AuditLexiconLoader
from ..audit_check.matcher import AuditMatchEngine
from ..audit_check.roi_mapper import AuditFieldContextMapper
from ..cad import A4MultipageGrouper, FrameDetector, ODAConverter, TitleblockExtractor
from ..cad.dwg_version import detect_dwg_version_code_or_none
from ..config import get_config, load_mechanism_spec, load_spec, normalize_audit_replace_factory_codes
from ..models import Job
from ..pipeline.shared_prep import SharedPrepService
from ..workload.calculator import WorkloadCalculator
from .factory_index_bridge import FactoryIndexMapReplacementService, FactoryIndexReplacementResult
from .mapping import ReplaceMapping, ReplaceMappingBuilder
from .reporting import write_replace_report_json, write_replace_report_xlsx


def derive_replaced_dwg_filename(
    *,
    source_name: str,
    source_project_no: str,
    target_project_no: str,
    source_unit_no: str | None = None,
    target_unit_no: str | None = None,
    unit_factory_codes: list[str] | None = None,
) -> str:
    path = Path(str(source_name or "").strip() or "replaced.dwg")
    suffix = path.suffix or ".dwg"
    stem = path.stem or "replaced"
    source_project_no = str(source_project_no or "").strip()
    target_project_no = str(target_project_no or "").strip()

    if source_project_no and source_project_no in stem:
        replaced_stem = stem.replace(source_project_no, target_project_no, 1)
        replaced_stem = rewrite_target_unit_text(
            replaced_stem,
            target_project_no=target_project_no,
            source_unit_no=source_unit_no,
            target_unit_no=target_unit_no,
            unit_factory_codes=unit_factory_codes,
        )
        return f"{replaced_stem}{suffix}"
    return f"{stem}——{target_project_no}{suffix}"


def normalize_unit_no(value: object) -> str:
    match = re.search(r"[0-9]", str(value or ""))
    return match.group(0) if match else ""


def rewrite_target_unit_text(
    text: str,
    *,
    target_project_no: str,
    source_unit_no: str | None,
    target_unit_no: str | None,
    unit_factory_codes: list[str] | None = None,
) -> str:
    source_unit = normalize_unit_no(source_unit_no)
    target_unit = normalize_unit_no(target_unit_no)
    if not text or not source_unit or not target_unit or source_unit == target_unit:
        return text

    updated = text
    target_project_no = str(target_project_no or "").strip()
    factory_code_alternation = _factory_code_alternation(unit_factory_codes)
    if target_project_no and factory_code_alternation:
        code_pattern = re.compile(
            rf"(?<!\d)({re.escape(target_project_no)}){re.escape(source_unit)}"
            rf"(?P<factory_code>{factory_code_alternation})(?P<rest>-[A-Z]{{3}}\d{{2}}(?:-\d{{3}})?)",
            re.IGNORECASE,
        )
        updated = code_pattern.sub(
            lambda match: f"{match.group(1)}{target_unit}{match.group('factory_code')}{match.group('rest')}",
            updated,
        )

    explicit_unit_pattern = re.compile(
        rf"{re.escape(source_unit)}(?P<suffix>\s*号\s*(?:机\s*组|岛))",
        re.IGNORECASE,
    )
    updated = explicit_unit_pattern.sub(lambda match: f"{target_unit}{match.group('suffix')}", updated)

    if not factory_code_alternation:
        return updated

    short_factory_pattern = re.compile(
        rf"(?<![A-Z0-9]){re.escape(source_unit)}(?P<factory_code>{factory_code_alternation})(?![A-Z0-9])",
        re.IGNORECASE,
    )
    updated = short_factory_pattern.sub(lambda match: f"{target_unit}{match.group('factory_code')}", updated)

    embedded_factory_prefix_pattern = re.compile(
        rf"(?<![A-Z0-9]){re.escape(source_unit)}(?P<factory_code>{factory_code_alternation})(?=\d)",
        re.IGNORECASE,
    )
    updated = embedded_factory_prefix_pattern.sub(
        lambda match: f"{target_unit}{match.group('factory_code')}",
        updated,
    )

    prefixed_external_code_pattern = re.compile(
        rf"(?<![A-Z0-9])(?P<prefix>[A-Z]{{1,4}}){re.escape(source_unit)}"
        rf"(?P<factory_code>{factory_code_alternation})(?=[A-Z0-9])",
        re.IGNORECASE,
    )
    return prefixed_external_code_pattern.sub(
        lambda match: f"{match.group('prefix')}{target_unit}{match.group('factory_code')}",
        updated,
    )


def _factory_code_alternation(unit_factory_codes: list[str] | None) -> str:
    codes = normalize_audit_replace_factory_codes(
        unit_factory_codes
        if unit_factory_codes is not None
        else load_mechanism_spec().audit_replace.unit_factory_codes,
    )
    return "|".join(re.escape(code) for code in sorted(codes, key=len, reverse=True))


class AuditReplaceExecutor:
    _EXTERNAL_CODE_CONTEXT = "titleblock_external_code"
    _EXTERNAL_CODE_MIN_LEN = 19

    def __init__(self) -> None:
        self.config = get_config()
        self.spec = load_spec()
        self.oda = ODAConverter()
        self.frame_detector = FrameDetector()
        self.titleblock_extractor = TitleblockExtractor()
        self.a4_grouper = A4MultipageGrouper()
        self.lexicon_loader = AuditLexiconLoader()
        self.dotnet_scanner = AuditDotNetScanner()
        self.mapping_builder = ReplaceMappingBuilder()
        self.factory_index_maps = FactoryIndexMapReplacementService()
        self.workload_calculator = WorkloadCalculator()

    def execute(self, job: Job) -> None:
        if not job.input_files:
            raise ValueError("audit_replace requires one uploaded dwg file")

        source_dwg = Path(job.input_files[0]).resolve()
        source_display_name = Path(str(job.source_filename or source_dwg.name)).name or source_dwg.name
        source_project_no = str(job.params.get("source_project_no") or "").strip()
        target_project_no = str(job.params.get("target_project_no") or "").strip()
        if not source_project_no or not target_project_no:
            raise ValueError("source_project_no and target_project_no are required for replace")
        source_unit_no = self._factory_index_source_variant(job.params)
        target_unit_no = self._factory_index_target_variant(job.params)
        unit_factory_codes = self._unit_factory_codes(job.params)

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
            unit_no=target_unit_no or str(job.params.get("unit_no") or "").strip() or None,
            items=annotated_items,
        )

        replace_entries = self._build_replace_entries(
            findings,
            mapping,
            source_unit_no=source_unit_no,
            target_unit_no=target_unit_no,
            unit_factory_codes=unit_factory_codes,
        )
        replace_entries.extend(
            self._build_external_code_prefix_entries(
                items=annotated_items,
                mapping=mapping,
                existing_entries=replace_entries,
            )
        )
        replace_entries.extend(
            self._build_external_code_unit_entries(
                items=annotated_items,
                mapping=mapping,
                existing_entries=replace_entries,
                source_unit_no=source_unit_no,
                target_unit_no=target_unit_no,
                unit_factory_codes=unit_factory_codes,
            )
        )
        postprocess_config = self._replace_postprocess_config()
        replace_entries.extend(
            self._build_titleblock_standardization_entries(
                items=annotated_items,
                existing_entries=replace_entries,
                issue_month_text=self._current_issue_month_text(
                    str(postprocess_config.get("issue_month_format") or "%Y.%m"),
                ),
                target_revision=str(postprocess_config.get("target_revision") or "A"),
                target_status=str(postprocess_config.get("target_status") or "CFC"),
                status_pattern=str(
                    postprocess_config.get("status_pattern") or r"^[A-Z]{2,6}$"
                ),
                target_revision_description=str(
                    postprocess_config.get("target_revision_description") or "首次出版",
                ),
                revision_description_keywords=[
                    str(value)
                    for value in postprocess_config.get("revision_description_keywords", ["出版", "升版"])
                    if str(value)
                ],
                date_pattern=str(postprocess_config.get("date_pattern") or r"\d{4}\.\d{2}"),
                source_project_no=mapping.source_project_no,
                target_project_no=mapping.target_project_no,
            )
        )
        replace_entries.extend(
            self._build_internal_code_revision_suffix_entries(
                items=annotated_items,
                existing_entries=replace_entries,
                pattern=str(
                    postprocess_config.get("internal_code_revision_suffix_pattern")
                    or (
                        r"^(?P<code>\d{4}[A-Z0-9]+(?:-[A-Z0-9]+){1,2})\s*"
                        r"[（(]\s*[A-Z]\s*(?:版)?\s*[）)]$"
                    )
                ),
                source_project_no=mapping.source_project_no,
                target_project_no=mapping.target_project_no,
            )
        )
        replace_dir = job.work_dir / "work" / "replace"
        replace_dir.mkdir(parents=True, exist_ok=True)
        replaced_dxf = replace_dir / "replaced.dxf"
        self._apply_replacements(
            source_dxf=source_dxf,
            output_dxf=replaced_dxf,
            entries=replace_entries,
            target_project_no=target_project_no,
            source_unit_no=source_unit_no,
            target_unit_no=target_unit_no,
            unit_factory_codes=unit_factory_codes,
        )

        converted_dir = replace_dir / "converted"
        converted_dwg = self.oda.dxf_to_dwg(replaced_dxf, converted_dir)
        if self._should_skip_factory_index_for_unit_without_template(
            source_project_no=source_project_no,
            source_unit_no=source_unit_no,
            target_project_no=target_project_no,
            target_unit_no=target_unit_no,
        ):
            factory_result = FactoryIndexReplacementResult(
                applied=False,
                output_dwg=converted_dwg,
                message="factory_index_map_skipped_unit_without_template",
            )
        else:
            factory_result = self.factory_index_maps.replace_if_configured(
                job_id=job.job_id,
                source_project_no=source_project_no,
                target_project_no=target_project_no,
                source_filename=source_display_name,
                source_variant=source_unit_no,
                target_variant=target_unit_no,
                source_dxf=replaced_dxf,
                source_dwg=converted_dwg,
                output_dwg=replace_dir / "factory_index" / "replaced_factory_index.dwg",
                workspace_dir=replace_dir / "factory_index",
                slot_runtime=slot_runtime if isinstance(slot_runtime, dict) else None,
            )
        final_dwg = factory_result.output_dwg if factory_result.applied else converted_dwg
        if factory_result.applied:
            final_dwg = self._rewrite_target_units_in_dwg(
                source_dwg=final_dwg,
                workspace_dir=replace_dir / "target_unit_postprocess",
                target_project_no=target_project_no,
                source_unit_no=source_unit_no,
                target_unit_no=target_unit_no,
                unit_factory_codes=unit_factory_codes,
            )
        replaced_dwg = job.work_dir / derive_replaced_dwg_filename(
            source_name=source_display_name,
            source_project_no=source_project_no,
            target_project_no=target_project_no,
            source_unit_no=source_unit_no,
            target_unit_no=target_unit_no,
            unit_factory_codes=unit_factory_codes,
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
        self._record_workload(job, remaining_frames, sheet_sets)
        job.mark_succeeded()

    def _record_workload(self, job: Job, frames: list, sheet_sets: list) -> None:
        summary = self.workload_calculator.build_from_frame_sets(frames, sheet_sets)
        job.progress.details["workload"] = summary.model_dump(mode="json")
        job.progress.details["effective_workload"] = round(
            float(summary.final_workload_a1 or summary.initial_workload_a1 or 0.0),
            self.workload_calculator.precision,
        )

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
    def _unit_factory_codes(params: dict[str, Any]) -> list[str]:
        if "unit_factory_codes" not in params:
            return normalize_audit_replace_factory_codes(
                load_mechanism_spec().audit_replace.unit_factory_codes,
            )
        raw = params.get("unit_factory_codes")
        if isinstance(raw, str):
            values = re.split(r"[\s,，;；、]+", raw)
        elif isinstance(raw, (list, tuple, set)):
            values = list(raw)
        else:
            values = []
        return normalize_audit_replace_factory_codes(values)

    def _should_skip_factory_index_for_unit_without_template(
        self,
        *,
        source_project_no: str,
        source_unit_no: str | None,
        target_project_no: str,
        target_unit_no: str | None,
    ) -> bool:
        if self._is_unlisted_unit_for_project(
            project_no=source_project_no,
            unit_no=source_unit_no,
        ) or self._is_unlisted_unit_for_project(
            project_no=target_project_no,
            unit_no=target_unit_no,
        ):
            return True

        source_rules = self.config.factory_index_maps.source_variant_rules.get(
            str(source_project_no or "").strip(),
        )
        normalized_source_unit = normalize_unit_no(source_unit_no)
        if source_rules and normalized_source_unit and normalized_source_unit not in source_rules:
            return True

        target_templates = self.config.factory_index_maps.island_templates.get(
            str(target_project_no or "").strip(),
        )
        normalized_target_unit = normalize_unit_no(target_unit_no)
        if target_templates and normalized_target_unit and normalized_target_unit not in target_templates:
            return True
        if (
            normalized_target_unit
            and self._is_universal_unit(normalized_target_unit)
            and target_templates is None
            and str(target_project_no or "").strip() in self.config.factory_index_maps.templates
        ):
            return True

        return False

    def _is_universal_unit(self, unit_no: str | None) -> bool:
        normalized_unit_no = normalize_unit_no(unit_no)
        if not normalized_unit_no:
            return False
        return normalized_unit_no in {
            str(value).strip()
            for value in self.config.audit_check.unit_consistency.universal_units
            if str(value).strip()
        }

    def _is_unlisted_unit_for_project(self, *, project_no: str, unit_no: str | None) -> bool:
        normalized_project_no = str(project_no or "").strip()
        normalized_unit_no = normalize_unit_no(unit_no)
        if not normalized_project_no or not normalized_unit_no:
            return False
        configured_units = [
            str(value).strip()
            for value in self.config.audit_check.unit_consistency.project_units.get(
                normalized_project_no,
                [],
            )
            if str(value).strip()
        ]
        if not configured_units or normalized_unit_no in configured_units:
            return False
        unit_config = self.config.audit_check.unit_consistency
        if not unit_config.allow_unlisted_unit_no:
            return False
        try:
            return bool(re.fullmatch(str(unit_config.unit_no_pattern or ""), normalized_unit_no))
        except re.error:
            return False

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

    def _replace_postprocess_config(self) -> dict[str, Any]:
        config = self.spec.titleblock_extract.get("replace_postprocess", {})
        return config if isinstance(config, dict) else {}

    @staticmethod
    def _current_issue_month_text(format_text: str = "%Y.%m") -> str:
        return date.today().strftime(format_text or "%Y.%m")

    @staticmethod
    def _build_replace_entries(
        findings: list[Any],
        mapping: ReplaceMapping,
        *,
        source_unit_no: str | None = None,
        target_unit_no: str | None = None,
        unit_factory_codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
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
            if getattr(finding, "context_kind", "") == "unit_consistency":
                replacement_text = rewrite_target_unit_text(
                    finding.matched_text,
                    target_project_no=mapping.target_project_no,
                    source_unit_no=source_unit_no,
                    target_unit_no=target_unit_no,
                    unit_factory_codes=unit_factory_codes,
                )
                if replacement_text == finding.matched_text:
                    status = "skipped_unmapped"
                    replacement_text = None
                    message = "replacement_not_configured"
            elif finding.matched_text in no_op_tokens:
                status = "skipped_no_op"
                message = "source_and_target_identical"
            elif finding.matched_text in missing_target_tokens:
                status = "skipped_missing_target"
                message = "target_term_missing"
            elif finding.matched_text not in mapping.replacements:
                status = "skipped_unmapped"
                message = "replacement_not_configured"
            else:
                replacement_text = mapping.replacements[finding.matched_text]
            if status == "pending" and not finding.entity_handle:
                status = "skipped_missing_handle"
                replacement_text = None
                message = "entity_handle_missing"

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
                    "context_kind": getattr(finding, "context_kind", ""),
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
            if any(char is None for char in chars):
                continue
            normalized_chars = [str(char) for char in chars]
            code = "".join(normalized_chars)
            if not cls._looks_like_external_code(code):
                continue

            upper_code = code.upper()
            matched_pair = next(
                (
                    (source_prefix, target_prefix)
                    for source_prefix, target_prefix in prefix_pairs
                    if upper_code.startswith(source_prefix)
                ),
                None,
            )
            if matched_pair is None:
                continue
            source_prefix, target_prefix = matched_pair
            for index, target_char in enumerate(target_prefix):
                item = ordered[index]
                source_char = normalized_chars[index].upper()
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
                        "context_kind": "code_like",
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
        return entries

    @classmethod
    def _build_external_code_unit_entries(
        cls,
        *,
        items: list[Any],
        mapping: ReplaceMapping,
        existing_entries: list[dict[str, Any]],
        source_unit_no: str | None,
        target_unit_no: str | None,
        unit_factory_codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        source_unit = normalize_unit_no(source_unit_no)
        target_unit = normalize_unit_no(target_unit_no)
        if not source_unit or not target_unit or source_unit == target_unit:
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
            if any(char is None for char in chars):
                continue
            normalized_chars = [str(char) for char in chars]
            code = "".join(normalized_chars)
            if not cls._looks_like_external_code(code):
                continue

            rewritten_code = rewrite_target_unit_text(
                code,
                target_project_no=mapping.target_project_no,
                source_unit_no=source_unit,
                target_unit_no=target_unit,
                unit_factory_codes=unit_factory_codes,
            ).upper()
            if rewritten_code == code.upper() or len(rewritten_code) != len(normalized_chars):
                continue

            for index, target_char in enumerate(rewritten_code):
                source_char = normalized_chars[index].upper()
                if source_char == target_char:
                    continue
                item = ordered[index]
                handle = str(item.entity_handle or "")
                if not handle or handle in existing_handles:
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
                        "matched_project_nos": [mapping.target_project_no],
                        "context_kind": "unit_consistency",
                        "internal_code": item.internal_code,
                        "layout_name": item.layout_name,
                        "entity_type": item.entity_type,
                        "entity_handle": item.entity_handle,
                        "field_context": item.field_context,
                        "block_path": item.block_path,
                        "position_x": item.position_x,
                        "position_y": item.position_y,
                        "message": "external_code_unit",
                    }
                )
        return entries

    @classmethod
    def _build_titleblock_standardization_entries(
        cls,
        *,
        items: list[Any],
        existing_entries: list[dict[str, Any]],
        issue_month_text: str,
        target_revision: str,
        target_revision_description: str,
        date_pattern: str,
        target_status: str = "CFC",
        status_pattern: str = r"^[A-Z]{2,6}$",
        revision_description_keywords: list[str] | None = None,
        source_project_no: str = "",
        target_project_no: str = "",
    ) -> list[dict[str, Any]]:
        existing_handles = {
            str(entry.get("entity_handle"))
            for entry in existing_entries
            if entry.get("entity_handle") and entry.get("status") == "pending"
        }
        entries: list[dict[str, Any]] = []

        try:
            compiled_date_pattern = re.compile(date_pattern)
        except re.error:
            compiled_date_pattern = re.compile(r"\d{4}\.\d{2}")
        try:
            compiled_status_pattern = re.compile(status_pattern)
        except re.error:
            compiled_status_pattern = re.compile(r"^[A-Z]{2,6}$")

        revision_groups_by_frame = cls._group_items_by_frame_key_and_context(
            items,
            field_context="titleblock_revision",
        )
        date_groups_by_frame = cls._group_items_by_frame_key_and_context(
            items,
            field_context="titleblock_date",
        )
        handled_date_handles: set[str] = set()
        for frame_key, revision_group in revision_groups_by_frame.items():
            sorted_revisions = sorted(revision_group, key=lambda item: cls._item_y(item) or 0.0)
            keep_revision = sorted_revisions[0] if sorted_revisions else None
            if keep_revision is None:
                continue
            for date_item in date_groups_by_frame.get(frame_key, []):
                handle = str(date_item.entity_handle or "")
                if not handle or handle in existing_handles:
                    continue
                paired_revision = cls._nearest_same_row_item(date_item, sorted_revisions)
                if paired_revision is None:
                    continue
                raw_text = str(date_item.raw_text or "")
                match = compiled_date_pattern.search(raw_text)
                if paired_revision is keep_revision:
                    if match is None or match.group(0) == issue_month_text:
                        continue
                    entries.append(
                        cls._make_standardization_entry(
                            date_item,
                            matched_text=match.group(0),
                            replacement_text=issue_month_text,
                            message="titleblock_date_month",
                            source_project_no=source_project_no,
                            target_project_no=target_project_no,
                        )
                    )
                else:
                    matched_text = match.group(0) if match is not None else raw_text
                    if not matched_text:
                        continue
                    entries.append(
                        cls._make_standardization_entry(
                            date_item,
                            matched_text=matched_text,
                            replacement_text="",
                            message="titleblock_date_clear_non_target_revision",
                            source_project_no=source_project_no,
                            target_project_no=target_project_no,
                        )
                    )
                existing_handles.add(handle)
                handled_date_handles.add(handle)

        status_groups_by_frame = cls._group_items_by_frame_key_and_context(
            items,
            field_context="titleblock_status",
        )
        for frame_key, status_group in status_groups_by_frame.items():
            status_group = [
                item
                for item in status_group
                if (
                    compiled_status_pattern.fullmatch(str(item.raw_text or "").strip())
                    or str(item.raw_text or "").strip().casefold() == target_status.casefold()
                )
            ]
            revisions = sorted(
                revision_groups_by_frame.get(frame_key, []),
                key=lambda item: cls._item_y(item) or 0.0,
            )
            keep_revision = revisions[0] if revisions else None
            sorted_statuses = sorted(status_group, key=lambda item: cls._item_y(item) or 0.0)
            keep_status = sorted_statuses[0] if keep_revision is None else None
            for status_item in sorted_statuses:
                handle = str(status_item.entity_handle or "")
                if not handle or handle in existing_handles:
                    continue
                if keep_revision is not None:
                    paired_revision = cls._nearest_same_row_item(status_item, revisions)
                    is_keep = paired_revision is keep_revision
                else:
                    is_keep = status_item is keep_status
                raw_text = str(status_item.raw_text or "")
                replacement_text = target_status if is_keep else ""
                if raw_text.strip() == replacement_text:
                    continue
                entries.append(
                    cls._make_standardization_entry(
                        status_item,
                        matched_text=raw_text,
                        replacement_text=replacement_text,
                        message=(
                            "titleblock_status_target_cfc"
                            if is_keep
                            else "titleblock_status_clear_non_target_revision"
                        ),
                        source_project_no=source_project_no,
                        target_project_no=target_project_no,
                    )
                )
                existing_handles.add(handle)

        for item in items:
            if item.field_context != "titleblock_date":
                continue
            handle = str(item.entity_handle or "")
            if not handle or handle in existing_handles or handle in handled_date_handles:
                continue
            match = compiled_date_pattern.search(str(item.raw_text or ""))
            if match is None or match.group(0) == issue_month_text:
                continue
            entries.append(
                cls._make_standardization_entry(
                    item,
                    matched_text=match.group(0),
                    replacement_text=issue_month_text,
                    message="titleblock_date_month",
                    source_project_no=source_project_no,
                    target_project_no=target_project_no,
                )
            )
            existing_handles.add(handle)

        for field_context, target_text, message in (
            ("titleblock_revision", target_revision, "titleblock_revision_target_a"),
            (
                "titleblock_revision_description",
                target_revision_description,
                "titleblock_revision_description_target_a",
            ),
        ):
            grouped = cls._group_items_by_frame_and_context(
                items,
                field_context=field_context,
                revision_description_keywords=revision_description_keywords,
            )
            for group in grouped:
                sorted_group = sorted(group, key=lambda item: cls._item_y(item) or 0.0)
                keep = sorted_group[0] if sorted_group else None
                for item in sorted_group:
                    handle = str(item.entity_handle or "")
                    if not handle or handle in existing_handles:
                        continue
                    raw_text = str(item.raw_text or "")
                    if item is keep:
                        if target_text and raw_text.strip() != target_text:
                            entries.append(
                                cls._make_standardization_entry(
                                    item,
                                    matched_text=raw_text,
                                    replacement_text=target_text,
                                    message=message,
                                    source_project_no=source_project_no,
                                    target_project_no=target_project_no,
                                )
                            )
                            existing_handles.add(handle)
                        continue
                    entries.append(
                        cls._make_standardization_entry(
                            item,
                            matched_text=raw_text,
                            replacement_text="",
                            message=message,
                            source_project_no=source_project_no,
                            target_project_no=target_project_no,
                        )
                    )
                    existing_handles.add(handle)

        return entries

    @classmethod
    def _build_internal_code_revision_suffix_entries(
        cls,
        *,
        items: list[Any],
        existing_entries: list[dict[str, Any]],
        pattern: str,
        source_project_no: str = "",
        target_project_no: str = "",
    ) -> list[dict[str, Any]]:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return []
        existing_suffix_handles = {
            str(entry.get("entity_handle"))
            for entry in existing_entries
            if entry.get("entity_handle")
            and entry.get("status") == "pending"
            and entry.get("message") == "internal_code_revision_suffix_removed"
        }
        entries: list[dict[str, Any]] = []
        for item in items:
            handle = str(item.entity_handle or "")
            if not handle or handle in existing_suffix_handles:
                continue
            raw_text = str(item.raw_text or "")
            match = compiled.fullmatch(raw_text.strip())
            if match is None:
                continue
            code = str(match.groupdict().get("code") or "").strip()
            if not code or code == raw_text:
                continue
            entries.append(
                cls._make_standardization_entry(
                    item,
                    matched_text=raw_text,
                    replacement_text=code,
                    message="internal_code_revision_suffix_removed",
                    source_project_no=source_project_no,
                    target_project_no=target_project_no,
                )
            )
            existing_suffix_handles.add(handle)
        return entries

    @staticmethod
    def _group_items_by_frame_and_context(
        items: list[Any],
        *,
        field_context: str,
        revision_description_keywords: list[str] | None = None,
    ) -> list[list[Any]]:
        grouped = AuditReplaceExecutor._group_items_by_frame_key_and_context(
            items,
            field_context=field_context,
            revision_description_keywords=revision_description_keywords,
        )
        return list(grouped.values())

    @staticmethod
    def _group_items_by_frame_key_and_context(
        items: list[Any],
        *,
        field_context: str,
        revision_description_keywords: list[str] | None = None,
    ) -> dict[tuple[str, str], list[Any]]:
        grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for item in items:
            if item.field_context != field_context or not item.entity_handle:
                continue
            if AuditReplaceExecutor._item_y(item) is None:
                continue
            if field_context == "titleblock_revision_description":
                raw_text = str(item.raw_text or "")
                keywords = revision_description_keywords or ["出版", "升版"]
                if not any(keyword and keyword in raw_text for keyword in keywords):
                    continue
            grouped[(str(item.internal_code or ""), str(item.layout_name or ""))].append(item)
        return grouped

    @classmethod
    def _nearest_same_row_item(cls, item: Any, candidates: list[Any]) -> Any | None:
        item_y = cls._item_y(item)
        if item_y is None:
            return None
        nearby: list[tuple[float, Any]] = []
        for candidate in candidates:
            candidate_y = cls._item_y(candidate)
            if candidate_y is None:
                continue
            distance = abs(candidate_y - item_y)
            if distance <= cls._same_titleblock_row_y_tolerance(item, candidate):
                nearby.append((distance, candidate))
        if not nearby:
            return None
        nearby.sort(key=lambda pair: pair[0])
        return nearby[0][1]

    @staticmethod
    def _same_titleblock_row_y_tolerance(*items: Any) -> float:
        heights = [
            float(item.text_bbox.height)
            for item in items
            if getattr(item, "text_bbox", None) is not None and item.text_bbox.height > 0
        ]
        return max([5.0, *(height * 0.75 for height in heights)])

    @staticmethod
    def _make_standardization_entry(
        item: Any,
        *,
        matched_text: str,
        replacement_text: str,
        message: str,
        source_project_no: str = "",
        target_project_no: str = "",
    ) -> dict[str, Any]:
        return {
            "status": "pending",
            "matched_text": matched_text,
            "replacement_text": replacement_text,
            "raw_text": item.raw_text,
            "new_text": item.raw_text,
            "source_project_no": source_project_no,
            "target_project_no": target_project_no,
            "matched_project_nos": [],
            "context_kind": "titleblock_standardization",
            "internal_code": item.internal_code,
            "layout_name": item.layout_name,
            "entity_type": item.entity_type,
            "entity_handle": item.entity_handle,
            "field_context": item.field_context,
            "block_path": item.block_path,
            "position_x": item.position_x,
            "position_y": item.position_y,
            "message": message,
        }

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
        target_project_no: str,
        source_unit_no: str | None = None,
        target_unit_no: str | None = None,
        unit_factory_codes: list[str] | None = None,
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
            updated_text = rewrite_target_unit_text(
                updated_text,
                target_project_no=target_project_no,
                source_unit_no=source_unit_no,
                target_unit_no=target_unit_no,
                unit_factory_codes=unit_factory_codes,
            )

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

        self._rewrite_target_units_in_all_text_entities(
            doc,
            target_project_no=target_project_no,
            source_unit_no=source_unit_no,
            target_unit_no=target_unit_no,
            unit_factory_codes=unit_factory_codes,
        )

        output_dxf.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(output_dxf)

    def _rewrite_target_units_in_dwg(
        self,
        *,
        source_dwg: Path,
        workspace_dir: Path,
        target_project_no: str,
        source_unit_no: str | None,
        target_unit_no: str | None,
        unit_factory_codes: list[str] | None = None,
    ) -> Path:
        source_unit = normalize_unit_no(source_unit_no)
        target_unit = normalize_unit_no(target_unit_no)
        if not source_unit or not target_unit or source_unit == target_unit:
            return source_dwg

        workspace_dir.mkdir(parents=True, exist_ok=True)
        source_dxf = self.oda.dwg_to_dxf(source_dwg, workspace_dir / "dxf")
        doc = ezdxf.readfile(source_dxf)
        changed_count = self._rewrite_target_units_in_all_text_entities(
            doc,
            target_project_no=target_project_no,
            source_unit_no=source_unit,
            target_unit_no=target_unit,
            unit_factory_codes=unit_factory_codes,
        )

        output_source_dxf = source_dxf
        if changed_count > 0:
            rewritten_dxf = workspace_dir / "rewritten.dxf"
            doc.saveas(rewritten_dxf)
            output_source_dxf = rewritten_dxf
        try:
            target_version_code = detect_dwg_version_code_or_none(source_dwg)
        except ValueError:
            target_version_code = None
        return self.oda.dxf_to_dwg(
            output_source_dxf,
            workspace_dir / "dwg",
            target_version_code=target_version_code,
        )

    def _rewrite_target_units_in_all_text_entities(
        self,
        doc: Drawing,
        *,
        target_project_no: str,
        source_unit_no: str | None,
        target_unit_no: str | None,
        unit_factory_codes: list[str] | None = None,
    ) -> int:
        changed_count = 0
        for entity in list(doc.entitydb.values()):
            current_text = self._get_entity_text(entity)
            if current_text is None:
                continue
            updated_text = rewrite_target_unit_text(
                current_text,
                target_project_no=target_project_no,
                source_unit_no=source_unit_no,
                target_unit_no=target_unit_no,
                unit_factory_codes=unit_factory_codes,
            )
            if updated_text != current_text:
                self._set_entity_text(entity, updated_text)
                changed_count += 1
        return changed_count

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
