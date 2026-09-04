"""Read persisted successful-job evidence without rerunning CAD or fabricating frames."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from ..archive.identity import ArchiveIdentity, build_archive_identity
from ..config import get_config, load_spec
from ..doc_gen.derivation import DerivationEngine
from ..models import GlobalDocParams, Job, TaskGroup, normalize_global_doc_params
from ..workload.models import WorkloadSummary

SOURCE_JOB_KEY = "workload_source_job_id"


def is_job_submission(group: TaskGroup) -> bool:
    return bool(group.metadata.get(SOURCE_JOB_KEY))


def read_job_submission(job: Job) -> tuple[WorkloadSummary, ArchiveIdentity]:
    raw = job.progress.details.get("workload")
    if not isinstance(raw, dict) or "initial_workload_a1" not in raw:
        raise ValueError("workload_snapshot_missing")
    value = raw["initial_workload_a1"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("workload_snapshot_invalid")
    root = get_config().get_job_dir(job.job_id)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("job_id") != job.job_id:
            raise ValueError("manifest job mismatch")
        drawings = manifest.get("drawings") or (manifest.get("deliverable_outputs") or {}).get("drawings") or []
        engine = DerivationEngine()
        albums = {
            engine._album_base_internal_code(str(drawing["internal_code"]))
            for drawing in drawings if drawing.get("internal_code")
        }
        if len(albums) != 1:
            raise ValueError("missing or conflicting album codes")
        album = next(iter(albums))
        if not album or any(c in album for c in '/\\:*?"<>|') or album in {".", ".."}:
            raise ValueError("invalid album code")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("workload_manifest_invalid") from exc
    params = GlobalDocParams.model_validate(normalize_global_doc_params(job.params))
    revision = _document_revision(manifest, drawings, engine)
    identity = build_archive_identity(params, album_internal_code=album, document_revision=revision)
    for part in identity.relative_parts:
        if part in {".", ".."} or any(c in part for c in ':*?"<>|'):
            raise ValueError("workload_archive_identity_invalid")
    return WorkloadSummary(initial_workload_a1=float(value), final_workload_a1=float(value)), identity


def _document_revision(manifest: dict, drawings: list[dict], engine: DerivationEngine) -> str:
    """Use the same drawing revision as the ordinary TaskGroup archive path."""
    derived = manifest.get("derived") or {}
    explicit = derived.get("document_revision") if isinstance(derived, dict) else None
    if explicit:
        return _safe_revision(explicit, engine)

    spec = load_spec()
    statuses = set(spec.get_mappings().get("status_to_design_phase", {}))
    inputs = manifest.get("inputs") or {}
    source_params = (inputs.get("params") or {}) if isinstance(inputs, dict) else {}
    if isinstance(source_params, dict) and source_params.get("doc_status"):
        statuses.add(str(source_params["doc_status"]).strip())
    revision_definition = spec.get_field_definitions().get("revision")
    pattern = str(revision_definition.parse.get("candidate_pattern") or "(?!)") if revision_definition else "(?!)"
    suffix = re.escape(spec.get_same_code_multipage_suffix_pattern())
    suffix = suffix.replace(re.escape("{page_index}"), r"(?P<page_index>[1-9][0-9]*)")
    suffix = suffix.replace(re.escape("{page_total}"), r"(?P<page_total>[1-9][0-9]*)")
    revisions = []
    for drawing in drawings:
        if drawing.get("revision"):
            revisions.append(_safe_revision(drawing["revision"], engine))
            continue
        # Old manifests did not persist revision separately. Recover only when
        # the complete generated name matches its known external/internal codes
        # and a known status; never substitute the unrelated cover revision.
        external = str(drawing.get("external_code") or "").strip()
        internal = str(drawing.get("internal_code") or "").strip()
        name = str(drawing.get("name") or "").strip()
        ending = f" ({internal})"
        if not external or not internal or not name.startswith(external) or not name.endswith(ending):
            raise ValueError("workload_revision_missing")
        middle = name[len(external):-len(ending)]
        candidates = set()
        for status in statuses:
            if not status or not middle.endswith(status):
                continue
            value = middle[:-len(status)]
            if re.fullmatch(pattern, value):
                candidates.add(value)
            match = re.fullmatch(r"(?P<revision>.+?)" + suffix, value)
            if (
                match and {"page_index", "page_total"} <= match.groupdict().keys()
                and 0 < int(match["page_index"]) <= int(match["page_total"])
                and int(match["page_total"]) > 1 and re.fullmatch(pattern, match["revision"])
            ):
                candidates.add(match["revision"])
        if len(candidates) != 1:
            raise ValueError("workload_revision_missing")
        revisions.append(_safe_revision(candidates.pop(), engine))
    if not revisions:
        raise ValueError("workload_revision_missing")
    return max(revisions, key=engine._revision_sort_key)


def _safe_revision(value: object, engine: DerivationEngine) -> str:
    if not isinstance(value, str):
        raise ValueError("workload_revision_missing")
    revision = engine._normalize_revision(value)
    if not revision or revision in {".", ".."} or any(char in revision for char in '/\\:*?"<>|'):
        raise ValueError("workload_revision_missing")
    return revision


def job_source_files(job: Job) -> list[Path]:
    root = get_config().get_job_dir(job.job_id).resolve()
    if not job.input_files:
        raise ValueError("workload_source_missing")
    result = []
    for source in job.input_files:
        source = source.resolve()
        if not source.is_relative_to(root):
            raise ValueError("workload_source_outside")
        if not source.is_file():
            raise ValueError("workload_source_missing")
        result.append(source)
    return result
