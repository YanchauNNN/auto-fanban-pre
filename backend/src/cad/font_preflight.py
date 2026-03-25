from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from .font_inventory import InstalledFontInventory
from .font_preflight_bridge import FontPreflightBridge


class FontPreflightService:
    def __init__(
        self,
        *,
        inventory: InstalledFontInventory | None = None,
        bridge: FontPreflightBridge | None = None,
    ) -> None:
        self.inventory = inventory or InstalledFontInventory()
        self.bridge = bridge or FontPreflightBridge()
        self._options_cache: list[dict[str, str]] | None = None

    def list_replacement_options(self, *, missing_kinds: list[str] | None = None) -> list[dict[str, str]]:
        normalized_kinds = {
            str(kind or "").strip().lower() for kind in (missing_kinds or []) if str(kind or "").strip()
        }
        if normalized_kinds:
            return list(self.inventory.list_options(preferred_kinds=normalized_kinds))
        if self._options_cache is None:
            self._options_cache = self.inventory.list_options(preferred_kinds=None)
        return list(self._options_cache)

    def validate_replacement_font(self, font_name: str) -> bool:
        normalized = str(font_name or "").strip().lower()
        if not normalized:
            return False
        return any(option["value"].lower() == normalized for option in self.list_replacement_options())

    def inspect_dwg(
        self,
        *,
        source_dwg: Path,
        replacement_policy: str = "none",
        replacement_font: str | None = None,
        workspace_dir: Path | None = None,
        slot_runtime: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        policy = str(replacement_policy or "none").strip().lower() or "none"
        if policy not in {"none", "replace_missing"}:
            raise ValueError(f"unsupported font_replace_policy: {replacement_policy}")
        if policy == "replace_missing":
            normalized_font = str(replacement_font or "").strip()
            if not normalized_font:
                raise ValueError("font_replacement_font is required")
            if not self.validate_replacement_font(normalized_font):
                raise ValueError(f"font_replacement_font is unavailable: {normalized_font}")
        else:
            normalized_font = None

        workspace = workspace_dir or (source_dwg.parent / f".font-preflight-{uuid4().hex[:8]}")
        if policy == "replace_missing":
            raw = self.bridge.replace_missing(
                job_id=f"font-{source_dwg.stem}",
                source_dwg=source_dwg,
                replacement_font=normalized_font or "",
                workspace_dir=workspace,
                slot_runtime=slot_runtime,
            )
        else:
            raw = self.bridge.preflight(
                job_id=f"font-{source_dwg.stem}",
                source_dwg=source_dwg,
                workspace_dir=workspace,
                slot_runtime=slot_runtime,
            )
        return self._normalize_result(
            source_dwg=source_dwg,
            payload=raw,
            replacement_font=normalized_font,
        )

    @staticmethod
    def _normalize_result(
        *,
        source_dwg: Path,
        payload: dict[str, Any],
        replacement_font: str | None,
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
        result = {
            "filename": str(payload.get("filename") or source_dwg.name),
            "status": status,
            "missing_fonts": missing_fonts,
            "detected_style_count": int(payload.get("detected_style_count", 0) or 0),
            "missing_style_count": int(payload.get("missing_style_count", len(missing_fonts)) or 0),
            "font_replacement_applied": bool(payload.get("font_replacement_applied", False)),
            "replacement_font": payload.get("replacement_font") or replacement_font,
            "replaced_style_count": int(payload.get("replaced_style_count", 0) or 0),
        }
        if errors:
            result["errors"] = errors
        return result
