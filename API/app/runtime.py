from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import queue
import re
import stat
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from fastapi import HTTPException, status

from src.audit_check.executor import AuditCheckExecutor
from src.audit_replace.executor import AuditReplaceExecutor
from src.cad import FrameDetector, ODAConverter
from src.cad.autocad_path_resolver import resolve_autocad_paths
from src.cad.font_preflight import FontPreflightService
from src.cad.font_replacement_plan import normalize_replacement_map
from src.cad.slot_pool import CADSlotPool
from src.calculation_book.archive import ArchiveLimits
from src.calculation_book.executor import (
    CalculationBookJobExecutor,
    build_calculation_book_warning_reason,
)
from src.calculation_book.models import CalculationBookParams
from src.calculation_book.ocr import recognize_stress_legend
from src.calculation_book.preflight import run_calculation_book_preflight
from src.config import get_config, load_mechanism_spec
from src.doc_gen.param_validator import DocParamValidator
from src.job_diagnostics import build_job_diagnostics
from src.models import (
    AccountSnapshot,
    Job,
    JobArtifacts,
    JobStatus,
    JobType,
    TaskGroup,
    TaskOwnerSnapshot,
)
from src.pipeline.executor import PipelineExecutor
from src.pipeline.group_manager import GroupManager
from src.pipeline.job_manager import JobManager
from src.pipeline.project_no_inference import (
    infer_project_no_from_path,
    infer_replace_batch_identity,
    infer_unit_no_from_path,
    resolve_project_no,
)
from src.pipeline.shared_prep import SharedPrepService
from src.pipeline.sqlite_queue import SQLiteQueueStore
from src.result_views import normalize_user_flags
from src.task_groups.visibility import TaskGroupVisibility
from src.workload.calculator import WorkloadCalculator
from src.workload.models import WorkloadSummary

from .metadata import FormMetadataService

logger = logging.getLogger(__name__)
_CALCULATION_PREFLIGHT_TTL_SECONDS = 1800
_UNSAFE_CALCULATION_PREFLIGHT_CACHE_ROOT = (
    "unsafe calculation preflight cache root"
)


def _validate_calculation_preflight_cache_root(cache_root: Path) -> None:
    root_stat = cache_root.lstat()
    is_junction = getattr(cache_root, "is_junction", lambda: False)
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or cache_root.is_symlink()
        or is_junction()
    ):
        raise RuntimeError(_UNSAFE_CALCULATION_PREFLIGHT_CACHE_ROOT)


def _ensure_calculation_preflight_cache_root(cache_root: Path) -> None:
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        _validate_calculation_preflight_cache_root(cache_root)
    except RuntimeError:
        raise
    except OSError as exc:
        raise RuntimeError(
            _UNSAFE_CALCULATION_PREFLIGHT_CACHE_ROOT
        ) from exc


def _cleanup_calculation_preflight_cache(
    cache_root: Path,
    *,
    now: float | None = None,
) -> None:
    """Delete only stale, regular preflight archives from the flat cache."""
    reference_time = time.time() if now is None else now
    try:
        _validate_calculation_preflight_cache_root(cache_root)
        candidates = tuple(cache_root.iterdir())
    except FileNotFoundError:
        return
    except OSError:
        return
    for candidate in candidates:
        if (
            not candidate.name.startswith("calculation-preflight-")
            or candidate.suffix.lower() not in {".zip", ".rar"}
        ):
            continue
        try:
            first_stat = candidate.lstat()
        except OSError:
            continue
        if (
            not stat.S_ISREG(first_stat.st_mode)
            or reference_time - first_stat.st_mtime
            <= _CALCULATION_PREFLIGHT_TTL_SECONDS
        ):
            continue
        try:
            second_stat = candidate.lstat()
            if (
                not stat.S_ISREG(second_stat.st_mode)
                or (second_stat.st_dev, second_stat.st_ino)
                != (first_stat.st_dev, first_stat.st_ino)
            ):
                continue
            candidate.unlink()
        except OSError:
            continue


@dataclass(frozen=True)
class UploadedFilePayload:
    filename: str
    content: bytes
    content_type: str | None = None


def _summary_int(summary: dict[str, object], key: str) -> int:
    value = summary.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        return int(text) if text else 0
    return 0


def _strict_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _safe_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _serialize_calculation_book_warnings(details: dict[str, Any]) -> list[dict[str, Any]]:
    raw_warnings = details.get("calculation_book_warnings")
    if not isinstance(raw_warnings, list):
        return []
    warnings: list[dict[str, Any]] = []
    for raw in raw_warnings:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "needs_review")
        if code not in {
            "needs_review",
            "duplicate_reinforcement_rows",
            "split_image_group",
            "image_only_wall",
            "workbook_only_wall",
            "image_only_slab",
            "workbook_only_slab",
        }:
            code = "needs_review"
        scope = str(raw.get("scope") or "reinforcement")
        if scope not in {"wall", "slab"}:
            scope = "reinforcement"
        allowed_fields = (
            {"wall_id", "wall", "X", "Y", "Z"}
            if scope == "wall"
            else {
                "elevation",
                "top_x",
                "top_y",
                "middle_x",
                "middle_y",
                "bottom_x",
                "bottom_y",
                "z",
            }
        )
        raw_identity = raw.get("identity")
        identity = (
            str(raw_identity).strip()[:100]
            if raw_identity is not None and str(raw_identity).strip()
            else None
        )
        raw_direction = raw.get("direction")
        direction = (
            str(raw_direction)
            if raw_direction is not None
            and str(raw_direction) in allowed_fields
            else None
        )
        source_row = _strict_positive_int(raw.get("source_row"))
        source_sheet = str(raw.get("source_sheet") or "").strip()
        if source_row is None or not source_sheet:
            source_row = None
            source_sheet_value: str | None = None
            source_cells: dict[str, str] = {}
        else:
            source_sheet_value = source_sheet[:100]
            raw_cells = raw.get("source_cells")
            source_cells = {
                str(field): str(address).upper()
                for field, address in (
                    raw_cells.items() if isinstance(raw_cells, dict) else ()
                )
                if str(field) in allowed_fields
                and re.fullmatch(r"[A-Za-z]+[1-9]\d*", str(address)) is not None
            }
        raw_blank_fields = raw.get("blank_fields")
        blank_fields = (
            [
                str(field)
                for field in raw_blank_fields
                if str(field) in allowed_fields
            ]
            if isinstance(raw_blank_fields, list)
            else []
        )
        warnings.append(
            {
                "code": code,
                "scope": scope,
                "identity": identity,
                "direction": direction,
                "source_sheet": source_sheet_value,
                "source_row": source_row,
                "source_cells": source_cells,
                "reason": build_calculation_book_warning_reason(
                    code=code,
                    scope=scope,
                    identity=identity,
                    direction=direction,
                ),
                "blank_fields": blank_fields,
            }
        )
    return warnings


def _serialize_calculation_ai_normalization(
    job: Job,
) -> tuple[bool, dict[str, Any] | None]:
    if job.options.get("ai_reinforcement_normalization") is not True:
        return False, None
    raw = job.progress.details.get("ai_reinforcement_normalization")
    if not isinstance(raw, dict) or raw.get("validation") != "passed":
        return False, None
    string_fields = ("skill_id", "model", "profile")
    integer_fields = (
        "call_count",
        "source_row_count",
        "normalized_wall_count",
        "normalized_slab_count",
        "review_warning_count",
        "duration_ms",
    )
    summary: dict[str, Any] = {
        field: str(raw.get(field) or "")[:160]
        for field in string_fields
    }
    for field in integer_fields:
        value = _safe_non_negative_int(raw.get(field))
        summary[field] = value if value is not None else 0
    summary["validation"] = "passed"
    return True, summary


class PipelineJobProcessor:
    def __init__(
        self,
        *,
        font_preflight_service: FontPreflightService | None = None,
        calculation_book_executor_factory: (
            Callable[[], CalculationBookJobExecutor] | None
        ) = None,
    ) -> None:
        self.font_preflight_service = font_preflight_service
        self.calculation_book_executor_factory = (
            calculation_book_executor_factory or CalculationBookJobExecutor
        )

    def _deliverable_executor(self) -> PipelineExecutor:
        if self.font_preflight_service is None:
            return PipelineExecutor()
        return PipelineExecutor(font_preflight_service=self.font_preflight_service)

    def __call__(self, job: Job) -> None:
        if job.job_type == JobType.CALCULATION_BOOK:
            self.calculation_book_executor_factory().execute(job)
            return
        if job.job_type == JobType.AUDIT_REPLACE:
            mode = str(job.options.get("mode", "")).strip().lower()
            if mode == "replace":
                AuditReplaceExecutor().execute(job)
                return
            AuditCheckExecutor().execute(job)
            return
        self._deliverable_executor().execute(job)

    def execute_slot_bound_phase(self, job: Job) -> Callable[[], None] | None:
        if job.job_type == JobType.AUDIT_REPLACE:
            self(job)
            return None
        return self._deliverable_executor().execute_slot_bound_phase(job)


class DeliverableApiRuntime:
    def __init__(
        self,
        job_processor: Callable[[Job], None] | None = None,
        shared_prep_service: SharedPrepService | None = None,
        font_preflight_service: FontPreflightService | None = None,
        process_jobs_in_api: bool = True,
        worker_process_mode: bool = False,
    ) -> None:
        self.config = get_config()
        self.config.ensure_dirs()
        try:
            _cleanup_calculation_preflight_cache(
                self.config.storage_dir
                / "runtime"
                / "calculation-preflight"
            )
        except RuntimeError:
            logger.error(_UNSAFE_CALCULATION_PREFLIGHT_CACHE_ROOT)
        self.process_jobs_in_api = process_jobs_in_api
        self.worker_process_mode = worker_process_mode
        self.queue_store = SQLiteQueueStore(
            self.config.storage_dir / "runtime" / "fanban_queue.sqlite3"
        )
        self.job_manager = JobManager()
        self.group_manager = GroupManager()
        self.task_visibility = TaskGroupVisibility()
        self.validator = DocParamValidator()
        self.metadata = FormMetadataService()
        self.font_preflight_service = font_preflight_service or FontPreflightService()
        self.font_preflight_oda = ODAConverter()
        self.font_preflight_frame_detector = FrameDetector()
        self.job_processor = job_processor or PipelineJobProcessor(
            font_preflight_service=self.font_preflight_service
        )
        self.shared_prep_service = shared_prep_service or SharedPrepService(
            font_preflight_service=self.font_preflight_service
        )
        self.workload_calculator = WorkloadCalculator()
        self.cad_slot_pool = CADSlotPool(
            config=self.config,
            slot_count=max(int(self.config.cad_runtime.slot_count), 1),
        )
        self._max_active_groups = max(int(self.config.concurrency.max_workers), 1)
        self._max_active_jobs = max(
            1,
            min(int(self.config.concurrency.max_jobs), self.cad_slot_pool.slot_count),
        )
        self._max_doc_jobs = max(int(self.config.concurrency.doc_max_jobs), 1)

        self._group_queue: queue.Queue[str | None] = queue.Queue()
        self._job_queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._group_dispatcher_thread: threading.Thread | None = None
        self._job_dispatcher_thread: threading.Thread | None = None
        self._summary_backfill_thread: threading.Thread | None = None

        self._group_executor = ThreadPoolExecutor(
            max_workers=self._max_active_groups,
            thread_name_prefix='fanban-group',
        )
        self._heavy_executor = ThreadPoolExecutor(
            max_workers=self._max_active_jobs,
            thread_name_prefix='fanban-heavy',
        )
        self._doc_executor = ThreadPoolExecutor(
            max_workers=self._max_doc_jobs,
            thread_name_prefix='fanban-doc',
        )
        self._group_futures: set[Future[None]] = set()
        self._job_futures: set[Future[None]] = set()
        self._doc_futures: set[Future[None]] = set()
        self._running_doc_job_ids: set[str] = set()
        self._future_lock = threading.Lock()
        self._job_completion_events: dict[str, threading.Event] = {}
        self._job_completion_lock = threading.Lock()
        self._calculation_preflight_tokens: dict[str, dict[str, Any]] = {}
        self._calculation_preflight_lock = threading.Lock()

    def start(self) -> None:
        self.queue_store.initialize()
        if not self.process_jobs_in_api:
            self._start_summary_backfill()
            return
        self._recover_groups_and_jobs()
        if self._group_dispatcher_thread and self._group_dispatcher_thread.is_alive():
            return
        self._stop_event.clear()
        self._group_dispatcher_thread = threading.Thread(
            target=self._group_dispatch_loop,
            name='deliverable-group-dispatcher',
            daemon=True,
        )
        self._job_dispatcher_thread = threading.Thread(
            target=self._job_dispatch_loop,
            name='deliverable-job-dispatcher',
            daemon=True,
        )
        self._group_dispatcher_thread.start()
        self._job_dispatcher_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self.process_jobs_in_api:
            self._group_queue.put(None)
            self._job_queue.put(None)
        if self._group_dispatcher_thread:
            self._group_dispatcher_thread.join(timeout=3)
        if self._job_dispatcher_thread:
            self._job_dispatcher_thread.join(timeout=3)
        if self._summary_backfill_thread and self._summary_backfill_thread.is_alive():
            self._summary_backfill_thread.join(timeout=3)
        self._group_executor.shutdown(wait=False, cancel_futures=True)
        self._heavy_executor.shutdown(wait=False, cancel_futures=True)
        self._doc_executor.shutdown(wait=False, cancel_futures=True)

    def health(self) -> dict[str, Any]:
        storage_writable = self._storage_writable()
        if not self.process_jobs_in_api:
            worker_status = self.queue_store.worker_status()
            queue_depth = self.queue_store.queue_depth()
            return {
                'status': 'ok',
                'server_time': datetime.now().astimezone().isoformat(),
                'ready': storage_writable and bool(worker_status["alive"]),
                'storage_writable': storage_writable,
                'worker_alive': bool(worker_status["alive"]),
                'queue_depth': queue_depth,
                'autocad_ready': self._autocad_ready(),
                'office_ready': importlib.util.find_spec('win32com.client') is not None,
                'active_groups': 0,
                'active_jobs': 0,
                'active_doc_jobs': 0,
                'pending_doc_jobs': 0,
                'active_total_jobs': 0,
                'worker_count': int(worker_status["count"]),
                'worker_last_seen_at': worker_status["last_seen_at"],
            }
        group_alive = bool(self._group_dispatcher_thread and self._group_dispatcher_thread.is_alive())
        job_alive = bool(self._job_dispatcher_thread and self._job_dispatcher_thread.is_alive())
        active_doc_jobs = self._active_doc_count()
        pending_doc_jobs = self._pending_doc_count()
        active_jobs = self._active_job_count()
        queue_depth = self._group_queue.qsize() + self._job_queue.qsize() + pending_doc_jobs
        return {
            'status': 'ok',
            'server_time': datetime.now().astimezone().isoformat(),
            'ready': storage_writable and group_alive and job_alive,
            'storage_writable': storage_writable,
            'worker_alive': group_alive and job_alive,
            'queue_depth': queue_depth,
            'autocad_ready': self._autocad_ready(),
            'office_ready': importlib.util.find_spec('win32com.client') is not None,
            'active_groups': self._active_group_count(),
            'active_jobs': active_jobs,
            'active_doc_jobs': active_doc_jobs,
            'pending_doc_jobs': pending_doc_jobs,
            'active_total_jobs': active_jobs + active_doc_jobs,
        }

    def form_schema(self) -> dict[str, Any]:
        return self.metadata.build_form_schema()

    def preflight_fonts(self, *, files: list[UploadedFilePayload]) -> dict[str, Any]:
        upload_errors = self._validate_uploads(files)
        if upload_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"upload_errors": upload_errors, "param_errors": {}},
            )

        preflight_id = f"preflight-{uuid.uuid4().hex[:8]}"
        preflight_root = self.config.storage_dir / "preflight" / preflight_id
        input_dir = preflight_root / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, Any]] = []
        for index, upload in enumerate(files, start=1):
            original_filename = Path(upload.filename).name or 'upload.dwg'
            source_path = input_dir / self._safe_storage_filename(
                upload.filename,
                fallback_stem=f"preflight_{index}",
                seed=preflight_id,
            )
            source_path.write_bytes(upload.content)
            workspace_dir = preflight_root / source_path.stem
            try:
                result = self.font_preflight_service.inspect_dwg(
                    source_dwg=source_path,
                    replacement_policy="none",
                    replacement_font=None,
                    replacement_fonts=None,
                    workspace_dir=workspace_dir,
                )
                result = self._augment_font_preflight_with_compatibility_probe(
                    result=result,
                    source_path=source_path,
                    workspace_dir=workspace_dir,
                    original_filename=original_filename,
                )
                result["filename"] = original_filename
                results.append(result)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "filename": original_filename,
                        "status": "failed",
                        "missing_fonts": [],
                        "detected_style_count": 0,
                        "missing_style_count": 0,
                        "font_replacement_applied": False,
                        "replacement_font": None,
                        "replacement_fonts": {},
                        "replaced_style_count": 0,
                        "errors": [str(exc)],
                    }
                )

        missing_kinds = self._collect_missing_font_kinds(results)
        missing_fonts = self._collect_missing_fonts(results)
        try:
            replacement_options = self.font_preflight_service.list_replacement_options(
                missing_kinds=missing_kinds
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("font preflight replacement options failed: %s", exc)
            replacement_options = []
        try:
            replacement_options_by_kind = self.font_preflight_service.list_replacement_options_by_kind(
                missing_kinds=missing_kinds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("font preflight replacement options by kind failed: %s", exc)
            replacement_options_by_kind = {}
        try:
            default_replacement_fonts = self.font_preflight_service.default_replacement_fonts(
                missing_kinds=missing_kinds,
                missing_fonts=missing_fonts,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("font preflight default replacement fonts failed: %s", exc)
            default_replacement_fonts = {}
        return {
            "files": results,
            "replacement_options": replacement_options,
            "default_replacement_font": replacement_options[0]["value"] if replacement_options else None,
            "replacement_options_by_kind": replacement_options_by_kind,
            "default_replacement_fonts": default_replacement_fonts,
            "requires_confirmation": any(
                self._font_preflight_requires_confirmation(item) for item in results
            ),
        }

    def _augment_font_preflight_with_compatibility_probe(
        self,
        *,
        result: dict[str, Any],
        source_path: Path,
        workspace_dir: Path,
        original_filename: str,
    ) -> dict[str, Any]:
        if str(result.get("status") or "").strip().lower() != "ok":
            return result
        if list(result.get("missing_fonts") or []):
            return result
        if not self._font_compatibility_probe_enabled():
            return result

        frames = self._detect_font_preflight_target_frames(
            source_path=source_path,
            workspace_dir=workspace_dir,
            original_filename=original_filename,
        )
        if not frames:
            return result

        compat_source_dir = workspace_dir / "compatibility_input"
        compat_source_dir.mkdir(parents=True, exist_ok=True)
        compat_source = compat_source_dir / source_path.name
        try:
            compat_source.write_bytes(source_path.read_bytes())
            compat = self.font_preflight_service.inspect_dwg(
                source_dwg=compat_source,
                replacement_policy="none",
                replacement_font=None,
                replacement_fonts=None,
                font_compatibility_mode=True,
                frames=frames,
                workspace_dir=workspace_dir / "compatibility_probe",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "font compatibility preflight probe failed for %s: %s",
                original_filename,
                exc,
            )
            result["font_compatibility_probe_errors"] = [str(exc)]
            return result

        empty_style_entity_count = _summary_int(compat, "empty_style_entity_replaced_count")
        empty_style_style_patched_count = _summary_int(
            compat,
            "empty_style_style_patched_count",
        )
        empty_style_shared_skipped_count = _summary_int(
            compat,
            "empty_style_shared_skipped_count",
        )
        empty_style_target_count = _summary_int(compat, "empty_style_target_regions_count")
        result["font_compatibility_mode"] = True
        result["font_compatibility_required"] = (
            empty_style_entity_count > 0
            or empty_style_style_patched_count > 0
            or empty_style_shared_skipped_count > 0
        )
        result["empty_style_entity_replaced_count"] = empty_style_entity_count
        result["empty_style_style_patched_count"] = empty_style_style_patched_count
        result["empty_style_shared_skipped_count"] = empty_style_shared_skipped_count
        result["empty_style_shared_styles"] = list(
            compat.get("empty_style_shared_styles") or []
        )
        result["empty_style_target_regions_count"] = empty_style_target_count
        result["empty_style_global_replaced_count"] = _summary_int(
            compat,
            "empty_style_global_replaced_count",
        )
        if isinstance(compat.get("empty_style_replacement"), dict):
            result["empty_style_replacement"] = dict(compat["empty_style_replacement"])
        return result

    def _detect_font_preflight_target_frames(
        self,
        *,
        source_path: Path,
        workspace_dir: Path,
        original_filename: str,
    ) -> list[Any]:
        try:
            probe_dir = workspace_dir / "frame_probe"
            probe_dir.mkdir(parents=True, exist_ok=True)
            dxf_path = self.font_preflight_oda.dwg_to_dxf(source_path, probe_dir)
            project_no = infer_project_no_from_path(original_filename) or infer_project_no_from_path(
                source_path.name
            )
            self.font_preflight_frame_detector.set_project_no(project_no)
            frames = self.font_preflight_frame_detector.detect_frames(dxf_path)
            for frame in frames:
                runtime = getattr(frame, "runtime", None)
                if runtime is not None:
                    runtime.cad_source_file = source_path
            return list(frames)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "font preflight target frame probe failed for %s: %s",
                original_filename,
                exc,
            )
            return []

    def _font_compatibility_probe_enabled(self) -> bool:
        font_cfg = self.config.font_preflight
        replacement = getattr(font_cfg, "empty_style_replacement", {})
        fields = getattr(font_cfg, "empty_style_target_fields", [])
        if not isinstance(replacement, dict):
            return False
        has_replacement = any(
            str(replacement.get(key) or "").strip()
            for key in ("font", "bigfont")
        )
        has_fields = any(str(item or "").strip() for item in fields or [])
        return has_replacement and has_fields

    @staticmethod
    def _font_preflight_requires_confirmation(item: dict[str, Any]) -> bool:
        if str(item.get("status") or "").strip().lower() == "missing_fonts":
            return True
        if bool(item.get("font_compatibility_required")):
            return True
        return (
            _summary_int(item, "empty_style_entity_replaced_count") > 0
            or _summary_int(item, "empty_style_style_patched_count") > 0
            or _summary_int(item, "empty_style_shared_skipped_count") > 0
        )

    @staticmethod
    def _collect_missing_font_kinds(results: list[dict[str, Any]]) -> list[str]:
        kinds: list[str] = []
        seen: set[str] = set()
        for item in results:
            for missing in item.get("missing_fonts") or []:
                if not isinstance(missing, dict):
                    continue
                kind = str(missing.get("kind") or "").strip().lower()
                if not kind or kind in seen:
                    continue
                seen.add(kind)
                kinds.append(kind)
        return kinds

    @staticmethod
    def _collect_missing_fonts(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        missing_fonts: list[dict[str, Any]] = []
        for item in results:
            for missing in item.get("missing_fonts") or []:
                if isinstance(missing, dict):
                    missing_fonts.append(dict(missing))
        return missing_fonts

    def create_batch(
        self,
        *,
        files: list[UploadedFilePayload],
        raw_params: dict[str, Any],
        run_audit_check: bool = False,
        split_only: bool = False,
        creator_snapshot: AccountSnapshot | None = None,
    ) -> dict[str, Any]:
        upload_errors = self._validate_uploads(files)
        resolved_submissions = [
            (upload, self._resolve_params_for_upload(raw_params, upload.filename)) for upload in files
        ]
        param_errors = {} if split_only else self._collect_param_errors(resolved_submissions)
        if split_only and run_audit_check:
            param_errors.setdefault("split_only", []).append("cannot_combine_with_audit_check")
        if run_audit_check:
            for field_name, field_errors in self._collect_unit_consistency_param_errors(
                resolved_submissions
            ).items():
                bucket = param_errors.setdefault(field_name, [])
                for error in field_errors:
                    if error not in bucket:
                        bucket.append(error)
        font_param_errors = self._collect_font_param_errors(raw_params)
        for field_name, field_errors in font_param_errors.items():
            bucket = param_errors.setdefault(field_name, [])
            for error in field_errors:
                if error not in bucket:
                    bucket.append(error)
        if upload_errors or param_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={'upload_errors': upload_errors, 'param_errors': param_errors},
            )

        batch_id = self._new_batch_id()
        self._log_submission(
            endpoint="/api/jobs/batch",
            batch_id=batch_id,
            files=files,
            run_audit_check=run_audit_check,
            split_only=split_only,
        )
        if run_audit_check:
            groups = [
                self._create_grouped_submission(
                    batch_id=batch_id,
                    upload=upload,
                    resolved_params=resolved_params,
                    creator_snapshot=creator_snapshot,
                )
                for upload, resolved_params in resolved_submissions
            ]
            return {'batch_id': batch_id, 'jobs': groups}

        jobs: list[dict[str, Any]] = []
        options = {'enabled': True, 'export_pdf': True, 'split_only': bool(split_only)}
        for upload, resolved_params in resolved_submissions:
            source_filename = Path(upload.filename).name or 'upload.dwg'
            job = self.job_manager.create_job(
                job_type=JobType.DELIVERABLE.value,
                project_no=str(resolved_params['project_no']),
                options=options,
                params=resolved_params,
                batch_id=batch_id,
                source_filename=source_filename,
                task_role='仅拆图' if split_only else None,
                creator_snapshot=creator_snapshot,
            )
            self._store_job_upload(job, upload)
            self.job_manager.update_job(job)
            summary = self._index_job_summary(job)
            self._enqueue_job(job.job_id)
            jobs.append(summary)
        return {'batch_id': batch_id, 'jobs': jobs}

    def create_calculation_book(
        self,
        *,
        archive: UploadedFilePayload | None,
        raw_params: dict[str, Any],
        creator_snapshot: AccountSnapshot | None = None,
    ) -> dict[str, Any]:
        param_errors: dict[str, list[str]] = {}
        params: CalculationBookParams | None = None
        try:
            params = CalculationBookParams.model_validate(raw_params)
        except Exception as exc:  # noqa: BLE001
            errors_method = getattr(exc, "errors", None)
            if callable(errors_method):
                for error in errors_method():
                    location = error.get("loc") or ("params_json",)
                    field = str(location[-1])
                    param_errors.setdefault(field, []).append(
                        str(error.get("msg") or "invalid")
                    )
            else:
                param_errors.setdefault("params_json", []).append(str(exc))

        if param_errors or params is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"upload_errors": {}, "param_errors": param_errors},
            )

        preflight_token = params.preflight_token.strip()
        expired_archive_paths: list[Path] = []
        requires_ai_confirmation = False
        with self._calculation_preflight_lock:
            now = time.monotonic()
            for token, entry in list(self._calculation_preflight_tokens.items()):
                if (
                    now - float(entry["created_at"])
                    <= _CALCULATION_PREFLIGHT_TTL_SECONDS
                ):
                    continue
                self._calculation_preflight_tokens.pop(token, None)
                expired_archive_paths.append(Path(str(entry["archive_path"])))
            preflight = self._calculation_preflight_tokens.get(
                preflight_token,
            )
            requires_ai_confirmation = bool(
                preflight is not None
                and preflight.get("requires_ai_normalization", False)
                and not params.confirm_ai_normalization
            )
            if not requires_ai_confirmation:
                preflight = self._calculation_preflight_tokens.pop(
                    preflight_token,
                    None,
                )
        for path in expired_archive_paths:
            path.unlink(missing_ok=True)
        if requires_ai_confirmation:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "upload_errors": {},
                    "param_errors": {
                        "confirm_ai_normalization": [
                            "请确认启动人工智能规范化非标准配筋表"
                        ]
                    },
                },
            )
        if preflight is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "upload_errors": {},
                    "param_errors": {
                        "preflight_token": ["请先完成计算书文件预检"]
                    },
                },
            )
        cached_archive_path = Path(str(preflight["archive_path"]))
        try:
            if bool(preflight.get("include_slab_stress", False)) != (
                params.include_slab_stress
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "upload_errors": {},
                        "param_errors": {
                            "include_slab_stress": [
                                "楼板应力选项已变化，请重新预检"
                            ]
                        },
                    },
                )
            try:
                cached_content = cached_archive_path.read_bytes()
            except OSError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "upload_errors": {
                            "archive": ["预检文件已失效，请重新选择 ZIP 或 RAR 并预检"]
                        },
                        "param_errors": {},
                    },
                ) from exc
            archive_digest = hashlib.sha256(cached_content).hexdigest()
            if preflight["archive_digest"] != archive_digest:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "upload_errors": {
                            "archive": ["预检暂存文件校验失败，请重新预检"]
                        },
                        "param_errors": {},
                    },
                )
            if archive is not None:
                provided_digest = hashlib.sha256(archive.content).hexdigest()
                if preflight["archive_digest"] != provided_digest:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail={
                            "upload_errors": {
                                "archive": [
                                    "当前压缩包与预检时的文件不一致，请重新预检"
                                ]
                            },
                            "param_errors": {},
                        },
                    )

            requires_ai_normalization = bool(
                preflight.get("requires_ai_normalization", False)
            )
            expected_source_row_count = _strict_positive_int(
                preflight.get(
                    "ai_reinforcement_expected_source_row_count"
                )
            )
            if requires_ai_normalization and expected_source_row_count is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "upload_errors": {},
                        "param_errors": {
                            "preflight_token": [
                                "非标准配筋表行数证据无效，请重新预检"
                            ]
                        },
                    },
                )
            cached_archive = UploadedFilePayload(
                filename=str(preflight["archive_filename"]),
                content=cached_content,
                content_type=str(preflight["content_type"]),
            )
            batch_id = self._new_batch_id()
            source_filename = (
                Path(cached_archive.filename).name or "calculation-images.zip"
            )
            job_options: dict[str, object] = {
                "mode": "calculation_book",
                "ai_reinforcement_normalization": (
                    requires_ai_normalization
                ),
            }
            if requires_ai_normalization:
                assert expected_source_row_count is not None
                job_options[
                    "ai_reinforcement_expected_source_row_count"
                ] = expected_source_row_count
            job = self.job_manager.create_job(
                job_type=JobType.CALCULATION_BOOK.value,
                project_no=params.project_no,
                options=job_options,
                params=params.model_dump(
                    mode="json",
                    exclude_computed_fields=True,
                ),
                batch_id=batch_id,
                source_filename=source_filename,
                task_role="计算书",
                creator_snapshot=creator_snapshot,
            )
            self._store_job_upload(job, cached_archive)
            self.job_manager.update_job(job)
            summary = self._index_job_summary(job)
            self._enqueue_job(job.job_id)
            return {"batch_id": batch_id, "jobs": [summary]}
        finally:
            cached_archive_path.unlink(missing_ok=True)

    def preflight_calculation_book(
        self,
        *,
        archive: UploadedFilePayload,
        include_slab_stress: bool = False,
    ) -> dict[str, Any]:
        upload_errors: dict[str, list[str]] = {}
        archive_suffix = Path(archive.filename).suffix.lower()
        if archive_suffix not in {".zip", ".rar"}:
            upload_errors.setdefault("archive", []).append(
                "only .zip or .rar files are allowed"
            )
        if not archive.content:
            upload_errors.setdefault("archive", []).append("archive is empty")
        runtime = self.config.calculation_book
        if len(archive.content) > runtime.max_archive_mb * 1024 * 1024:
            upload_errors.setdefault("archive", []).append(
                f"archive exceeds {runtime.max_archive_mb} MB"
            )
        if upload_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"upload_errors": upload_errors, "param_errors": {}},
            )

        mechanism = load_mechanism_spec().calculation_book
        try:
            cache_root = (
                self.config.storage_dir
                / "runtime"
                / "calculation-preflight"
            )
            _ensure_calculation_preflight_cache_root(cache_root)
            _cleanup_calculation_preflight_cache(cache_root)
            with TemporaryDirectory(prefix="fanban-calculation-preflight-") as temp_dir:
                work_dir = Path(temp_dir)
                archive_path = work_dir / (
                    Path(archive.filename).name or "calculation-images.zip"
                )
                archive_path.write_bytes(archive.content)
                payload = run_calculation_book_preflight(
                    archive_path=archive_path,
                    extraction_root=work_dir / "extracted",
                    include_slab_stress=include_slab_stress,
                    archive_limits=ArchiveLimits(
                        max_files=runtime.max_archive_files,
                        max_total_bytes=runtime.max_archive_mb * 1024 * 1024,
                        max_single_file_bytes=runtime.max_single_file_mb * 1024 * 1024,
                        max_compression_ratio=runtime.max_compression_ratio,
                    ),
                    ocr_recognizer=lambda path, direction: recognize_stress_legend(
                        path,
                        direction=direction,
                        tesseract_exe=runtime.tesseract_exe,
                        tessdata_dir=runtime.tessdata_dir,
                        threshold=mechanism.ocr_threshold,
                        expected_count=mechanism.ocr_legend_value_count,
                        min_confidence=mechanism.ocr_min_confidence,
                        min_vertical_ratio=mechanism.ocr_min_vertical_ratio,
                        endpoint_absolute_tolerance=(
                            mechanism.ocr_endpoint_absolute_tolerance
                        ),
                        endpoint_relative_tolerance=(
                            mechanism.ocr_endpoint_relative_tolerance
                        ),
                        header_crop=tuple(mechanism.ocr_header_crop),
                        legend_crop=tuple(mechanism.ocr_legend_crop),
                        header_scale=mechanism.ocr_header_scale,
                        legend_scale=mechanism.ocr_legend_scale,
                    ),
                )
                requires_ai_normalization = bool(
                    payload.get("requires_ai_normalization", False)
                )
                expected_source_row_count = _strict_positive_int(
                    payload.get(
                        "ai_reinforcement_expected_source_row_count"
                    )
                )
                if (
                    requires_ai_normalization
                    and expected_source_row_count is None
                ):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail={
                            "upload_errors": {
                                "archive": [
                                    "无法可靠统计非标准配筋表数据行"
                                ]
                            },
                            "param_errors": {},
                        },
                    )
                token = f"calculation-preflight-{uuid.uuid4().hex}"
                confirmation_candidates = {
                    str(item["wall_id"]): {
                        int(candidate["source_row"])
                        for candidate in item["candidates"]
                    }
                    for item in payload["confirmations"]
                }
                cached_archive_path = cache_root / f"{token}{archive_suffix}"
                cached_archive_path.write_bytes(archive.content)
                expired_archive_paths: list[Path] = []
                with self._calculation_preflight_lock:
                    now = time.monotonic()
                    for old_token, entry in list(
                        self._calculation_preflight_tokens.items()
                    ):
                        if (
                            now - float(entry["created_at"])
                            <= _CALCULATION_PREFLIGHT_TTL_SECONDS
                        ):
                            continue
                        self._calculation_preflight_tokens.pop(old_token, None)
                        expired_archive_paths.append(
                            Path(str(entry["archive_path"]))
                        )
                    self._calculation_preflight_tokens[token] = {
                        "created_at": now,
                        "archive_digest": hashlib.sha256(archive.content).hexdigest(),
                        "archive_path": str(cached_archive_path),
                        "archive_filename": (
                            Path(archive.filename).name
                            or "calculation-images.zip"
                        ),
                        "content_type": (
                            archive.content_type
                            or (
                                "application/vnd.rar"
                                if archive_suffix == ".rar"
                                else "application/zip"
                            )
                        ),
                        "include_slab_stress": include_slab_stress,
                        "confirmation_candidates": confirmation_candidates,
                        "requires_wall_count_confirmation": bool(
                            payload.get(
                                "requires_wall_count_confirmation",
                                False,
                            )
                        ),
                        "requires_ai_normalization": bool(
                            payload.get("requires_ai_normalization", False)
                        ),
                        **(
                            {
                                "ai_reinforcement_expected_source_row_count": (
                                    expected_source_row_count
                                )
                            }
                            if requires_ai_normalization
                            else {}
                        ),
                        "format_inspection": payload.get(
                            "format_inspection",
                            {},
                        ),
                    }
                for path in expired_archive_paths:
                    path.unlink(missing_ok=True)
                payload["preflight_token"] = token
                return payload
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "upload_errors": {"archive": [str(exc)]},
                    "param_errors": {},
                },
            ) from exc

    def create_audit_batch(
        self,
        *,
        mode: str,
        files: list[UploadedFilePayload],
        raw_params: dict[str, Any],
        creator_snapshot: AccountSnapshot | None = None,
    ) -> dict[str, Any]:
        normalized_mode = str(mode or '').strip().lower()
        if normalized_mode not in {'check', 'replace'}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={'upload_errors': {}, 'param_errors': {'mode': ['unsupported_audit_mode']}},
            )

        upload_errors = self._validate_uploads(files)
        if normalized_mode == 'check':
            resolved_submissions = [
                (upload, self._resolve_audit_params_for_upload(raw_params, upload.filename))
                for upload in files
            ]
            param_errors = self._collect_audit_param_errors(resolved_submissions)
            for field_name, field_errors in self._collect_unit_consistency_param_errors(
                resolved_submissions
            ).items():
                bucket = param_errors.setdefault(field_name, [])
                for error in field_errors:
                    if error not in bucket:
                        bucket.append(error)
        else:
            resolved_submissions = [(upload, self._resolve_replace_params(raw_params)) for upload in files]
            param_errors = self._collect_replace_param_errors(raw_params)
            for field_name, field_errors in self._collect_replace_batch_identity_errors(
                files,
                raw_params,
            ).items():
                bucket = param_errors.setdefault(field_name, [])
                for error in field_errors:
                    if error not in bucket:
                        bucket.append(error)
        if upload_errors or param_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={'upload_errors': upload_errors, 'param_errors': param_errors},
            )

        explicit_batch_id = str(raw_params.get('batch_id') or '').strip()
        batch_id = explicit_batch_id or self._new_batch_id()
        self._log_submission(
            endpoint="/api/jobs/audit-replace",
            batch_id=batch_id,
            files=files,
            mode=normalized_mode,
        )
        jobs: list[dict[str, Any]] = []
        if normalized_mode == 'replace':
            for upload, resolved_params in resolved_submissions:
                source_filename = Path(upload.filename).name or 'upload.dwg'
                if self._coerce_bool(resolved_params.get('run_deliverable')):
                    jobs.append(
                        self._create_replace_grouped_submission(
                            batch_id=batch_id,
                            upload=upload,
                            resolved_params=resolved_params,
                            creator_snapshot=creator_snapshot,
                        )
                    )
                    continue

                job = self.job_manager.create_job(
                    job_type=JobType.AUDIT_REPLACE.value,
                    project_no=str(resolved_params['target_project_no']),
                    options={'mode': 'replace'},
                    params={key: value for key, value in resolved_params.items() if key != 'batch_id'},
                    batch_id=batch_id,
                    source_filename=source_filename,
                    task_role='audit_replace',
                    creator_snapshot=creator_snapshot,
                )
                self._store_job_upload(job, upload)
                self.job_manager.update_job(job)
                summary = self._index_job_summary(job)
                self._enqueue_job(job.job_id)
                jobs.append(summary)
            return {'batch_id': batch_id, 'jobs': jobs}

        for upload, resolved_params in resolved_submissions:
            source_filename = Path(upload.filename).name or 'upload.dwg'
            job = self.job_manager.create_job(
                job_type=JobType.AUDIT_REPLACE.value,
                project_no=str(resolved_params['project_no']),
                options={'mode': 'check'},
                params={key: value for key, value in resolved_params.items() if key != 'batch_id'},
                batch_id=batch_id,
                source_filename=source_filename,
                task_role='audit_check',
                creator_snapshot=creator_snapshot,
            )
            self._store_job_upload(job, upload)
            self.job_manager.update_job(job)
            summary = self._index_job_summary(job)
            self._enqueue_job(job.job_id)
            jobs.append(summary)
        return {'batch_id': batch_id, 'jobs': jobs}

    @staticmethod
    def _resolve_params_for_upload(raw_params: dict[str, Any], filename: str) -> dict[str, Any]:
        resolved = dict(raw_params)
        resolved['project_no'] = resolve_project_no(raw_params.get('project_no'), filename)
        resolved['unit_no'] = DeliverableApiRuntime._resolve_unit_no(
            raw_params,
            filename,
            resolved['project_no'],
        )
        return resolved

    @staticmethod
    def _resolve_audit_params_for_upload(raw_params: dict[str, Any], filename: str) -> dict[str, Any]:
        resolved = dict(raw_params)
        explicit = str(raw_params.get('project_no') or '').strip()
        inferred = infer_project_no_from_path(filename)
        resolved['project_no'] = explicit or inferred or ''
        resolved['unit_no'] = DeliverableApiRuntime._resolve_unit_no(
            raw_params,
            filename,
            resolved['project_no'],
        )
        return resolved

    @staticmethod
    def _resolve_replace_params(raw_params: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(raw_params)
        resolved['source_project_no'] = str(raw_params.get('source_project_no') or '').strip()
        resolved['target_project_no'] = str(raw_params.get('target_project_no') or '').strip()
        resolved['run_deliverable'] = DeliverableApiRuntime._coerce_bool(raw_params.get('run_deliverable'))
        deliverable_params = raw_params.get('deliverable_params')
        if isinstance(deliverable_params, dict):
            normalized_deliverable = dict(deliverable_params)
            normalized_deliverable['project_no'] = resolved['target_project_no']
            resolved['deliverable_params'] = normalized_deliverable
        return resolved

    @staticmethod
    def _resolve_unit_no(raw_params: dict[str, Any], filename: str, project_no: str | None) -> str:
        explicit = str(raw_params.get("unit_no") or "").strip()
        if explicit:
            return explicit
        return infer_unit_no_from_path(filename, project_no) or ""

    def _collect_param_errors(
        self,
        resolved_submissions: list[tuple[UploadedFilePayload, dict[str, Any]]],
    ) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {}
        for _, params in resolved_submissions:
            for field_name, field_errors in self.validator.validate_frontend_params(params).items():
                bucket = merged.setdefault(field_name, [])
                for error in field_errors:
                    if error not in bucket:
                        bucket.append(error)
        return merged

    @staticmethod
    def _collect_audit_param_errors(
        resolved_submissions: list[tuple[UploadedFilePayload, dict[str, Any]]],
    ) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {}
        for _, params in resolved_submissions:
            if not str(params.get('project_no') or '').strip():
                merged.setdefault('project_no', []).append('required_for_audit_check')
        return merged

    def _collect_unit_consistency_param_errors(
        self,
        resolved_submissions: list[tuple[UploadedFilePayload, dict[str, Any]]],
    ) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {}
        unit_config = self.config.audit_check.unit_consistency
        if not unit_config.enabled:
            return merged
        for _, params in resolved_submissions:
            project_no = str(params.get("project_no") or "").strip()
            allowed_units = [
                str(value).strip()
                for value in unit_config.project_units.get(project_no, [])
            ]
            if not allowed_units:
                continue
            unit_no = str(params.get("unit_no") or "").strip()
            if not unit_no:
                merged.setdefault("unit_no", []).append("required_for_unit_consistency")
            elif not self._is_supported_unit_no(
                unit_no=unit_no,
                allowed_units=allowed_units,
                allow_unlisted=bool(unit_config.allow_unlisted_unit_no),
                unit_no_pattern=str(unit_config.unit_no_pattern or ""),
            ):
                merged.setdefault("unit_no", []).append("unsupported_unit_no")
        return merged

    @staticmethod
    def _is_supported_unit_no(
        *,
        unit_no: str,
        allowed_units: list[str],
        allow_unlisted: bool,
        unit_no_pattern: str,
    ) -> bool:
        if unit_no in allowed_units:
            return True
        if not allow_unlisted:
            return False
        try:
            return bool(re.fullmatch(unit_no_pattern, unit_no))
        except re.error:
            return False

    def _collect_replace_param_errors(self, raw_params: dict[str, Any]) -> dict[str, list[str]]:
        return self.validator.validate_replace_frontend_params(raw_params)

    @staticmethod
    def _collect_replace_batch_identity_errors(
        files: list[UploadedFilePayload],
        raw_params: dict[str, Any],
    ) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}
        raw_factory_codes = raw_params.get("unit_factory_codes")
        selected_factory_codes = {
            str(value).strip().upper()
            for value in (raw_factory_codes if isinstance(raw_factory_codes, list) else [])
            if str(value).strip()
        }
        if not selected_factory_codes:
            errors.setdefault("unit_factory_codes", []).append("required_for_replace")
        elif len(selected_factory_codes) != 1:
            errors.setdefault("unit_factory_codes", []).append("single_factory_code_required")

        identities = [
            identity
            for upload in files
            if (identity := infer_replace_batch_identity(upload.filename)) is not None
        ]
        if not identities:
            return errors

        projects = {identity.project_no for identity in identities}
        units = {identity.unit_no for identity in identities}
        factory_codes = {identity.factory_code for identity in identities}

        if len(projects) > 1:
            errors.setdefault("source_project_no", []).append("mixed_source_projects")
        if len(units) > 1:
            errors.setdefault("source_island_no", []).append("mixed_source_units")
        if len(factory_codes) > 1:
            errors.setdefault("unit_factory_codes", []).append("mixed_factory_codes")

        source_project_no = str(raw_params.get("source_project_no") or "").strip()
        if len(projects) == 1 and source_project_no and source_project_no not in projects:
            errors.setdefault("source_project_no", []).append("source_project_mismatch")

        source_unit_no = str(raw_params.get("source_island_no") or "").strip()
        if len(units) == 1 and source_unit_no and source_unit_no not in units:
            errors.setdefault("source_island_no", []).append("source_unit_mismatch")

        if (
            len(factory_codes) == 1
            and len(selected_factory_codes) == 1
            and selected_factory_codes != factory_codes
        ):
            errors.setdefault("unit_factory_codes", []).append("factory_code_mismatch")

        return errors

    def _collect_font_param_errors(self, raw_params: dict[str, Any]) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}
        policy = str(raw_params.get("font_replace_policy") or "none").strip().lower() or "none"
        replacement_font = str(raw_params.get("font_replacement_font") or "").strip()
        replacement_fonts = normalize_replacement_map(raw_params.get("font_replacement_fonts"))

        if policy not in {"none", "replace_missing"}:
            errors.setdefault("font_replace_policy", []).append("unsupported_font_replace_policy")
            return errors

        if policy != "replace_missing":
            return errors

        if not replacement_font and not replacement_fonts:
            errors.setdefault("font_replacement_font", []).append(
                "required_when_font_replace_policy_is_replace_missing"
            )
            return errors

        if replacement_font and not self.font_preflight_service.validate_replacement_font(replacement_font):
            errors.setdefault("font_replacement_font", []).append("unavailable_font_replacement_font")
        for kind, font_name in replacement_fonts.items():
            if not self.font_preflight_service.validate_replacement_font(font_name, kind=kind):
                errors.setdefault("font_replacement_fonts", []).append(
                    f"unavailable_font_replacement_fonts[{kind}]"
                )
        return errors
    def list_jobs(
        self,
        *,
        account: AccountSnapshot,
        status_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "updated_at",
    ) -> dict[str, Any]:
        if not self.process_jobs_in_api:
            indexed = self.queue_store.list_summaries(
                status=status_filter,
                limit=None,
                offset=0,
                sort_by=sort_by,
            )
            visible_items = [
                item for item in indexed["items"] if self._can_view_summary(item, account)
            ]
            normalized_limit = max(limit, 0)
            normalized_offset = max(offset, 0)
            return {
                "items": visible_items[normalized_offset:normalized_offset + normalized_limit],
                "total": len(visible_items),
            }
        groups = [
            self._serialize_group_summary(group)
            for group in self.group_manager.load_all_groups()
            if self.task_visibility.can_view(group, account)
            and (status_filter is None or group.status.value == status_filter)
        ]
        standalone_jobs = [
            self._serialize_job_summary(job)
            for job in self.job_manager.load_all_jobs()
            if job.group_id is None
            and self.task_visibility.can_view_job(job, account)
            and (status_filter is None or job.status.value == status_filter)
        ]
        sort_key = 'created_at' if sort_by == 'created_at' else 'updated_at'
        all_items = sorted(
            [*groups, *standalone_jobs],
            key=lambda item: item.get(sort_key) or item['created_at'],
            reverse=True,
        )
        normalized_limit = max(limit, 0)
        normalized_offset = max(offset, 0)
        items = all_items[normalized_offset:normalized_offset + normalized_limit]
        return {'items': items, 'total': len(all_items)}

    def jobs_activity(self) -> dict[str, Any]:
        return self.queue_store.activity()

    def get_job_detail(self, job_id: str, *, account: AccountSnapshot) -> dict[str, Any]:
        group = self._get_group_for_read(job_id)
        if group is not None:
            if not self.task_visibility.can_view(group, account):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='job not visible')
            return self._serialize_group_detail(group)
        job = self._get_job_for_read(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='job not found')
        if not self.task_visibility.can_view_job(job, account):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='job not visible')
        return self._serialize_job_detail(job)

    def get_artifact_path(self, job_id: str, artifact: str, *, account: AccountSnapshot) -> Path:
        group = self._get_group_for_read(job_id)
        if group is not None:
            if not self.task_visibility.can_view(group, account):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='job not visible')
            owner_job = self._resolve_group_artifact_owner(group, artifact)
            if owner_job is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'{artifact} artifact not found')
            return self._get_job_artifact_path(owner_job, artifact)

        job = self._get_job_for_read(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='job not found')
        if not self.task_visibility.can_view_job(job, account):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='job not visible')
        return self._get_job_artifact_path(job, artifact)

    def _get_job_artifact_path(self, job: Job, artifact: str) -> Path:
        path = {
            'package': job.artifacts.package_zip,
            'ied': job.artifacts.ied_xlsx,
            'preview': job.artifacts.preview_pdf,
            'report': job.artifacts.report_xlsx,
            'replaced': job.artifacts.replaced_dwg,
            'calculation_book': job.artifacts.calculation_docx,
        }.get(artifact)
        if path is None or not Path(path).exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'{artifact} artifact not found')
        return Path(path)

    def _can_view_summary(self, summary: dict[str, Any], account: AccountSnapshot) -> bool:
        owner_payload = summary.get('owner_snapshot')
        owner_snapshot: TaskOwnerSnapshot | None = None
        if isinstance(owner_payload, dict):
            try:
                owner_snapshot = TaskOwnerSnapshot.model_validate(owner_payload)
            except Exception:  # noqa: BLE001
                owner_snapshot = None
        legacy_scope = None
        legacy_visibility = summary.get('legacy_visibility')
        if isinstance(legacy_visibility, dict):
            legacy_scope = str(legacy_visibility.get('scope') or '') or None
        return self.task_visibility.can_view_owner_snapshot(
            owner_snapshot,
            account,
            legacy_scope=legacy_scope,
        )

    def _get_job_for_read(self, job_id: str) -> Job | None:
        if self.process_jobs_in_api:
            return self.job_manager.get_job(job_id)
        return self.job_manager.reload_job(job_id) or self.job_manager.get_job(job_id)

    def _get_group_for_read(self, group_id: str) -> TaskGroup | None:
        if self.process_jobs_in_api:
            return self.group_manager.get_group(group_id)
        return self.group_manager.reload_group(group_id) or self.group_manager.get_group(group_id)

    def _create_grouped_submission(
        self,
        *,
        batch_id: str,
        upload: UploadedFilePayload,
        resolved_params: dict[str, Any],
        creator_snapshot: AccountSnapshot | None = None,
    ) -> dict[str, Any]:
        source_filename = Path(upload.filename).name or 'upload.dwg'
        group = self.group_manager.create_group(
            batch_id=batch_id,
            source_filenames=[source_filename],
            project_no=str(resolved_params['project_no']),
            run_audit_check=True,
            creator_snapshot=creator_snapshot,
        )
        upload_path = self._store_group_upload(group, upload)
        group.shared_dir = self.config.get_group_dir(group.group_id) / 'shared' / self._safe_source_key(source_filename)
        group.metadata['source_input_path'] = str(upload_path)

        deliverable_job = self.job_manager.create_job(
            job_type=JobType.DELIVERABLE.value,
            project_no=group.project_no,
            options={'enabled': True, 'export_pdf': True, 'split_only': False},
            params=dict(resolved_params),
            batch_id=batch_id,
            source_filename=source_filename,
            group_id=group.group_id,
            task_role='deliverable_main',
            shared_run_id=group.shared_run_id,
            creator_snapshot=creator_snapshot,
        )
        audit_job = self.job_manager.create_job(
            job_type=JobType.AUDIT_REPLACE.value,
            project_no=group.project_no,
            options={'mode': 'check'},
            params=dict(resolved_params),
            batch_id=batch_id,
            source_filename=source_filename,
            group_id=group.group_id,
            task_role='audit_check',
            shared_run_id=group.shared_run_id,
            creator_snapshot=creator_snapshot,
        )
        for child in (deliverable_job, audit_job):
            child.input_files = [upload_path.resolve()]
            self.job_manager.update_job(child)

        group.child_job_ids = [deliverable_job.job_id, audit_job.job_id]
        self.group_manager.update_group(group)
        summary = self._index_group_summary(group)
        self._enqueue_group(group.group_id)
        return summary

    def _create_replace_grouped_submission(
        self,
        *,
        batch_id: str,
        upload: UploadedFilePayload,
        resolved_params: dict[str, Any],
        creator_snapshot: AccountSnapshot | None = None,
    ) -> dict[str, Any]:
        source_filename = Path(upload.filename).name or 'upload.dwg'
        target_project_no = str(resolved_params['target_project_no'])
        group = self.group_manager.create_group(
            batch_id=batch_id,
            source_filenames=[source_filename],
            project_no=target_project_no,
            run_audit_check=False,
            creator_snapshot=creator_snapshot,
        )
        upload_path = self._store_group_upload(group, upload)
        group.shared_dir = self.config.get_group_dir(group.group_id) / 'shared' / self._safe_source_key(source_filename)
        group.metadata['source_input_path'] = str(upload_path)
        group.metadata['group_mode'] = 'replace_then_deliverable'

        replace_job = self.job_manager.create_job(
            job_type=JobType.AUDIT_REPLACE.value,
            project_no=target_project_no,
            options={'mode': 'replace'},
            params={key: value for key, value in resolved_params.items() if key != 'batch_id'},
            batch_id=batch_id,
            source_filename=source_filename,
            group_id=group.group_id,
            task_role='audit_replace',
            shared_run_id=group.shared_run_id,
            creator_snapshot=creator_snapshot,
        )
        deliverable_job = self.job_manager.create_job(
            job_type=JobType.DELIVERABLE.value,
            project_no=target_project_no,
            options={'enabled': True, 'export_pdf': True, 'split_only': False},
            params=dict(resolved_params.get('deliverable_params') or {}),
            batch_id=batch_id,
            source_filename=source_filename,
            group_id=group.group_id,
            task_role='deliverable_main',
            shared_run_id=group.shared_run_id,
            creator_snapshot=creator_snapshot,
        )
        for child in (replace_job, deliverable_job):
            child.input_files = [upload_path.resolve()]
            self.job_manager.update_job(child)

        group.child_job_ids = [replace_job.job_id, deliverable_job.job_id]
        self.group_manager.update_group(group)
        summary = self._index_group_summary(group)
        self._enqueue_group(group.group_id)
        return summary

    def refresh_summary_index(self, item_type: str, item_id: str) -> None:
        if item_type == "group":
            group = self.group_manager.get_group(item_id)
            if group is not None:
                self._index_group_summary(group)
            return
        if item_type == "job":
            job = self.job_manager.get_job(item_id)
            if job is not None and job.group_id is None:
                self._index_job_summary(job)

    def _backfill_summary_index(self) -> None:
        for group in self.group_manager.load_all_groups():
            self._index_group_summary(group, touch_updated_at=False)
        for job in self.job_manager.load_all_jobs():
            if job.group_id is None:
                self._index_job_summary(job, touch_updated_at=False)

    def _start_summary_backfill(self) -> None:
        if self._summary_backfill_thread and self._summary_backfill_thread.is_alive():
            return
        self._summary_backfill_thread = threading.Thread(
            target=self._run_summary_backfill,
            name='fanban-summary-backfill',
            daemon=True,
        )
        self._summary_backfill_thread.start()
        self._summary_backfill_thread.join(timeout=0.25)

    def _run_summary_backfill(self) -> None:
        try:
            self._backfill_summary_index()
        except Exception:  # noqa: BLE001
            logger.exception('summary index backfill failed')

    def _index_job_summary(self, job: Job, *, touch_updated_at: bool = True) -> dict[str, Any]:
        summary = self._serialize_job_summary(job)
        self._upsert_summary_index(summary, touch_updated_at=touch_updated_at)
        return summary

    def _index_group_summary(self, group: TaskGroup, *, touch_updated_at: bool = True) -> dict[str, Any]:
        summary = self._serialize_group_summary(group)
        self._upsert_summary_index(summary, touch_updated_at=touch_updated_at)
        return summary

    def _upsert_summary_index(self, summary: dict[str, Any], *, touch_updated_at: bool = True) -> None:
        item_id = str(summary.get("job_id") or summary.get("group_id") or "").strip()
        if not item_id:
            return
        payload = dict(summary)
        payload["item_id"] = item_id
        payload["updated_at"] = (
            datetime.now().astimezone().isoformat()
            if touch_updated_at
            else self._historical_summary_updated_at(summary)
        )
        payload["artifact_flags"] = dict(summary.get("artifacts") or {})
        self.queue_store.upsert_summary(payload)

    @staticmethod
    def _historical_summary_updated_at(summary: dict[str, Any]) -> str:
        value = summary.get("finished_at") or summary.get("created_at") or datetime.now().astimezone()
        return value.isoformat() if isinstance(value, datetime) else str(value)

    @staticmethod
    def _log_submission(
        *,
        endpoint: str,
        batch_id: str,
        files: list[UploadedFilePayload],
        **context: Any,
    ) -> None:
        filenames = [Path(upload.filename).name or "upload.dwg" for upload in files]
        logged_filenames = filenames[:100]
        omitted = max(len(filenames) - len(logged_filenames), 0)
        logger.info(
            "job submission accepted endpoint=%s batch_id=%s file_count=%s omitted_filenames=%s context=%s filenames=%s",
            endpoint,
            batch_id,
            len(filenames),
            omitted,
            context,
            logged_filenames,
        )

    def _recover_groups_and_jobs(self) -> None:
        for job in self.job_manager.load_all_jobs():
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                if 'service_restarted_before_completion' not in job.errors:
                    job.mark_failed('service_restarted_before_completion')
                self.job_manager.update_job(job)
        for group in self.group_manager.load_all_groups():
            if group.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                if 'service_restarted_before_completion' not in group.errors:
                    group.mark_failed('service_restarted_before_completion')
                self.group_manager.update_group(group)

    def _group_dispatch_loop(self) -> None:
        while not self._stop_event.is_set():
            self._prune_futures()
            if self._active_group_count() >= self._max_active_groups:
                self._stop_event.wait(0.05)
                continue
            try:
                group_id = self._group_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if group_id is None:
                break
            future = self._group_executor.submit(self._process_group, group_id)
            with self._future_lock:
                self._group_futures.add(future)
            future.add_done_callback(self._discard_group_future)
            self._group_queue.task_done()

    def _job_dispatch_loop(self) -> None:
        while not self._stop_event.is_set():
            self._prune_futures()
            if self._active_job_count() >= self._max_active_jobs:
                self._stop_event.wait(0.05)
                continue
            try:
                job_id = self._job_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if job_id is None:
                break
            self._submit_heavy_job(job_id)
            self._job_queue.task_done()

    def _process_group(self, group_id: str) -> None:
        group = self.group_manager.get_group(group_id)
        if group is None or group.status != JobStatus.QUEUED:
            return
        try:
            group.mark_running('PREP_SOURCE')
            group.progress.percent = 5
            group.progress.message = '共享前处理准备中'
            self.group_manager.update_group(group)

            source_input = self._resolve_group_source_input(group)
            shared_dir = group.shared_dir or (self.config.get_group_dir(group.group_id) / 'shared' / self._safe_source_key(source_input.name))
            child_jobs = [child for child in (self.job_manager.get_job(job_id) for job_id in group.child_job_ids) if child is not None]
            font_params = next(
                (child.params for child in child_jobs if child.task_role == 'deliverable_main'),
                child_jobs[0].params if child_jobs else {},
            )
            shared_prep_project_no = next(
                (
                    str(child.params.get("source_project_no") or child.project_no or "").strip()
                    for child in child_jobs
                    if str(child.params.get("source_project_no") or child.project_no or "").strip()
                ),
                "",
            )
            prep = self.shared_prep_service.prepare(
                group_id=group.group_id,
                project_no=shared_prep_project_no or None,
                source_dwg=source_input,
                shared_dir=shared_dir,
                font_replace_policy=str(font_params.get("font_replace_policy") or "none"),
                font_replacement_font=str(font_params.get("font_replacement_font") or "").strip() or None,
                font_replacement_fonts=normalize_replacement_map(font_params.get("font_replacement_fonts")),
                font_compatibility_mode=self._coerce_bool(font_params.get("font_compatibility_mode")),
            )
            group.shared_dir = prep.shared_dir
            group.workload = self.workload_calculator.build_from_shared_prep(prep)
            group.progress.percent = 35
            group.progress.message = '共享前处理完成'
            self.group_manager.update_group(group)
            for child in child_jobs:
                child.params['shared_prep_dir'] = str(prep.shared_dir)
                child.params['shared_source_dwg'] = str(prep.source_input_dwg)
                child.params['shared_source_dxf'] = str(prep.source_converted_dxf)
                child.font_preflight_summary = {
                    "files": [prep.font_preflight_summary],
                    "policy": str(font_params.get("font_replace_policy") or "none"),
                    "font_compatibility_mode": self._coerce_bool(
                        font_params.get("font_compatibility_mode")
                    ),
                }
                child.missing_fonts_detected = str(prep.font_preflight_summary.get("status") or "").strip().lower() == "missing_fonts"
                child.font_replacement_applied = bool(prep.font_preflight_summary.get("font_replacement_applied", False))
                child.replacement_font = str(prep.font_preflight_summary.get("replacement_font") or "").strip() or None
                child.replacement_fonts = normalize_replacement_map(
                    prep.font_preflight_summary.get("replacement_fonts")
                )
                child.replaced_style_count = _summary_int(prep.font_preflight_summary, "replaced_style_count")
                self.job_manager.update_job(child)

            group.progress.stage = 'DELIVERABLE_BRANCH' if group.run_audit_check else 'DOCS_AND_PACKAGE'
            group.progress.percent = 45
            group.progress.message = '子任务执行中'
            self.group_manager.update_group(group)

            if str(group.metadata.get('group_mode') or '').strip() == 'replace_then_deliverable':
                self._run_replace_then_deliverable_group(group, child_jobs)
            else:
                for child in child_jobs:
                    self._enqueue_job(child.job_id)
                for child in child_jobs:
                    self._wait_for_job_completion(child.job_id)

            children = [child for child in (self.job_manager.get_job(job_id) for job_id in group.child_job_ids) if child is not None]
            group.flags = self._merge_unique(*(child.flags for child in children))
            group.errors = self._merge_unique(*(child.errors for child in children))
            group.artifacts = self._merge_group_artifacts(children)
            group.progress.stage = 'GROUP_COMPLETE'
            group.progress.percent = 100
            group.progress.message = '任务完成'
            if any(child.status == JobStatus.FAILED for child in children):
                group.mark_failed('child_job_failed')
            else:
                group.mark_succeeded()
            self.group_manager.update_group(group)
        except Exception as exc:  # noqa: BLE001
            group.mark_failed(str(exc))
            group.progress.message = f'任务组失败: {exc}'
            self.group_manager.update_group(group)

    def _run_replace_then_deliverable_group(self, group: TaskGroup, children: list[Job]) -> None:
        replace_job = next((child for child in children if child.task_role == 'audit_replace'), None)
        deliverable_job = next((child for child in children if child.task_role == 'deliverable_main'), None)
        if replace_job is None or deliverable_job is None:
            raise RuntimeError('replace_then_deliverable group is missing required child jobs')

        self._enqueue_job(replace_job.job_id)
        replace_job = self._wait_for_job_completion(replace_job.job_id)
        if replace_job is None or replace_job.status != JobStatus.SUCCEEDED or replace_job.artifacts.replaced_dwg is None:
            if deliverable_job.status == JobStatus.QUEUED:
                deliverable_job.mark_failed('replace_job_failed')
                self.job_manager.update_job(deliverable_job)
            return

        replaced_dwg = Path(replace_job.artifacts.replaced_dwg).resolve()
        deliverable_shared_dir = (
            self.config.get_group_dir(group.group_id)
            / 'shared'
            / self._safe_source_key(replaced_dwg.name)
            / 'deliverable'
        )
        deliverable_prep = self.shared_prep_service.prepare(
            group_id=f'{group.group_id}-deliverable',
            project_no=str(deliverable_job.project_no or "").strip() or None,
            source_dwg=replaced_dwg,
            shared_dir=deliverable_shared_dir,
            font_replace_policy=str(deliverable_job.params.get("font_replace_policy") or "none"),
            font_replacement_font=str(deliverable_job.params.get("font_replacement_font") or "").strip() or None,
            font_replacement_fonts=normalize_replacement_map(
                deliverable_job.params.get("font_replacement_fonts")
            ),
            font_compatibility_mode=self._coerce_bool(
                deliverable_job.params.get("font_compatibility_mode")
            ),
        )

        group.workload = self.workload_calculator.build_from_shared_prep(deliverable_prep)
        self.group_manager.update_group(group)

        deliverable_job.input_files = [replaced_dwg]
        deliverable_job.params['shared_prep_dir'] = str(deliverable_prep.shared_dir)
        deliverable_job.params['shared_source_dwg'] = str(deliverable_prep.source_input_dwg)
        deliverable_job.params['shared_source_dxf'] = str(deliverable_prep.source_converted_dxf)
        deliverable_job.font_preflight_summary = {
            "files": [deliverable_prep.font_preflight_summary],
            "policy": str(deliverable_job.params.get("font_replace_policy") or "none"),
            "font_compatibility_mode": self._coerce_bool(
                deliverable_job.params.get("font_compatibility_mode")
            ),
        }
        deliverable_job.missing_fonts_detected = (
            str(deliverable_prep.font_preflight_summary.get("status") or "").strip().lower() == "missing_fonts"
        )
        deliverable_job.font_replacement_applied = bool(
            deliverable_prep.font_preflight_summary.get("font_replacement_applied", False)
        )
        deliverable_job.replacement_font = (
            str(deliverable_prep.font_preflight_summary.get("replacement_font") or "").strip() or None
        )
        deliverable_job.replacement_fonts = normalize_replacement_map(
            deliverable_prep.font_preflight_summary.get("replacement_fonts")
        )
        deliverable_job.replaced_style_count = _summary_int(
            deliverable_prep.font_preflight_summary,
            "replaced_style_count",
        )
        self.job_manager.update_job(deliverable_job)
        self._enqueue_job(deliverable_job.job_id)
        self._wait_for_job_completion(deliverable_job.job_id)

    def _run_job(self, job_id: str) -> None:
        job = self.job_manager.get_job(job_id)
        if job is None or job.status != JobStatus.QUEUED:
            return
        slot = None
        completion_deferred = False
        try:
            if job.job_type == JobType.CALCULATION_BOOK:
                job.work_dir = self.config.get_job_dir(job.job_id)
                job.work_dir.mkdir(parents=True, exist_ok=True)
                self._submit_doc_job(job.job_id, lambda: self.job_processor(job))
                completion_deferred = True
                return
            slot = self.cad_slot_pool.acquire(job.job_id, timeout=300)
            resolved_plot_style_key, resolved_ctb_name = self._resolve_job_plot_style(job)
            job.slot_id = slot.slot_id
            job.cad_version = str(slot.cad_version) if slot.cad_version is not None else None
            job.accoreconsole_exe = str(slot.accoreconsole_exe) if slot.accoreconsole_exe else None
            job.profile_arg = str(slot.profile_arg_path)
            job.plot_style_key = resolved_plot_style_key
            job.plot_resource_mode = "slot_private_with_shared_mirror"
            job.pc3_path = str(slot.plotters_dir / self.config.module5_export.plot.pc3_name)
            job.pmp_path = str(slot.pmp_dir / "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp")
            job.ctb_path = str(slot.plot_styles_dir / resolved_ctb_name)
            job.params["cad_slot_id"] = slot.slot_id
            job.params["cad_slot_root"] = str(slot.slot_root)
            job.params["cad_slot_profile_arg"] = str(slot.profile_arg_path)
            job.params["cad_slot_plotters_dir"] = str(slot.plotters_dir)
            job.params["cad_slot_pmp_dir"] = str(slot.pmp_dir)
            job.params["cad_slot_plot_styles_dir"] = str(slot.plot_styles_dir)
            job.params["plot_style_key"] = resolved_plot_style_key
            job.params["plot_resource_mode"] = job.plot_resource_mode
            job.params["cad_slot_runtime"] = {
                "slot_id": slot.slot_id,
                "slot_root": str(slot.slot_root),
                "profile_arg": str(slot.profile_arg_path),
                "plotters_dir": str(slot.plotters_dir),
                "pmp_dir": str(slot.pmp_dir),
                "plot_styles_dir": str(slot.plot_styles_dir),
                "spool_dir": str(slot.spool_dir),
                "temp_dir": str(slot.temp_dir),
            }
            job.work_dir = self.config.get_job_dir(job.job_id)
            job.work_dir.mkdir(parents=True, exist_ok=True)
            staged_processor = getattr(self.job_processor, 'execute_slot_bound_phase', None)
            if callable(staged_processor):
                post_slot_work = staged_processor(job)
                self.job_manager.update_job(job)
                if post_slot_work is not None:
                    self.cad_slot_pool.release(slot.slot_id)
                    slot = None
                    self._submit_doc_job(job.job_id, cast(Callable[[], None], post_slot_work))
                    completion_deferred = True
                    return
            else:
                self.job_processor(job)
        except Exception as exc:  # noqa: BLE001
            if job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                job.mark_failed(str(exc))
        finally:
            if not completion_deferred:
                self.job_manager.update_job(job)
            if slot is not None:
                self.cad_slot_pool.release(slot.slot_id)
            if not completion_deferred:
                self._signal_job_completion(job.job_id)

    def _enqueue_group(self, group_id: str) -> None:
        if not self.process_jobs_in_api:
            self.queue_store.enqueue("group", group_id)
            return
        self._group_queue.put(group_id)

    def _enqueue_job(self, job_id: str) -> None:
        if not self.process_jobs_in_api:
            self.queue_store.enqueue("job", job_id)
            return
        with self._job_completion_lock:
            event = self._job_completion_events.get(job_id)
            if event is None:
                event = threading.Event()
                self._job_completion_events[job_id] = event
            event.clear()
        if self.worker_process_mode:
            self._submit_heavy_job(job_id)
            return
        self._job_queue.put(job_id)

    def _submit_heavy_job(self, job_id: str) -> Future[None]:
        future = self._heavy_executor.submit(self._run_job, job_id)
        with self._future_lock:
            self._job_futures.add(future)
        future.add_done_callback(self._discard_job_future)
        return future

    def _submit_doc_job(
        self,
        job_id: str,
        post_slot_work: Callable[[], None],
    ) -> Future[None]:
        future = self._doc_executor.submit(self._run_doc_job, job_id, post_slot_work)
        with self._future_lock:
            self._doc_futures.add(future)
        future.add_done_callback(self._discard_doc_future)
        return future

    def _run_doc_job(
        self,
        job_id: str,
        post_slot_work: Callable[[], None],
    ) -> None:
        job = self.job_manager.get_job(job_id)
        with self._future_lock:
            self._running_doc_job_ids.add(job_id)
        try:
            post_slot_work()
        except Exception as exc:  # noqa: BLE001
            latest = self._latest_doc_phase_job(job_id, fallback=job)
            if latest is not None and latest.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                latest.mark_failed(str(exc))
                job = latest
        finally:
            with self._future_lock:
                self._running_doc_job_ids.discard(job_id)
            latest = self._latest_doc_phase_job(job_id, fallback=job)
            if latest is not None:
                self.job_manager.update_job(latest)
            self._signal_job_completion(job_id)

    def _latest_doc_phase_job(self, job_id: str, *, fallback: Job | None) -> Job | None:
        terminal_statuses = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
        if fallback is not None and fallback.status in terminal_statuses:
            return fallback
        latest = self.job_manager.reload_job(job_id)
        return latest or fallback

    def _wait_for_job_completion(self, job_id: str, timeout_sec: float | None = None) -> Job | None:
        wait_timeout = (
            float(timeout_sec)
            if timeout_sec is not None
            else float(load_mechanism_spec().api_runtime.job_completion_wait_timeout_sec)
        )
        deadline = time.monotonic() + wait_timeout
        while not self._stop_event.is_set():
            with self._job_completion_lock:
                event = self._job_completion_events.setdefault(job_id, threading.Event())
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'job did not finish within {wait_timeout}s: {job_id}')
            if event.wait(timeout=min(0.2, remaining)):
                return self.job_manager.get_job(job_id)
        raise RuntimeError(f'service stopping before job completion: {job_id}')

    def _signal_job_completion(self, job_id: str) -> None:
        with self._job_completion_lock:
            event = self._job_completion_events.get(job_id)
            if event is None:
                event = threading.Event()
                self._job_completion_events[job_id] = event
            event.set()

    def _resolve_job_plot_style(self, job: Job) -> tuple[str, str]:
        plot_cfg = self.config.module5_export.plot
        profiles = dict(getattr(plot_cfg, "plot_style_profiles", {}) or {})
        default_key = str(getattr(plot_cfg, "default_plot_style_key", "") or "").strip() or "red_wider"
        requested_key = str(job.params.get("plot_style_key", "") or "").strip()
        resolved_key = requested_key or default_key
        ctb_name = str(profiles.get(resolved_key, "") or "").strip()
        if not ctb_name:
            resolved_key = default_key
            ctb_name = str(profiles.get(resolved_key, "") or "").strip()
        if not ctb_name:
            ctb_name = str(plot_cfg.ctb_name)
        return resolved_key, ctb_name
    def _resolve_group_source_input(self, group: TaskGroup) -> Path:
        raw = str(group.metadata.get('source_input_path') or '').strip()
        if raw:
            return Path(raw).resolve()
        for child_job_id in group.child_job_ids:
            child = self.job_manager.get_job(child_job_id)
            if child and child.input_files:
                return Path(child.input_files[0]).resolve()
        raise FileNotFoundError(f'group source input not found: {group.group_id}')

    def _storage_writable(self) -> bool:
        probe: Path | None = None
        try:
            self.config.ensure_dirs()
            probe = self.config.storage_dir / f'.api-healthcheck-{uuid.uuid4().hex}.tmp'
            probe.write_text('ok', encoding='utf-8')
            probe.unlink(missing_ok=True)
        except Exception:
            return False
        finally:
            if probe is not None:
                try:
                    probe.unlink(missing_ok=True)
                except Exception:
                    pass
        return True

    def _autocad_ready(self) -> bool:
        configured_runner = str(self.config.module5_export.cad_runner.accoreconsole_exe or '').strip()
        if configured_runner and Path(configured_runner).is_file():
            return True
        detected = resolve_autocad_paths(configured_install_dir=self.config.autocad.install_dir).accoreconsole_exe
        return detected is not None and Path(detected).is_file()

    def _validate_uploads(self, files: list[UploadedFilePayload]) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}
        limits = self.config.upload_limits
        if not files:
            errors.setdefault('files', []).append('at least one file is required')
            return errors
        if len(files) > limits.max_files:
            errors.setdefault('files', []).append(f'too many files: max {limits.max_files}')
        allowed_exts = {ext.lower() for ext in limits.allowed_exts}
        invalid = [upload.filename for upload in files if Path(upload.filename).suffix.lower() not in allowed_exts]
        if invalid:
            errors.setdefault('files', []).append('only .dwg files are allowed')
        max_total_bytes = limits.max_total_mb * 1024 * 1024
        if sum(len(upload.content) for upload in files) > max_total_bytes:
            errors.setdefault('files', []).append(f'total upload exceeds {limits.max_total_mb} MB')
        return errors

    def _store_job_upload(self, job: Job, upload: UploadedFilePayload) -> None:
        job_dir = self.config.get_job_dir(job.job_id)
        upload_dir = job_dir / 'uploads'
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path = upload_dir / self._safe_storage_filename(
            upload.filename,
            fallback_stem=job.job_id,
            seed=job.job_id,
        )
        upload_path.write_bytes(upload.content)
        job.work_dir = job_dir
        job.input_files = [upload_path.resolve()]

    def _store_group_upload(self, group: TaskGroup, upload: UploadedFilePayload) -> Path:
        group_dir = self.config.get_group_dir(group.group_id)
        upload_dir = group_dir / 'input'
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path = upload_dir / self._safe_storage_filename(
            upload.filename,
            fallback_stem=group.group_id,
            seed=group.group_id,
        )
        upload_path.write_bytes(upload.content)
        return upload_path.resolve()

    @staticmethod
    def _new_batch_id() -> str:
        return f"batch-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    @classmethod
    def _safe_source_key(cls, source_name: str) -> str:
        stem = cls._ascii_token(Path(source_name).stem, fallback='source')
        digest = hashlib.sha1(source_name.encode('utf-8')).hexdigest()[:8]
        return f"{stem[:60]}-{digest}"

    @classmethod
    def _safe_storage_filename(
        cls,
        source_name: str,
        *,
        fallback_stem: str,
        seed: str,
    ) -> str:
        path = Path(source_name)
        suffix = path.suffix.lower() or '.dwg'
        stem = cls._ascii_token(path.stem, fallback=fallback_stem)
        digest = hashlib.sha1(f"{source_name}|{seed}".encode('utf-8')).hexdigest()[:8]
        return f"{stem[:80]}-{digest}{suffix}"

    @staticmethod
    def _ascii_token(value: str, *, fallback: str) -> str:
        normalized = unicodedata.normalize('NFKD', str(value or ''))
        ascii_only = normalized.encode('ascii', 'ignore').decode('ascii')
        safe = re.sub(r'[^A-Za-z0-9_-]+', '_', ascii_only).strip('_')
        return safe or fallback

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on'}

    @staticmethod
    def _serialize_workload_from_details(details: dict[str, Any]) -> tuple[dict[str, Any] | None, float | None]:
        raw_workload = details.get("workload")
        if not isinstance(raw_workload, dict):
            return None, None
        try:
            workload = WorkloadSummary.model_validate(raw_workload)
        except Exception:  # noqa: BLE001
            return None, None
        effective_raw = details.get("effective_workload")
        try:
            effective = float(effective_raw)
        except (TypeError, ValueError):
            effective = float(workload.final_workload_a1 or workload.initial_workload_a1 or 0.0)
        return workload.model_dump(mode="json"), round(effective, 2)

    def _serialize_job_summary(self, job: Job) -> dict[str, Any]:
        owner = job.owner_snapshot.model_dump(mode='json') if job.owner_snapshot else None
        task_kind = 'deliverable'
        job_mode = 'deliverable'
        if job.job_type == JobType.CALCULATION_BOOK:
            task_kind = 'calculation_book'
            job_mode = 'calculation_book'
        elif job.job_type == JobType.AUDIT_REPLACE:
            mode = str(job.options.get('mode', '')).strip().lower()
            if mode == 'check':
                task_kind = 'audit_check'
                job_mode = 'check'
            else:
                task_kind = 'audit_replace'
                job_mode = mode or 'replace'
        elif job.job_type == JobType.DELIVERABLE and self._coerce_bool(job.options.get('split_only')):
            job_mode = 'split_only'
        failure_display = self._build_failure_display(
            status_value=job.status.value,
            stage=job.progress.stage,
            message=job.progress.message,
            errors=job.errors,
        )
        workload_payload, effective_workload = self._serialize_workload_from_details(job.progress.details)
        return {
            'job_id': job.job_id,
            'batch_id': job.batch_id,
            'group_id': job.group_id,
            'shared_run_id': job.shared_run_id,
            'task_role': job.task_role,
            'owner_snapshot': owner,
            'creator_name': job.owner_snapshot.creator_name if job.owner_snapshot else None,
            'creator_account': job.owner_snapshot.creator_account if job.owner_snapshot else None,
            'creator_office': job.owner_snapshot.creator_office if job.owner_snapshot else None,
            'plot_style_key': job.plot_style_key,
            'plot_resource_mode': job.plot_resource_mode,
            'slot_id': job.slot_id,
            'cad_version': job.cad_version,
            'accoreconsole_exe': job.accoreconsole_exe,
            'profile_arg': job.profile_arg,
            'pc3_path': job.pc3_path,
            'pmp_path': job.pmp_path,
            'ctb_path': job.ctb_path,
            'font_preflight_summary': job.font_preflight_summary,
            'missing_fonts_detected': job.missing_fonts_detected,
            'font_replacement_applied': job.font_replacement_applied,
            'replacement_font': job.replacement_font,
            'replacement_fonts': job.replacement_fonts,
            'replaced_style_count': job.replaced_style_count,
            'is_group': False,
            'source_filename': job.source_filename,
            'task_kind': task_kind,
            'job_mode': job_mode,
            'project_no': job.project_no,
            'status': job.status.value,
            'stage': job.progress.stage,
            'percent': job.progress.percent,
            'message': job.progress.message,
            'failure_reason': failure_display['failure_reason'],
            'stage_context': failure_display['stage_context'],
            'created_at': job.created_at.isoformat(),
            'finished_at': job.finished_at.isoformat() if job.finished_at else None,
            'artifacts': self._serialize_job_artifacts(job),
            'findings_count': int(job.progress.details.get('findings_count', 0) or 0),
            'affected_drawings_count': int(job.progress.details.get('affected_drawings_count', 0) or 0),
            'workload': workload_payload,
            'effective_workload': effective_workload,
            'retry_available': False,
        }

    def _serialize_job_detail(self, job: Job) -> dict[str, Any]:
        payload = self._serialize_job_summary(job)
        manifest_payload = self._load_json_artifact(job.work_dir / 'manifest.json' if job.work_dir else None)
        report_payload = self._load_json_artifact(job.artifacts.report_json)
        payload.update({
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'current_file': job.progress.current_file,
            'flags': normalize_user_flags(job.flags),
            'errors': job.errors,
            'diagnostics': build_job_diagnostics(
                flags=normalize_user_flags(job.flags),
                errors=job.errors,
                progress_details=job.progress.details,
                font_preflight_summary=job.font_preflight_summary,
            ),
            'top_wrong_texts': list(job.progress.details.get('top_wrong_texts', []) or []),
            'top_internal_codes': list(job.progress.details.get('top_internal_codes', []) or []),
            'artifacts': self._serialize_job_artifacts(job, include_urls=True, job_id=job.job_id),
            'plot_style_key': job.plot_style_key,
            'plot_resource_mode': job.plot_resource_mode,
            'font_preflight_summary': job.font_preflight_summary,
            'missing_fonts_detected': job.missing_fonts_detected,
            'font_replacement_applied': job.font_replacement_applied,
            'replacement_font': job.replacement_font,
            'replacement_fonts': job.replacement_fonts,
            'replaced_style_count': job.replaced_style_count,
        })
        if job.job_type == JobType.DELIVERABLE:
            payload['deliverable_outputs'] = manifest_payload.get('deliverable_outputs', {})
        elif job.job_type == JobType.CALCULATION_BOOK:
            warnings = _serialize_calculation_book_warnings(job.progress.details)
            ai_normalized, ai_normalization = (
                _serialize_calculation_ai_normalization(job)
            )
            payload['calculation_book_output'] = {
                'figure_count': int(job.progress.details.get('figure_count', 0) or 0),
                'template_type': str(job.progress.details.get('template_type') or ''),
                'output_filename': str(job.progress.details.get('output_filename') or ''),
                'ai_normalized': ai_normalized,
                'warning_count': len(warnings),
                'warnings': warnings,
                'ai_normalization': ai_normalization,
            }
        elif job.job_type == JobType.AUDIT_REPLACE:
            mode = str(job.options.get('mode', '')).strip().lower()
            if mode == 'check':
                payload['finding_groups'] = report_payload.get('finding_groups', [])
            else:
                payload['replace_summary'] = {
                    'replacement_count': int(report_payload.get('replacement_count', 0) or 0),
                    'skipped_count': int(report_payload.get('skipped_count', 0) or 0),
                    'affected_drawings_count': int(report_payload.get('affected_drawings_count', 0) or 0),
                    'source_project_no': str(report_payload.get('source_project_no') or ''),
                    'source_island_no': str(job.params.get('source_island_no') or '').strip() or None,
                    'target_project_no': str(report_payload.get('target_project_no') or ''),
                    'target_island_no': str(job.params.get('target_island_no') or '').strip() or None,
                    'top_replaced_texts': list(report_payload.get('top_replaced_texts', []) or []),
                    'top_internal_codes': list(report_payload.get('top_internal_codes', []) or []),
                }
                factory_index_map = job.progress.details.get('factory_index_map')
                if isinstance(factory_index_map, dict):
                    payload['factory_index_map'] = {
                        'applied': bool(factory_index_map.get('applied')),
                        'action_count': int(factory_index_map.get('action_count', 0) or 0),
                        'report_json': str(factory_index_map.get('report_json') or '') or None,
                        'message': str(factory_index_map.get('message') or ''),
                    }
        return payload

    def _serialize_job_artifacts(self, job: Job, *, include_urls: bool = False, job_id: str | None = None) -> dict[str, Any]:
        package_available = bool(job.artifacts.package_zip and Path(job.artifacts.package_zip).exists())
        ied_available = bool(job.artifacts.ied_xlsx and Path(job.artifacts.ied_xlsx).exists())
        report_available = bool(job.artifacts.report_xlsx and Path(job.artifacts.report_xlsx).exists())
        replaced_dwg_available = bool(job.artifacts.replaced_dwg and Path(job.artifacts.replaced_dwg).exists())
        preview_available = bool(job.artifacts.preview_pdf and Path(job.artifacts.preview_pdf).exists())
        calculation_docx_available = bool(
            job.artifacts.calculation_docx and Path(job.artifacts.calculation_docx).exists()
        )
        payload: dict[str, Any] = {
            'package_available': package_available,
            'ied_available': ied_available,
            'preview_available': preview_available,
            'preview_mode': job.artifacts.preview_mode if preview_available else None,
            'report_available': report_available,
            'replaced_dwg_available': replaced_dwg_available,
            'calculation_docx_available': calculation_docx_available,
        }
        if include_urls and job_id is not None:
            payload.update({
                'package_download_url': f'/api/jobs/{job_id}/download/package' if package_available else None,
                'ied_download_url': f'/api/jobs/{job_id}/download/ied' if ied_available else None,
                'preview_download_url': f'/api/jobs/{job_id}/download/preview' if preview_available else None,
                'report_download_url': f'/api/jobs/{job_id}/download/report' if report_available else None,
                'replaced_dwg_download_url': f'/api/jobs/{job_id}/download/replaced' if replaced_dwg_available else None,
                'calculation_docx_download_url': (
                    f'/api/jobs/{job_id}/download/calculation-book'
                    if calculation_docx_available
                    else None
                ),
            })
        return payload
    def _serialize_group_summary(self, group: TaskGroup) -> dict[str, Any]:
        owner = group.owner_snapshot.model_dump(mode='json') if group.owner_snapshot else None
        source_filename = group.source_filenames[0] if group.source_filenames else None
        findings_count = 0
        affected_drawings_count = 0
        for child in self._iter_group_children(group):
            findings_count = max(findings_count, int(child.progress.details.get('findings_count', 0) or 0))
            affected_drawings_count = max(
                affected_drawings_count,
                int(child.progress.details.get('affected_drawings_count', 0) or 0),
            )
        failure_display = self._build_failure_display(
            status_value=group.status.value,
            stage=group.progress.stage,
            message=group.progress.message,
            errors=list(group.errors),
        )
        effective_workload = float(
            group.workload.final_workload_a1
            or group.workload.initial_workload_a1
            or 0.0
        )
        return {
            'job_id': group.group_id,
            'group_id': group.group_id,
            'batch_id': group.batch_id,
            'is_group': True,
            'source_filename': source_filename,
            'source_filenames': list(group.source_filenames),
            'owner_snapshot': owner,
            'creator_name': group.owner_snapshot.creator_name if group.owner_snapshot else None,
            'creator_account': group.owner_snapshot.creator_account if group.owner_snapshot else None,
            'creator_office': group.owner_snapshot.creator_office if group.owner_snapshot else None,
            'legacy_visibility': group.legacy_visibility.model_dump(mode='json'),
            'project_no': group.project_no,
            'status': group.status.value,
            'stage': group.progress.stage,
            'percent': group.progress.percent,
            'message': group.progress.message,
            'failure_reason': failure_display['failure_reason'],
            'stage_context': failure_display['stage_context'],
            'created_at': group.created_at.isoformat(),
            'finished_at': group.finished_at.isoformat() if group.finished_at else None,
            'run_audit_check': group.run_audit_check,
            'child_job_ids': list(group.child_job_ids),
            'artifacts': self._serialize_group_artifacts(group),
            'findings_count': findings_count,
            'affected_drawings_count': affected_drawings_count,
            'workload': group.workload.model_dump(mode='json'),
            'effective_workload': round(effective_workload, 2),
            'retry_available': False,
        }

    def _serialize_group_detail(self, group: TaskGroup) -> dict[str, Any]:
        payload = self._serialize_group_summary(group)
        payload.update({
            'started_at': group.started_at.isoformat() if group.started_at else None,
            'flags': normalize_user_flags(group.flags),
            'errors': list(group.errors),
            'diagnostics': build_job_diagnostics(
                flags=normalize_user_flags(group.flags),
                errors=list(group.errors),
                progress_details=group.progress.details,
            ),
            'shared_run_id': group.shared_run_id,
            'shared_dir': str(group.shared_dir) if group.shared_dir else None,
            'children': [self._serialize_job_summary(child) for child in self._iter_group_children(group)],
        })
        return payload

    def _serialize_group_artifacts(self, group: TaskGroup) -> dict[str, Any]:
        artifacts = self._merge_group_artifacts(self._iter_group_children(group))
        package_available = bool(artifacts.package_zip and Path(artifacts.package_zip).exists())
        ied_available = bool(artifacts.ied_xlsx and Path(artifacts.ied_xlsx).exists())
        report_available = bool(artifacts.report_xlsx and Path(artifacts.report_xlsx).exists())
        replaced_dwg_available = bool(artifacts.replaced_dwg and Path(artifacts.replaced_dwg).exists())
        preview_available = bool(artifacts.preview_pdf and Path(artifacts.preview_pdf).exists())
        return {
            'package_available': package_available,
            'ied_available': ied_available,
            'preview_available': preview_available,
            'preview_mode': artifacts.preview_mode if preview_available else None,
            'report_available': report_available,
            'replaced_dwg_available': replaced_dwg_available,
            'package_download_url': f'/api/jobs/{group.group_id}/download/package' if package_available else None,
            'ied_download_url': f'/api/jobs/{group.group_id}/download/ied' if ied_available else None,
            'preview_download_url': f'/api/jobs/{group.group_id}/download/preview' if preview_available else None,
            'report_download_url': f'/api/jobs/{group.group_id}/download/report' if report_available else None,
            'replaced_dwg_download_url': (
                f'/api/jobs/{group.group_id}/download/replaced' if replaced_dwg_available else None
            ),
        }

    @classmethod
    def _build_failure_display(
        cls,
        *,
        status_value: str,
        stage: str | None,
        message: str | None,
        errors: list[str],
    ) -> dict[str, str | None]:
        if status_value != JobStatus.FAILED.value:
            return {'failure_reason': None, 'stage_context': None}

        normalized_errors = [str(error).strip() for error in errors if str(error).strip()]
        failure_reason = cls._normalize_failure_reason(normalized_errors, message)
        stage_label = cls._display_stage_label(stage)
        stage_context: str | None = None
        if stage_label:
            if 'service_restarted_before_completion' in normalized_errors:
                stage_context = f'中断前最后完成阶段：{stage_label}'
            else:
                stage_context = f'失败发生阶段：{stage_label}'

        return {'failure_reason': failure_reason, 'stage_context': stage_context}

    @classmethod
    def _normalize_failure_reason(cls, errors: list[str], message: str | None) -> str:
        if 'service_restarted_before_completion' in errors:
            return '服务重启/中断，任务未完成'

        if errors:
            return errors[0]

        readable_message = str(message or '').strip()
        if cls._is_readable_failure_message(readable_message):
            return readable_message
        return '任务失败，请查看详情'

    @staticmethod
    def _display_stage_label(stage: str | None) -> str | None:
        if not stage:
            return None
        return load_mechanism_spec().api_runtime.stage_labels.get(stage, stage)

    @staticmethod
    def _is_readable_failure_message(message: str) -> bool:
        if not message:
            return False
        if message == '?' * len(message) or '????' in message:
            return False
        if '\ufffd' in message:
            return False
        return True

    def _resolve_group_artifact_owner(self, group: TaskGroup, artifact: str) -> Job | None:
        for child in self._iter_group_children(group):
            if artifact == 'package' and child.artifacts.package_zip:
                return child
            if artifact == 'ied' and child.artifacts.ied_xlsx:
                return child
            if artifact == 'preview' and child.artifacts.preview_pdf and child.artifacts.preview_mode == 'annotated':
                return child
        for child in self._iter_group_children(group):
            if artifact == 'preview' and child.artifacts.preview_pdf:
                return child
            if artifact == 'package' and child.artifacts.package_zip:
                return child
            if artifact == 'ied' and child.artifacts.ied_xlsx:
                return child
            if artifact == 'report' and child.artifacts.report_xlsx:
                return child
            if artifact == 'replaced' and child.artifacts.replaced_dwg:
                return child
        return None

    @staticmethod
    def _merge_unique(*groups: list[str]) -> list[str]:
        merged: list[str] = []
        for items in groups:
            for item in items:
                if item not in merged:
                    merged.append(item)
        return merged

    @staticmethod
    def _merge_group_artifacts(children: list[Job]) -> JobArtifacts:
        merged = JobArtifacts()
        for child in children:
            if merged.package_zip is None and child.artifacts.package_zip:
                merged.package_zip = child.artifacts.package_zip
            if merged.ied_xlsx is None and child.artifacts.ied_xlsx:
                merged.ied_xlsx = child.artifacts.ied_xlsx
            if merged.drawings_dir is None and child.artifacts.drawings_dir:
                merged.drawings_dir = child.artifacts.drawings_dir
            if merged.docs_dir is None and child.artifacts.docs_dir:
                merged.docs_dir = child.artifacts.docs_dir
            if child.artifacts.preview_pdf:
                if merged.preview_pdf is None or child.artifacts.preview_mode == 'annotated':
                    merged.preview_pdf = child.artifacts.preview_pdf
                    merged.preview_mode = child.artifacts.preview_mode
            if merged.reports_dir is None and child.artifacts.reports_dir:
                merged.reports_dir = child.artifacts.reports_dir
            if merged.report_xlsx is None and child.artifacts.report_xlsx:
                merged.report_xlsx = child.artifacts.report_xlsx
            if merged.report_json is None and child.artifacts.report_json:
                merged.report_json = child.artifacts.report_json
            if merged.replaced_dwg is None and child.artifacts.replaced_dwg:
                merged.replaced_dwg = child.artifacts.replaced_dwg
        return merged

    @staticmethod
    def _load_json_artifact(path: Path | None) -> dict[str, Any]:
        if path is None or not Path(path).exists():
            return {}
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return {}

    def _iter_group_children(self, group: TaskGroup) -> list[Job]:
        children: list[Job] = []
        for child_job_id in group.child_job_ids:
            child = self._get_job_for_read(child_job_id)
            if child is not None:
                children.append(child)
        return children

    def _discard_group_future(self, future: Future[None]) -> None:
        with self._future_lock:
            self._group_futures.discard(future)

    def _discard_job_future(self, future: Future[None]) -> None:
        with self._future_lock:
            self._job_futures.discard(future)

    def _discard_doc_future(self, future: Future[None]) -> None:
        with self._future_lock:
            self._doc_futures.discard(future)

    def _prune_futures(self) -> None:
        with self._future_lock:
            self._group_futures = {future for future in self._group_futures if not future.done()}
            self._job_futures = {future for future in self._job_futures if not future.done()}
            self._doc_futures = {future for future in self._doc_futures if not future.done()}

    def _active_group_count(self) -> int:
        self._prune_futures()
        with self._future_lock:
            return len(self._group_futures)

    def _active_job_count(self) -> int:
        self._prune_futures()
        with self._future_lock:
            return len(self._job_futures)

    def _active_doc_count(self) -> int:
        self._prune_futures()
        with self._future_lock:
            return len(self._running_doc_job_ids)

    def _pending_doc_count(self) -> int:
        self._prune_futures()
        with self._future_lock:
            return max(len(self._doc_futures) - len(self._running_doc_job_ids), 0)
