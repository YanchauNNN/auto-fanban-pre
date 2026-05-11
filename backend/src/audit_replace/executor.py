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


class AuditReplaceExecutor:
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
            items=annotated_items,
        )

        replace_entries = self._build_replace_entries(findings, mapping)
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
            source_dxf=replaced_dxf,
            source_dwg=converted_dwg,
            output_dwg=replace_dir / "factory_index" / "replaced_factory_index.dwg",
            workspace_dir=replace_dir / "factory_index",
            slot_runtime=slot_runtime if isinstance(slot_runtime, dict) else None,
        )
        final_dwg = factory_result.output_dwg if factory_result.applied else converted_dwg
        replaced_dwg = job.work_dir / "replaced.dwg"
        replaced_dwg.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(final_dwg, replaced_dwg)

        reports_dir = job.work_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_json = reports_dir / "report.json"
        report_xlsx = reports_dir / "report.xlsx"

        summary = write_replace_report_json(
            report_json,
            source_filename=source_dwg.name,
            source_project_no=source_project_no,
            target_project_no=target_project_no,
            entries=replace_entries,
            no_op_tokens=mapping.no_op_tokens,
            missing_target_tokens=mapping.missing_target_tokens,
        )
        write_replace_report_xlsx(
            report_xlsx,
            source_filename=source_dwg.name,
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
