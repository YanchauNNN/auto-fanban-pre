from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
GUI_PATH = PROJECT_ROOT / "test" / "dist" / "src" / "fanban_m5_gui.py"


def _load_gui():
    spec = importlib.util.spec_from_file_location("fanban_m5_gui", GUI_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pick_dwg_project_no_overwrites_auto_managed_default() -> None:
    gui = _load_gui()

    value, auto_managed = gui.resolve_project_field_update(
        current_value="2016",
        auto_managed=True,
        dwg_path=Path("20261RS-JGS65.dwg"),
    )

    assert value == "2026"
    assert auto_managed is True


def test_pick_dwg_project_no_preserves_manual_value() -> None:
    gui = _load_gui()

    value, auto_managed = gui.resolve_project_field_update(
        current_value="1818",
        auto_managed=False,
        dwg_path=Path("20261RS-JGS65.dwg"),
    )

    assert value == "1818"
    assert auto_managed is False


def test_pick_dwg_project_no_keeps_current_value_when_not_inferable() -> None:
    gui = _load_gui()

    value, auto_managed = gui.resolve_project_field_update(
        current_value="2016",
        auto_managed=True,
        dwg_path=Path("sample.dwg"),
    )

    assert value == "2016"
    assert auto_managed is True
