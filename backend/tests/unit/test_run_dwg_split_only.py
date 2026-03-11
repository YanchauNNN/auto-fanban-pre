from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "tools" / "run_dwg_split_only.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("run_dwg_split_only", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_resolve_cli_project_no_prefers_explicit_value() -> None:
    script = _load_script()

    assert script.resolve_cli_project_no("2016", Path("20261RS-JGS65.dwg")) == "2016"


def test_resolve_cli_project_no_uses_inferred_value_when_blank() -> None:
    script = _load_script()

    assert script.resolve_cli_project_no("", Path("20261RS-JGS65.dwg")) == "2026"


def test_find_probe_pdfs_matches_new_output_naming_rule(tmp_path: Path) -> None:
    script = _load_script()
    drawings_dir = tmp_path / "drawings"
    drawings_dir.mkdir()
    pdf_001 = drawings_dir / "XZ1RSL32001B25C42SDACFC (20261RS-JGS65-001).pdf"
    pdf_002 = drawings_dir / "XZ1RSL32002B25C42SDACFC (20261RS-JGS65-002).pdf"
    pdf_003 = drawings_dir / "XZ1RSL32003B25C42SDACFC (20261RS-JGS65-003).pdf"
    pdf_001.touch()
    pdf_002.touch()
    pdf_003.touch()

    probes = script.find_probe_pdfs(drawings_dir)

    assert probes["001"] == pdf_001
    assert probes["002"] == pdf_002
