from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Protocol
from uuid import uuid4

from ..config import get_config
from .autocad_path_resolver import list_available_autocad_installations, resolve_autocad_paths


def _normalize_path_key(value: str | Path) -> str:
    return str(value).strip().replace("/", "\\").rstrip("\\").lower()


def _normalize_font_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return Path(text).name.lower()


def _split_support_path(value: str | None) -> list[str]:
    if not value:
        return []
    return [segment.strip() for segment in str(value).split(";") if segment.strip()]


def merge_support_path(existing: str | None, managed_dir: str | Path) -> str:
    segments = _split_support_path(existing)
    normalized_existing = {_normalize_path_key(segment) for segment in segments}
    managed_text = str(managed_dir)
    if _normalize_path_key(managed_text) not in normalized_existing:
        segments.append(managed_text)
    return ";".join(segments)


def _path_parts(value: str | Path) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    return tuple(part.lower() for part in PureWindowsPath(text).parts if str(part).strip())


def _shared_suffix_length(left: str | Path, right: str | Path) -> int:
    left_parts = _path_parts(left)
    right_parts = _path_parts(right)
    count = 0
    for left_part, right_part in zip(reversed(left_parts), reversed(right_parts), strict=False):
        if left_part != right_part:
            break
        count += 1
    return count


def _replace_path_prefix(
    value: str | Path,
    *,
    source_root: str | Path | None,
    target_root: str | Path | None,
) -> str | None:
    source_text = str(source_root or "").strip()
    target_text = str(target_root or "").strip()
    candidate_text = str(value or "").strip()
    if not source_text or not target_text or not candidate_text:
        return None
    try:
        relative = PureWindowsPath(candidate_text).relative_to(PureWindowsPath(source_text))
    except Exception:  # noqa: BLE001
        return None
    return str(PureWindowsPath(target_text) / relative)


def build_strict_support_path(
    *,
    source_environment: dict[str, object] | None,
    current_environment: dict[str, object],
    managed_dir: str | Path,
) -> str:
    source_environment = dict(source_environment or {})
    source_segments = _split_support_path(str(source_environment.get("support_path") or ""))
    current_segments = _split_support_path(str(current_environment.get("support_path") or ""))
    source_install_dir = (
        source_environment.get("selected_installation") or {}
    ).get("install_dir") if isinstance(source_environment.get("selected_installation"), dict) else None
    target_install_dir = (
        current_environment.get("selected_installation") or {}
    ).get("install_dir") if isinstance(current_environment.get("selected_installation"), dict) else None
    source_windows_fonts_dir = source_environment.get("windows_fonts_dir")
    target_windows_fonts_dir = current_environment.get("windows_fonts_dir")
    managed_text = str(managed_dir)

    planned_segments: list[str] = []
    seen: set[str] = set()

    def add_segment(segment: str | None) -> None:
        text = str(segment or "").strip()
        if not text:
            return
        normalized = _normalize_path_key(text)
        if normalized in seen:
            return
        seen.add(normalized)
        planned_segments.append(text)

    for source_segment in source_segments:
        normalized_source = _normalize_path_key(source_segment)
        translated_segment: str | None = None

        if "font-sync-managed" in normalized_source:
            translated_segment = managed_text
        else:
            translated_segment = _replace_path_prefix(
                source_segment,
                source_root=source_install_dir,
                target_root=target_install_dir,
            )
            if translated_segment is None:
                translated_segment = _replace_path_prefix(
                    source_segment,
                    source_root=source_windows_fonts_dir,
                    target_root=target_windows_fonts_dir,
                )
            if translated_segment is None:
                best_match = None
                best_score = 0
                for current_segment in current_segments:
                    score = _shared_suffix_length(source_segment, current_segment)
                    if score > best_score:
                        best_match = current_segment
                        best_score = score
                if best_match and best_score >= 2:
                    translated_segment = best_match
            if translated_segment is None:
                translated_segment = source_segment

        add_segment(translated_segment)

    add_segment(managed_text)
    return ";".join(planned_segments)


def _dedupe_paths(paths: list[str | Path]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for value in paths:
        text = str(value or "").strip()
        if not text:
            continue
        key = _normalize_path_key(text)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(text)
    return resolved


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _guess_kind(font_name: str, fallback: str | None = None) -> str:
    normalized = str(fallback or "").strip().lower()
    if normalized:
        return normalized
    suffix = Path(str(font_name or "")).suffix.lower()
    if suffix in {".ttf", ".ttc", ".otf"}:
        return "ttf"
    if suffix == ".shx":
        return "shx"
    return "unknown"


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _find_font_file(font_name: str, search_roots: list[str]) -> Path | None:
    candidate_text = str(font_name or "").strip()
    if not candidate_text:
        return None

    candidate_path = Path(candidate_text)
    if candidate_path.is_absolute():
        return candidate_path if candidate_path.exists() else None

    normalized_name = candidate_path.name.lower()
    for root in search_roots:
        root_path = Path(root)
        direct = root_path / candidate_path.name
        if direct.exists():
            return direct
        if not root_path.exists() or not root_path.is_dir():
            continue
        for child in root_path.iterdir():
            if child.is_file() and child.name.lower() == normalized_name:
                return child
    return None


class FontSyncAutoCADAdapterProtocol(Protocol):
    def read_local_settings(self) -> dict[str, object]:
        ...

    def inspect_dwg_styles(self, source_dwg: Path) -> list[dict[str, object]]:
        ...

    def export_profile_backup(self, output_path: Path) -> Path:
        ...

    def apply_font_settings(
        self,
        *,
        support_path: str,
        font_file_map: str | None,
        alt_font_file: str | None,
    ) -> dict[str, object]:
        ...


@dataclass(frozen=True)
class _ConnectionContext:
    app: Any
    quit_on_exit: bool


class AutoCADFontSyncAdapter:
    def __init__(self) -> None:
        self._config = get_config()

    def read_local_settings(self) -> dict[str, object]:
        installations = self._discover_installations()
        selected_installation = installations[0] if installations else None
        windows_fonts_dir = self._resolve_windows_fonts_dir()

        base_snapshot: dict[str, object] = {
            "autocad_ready": False,
            "supported": bool(selected_installation),
            "active_profile": "",
            "support_path": "",
            "font_file_map": None,
            "alt_font_file": None,
            "installations": installations,
            "selected_installation": selected_installation,
            "windows_fonts_dir": windows_fonts_dir,
            "font_search_roots": _dedupe_paths(
                [
                    *(
                        selected_installation["fonts_dir"]
                        for _ in [1]
                        if selected_installation and selected_installation.get("fonts_dir")
                    ),
                    windows_fonts_dir,
                ]
            ),
        }

        try:
            with self._connect() as connection:
                preferences = connection.app.Preferences
                files = preferences.Files
                profiles = preferences.Profiles
                support_path = str(getattr(files, "SupportPath", "") or "")
                font_file_map = getattr(files, "FontFileMap", None)
                alt_font_file = getattr(files, "AltFontFile", None)
                font_search_roots = _dedupe_paths(
                    [
                        *_split_support_path(support_path),
                        *(
                            selected_installation["fonts_dir"]
                            for _ in [1]
                            if selected_installation and selected_installation.get("fonts_dir")
                        ),
                        windows_fonts_dir,
                    ]
                )
                return {
                    **base_snapshot,
                    "autocad_ready": True,
                    "active_profile": str(getattr(profiles, "ActiveProfile", "") or ""),
                    "support_path": support_path,
                    "font_file_map": str(font_file_map) if font_file_map else None,
                    "alt_font_file": str(alt_font_file) if alt_font_file else None,
                    "font_search_roots": font_search_roots,
                }
        except Exception as exc:  # noqa: BLE001
            return {
                **base_snapshot,
                "errors": [str(exc)],
            }

    def inspect_dwg_styles(self, source_dwg: Path) -> list[dict[str, object]]:
        with self._connect() as connection:
            self._prepare_app(connection.app)
            document = connection.app.Documents.Open(str(source_dwg.resolve()))
            try:
                styles: list[dict[str, object]] = []
                for style in document.TextStyles:
                    font_file = str(getattr(style, "FontFile", "") or "")
                    big_font_file = str(getattr(style, "BigFontFile", "") or "")
                    styles.append(
                        {
                            "style_name": str(getattr(style, "Name", "") or ""),
                            "font_name": font_file,
                            "bigfont_name": big_font_file,
                            "kind": "bigfont" if big_font_file else _guess_kind(font_file),
                        }
                    )
                return styles
            finally:
                with contextlib.suppress(Exception):
                    document.Saved = True
                with contextlib.suppress(Exception):
                    document.Close(False)

    def export_profile_backup(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            preferences = connection.app.Preferences
            profiles = preferences.Profiles
            active_profile = str(getattr(profiles, "ActiveProfile", "") or "")
            if not active_profile:
                raise RuntimeError("AutoCAD active profile is unavailable.")
            profiles.ExportProfile(active_profile, str(output_path))
        return output_path

    def apply_font_settings(
        self,
        *,
        support_path: str,
        font_file_map: str | None,
        alt_font_file: str | None,
    ) -> dict[str, object]:
        with self._connect() as connection:
            preferences = connection.app.Preferences
            files = preferences.Files
            files.SupportPath = support_path
            if font_file_map is not None:
                files.FontFileMap = font_file_map
            if alt_font_file is not None:
                files.AltFontFile = alt_font_file
        return self.read_local_settings()

    def _discover_installations(self) -> list[dict[str, object]]:
        configured_install_dir = self._config.autocad.install_dir or None
        installations = list_available_autocad_installations(
            configured_install_dir=configured_install_dir,
        )
        if not installations:
            resolved = resolve_autocad_paths(configured_install_dir)
            if resolved.install_dir is None:
                return []
            return [
                {
                    "label": resolved.install_dir.name,
                    "install_dir": str(resolved.install_dir),
                    "acad_exe": str(resolved.acad_exe) if resolved.acad_exe else None,
                    "accoreconsole_exe": str(resolved.accoreconsole_exe)
                    if resolved.accoreconsole_exe
                    else None,
                    "fonts_dir": str(resolved.fonts_dir) if resolved.fonts_dir else None,
                }
            ]

        result: list[dict[str, object]] = []
        for item in installations:
            fonts_dir = item.install_dir / "Fonts"
            result.append(
                {
                    "label": f"AutoCAD {item.year}" if item.year else item.install_dir.name,
                    "install_dir": str(item.install_dir),
                    "acad_exe": str(item.acad_exe) if item.acad_exe else None,
                    "accoreconsole_exe": str(item.accoreconsole_exe)
                    if item.accoreconsole_exe
                    else None,
                    "fonts_dir": str(fonts_dir) if fonts_dir.exists() else None,
                }
            )
        return result

    def _resolve_windows_fonts_dir(self) -> str | None:
        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT")
        if not windir:
            return None
        fonts_dir = Path(windir) / "Fonts"
        return str(fonts_dir) if fonts_dir.exists() else None

    def _prepare_app(self, app: Any) -> None:
        from .autocad_pdf_exporter import _suppress_autocad_dialogs, _wait_docs_ready

        _wait_docs_ready(app)
        with contextlib.suppress(Exception):
            app.Visible = bool(self._config.autocad.visible)
        _suppress_autocad_dialogs(app)

    @contextlib.contextmanager
    def _connect(self):
        import pythoncom
        import win32com.client

        from .autocad_pdf_exporter import _dispatch_autocad

        pythoncom.CoInitialize()
        quit_on_exit = False
        app = None
        try:
            prog_id_candidates = list(self._config.autocad.prog_id_candidates)
            app = _dispatch_autocad(win32com, prog_id_candidates)
            quit_on_exit = True
            yield _ConnectionContext(app=app, quit_on_exit=quit_on_exit)
        finally:
            if app is not None and quit_on_exit:
                with contextlib.suppress(Exception):
                    app.Quit()
            pythoncom.CoUninitialize()


class FontSyncService:
    def __init__(
        self,
        *,
        font_preflight_service: Any,
        autocad_adapter: FontSyncAutoCADAdapterProtocol | None = None,
        storage_root: Path | None = None,
        managed_root: Path | None = None,
    ) -> None:
        self.font_preflight_service = font_preflight_service
        self.autocad_adapter = autocad_adapter or AutoCADFontSyncAdapter()
        config = get_config()
        self.storage_root = (storage_root or (config.storage_dir / "font-sync")).resolve()
        self.managed_root = (managed_root or (config.storage_dir / "font-sync-managed")).resolve()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.managed_root.mkdir(parents=True, exist_ok=True)

    def scan_target_environment(self) -> dict[str, object]:
        return self.autocad_adapter.read_local_settings()

    def bundle_path_for_id(self, bundle_id: str) -> Path:
        return (self.storage_root / "bundles" / f"{bundle_id}.fanfontsync").resolve()

    def scan_source_dwg(self, *, source_dwg: Path) -> dict[str, object]:
        drawing = self.font_preflight_service.inspect_dwg(
            source_dwg=source_dwg,
            replacement_policy="none",
            replacement_font=None,
            replacement_fonts=None,
        )
        environment = self.autocad_adapter.read_local_settings()
        styles = self.autocad_adapter.inspect_dwg_styles(source_dwg)
        dependencies = self._collect_font_dependencies(
            styles=styles,
            environment=environment,
            source_dwg=source_dwg,
        )
        bundle_mode = self._determine_bundle_mode(dependencies)
        return {
            "bundle_mode": bundle_mode,
            "drawing": drawing,
            "environment": environment,
            "styles": styles,
            "font_dependencies": dependencies,
        }

    def export_bundle(self, *, source_dwg: Path) -> dict[str, object]:
        scan_result = self.scan_source_dwg(source_dwg=source_dwg)
        bundle_id = uuid4().hex[:12]
        staging_dir = self.storage_root / "build" / bundle_id
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        font_dependencies = [
            dict(item) for item in scan_result["font_dependencies"]  # type: ignore[index]
        ]
        font_plan = self._materialize_bundle_fonts(
            staging_dir=staging_dir,
            font_dependencies=font_dependencies,
        )
        profile_path = self.autocad_adapter.export_profile_backup(
            staging_dir / "profiles" / "source-profile.arg"
        )
        styles_csv_path = self._write_styles_csv(
            output_path=staging_dir / "reports" / "styles.csv",
            styles=scan_result["styles"],
            dependencies=font_dependencies,
        )
        bundle_fontmap_path = self._write_font_map(
            output_path=staging_dir / "managed" / "fontmap.fmp",
            font_dependencies=font_dependencies,
        )
        checksums_path = self._write_checksums(
            output_path=staging_dir / "checksums.json",
            files=[profile_path, styles_csv_path, bundle_fontmap_path, *font_plan["copied_files"]],
        )

        manifest = {
            "bundle_id": bundle_id,
            "bundle_mode": scan_result["bundle_mode"],
            "created_at": _iso_now(),
            "source": {
                "dwg_filename": Path(source_dwg).name,
                "drawing": scan_result["drawing"],
                "environment": scan_result["environment"],
            },
            "font_dependencies": font_dependencies,
            "styles": scan_result["styles"],
            "managed": {
                "font_file_map": "managed/fontmap.fmp",
                "fonts_dir": "fonts",
                "alt_font_file": self._determine_alt_font(
                    environment=scan_result["environment"],
                    dependencies=font_dependencies,
                ),
            },
            "files": {
                "profile_backup": "profiles/source-profile.arg",
                "styles_csv": "reports/styles.csv",
                "checksums": "checksums.json",
            },
        }
        manifest_path = staging_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        bundle_path = self.storage_root / "bundles" / f"{bundle_id}.fanfontsync"
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        self._zip_directory(source_dir=staging_dir, bundle_path=bundle_path)

        return {
            **scan_result,
            "bundle_id": bundle_id,
            "bundle_path": str(bundle_path),
            "profile_backup_path": str(profile_path),
            "checksums_path": str(checksums_path),
            "bundle_mode": manifest["bundle_mode"],
        }

    def preview_bundle(self, *, bundle_path: Path) -> dict[str, object]:
        manifest = self._load_manifest(bundle_path)
        environment = self.autocad_adapter.read_local_settings()
        managed_bundle_root = self.managed_root / str(manifest["bundle_id"])
        managed_fonts_dir = managed_bundle_root / "fonts"
        target_support_path = build_strict_support_path(
            source_environment=manifest.get("source", {}).get("environment")
            if isinstance(manifest.get("source"), dict)
            else None,
            current_environment=environment,
            managed_dir=managed_fonts_dir,
        )
        managed_fontmap_path = managed_bundle_root / "fontmap.fmp"
        alt_font_file = str(manifest["managed"].get("alt_font_file") or "") or None
        return {
            "bundle_id": manifest["bundle_id"],
            "bundle_mode": manifest["bundle_mode"],
            "manifest": manifest,
            "current_environment": environment,
            "planned_changes": {
                "managed_root": str(managed_bundle_root),
                "managed_fonts_dir": str(managed_fonts_dir),
                "support_path": target_support_path,
                "font_file_map": str(managed_fontmap_path),
                "alt_font_file": alt_font_file,
            },
            "diff": {
                "support_path_changed": _normalize_path_key(target_support_path)
                != _normalize_path_key(str(environment.get("support_path") or "")),
                "font_file_map_changed": _normalize_path_key(managed_fontmap_path)
                != _normalize_path_key(str(environment.get("font_file_map") or "")),
                "alt_font_file_changed": (alt_font_file or "").strip().lower()
                != str(environment.get("alt_font_file") or "").strip().lower(),
            },
        }

    def apply_bundle(self, *, bundle_path: Path) -> dict[str, object]:
        preview = self.preview_bundle(bundle_path=bundle_path)
        manifest = preview["manifest"]
        bundle_id = str(manifest["bundle_id"])
        managed_bundle_root = self.managed_root / bundle_id
        managed_fonts_dir = managed_bundle_root / "fonts"
        bundle_extract_dir = self.storage_root / "imports" / bundle_id
        if bundle_extract_dir.exists():
            shutil.rmtree(bundle_extract_dir)
        bundle_extract_dir.mkdir(parents=True, exist_ok=True)

        self._extract_bundle(bundle_path=bundle_path, destination=bundle_extract_dir)
        managed_bundle_root.mkdir(parents=True, exist_ok=True)
        managed_fonts_dir.mkdir(parents=True, exist_ok=True)

        source_fonts_dir = bundle_extract_dir / "fonts"
        if source_fonts_dir.exists():
            for item in source_fonts_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, managed_fonts_dir / item.name)

        source_fontmap = bundle_extract_dir / "managed" / "fontmap.fmp"
        managed_fontmap_path = managed_bundle_root / "fontmap.fmp"
        managed_fontmap_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_fontmap, managed_fontmap_path)

        backup_path = self.autocad_adapter.export_profile_backup(
            self.storage_root / "backups" / bundle_id / "target-profile.arg"
        )
        applied_environment = self.autocad_adapter.apply_font_settings(
            support_path=str(preview["planned_changes"]["support_path"]),
            font_file_map=str(preview["planned_changes"]["font_file_map"]),
            alt_font_file=preview["planned_changes"]["alt_font_file"],
        )
        verification = self._verify_applied_state(
            applied_environment=applied_environment,
            preview=preview,
        )
        return {
            "bundle_id": bundle_id,
            "bundle_mode": manifest["bundle_mode"],
            "status": verification,
            "profile_backup_path": str(backup_path),
            "managed_root": str(managed_bundle_root),
            "managed_fonts_dir": str(managed_fonts_dir),
            "font_file_map": str(managed_fontmap_path),
            "environment": applied_environment,
        }

    def _collect_font_dependencies(
        self,
        *,
        styles: list[dict[str, object]],
        environment: dict[str, object],
        source_dwg: Path,
    ) -> list[dict[str, object]]:
        search_roots = _dedupe_paths(
            [
                *(str(item) for item in list(environment.get("font_search_roots") or []) if str(item).strip()),
                *_split_support_path(str(environment.get("support_path") or "")),
                str(source_dwg.parent),
            ]
        )

        dependencies: list[dict[str, object]] = []
        for style in styles:
            style_name = str(style.get("style_name") or "")
            font_name = str(style.get("font_name") or "")
            bigfont_name = str(style.get("bigfont_name") or "")
            kind = str(style.get("kind") or _guess_kind(font_name)).strip().lower() or "unknown"
            dependencies.append(
                self._build_dependency(
                    style_name=style_name,
                    role="font",
                    requested_name=font_name,
                    kind=kind,
                    used_in_block=_coerce_bool(style.get("used_in_block")),
                    search_roots=search_roots,
                )
            )
            if bigfont_name:
                dependencies.append(
                    self._build_dependency(
                        style_name=style_name,
                        role="bigfont",
                        requested_name=bigfont_name,
                        kind="bigfont",
                        used_in_block=_coerce_bool(style.get("used_in_block")),
                        search_roots=search_roots,
                    )
                )
        return dependencies

    def _build_dependency(
        self,
        *,
        style_name: str,
        role: str,
        requested_name: str,
        kind: str,
        used_in_block: bool,
        search_roots: list[str],
    ) -> dict[str, object]:
        resolved_path = _find_font_file(requested_name, search_roots)
        return {
            "dependency_id": f"{style_name}:{role}:{_normalize_font_key(requested_name)}",
            "style_name": style_name,
            "role": role,
            "font_name": requested_name,
            "kind": kind,
            "used_in_block": used_in_block,
            "absolute_path_reference": Path(str(requested_name or "")).is_absolute(),
            "resolved": resolved_path is not None,
            "resolved_path": str(resolved_path) if resolved_path else None,
            "copy_status": "ready" if resolved_path else "unresolved",
            "bundle_font_name": Path(str(requested_name or "")).name if requested_name else "",
        }

    def _determine_bundle_mode(self, dependencies: list[dict[str, object]]) -> str:
        unresolved = any(not bool(item.get("resolved")) for item in dependencies)
        return "best_effort" if unresolved else "guaranteed"

    def _materialize_bundle_fonts(
        self,
        *,
        staging_dir: Path,
        font_dependencies: list[dict[str, object]],
    ) -> dict[str, object]:
        fonts_dir = staging_dir / "fonts"
        fonts_dir.mkdir(parents=True, exist_ok=True)
        copied_files: list[Path] = []
        seen_hash_by_name: dict[str, str] = {}
        for dependency in font_dependencies:
            resolved_path_text = str(dependency.get("resolved_path") or "")
            if not resolved_path_text:
                dependency["copy_status"] = "unresolved"
                continue

            source_path = Path(resolved_path_text)
            file_name = source_path.name
            target_path = fonts_dir / file_name
            file_hash = _sha256_file(source_path)
            normalized_name = file_name.lower()

            if normalized_name in seen_hash_by_name:
                dependency["copy_status"] = (
                    "copied" if seen_hash_by_name[normalized_name] == file_hash else "conflict"
                )
                if seen_hash_by_name[normalized_name] != file_hash:
                    dependency["resolved"] = False
                dependency["bundle_font_path"] = f"fonts/{file_name}"
                dependency["sha256"] = file_hash
                continue

            shutil.copy2(source_path, target_path)
            copied_files.append(target_path)
            seen_hash_by_name[normalized_name] = file_hash
            dependency["copy_status"] = "copied"
            dependency["bundle_font_path"] = f"fonts/{file_name}"
            dependency["sha256"] = file_hash

        return {
            "copied_files": copied_files,
        }

    def _write_font_map(
        self,
        *,
        output_path: Path,
        font_dependencies: list[dict[str, object]],
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        seen: set[str] = set()
        for dependency in font_dependencies:
            if not bool(dependency.get("resolved")):
                continue
            font_name = Path(str(dependency.get("font_name") or "")).name
            bundle_font_name = Path(str(dependency.get("bundle_font_name") or "")).name
            if not font_name or not bundle_font_name:
                continue
            mapping_line = f"{font_name};{bundle_font_name}"
            normalized = mapping_line.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            lines.append(mapping_line)
        output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return output_path

    def _write_styles_csv(
        self,
        *,
        output_path: Path,
        styles: object,
        dependencies: list[dict[str, object]],
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows = {
            (str(item.get("style_name") or ""), str(item.get("role") or "")): item
            for item in dependencies
        }
        style_items = styles if isinstance(styles, list) else []
        with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "style_name",
                    "font_name",
                    "bigfont_name",
                    "kind",
                    "font_resolved",
                    "bigfont_resolved",
                ],
            )
            writer.writeheader()
            for style in style_items:
                if not isinstance(style, dict):
                    continue
                font_dep = rows.get((str(style.get("style_name") or ""), "font"))
                bigfont_dep = rows.get((str(style.get("style_name") or ""), "bigfont"))
                writer.writerow(
                    {
                        "style_name": str(style.get("style_name") or ""),
                        "font_name": str(style.get("font_name") or ""),
                        "bigfont_name": str(style.get("bigfont_name") or ""),
                        "kind": str(style.get("kind") or ""),
                        "font_resolved": bool(font_dep and font_dep.get("resolved")),
                        "bigfont_resolved": bool(bigfont_dep and bigfont_dep.get("resolved")),
                    }
                )
        return output_path

    def _write_checksums(self, *, output_path: Path, files: list[Path]) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            str(path.relative_to(output_path.parent.parent)).replace("\\", "/"): _sha256_file(path)
            for path in files
            if path.exists()
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path

    def _determine_alt_font(
        self,
        *,
        environment: dict[str, object],
        dependencies: list[dict[str, object]],
    ) -> str | None:
        existing = str(environment.get("alt_font_file") or "").strip()
        if existing:
            return existing
        for dependency in dependencies:
            if str(dependency.get("kind") or "").strip().lower() in {"shx", "bigfont"}:
                candidate = Path(str(dependency.get("font_name") or "")).name
                if candidate:
                    return candidate
        for dependency in dependencies:
            candidate = Path(str(dependency.get("font_name") or "")).name
            if candidate:
                return candidate
        return None

    def _zip_directory(self, *, source_dir: Path, bundle_path: Path) -> None:
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source_dir.rglob("*")):
                if path.is_dir():
                    continue
                archive.write(path, path.relative_to(source_dir).as_posix())

    def _load_manifest(self, bundle_path: Path) -> dict[str, object]:
        with zipfile.ZipFile(bundle_path) as archive:
            return json.loads(archive.read("manifest.json").decode("utf-8"))

    def _extract_bundle(self, *, bundle_path: Path, destination: Path) -> None:
        with zipfile.ZipFile(bundle_path) as archive:
            archive.extractall(destination)

    def _verify_applied_state(
        self,
        *,
        applied_environment: dict[str, object],
        preview: dict[str, object],
    ) -> str:
        planned_changes = preview["planned_changes"]
        expected_support_path = str(planned_changes["support_path"])
        expected_font_map = str(planned_changes["font_file_map"])
        expected_alt_font = str(planned_changes["alt_font_file"] or "")

        support_matches = _normalize_path_key(
            str(applied_environment.get("support_path") or "")
        ) == _normalize_path_key(expected_support_path)
        font_map_matches = _normalize_path_key(
            str(applied_environment.get("font_file_map") or "")
        ) == _normalize_path_key(expected_font_map)
        alt_matches = (
            str(applied_environment.get("alt_font_file") or "").strip().lower()
            == expected_alt_font.strip().lower()
        )

        if support_matches and font_map_matches and alt_matches:
            return "matched" if str(preview["bundle_mode"]) == "guaranteed" else "partial"
        if support_matches or font_map_matches or alt_matches:
            return "partial"
        return "failed"
