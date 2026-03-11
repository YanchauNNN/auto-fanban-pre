from __future__ import annotations

from pathlib import Path


def test_probe_target_env_avoids_psscriptanalyzer_naming_issues() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert '[string]$Error = ""' not in script_text
    assert "function Try-RemovePath" not in script_text
    assert "function Pick-BestAccoreconsole" not in script_text
    assert "function Pick-BestPlotterDir" not in script_text
    assert "function Detect-RepoRoot" not in script_text
    assert "function Release-ComObject" not in script_text


def test_probe_target_env_avoids_scalar_count_on_ipv4_addresses() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "$addresses.Count" not in script_text
