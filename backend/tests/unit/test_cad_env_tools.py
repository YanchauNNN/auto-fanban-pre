from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _run_powershell(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            *args,
        ],
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=True,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cad_env_fingerprint_generates_stable_json(tmp_path: Path) -> None:
    script = _repo_root() / "tools" / "cad_env_fingerprint.ps1"
    font_dir = tmp_path / "font-library"
    plotters_dir = tmp_path / "Plotters"
    pmp_dir = plotters_dir / "PMP Files"
    plot_styles_dir = plotters_dir / "Plot Styles"
    font_dir.mkdir()
    pmp_dir.mkdir(parents=True)
    plot_styles_dir.mkdir(parents=True)
    (font_dir / "tssdeng.shx").write_text("team-shx", encoding="utf-8")
    (font_dir / "hztxt.shx").write_text("big-font", encoding="utf-8")
    pc3 = plotters_dir / "打印PDF2.pc3"
    pmp = pmp_dir / "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp"
    ctb = plot_styles_dir / "fanban_monochrome.ctb"
    pc3.write_text("pc3-from-golden", encoding="utf-8")
    pmp.write_text("pmp-from-golden", encoding="utf-8")
    ctb.write_text("ctb-from-golden", encoding="utf-8")
    output_json = tmp_path / "fingerprint.json"

    _run_powershell(
        script,
        "-RepoRoot",
        str(_repo_root()),
        "-OutputJson",
        str(output_json),
        "-FontLibraryDir",
        str(font_dir),
        "-PlottersDir",
        str(plotters_dir),
        "-PlotStylesDir",
        str(plot_styles_dir),
        "-Pc3Name",
        "打印PDF2.pc3",
        "-CtbName",
        "fanban_monochrome.ctb",
    )

    payload = json.loads(output_json.read_text(encoding="utf-8-sig"))
    assert payload["schema_version"] == "fanban-cad-env-fingerprint@1"
    assert payload["safety"]["read_only"] is True
    assert payload["cad_session"]["status"] == "not_run"
    assert payload["plot_assets"]["pc3"]["path"] == str(pc3.resolve())
    assert payload["plot_assets"]["pc3"]["sha256"] == _sha256(pc3)
    assert payload["plot_assets"]["pmp"]["sha256"] == _sha256(pmp)
    assert payload["plot_assets"]["ctb"]["sha256"] == _sha256(ctb)
    font_names = {item["name"] for item in payload["font_library"]["files"]}
    assert {"tssdeng.shx", "hztxt.shx"} <= font_names


def test_cad_env_fingerprint_runs_accoreconsole_session_probe(tmp_path: Path) -> None:
    script = _repo_root() / "tools" / "cad_env_fingerprint.ps1"
    fake_accore = tmp_path / "fake_accore.cmd"
    fake_accore.write_text(
        "\n".join(
            [
                "@echo off",
                "echo getvar^|FONTMAP^|acad.fmp> \"%FANBAN_CAD_ENV_PROBE_OUT%\"",
                "echo getvar^|FONTALT^|simplex.shx>> \"%FANBAN_CAD_ENV_PROBE_OUT%\"",
                "echo getvar^|ACADPREFIX^|C:\\cad-support;C:\\team-fonts>> \"%FANBAN_CAD_ENV_PROBE_OUT%\"",
                "echo findfile^|tssdeng.shx^|C:\\team-fonts\\tssdeng.shx>> \"%FANBAN_CAD_ENV_PROBE_OUT%\"",
                "exit /b 0",
            ]
        ),
        encoding="utf-8",
    )
    sample_dwg = tmp_path / "sample.dwg"
    sample_dwg.write_text("fake", encoding="utf-8")
    output_json = tmp_path / "fingerprint.json"

    _run_powershell(
        script,
        "-OutputJson",
        str(output_json),
        "-AccoreConsoleExe",
        str(fake_accore),
        "-SampleDwg",
        str(sample_dwg),
    )

    payload = json.loads(output_json.read_text(encoding="utf-8-sig"))
    assert payload["cad_session"]["status"] == "pass"
    assert payload["font_vars"]["FONTMAP"] == "acad.fmp"
    assert payload["font_vars"]["FONTALT"] == "simplex.shx"
    assert payload["support_paths"]["entries"] == ["C:\\cad-support", "C:\\team-fonts"]
    assert payload["font_findfile"]["tssdeng.shx"]["path"] == "C:\\team-fonts\\tssdeng.shx"
    assert payload["logs"]["accoreconsole_log"]


def test_cad_env_sync_defaults_to_dry_run_and_reports_differences(tmp_path: Path) -> None:
    script = _repo_root() / "tools" / "cad_env_sync.ps1"
    golden_pc3 = tmp_path / "golden.pc3"
    golden_ctb = tmp_path / "golden.ctb"
    golden_pc3.write_text("golden-pc3", encoding="utf-8")
    golden_ctb.write_text("golden-ctb", encoding="utf-8")
    golden_json = tmp_path / "golden.json"
    target_json = tmp_path / "target.json"
    output_json = tmp_path / "sync-plan.json"
    golden_json.write_text(
        json.dumps(
            {
                "support_paths": {"entries": ["C:/golden/fonts"]},
                "font_vars": {"FONTMAP": "golden.fmp", "FONTALT": "simsun.ttc"},
                "font_findfile": {"tssdeng.shx": {"path": "C:/golden/tssdeng.shx", "sha256": "a"}},
                "plot_assets": {
                    "pc3": {"path": str(golden_pc3), "sha256": _sha256(golden_pc3)},
                    "ctb": {"path": str(golden_ctb), "sha256": _sha256(golden_ctb)},
                },
            }
        ),
        encoding="utf-8",
    )
    target_json.write_text(
        json.dumps(
            {
                "support_paths": {"entries": ["C:/target/fonts"]},
                "font_vars": {"FONTMAP": "target.fmp", "FONTALT": "simplex.shx"},
                "font_findfile": {"tssdeng.shx": {"path": "C:/target/tssdeng.shx", "sha256": "b"}},
                "plot_assets": {
                    "pc3": {"path": "C:/target/打印PDF2.pc3", "sha256": "different"},
                    "ctb": {"path": "C:/target/fanban_monochrome.ctb", "sha256": "different"},
                },
            }
        ),
        encoding="utf-8",
    )

    _run_powershell(
        script,
        "-GoldenJson",
        str(golden_json),
        "-TargetJson",
        str(target_json),
        "-OutputJson",
        str(output_json),
    )

    payload = json.loads(output_json.read_text(encoding="utf-8-sig"))
    assert payload["schema_version"] == "fanban-cad-env-sync-plan@1"
    assert payload["mode"] == "dry-run"
    assert payload["safety"]["apply"] is False
    difference_codes = {item["code"] for item in payload["differences"]}
    assert {"support_path", "FONTMAP", "FONTALT", "font_findfile:tssdeng.shx", "plot_asset:pc3"} <= difference_codes
    assert all(action["status"] == "planned" for action in payload["actions"])


def test_cad_env_sync_apply_copies_only_to_private_target_dirs(tmp_path: Path) -> None:
    script = _repo_root() / "tools" / "cad_env_sync.ps1"
    source_plotters = tmp_path / "source-plotters"
    source_styles = tmp_path / "source-styles"
    target_plotters = tmp_path / "target-slot" / "support" / "Plotters"
    target_styles = target_plotters / "Plot Styles"
    source_plotters.mkdir()
    source_styles.mkdir()
    pc3 = source_plotters / "打印PDF2.pc3"
    pmp = source_plotters / "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp"
    ctb = source_styles / "fanban_monochrome.ctb"
    pc3.write_text("golden-pc3", encoding="utf-8")
    pmp.write_text("golden-pmp", encoding="utf-8")
    ctb.write_text("golden-ctb", encoding="utf-8")
    golden_json = tmp_path / "golden.json"
    target_json = tmp_path / "target.json"
    output_json = tmp_path / "sync-apply.json"
    golden_json.write_text(
        json.dumps(
            {
                "plot_assets": {
                    "pc3": {"path": str(pc3), "sha256": _sha256(pc3)},
                    "pmp": {"path": str(pmp), "sha256": _sha256(pmp)},
                    "ctb": {"path": str(ctb), "sha256": _sha256(ctb)},
                }
            }
        ),
        encoding="utf-8",
    )
    target_json.write_text(json.dumps({"plot_assets": {}}), encoding="utf-8")

    _run_powershell(
        script,
        "-GoldenJson",
        str(golden_json),
        "-TargetJson",
        str(target_json),
        "-OutputJson",
        str(output_json),
        "-TargetPlottersDir",
        str(target_plotters),
        "-TargetPlotStylesDir",
        str(target_styles),
        "-Apply:$true",
    )

    payload = json.loads(output_json.read_text(encoding="utf-8-sig"))
    assert payload["mode"] == "apply"
    assert (target_plotters / pc3.name).read_text(encoding="utf-8") == "golden-pc3"
    assert (target_plotters / pmp.name).read_text(encoding="utf-8") == "golden-pmp"
    assert (target_styles / ctb.name).read_text(encoding="utf-8") == "golden-ctb"
    assert all(str(tmp_path / "target-slot") in action["target"] for action in payload["actions"])
