from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from src.cad.font_preflight import FontPreflightService


class _Inventory:
    def list_options(self, *, preferred_kinds: set[str] | None = None) -> list[dict[str, str]]:
        if preferred_kinds == {"ttf"}:
            return [
                {
                    "label": "SimSun (simsun.ttc)",
                    "value": "simsun.ttc",
                    "family": "SimSun",
                    "path": r"C:\Windows\Fonts\simsun.ttc",
                    "kind": "ttf",
                }
            ]
        return []

    def is_valid_font(self, value: str, *, kind: str | None = None) -> bool:
        return value.lower() == "simsun.ttc"


class _VerifyingBridge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def preflight(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "preflight", **kwargs})
        if str(kwargs.get("job_id", "")).endswith("-verify"):
            return {
                "status": "ok",
                "missing_fonts": [],
                "detected_style_count": 2,
                "missing_style_count": 0,
            }
        return {
            "status": "missing_fonts",
            "missing_fonts": [
                {
                    "style_name": "宋体",
                    "font_name": "MENU2.TTF",
                    "bigfont_name": "",
                    "kind": "ttf",
                    "used_in_block": True,
                }
            ],
            "detected_style_count": 2,
            "missing_style_count": 1,
        }

    def replace_missing(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "replace_missing", **kwargs})
        return {
            "status": "ok",
            "missing_fonts": [],
            "detected_style_count": 2,
            "missing_style_count": 0,
            "font_replacement_applied": True,
            "replacement_fonts": kwargs.get("replacement_fonts") or {},
            "replaced_style_count": 1,
        }


class _LibraryAwareBridge:
    def __init__(self, expected_support_path: Path) -> None:
        self.calls: list[dict[str, Any]] = []
        self.expected_support_path = expected_support_path

    def preflight(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "preflight", **kwargs})
        runtime = kwargs.get("slot_runtime") or {}
        support_path = str(runtime.get("support_path") or "")
        if str(self.expected_support_path) in support_path:
            return {
                "status": "ok",
                "missing_fonts": [],
                "detected_style_count": 2,
                "missing_style_count": 0,
            }
        return {
            "status": "missing_fonts",
            "missing_fonts": [
                {
                    "style_name": "宋体",
                    "font_name": "MENU2.TTF",
                    "bigfont_name": "",
                    "kind": "ttf",
                    "used_in_block": True,
                }
            ],
            "detected_style_count": 2,
            "missing_style_count": 1,
        }

    def replace_missing(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "replace_missing", **kwargs})
        return {
            "status": "ok",
            "missing_fonts": [],
            "detected_style_count": 2,
            "missing_style_count": 0,
            "font_replacement_applied": True,
            "replacement_fonts": kwargs.get("replacement_fonts") or {},
            "replaced_style_count": 1,
        }


def test_font_preflight_service_wires_fontmap_runtime_into_replace_and_verify(
    tmp_path: Path,
) -> None:
    bridge = _VerifyingBridge()
    service = FontPreflightService(
        inventory=cast(Any, _Inventory()),
        bridge=cast(Any, bridge),
    )
    service.config.font_preflight.enable_fontmap = True
    service.config.font_preflight.verify_after_replace = True
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    result = service.inspect_dwg(
        source_dwg=source,
        replacement_policy="replace_missing",
        replacement_fonts={"ttf": "simsun.ttc"},
        workspace_dir=tmp_path / "work",
    )

    replace_call = next(call for call in bridge.calls if call["method"] == "replace_missing")
    assert replace_call["slot_runtime"]["font_alt"] == "simsun.ttc"
    assert Path(replace_call["slot_runtime"]["font_map_path"]).exists()
    assert "verify_after_replace" in result
    assert result.get("font_replacement_incomplete") is None


def test_font_preflight_service_injects_font_library_support_path_before_first_preflight(
    tmp_path: Path,
) -> None:
    font_lib = tmp_path / "font-lib"
    font_lib.mkdir()
    bridge = _LibraryAwareBridge(font_lib)
    service = FontPreflightService(
        inventory=cast(Any, _Inventory()),
        bridge=cast(Any, bridge),
    )
    service.config.font_preflight.font_library_dirs = [font_lib]
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    result = service.inspect_dwg(
        source_dwg=source,
        replacement_policy="none",
        workspace_dir=tmp_path / "work",
    )

    assert result["status"] == "ok"
    preflight_call = next(call for call in bridge.calls if call["method"] == "preflight")
    assert preflight_call["slot_runtime"]["support_path"] == str(font_lib)
    assert [call["method"] for call in bridge.calls] == ["preflight"]
