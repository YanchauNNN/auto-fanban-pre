from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import get_config
from .font_inventory import InstalledFontInventory
from .font_mapping_runtime import (
    build_font_runtime_plan,
    build_font_search_runtime_overrides,
    materialize_font_library_files,
)
from .font_preflight_bridge import FontPreflightBridge
from .font_replacement_plan import (
    normalize_kind,
    normalize_missing_kinds,
    normalize_replacement_map,
)


class FontPreflightService:
    def __init__(
        self,
        *,
        inventory: InstalledFontInventory | None = None,
        bridge: FontPreflightBridge | None = None,
    ) -> None:
        self.config = get_config()
        self.inventory = inventory or InstalledFontInventory()
        self.bridge = bridge or FontPreflightBridge()
        self._options_cache: list[dict[str, str]] | None = None

    def list_replacement_options(self, *, missing_kinds: list[str] | None = None) -> list[dict[str, str]]:
        normalized_kinds = normalize_missing_kinds(missing_kinds)
        if normalized_kinds:
            options: list[dict[str, str]] = []
            seen_values: set[str] = set()
            for kind in normalized_kinds:
                for option in self.inventory.list_options(preferred_kinds={kind}):
                    value_key = str(option.get("value") or "").strip().lower()
                    if not value_key or value_key in seen_values:
                        continue
                    seen_values.add(value_key)
                    options.append(option)
            return options
        if self._options_cache is None:
            self._options_cache = self.inventory.list_options(preferred_kinds=None)
        return list(self._options_cache)

    def list_replacement_options_by_kind(
        self,
        *,
        missing_kinds: list[str] | None = None,
    ) -> dict[str, list[dict[str, str]]]:
        return {
            kind: self.inventory.list_options(preferred_kinds={kind})
            for kind in normalize_missing_kinds(missing_kinds)
        }

    def default_replacement_fonts(
        self,
        *,
        missing_kinds: list[str] | None = None,
        missing_fonts: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        options_by_kind = self.list_replacement_options_by_kind(missing_kinds=missing_kinds)
        defaults: dict[str, str] = {}
        for kind, options in options_by_kind.items():
            preferred = self._preferred_replacements_for_kind(kind, missing_fonts=missing_fonts)
            selected = self._select_default_option(options, preferred)
            if selected:
                defaults[kind] = selected["value"]
        return defaults

    def validate_replacement_font(self, font_name: str, *, kind: str | None = None) -> bool:
        normalized = str(font_name or "").strip().lower()
        if not normalized:
            return False
        normalized_kind = normalize_kind(kind)
        if normalized_kind != "unknown" or str(kind or "").strip():
            return self.inventory.is_valid_font(font_name, kind=normalized_kind)
        return any(option["value"].lower() == normalized for option in self.list_replacement_options())

    def resolve_replacement_fonts(
        self,
        *,
        missing_kinds: list[str],
        missing_fonts: list[dict[str, Any]] | None = None,
        replacement_font: str | None = None,
        replacement_fonts: dict[str, str] | None = None,
    ) -> dict[str, str]:
        normalized_kinds = normalize_missing_kinds(missing_kinds)
        resolved = normalize_replacement_map(replacement_fonts)
        for kind, value in list(resolved.items()):
            if not self.validate_replacement_font(value, kind=kind):
                raise ValueError(f"font_replacement_fonts[{kind}] is unavailable: {value}")

        normalized_font = str(replacement_font or "").strip()
        if normalized_font:
            matched = [
                kind
                for kind in normalized_kinds
                if self.validate_replacement_font(normalized_font, kind=kind)
            ]
            if not matched:
                raise ValueError(f"font_replacement_font is unavailable: {normalized_font}")
            for kind in matched:
                resolved.setdefault(kind, normalized_font)

        defaults = self.default_replacement_fonts(
            missing_kinds=normalized_kinds,
            missing_fonts=missing_fonts,
        )
        for kind in normalized_kinds:
            resolved.setdefault(kind, defaults.get(kind, ""))

        missing_required = [kind for kind in normalized_kinds if not str(resolved.get(kind) or "").strip()]
        if missing_required:
            raise ValueError(
                "font replacement is required for kinds: " + ", ".join(missing_required),
            )
        return {kind: value for kind, value in resolved.items() if kind in normalized_kinds and value}

    def inspect_dwg(
        self,
        *,
        source_dwg: Path,
        replacement_policy: str = "none",
        replacement_font: str | None = None,
        replacement_fonts: dict[str, str] | None = None,
        font_compatibility_mode: bool = False,
        workspace_dir: Path | None = None,
        slot_runtime: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        policy = str(replacement_policy or "none").strip().lower() or "none"
        if policy not in {"none", "replace_missing"}:
            raise ValueError(f"unsupported font_replace_policy: {replacement_policy}")
        normalized_font = str(replacement_font or "").strip() or None
        normalized_font_map = normalize_replacement_map(replacement_fonts)
        font_compatibility_replacements = (
            self._resolve_font_compatibility_replacements()
            if font_compatibility_mode
            else {}
        )
        base_runtime = dict(slot_runtime or {})
        base_runtime.update(
            build_font_search_runtime_overrides(
                font_library_dirs=self.config.font_preflight.font_library_dirs,
                existing_support_path=str(base_runtime.get("support_path") or ""),
            ),
        )

        workspace_root = (workspace_dir or (source_dwg.parent / f".font-preflight-{uuid4().hex[:8]}")).resolve()
        workspace = (workspace_root / _safe_bridge_token(source_dwg.stem)).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        staged_source = workspace / _safe_bridge_filename(source_dwg)
        if staged_source.resolve() != source_dwg.resolve():
            shutil.copy2(source_dwg, staged_source)
        else:
            staged_source = source_dwg
        materialize_font_library_files(
            workspace_dir=workspace,
            font_library_dirs=self.config.font_preflight.font_library_dirs,
        )
        preflight_raw = self.bridge.preflight(
            job_id=f"font-{source_dwg.stem}",
            source_dwg=staged_source,
            workspace_dir=workspace,
            slot_runtime=base_runtime or None,
        )
        preflight_result = self._normalize_result(
            source_dwg=source_dwg,
            payload=preflight_raw,
            replacement_font=None,
            replacement_fonts=None,
        )
        should_replace_missing = (
            policy == "replace_missing"
            and bool(list(preflight_result.get("missing_fonts") or []))
        )
        should_run_replace_pass = should_replace_missing or bool(font_compatibility_replacements)
        if should_replace_missing:
            effective_replacements = self.resolve_replacement_fonts(
                missing_kinds=self._collect_missing_kinds(preflight_result.get("missing_fonts")),
                missing_fonts=list(preflight_result.get("missing_fonts") or []),
                replacement_font=normalized_font,
                replacement_fonts=normalized_font_map,
            )
            replacement_targets = self._normalize_replacement_targets(
                preflight_result.get("missing_fonts"),
            )
            font_runtime_plan = build_font_runtime_plan(
                workspace_dir=workspace,
                missing_fonts=list(preflight_result.get("missing_fonts") or []),
                replacement_fonts=effective_replacements,
                enable_fontmap=bool(self.config.font_preflight.enable_fontmap),
                default_fontalt_by_kind=dict(self.config.font_preflight.default_fontalt_by_kind),
                font_library_dirs=self.config.font_preflight.font_library_dirs,
            )
            replace_runtime = dict(base_runtime)
            replace_runtime.update(font_runtime_plan.runtime_overrides)
            raw = self.bridge.replace_missing(
                job_id=f"font-{source_dwg.stem}",
                source_dwg=staged_source,
                replacement_font=self._legacy_replacement_font(effective_replacements),
                replacement_fonts=effective_replacements,
                replacement_targets=replacement_targets,
                font_compatibility_replacements=font_compatibility_replacements,
                workspace_dir=workspace,
                slot_runtime=replace_runtime or None,
            )
        elif should_run_replace_pass:
            effective_replacements = {}
            font_runtime_plan = None
            raw = self.bridge.replace_missing(
                job_id=f"font-{source_dwg.stem}",
                source_dwg=staged_source,
                replacement_font=None,
                replacement_fonts={},
                replacement_targets=[],
                font_compatibility_replacements=font_compatibility_replacements,
                workspace_dir=workspace,
                slot_runtime=base_runtime or None,
            )
        else:
            raw = preflight_raw
            effective_replacements = {}
            font_runtime_plan = None

        if should_run_replace_pass and staged_source.resolve() != source_dwg.resolve():
            shutil.copy2(staged_source, source_dwg)
        normalized_result = self._normalize_result(
            source_dwg=source_dwg,
            payload=raw,
            replacement_font=normalized_font,
            replacement_fonts=effective_replacements if policy == "replace_missing" else normalized_font_map,
        )
        normalized_result["font_compatibility_mode"] = bool(font_compatibility_mode)
        normalized_result["font_compatibility_replacements"] = dict(
            raw.get("font_compatibility_replacements") or font_compatibility_replacements
        )
        if font_runtime_plan is not None:
            if font_runtime_plan.font_map_path is not None:
                normalized_result["font_map_path"] = str(font_runtime_plan.font_map_path)
            if font_runtime_plan.font_alt:
                normalized_result["font_alt"] = font_runtime_plan.font_alt
        if (
            policy == "replace_missing"
            and bool(normalized_result.get("font_replacement_applied"))
            and bool(self.config.font_preflight.verify_after_replace)
        ):
            verify_runtime = dict(slot_runtime or {})
            verify_runtime = dict(base_runtime)
            if font_runtime_plan is not None:
                verify_runtime.update(font_runtime_plan.runtime_overrides)
            verify_raw = self.bridge.preflight(
                job_id=f"font-{source_dwg.stem}-verify",
                source_dwg=staged_source,
                workspace_dir=workspace / "verify",
                slot_runtime=verify_runtime or None,
            )
            verify_result = self._normalize_result(
                source_dwg=source_dwg,
                payload=verify_raw,
                replacement_font=normalized_font,
                replacement_fonts=effective_replacements,
            )
            normalized_result["verify_after_replace"] = {
                "status": verify_result.get("status"),
                "missing_style_count": verify_result.get("missing_style_count", 0),
                "missing_fonts": verify_result.get("missing_fonts", []),
            }
            if int(verify_result.get("missing_style_count", 0) or 0) > 0:
                normalized_result["font_replacement_incomplete"] = True
                flags = normalized_result.setdefault("flags", [])
                if isinstance(flags, list) and "FONT_REPLACEMENT_INCOMPLETE" not in flags:
                    flags.append("FONT_REPLACEMENT_INCOMPLETE")
        return normalized_result

    def _resolve_font_compatibility_replacements(self) -> dict[str, str]:
        replacements: dict[str, str] = {}
        configured = getattr(
            self.config.font_preflight,
            "font_compatibility_replacements",
            {},
        )
        if not isinstance(configured, dict):
            return replacements
        for raw_source, raw_target in configured.items():
            source_name = Path(str(raw_source or "").strip()).name
            target_name = Path(str(raw_target or "").strip()).name
            if not source_name or not target_name:
                continue
            if not self._is_runtime_font_available(target_name):
                raise ValueError(
                    f"font_compatibility_replacements target is unavailable: {target_name}"
                )
            replacements[source_name] = target_name
        return replacements

    def _is_runtime_font_available(self, font_name: str) -> bool:
        normalized = str(font_name or "").strip()
        if not normalized:
            return False
        for kind in ("bigfont", "shx", "ttf"):
            try:
                if self.inventory.is_valid_font(normalized, kind=kind):
                    return True
            except Exception:  # noqa: BLE001
                continue
        for fonts_dir in self.config.font_preflight.font_library_dirs:
            for candidate_name in self._font_file_candidates(normalized):
                try:
                    if (Path(fonts_dir) / candidate_name).exists():
                        return True
                except OSError:
                    continue
        return False

    @staticmethod
    def _font_file_candidates(font_name: str) -> list[str]:
        normalized = Path(str(font_name or "").strip()).name
        if not normalized:
            return []
        if Path(normalized).suffix:
            return [normalized]
        return [normalized, f"{normalized}.shx"]

    @staticmethod
    def _normalize_result(
        *,
        source_dwg: Path,
        payload: dict[str, Any],
        replacement_font: str | None,
        replacement_fonts: dict[str, str] | None,
    ) -> dict[str, Any]:
        missing_fonts = payload.get("missing_fonts")
        if not isinstance(missing_fonts, list):
            missing_fonts = []
        errors = payload.get("errors")
        if not isinstance(errors, list):
            errors = []
        status = str(payload.get("status", "") or "").strip().lower()
        if not status:
            status = "failed" if errors else ("missing_fonts" if missing_fonts else "ok")
        normalized_font_map = normalize_replacement_map(
            payload.get("replacement_fonts") or replacement_fonts,
        )
        result = {
            "filename": str(payload.get("filename") or source_dwg.name),
            "status": status,
            "missing_fonts": missing_fonts,
            "detected_style_count": int(payload.get("detected_style_count", 0) or 0),
            "missing_style_count": int(payload.get("missing_style_count", len(missing_fonts)) or 0),
            "font_replacement_applied": bool(payload.get("font_replacement_applied", False)),
            "replacement_font": payload.get("replacement_font")
            or replacement_font
            or FontPreflightService._legacy_replacement_font(normalized_font_map),
            "replacement_fonts": normalized_font_map,
            "replaced_style_count": int(payload.get("replaced_style_count", 0) or 0),
        }
        if errors:
            result["errors"] = errors
        return result

    def _preferred_replacements_for_kind(
        self,
        kind: str,
        *,
        missing_fonts: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        normalized = normalize_kind(kind)
        preferred: list[str] = []
        configured_by_missing_font = {
            str(key or "").strip().lower(): str(value or "").strip()
            for key, value in self.config.font_preflight.preferred_replacements_by_missing_font.items()
            if str(key or "").strip() and str(value or "").strip()
        }
        for item in missing_fonts or []:
            if not isinstance(item, dict):
                continue
            item_kind = normalize_kind(str(item.get("kind") or ""))
            if item_kind != normalized:
                continue
            raw_font_name = str(item.get("font_name") or "").strip()
            raw_bigfont_name = str(item.get("bigfont_name") or "").strip()
            lookup_name = raw_bigfont_name if normalized == "bigfont" and raw_bigfont_name else raw_font_name
            mapped = configured_by_missing_font.get(lookup_name.lower())
            if mapped and mapped not in preferred:
                preferred.append(mapped)
        if normalized == "ttf":
            preferred.extend(
                value
                for value in self.config.font_preflight.default_ttf_families
                if value not in preferred
            )
            return preferred
        if normalized == "bigfont":
            preferred.extend(
                value
                for value in self.config.font_preflight.default_bigfont_fonts
                if value not in preferred
            )
            return preferred
        if normalized == "shx":
            preferred.extend(
                value
                for value in self.config.font_preflight.default_shx_fonts
                if value not in preferred
            )
            return preferred
        return preferred

    @staticmethod
    def _select_default_option(
        options: list[dict[str, str]],
        preferred_values: list[str],
    ) -> dict[str, str] | None:
        if not options:
            return None
        lookup = {
            str(option.get("value") or "").strip().lower(): option
            for option in options
        }
        stem_lookup = {
            _font_option_stem(str(option.get("value") or "")): option
            for option in options
            if _font_option_stem(str(option.get("value") or ""))
        }
        family_lookup = {
            str(option.get("family") or "").strip().lower(): option
            for option in options
        }
        for preferred in preferred_values:
            normalized = str(preferred or "").strip().lower()
            if not normalized:
                continue
            if normalized in lookup:
                return lookup[normalized]
            if normalized in family_lookup:
                return family_lookup[normalized]
            stem = _font_option_stem(normalized)
            if stem in stem_lookup:
                return stem_lookup[stem]
            if stem in family_lookup:
                return family_lookup[stem]
            for option in options:
                family = str(option.get("family") or "").strip().lower()
                label = str(option.get("label") or "").strip().lower()
                if stem and (stem in family or stem in label):
                    return option
        return options[0]

    @staticmethod
    def _collect_missing_kinds(missing_fonts: object) -> list[str]:
        if not isinstance(missing_fonts, list):
            return []
        return normalize_missing_kinds(
            str(item.get("kind") or "")
            for item in missing_fonts
            if isinstance(item, dict)
        )

    @staticmethod
    def _legacy_replacement_font(replacement_fonts: dict[str, str] | None) -> str | None:
        if not replacement_fonts:
            return None
        unique_values = []
        for value in replacement_fonts.values():
            normalized = str(value or "").strip()
            if normalized and normalized not in unique_values:
                unique_values.append(normalized)
        if len(unique_values) == 1:
            return unique_values[0]
        return None

    @staticmethod
    def _normalize_replacement_targets(missing_fonts: object) -> list[dict[str, Any]]:
        if not isinstance(missing_fonts, list):
            return []
        normalized_targets: list[dict[str, Any]] = []
        for item in missing_fonts:
            if not isinstance(item, dict):
                continue
            style_name = str(item.get("style_name") or "").strip()
            kind = normalize_kind(item.get("kind"))
            if not style_name or not kind or kind == "unknown":
                continue
            normalized_targets.append(
                {
                    "style_name": style_name,
                    "font_name": str(item.get("font_name") or "").strip(),
                    "bigfont_name": str(item.get("bigfont_name") or "").strip(),
                    "kind": kind,
                    "used_in_block": bool(item.get("used_in_block", False)),
                }
            )
        return normalized_targets


_SAFE_BRIDGE_TOKEN_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_bridge_token(value: str) -> str:
    normalized = _SAFE_BRIDGE_TOKEN_RE.sub("-", str(value or "").strip()).strip("-.")
    if not normalized:
        normalized = "dwg"
    return f"{normalized}-{uuid4().hex[:8]}"


def _safe_bridge_filename(source_dwg: Path) -> str:
    return f"{_safe_bridge_token(source_dwg.stem)}{source_dwg.suffix.lower()}"


def _font_option_stem(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("\\", "/")
    if not normalized:
        return ""
    name = normalized.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0]
