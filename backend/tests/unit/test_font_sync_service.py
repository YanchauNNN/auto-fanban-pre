from __future__ import annotations

import json
import zipfile
from pathlib import Path


class _FakeFontPreflightService:
    def inspect_dwg(
        self,
        *,
        source_dwg: Path,
        replacement_policy: str = "none",
        replacement_font: str | None = None,
        replacement_fonts: dict[str, str] | None = None,
        workspace_dir: Path | None = None,
        slot_runtime: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return {
            "filename": source_dwg.name,
            "status": "ok",
            "missing_fonts": [],
            "detected_style_count": 3,
            "missing_style_count": 0,
            "font_replacement_applied": False,
            "replacement_font": None,
            "replacement_fonts": {},
            "replaced_style_count": 0,
        }


class _FakeAutoCADAdapter:
    def __init__(self, *, snapshot: dict[str, object], styles: list[dict[str, object]]) -> None:
        self.snapshot = snapshot
        self.styles = styles
        self.exported_profiles: list[Path] = []
        self.applied_settings: list[dict[str, object]] = []
        self.applied_snapshot = dict(snapshot)

    def read_local_settings(self) -> dict[str, object]:
        return dict(self.applied_snapshot)

    def inspect_dwg_styles(self, source_dwg: Path) -> list[dict[str, object]]:
        assert source_dwg.exists()
        return [dict(item) for item in self.styles]

    def export_profile_backup(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("profile-backup", encoding="utf-8")
        self.exported_profiles.append(output_path)
        return output_path

    def apply_font_settings(
        self,
        *,
        support_path: str,
        font_file_map: str | None,
        alt_font_file: str | None,
    ) -> dict[str, object]:
        self.applied_settings.append(
            {
                "support_path": support_path,
                "font_file_map": font_file_map,
                "alt_font_file": alt_font_file,
            }
        )
        self.applied_snapshot = {
            **self.applied_snapshot,
            "support_path": support_path,
            "font_file_map": font_file_map,
            "alt_font_file": alt_font_file,
        }
        return dict(self.applied_snapshot)


def _build_snapshot(*, tmp_path: Path) -> dict[str, object]:
    install_dir = tmp_path / "AutoCAD 2022"
    fonts_dir = install_dir / "Fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    (fonts_dir / "simplex.shx").write_text("simplex", encoding="utf-8")
    (fonts_dir / "gbcbig.shx").write_text("gbcbig", encoding="utf-8")

    user_support = (
        tmp_path
        / "source-user"
        / "AppData"
        / "Roaming"
        / "Autodesk"
        / "AutoCAD 2022"
        / "R24.1"
        / "chs"
        / "support"
    )
    user_support.mkdir(parents=True, exist_ok=True)
    win_fonts = tmp_path / "WindowsFonts"
    win_fonts.mkdir(parents=True, exist_ok=True)
    (win_fonts / "simsun.ttc").write_text("simsun", encoding="utf-8")

    shared_support = tmp_path / "shared-support"
    shared_support.mkdir(parents=True, exist_ok=True)
    (shared_support / "custom.shx").write_text("custom", encoding="utf-8")

    return {
        "autocad_ready": True,
        "supported": True,
        "active_profile": "CADUserProfile",
        "support_path": f"{user_support};{shared_support};{fonts_dir}",
        "font_file_map": r"C:\Users\demo\AppData\Roaming\Autodesk\fontmap.fmp",
        "alt_font_file": "simplex.shx",
        "installations": [
            {
                "label": "AutoCAD 2022",
                "install_dir": str(install_dir),
                "acad_exe": str(install_dir / "acad.exe"),
                "accoreconsole_exe": str(install_dir / "accoreconsole.exe"),
                "fonts_dir": str(fonts_dir),
            }
        ],
        "selected_installation": {
            "label": "AutoCAD 2022",
            "install_dir": str(install_dir),
            "acad_exe": str(install_dir / "acad.exe"),
            "accoreconsole_exe": str(install_dir / "accoreconsole.exe"),
            "fonts_dir": str(fonts_dir),
        },
        "windows_fonts_dir": str(win_fonts),
        "font_search_roots": [str(user_support), str(shared_support), str(fonts_dir), str(win_fonts)],
    }


def _build_styles(*, tmp_path: Path) -> list[dict[str, object]]:
    absolute_font = tmp_path / "absolute-fonts" / "hz.shx"
    absolute_font.parent.mkdir(parents=True, exist_ok=True)
    absolute_font.write_text("hz", encoding="utf-8")
    return [
        {
            "style_name": "STYLE-SHX",
            "font_name": "simplex.shx",
            "bigfont_name": "",
            "kind": "shx",
        },
        {
            "style_name": "STYLE-TTF",
            "font_name": "simsun.ttc",
            "bigfont_name": "",
            "kind": "ttf",
        },
        {
            "style_name": "STYLE-BIGFONT",
            "font_name": str(absolute_font),
            "bigfont_name": "gbcbig.shx",
            "kind": "bigfont",
        },
    ]


def _build_service(tmp_path: Path):
    from src.cad.font_sync_service import FontSyncService

    snapshot = _build_snapshot(tmp_path=tmp_path)
    adapter = _FakeAutoCADAdapter(snapshot=snapshot, styles=_build_styles(tmp_path=tmp_path))
    service = FontSyncService(
        font_preflight_service=_FakeFontPreflightService(),
        autocad_adapter=adapter,
        storage_root=tmp_path / "storage",
        managed_root=tmp_path / "managed",
    )
    return service, adapter


def test_merge_support_path_preserves_existing_segments_and_is_idempotent() -> None:
    from src.cad.font_sync_service import merge_support_path

    merged = merge_support_path(r"C:\A;C:\B", r"C:\Managed\Fonts")
    assert merged == r"C:\A;C:\B;C:\Managed\Fonts"

    merged_again = merge_support_path(merged, r"C:\Managed\Fonts")
    assert merged_again == merged


def test_source_scan_resolves_font_dependencies_and_is_guaranteed(tmp_path: Path) -> None:
    service, _adapter = _build_service(tmp_path)
    source_dwg = tmp_path / "source.dwg"
    source_dwg.write_bytes(b"dwg")

    result = service.scan_source_dwg(source_dwg=source_dwg)

    assert result["bundle_mode"] == "guaranteed"
    assert result["drawing"]["filename"] == "source.dwg"
    assert len(result["font_dependencies"]) == 4
    assert all(item["resolved"] is True for item in result["font_dependencies"])
    assert result["environment"]["active_profile"] == "CADUserProfile"


def test_export_bundle_writes_manifest_fonts_and_profile_backup(tmp_path: Path) -> None:
    service, adapter = _build_service(tmp_path)
    source_dwg = tmp_path / "source.dwg"
    source_dwg.write_bytes(b"dwg")

    export_result = service.export_bundle(source_dwg=source_dwg)
    bundle_path = Path(str(export_result["bundle_path"]))

    assert bundle_path.suffix == ".fanfontsync"
    assert bundle_path.exists()
    assert len(adapter.exported_profiles) == 1

    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "reports/styles.csv" in names
        assert "managed/fontmap.fmp" in names
        assert "profiles/source-profile.arg" in names
        assert any(name.startswith("fonts/") for name in names)
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert manifest["bundle_mode"] == "guaranteed"
    assert manifest["source"]["dwg_filename"] == "source.dwg"
    assert len(manifest["font_dependencies"]) == 4


def test_preview_and_apply_bundle_report_matched_state(tmp_path: Path) -> None:
    service, adapter = _build_service(tmp_path)
    source_dwg = tmp_path / "source.dwg"
    source_dwg.write_bytes(b"dwg")
    export_result = service.export_bundle(source_dwg=source_dwg)
    bundle_path = Path(str(export_result["bundle_path"]))

    preview = service.preview_bundle(bundle_path=bundle_path)
    assert preview["bundle_mode"] == "guaranteed"
    assert preview["diff"]["support_path_changed"] is True
    assert preview["planned_changes"]["managed_fonts_dir"]

    applied = service.apply_bundle(bundle_path=bundle_path)
    assert applied["status"] == "matched"
    assert len(adapter.exported_profiles) == 2
    assert adapter.applied_settings
    assert Path(str(applied["profile_backup_path"])).exists()
    assert Path(str(applied["managed_fonts_dir"])).exists()


def test_export_bundle_marks_best_effort_when_font_dependency_is_unresolved(tmp_path: Path) -> None:
    from src.cad.font_sync_service import FontSyncService

    snapshot = _build_snapshot(tmp_path=tmp_path)
    adapter = _FakeAutoCADAdapter(
        snapshot=snapshot,
        styles=[
            {
                "style_name": "STYLE-MISSING",
                "font_name": "missing-font.shx",
                "bigfont_name": "",
                "kind": "shx",
            }
        ],
    )
    service = FontSyncService(
        font_preflight_service=_FakeFontPreflightService(),
        autocad_adapter=adapter,
        storage_root=tmp_path / "storage",
        managed_root=tmp_path / "managed",
    )
    source_dwg = tmp_path / "source.dwg"
    source_dwg.write_bytes(b"dwg")

    export_result = service.export_bundle(source_dwg=source_dwg)

    assert export_result["bundle_mode"] == "best_effort"
    assert export_result["font_dependencies"][0]["resolved"] is False


def test_preview_and_apply_bundle_use_strict_support_path_without_target_residue(
    tmp_path: Path,
) -> None:
    service, adapter = _build_service(tmp_path)
    source_dwg = tmp_path / "source.dwg"
    source_dwg.write_bytes(b"dwg")
    export_result = service.export_bundle(source_dwg=source_dwg)
    bundle_path = Path(str(export_result["bundle_path"]))

    target_install_dir = tmp_path / "TargetAutoCAD 2024"
    target_fonts_dir = target_install_dir / "Fonts"
    target_fonts_dir.mkdir(parents=True, exist_ok=True)
    target_user_support = (
        tmp_path
        / "target-user"
        / "AppData"
        / "Roaming"
        / "Autodesk"
        / "AutoCAD 2022"
        / "R24.1"
        / "chs"
        / "support"
    )
    target_user_support.mkdir(parents=True, exist_ok=True)
    target_win_fonts = tmp_path / "TargetWindowsFonts"
    target_win_fonts.mkdir(parents=True, exist_ok=True)
    target_only_support = tmp_path / "target-only-support"
    target_only_support.mkdir(parents=True, exist_ok=True)
    shared_support = tmp_path / "shared-support"

    adapter.applied_snapshot = {
        **adapter.applied_snapshot,
        "support_path": f"{target_user_support};{target_fonts_dir};{target_only_support}",
        "font_file_map": str(tmp_path / "target-user" / "fontmap.fmp"),
        "alt_font_file": "txt.shx",
        "installations": [
            {
                "label": "AutoCAD 2024",
                "install_dir": str(target_install_dir),
                "acad_exe": str(target_install_dir / "acad.exe"),
                "accoreconsole_exe": str(target_install_dir / "accoreconsole.exe"),
                "fonts_dir": str(target_fonts_dir),
            }
        ],
        "selected_installation": {
            "label": "AutoCAD 2024",
            "install_dir": str(target_install_dir),
            "acad_exe": str(target_install_dir / "acad.exe"),
            "accoreconsole_exe": str(target_install_dir / "accoreconsole.exe"),
            "fonts_dir": str(target_fonts_dir),
        },
        "windows_fonts_dir": str(target_win_fonts),
        "font_search_roots": [
            str(target_user_support),
            str(target_fonts_dir),
            str(target_only_support),
            str(target_win_fonts),
        ],
    }

    preview = service.preview_bundle(bundle_path=bundle_path)
    planned_support_path = str(preview["planned_changes"]["support_path"])
    managed_fonts_dir = str(preview["planned_changes"]["managed_fonts_dir"])

    assert str(target_user_support) in planned_support_path
    assert str(shared_support) in planned_support_path
    assert str(target_fonts_dir) in planned_support_path
    assert managed_fonts_dir in planned_support_path
    assert str(target_only_support) not in planned_support_path
    assert preview["diff"]["support_path_changed"] is True
    assert preview["diff"]["font_file_map_changed"] is True
    assert preview["diff"]["alt_font_file_changed"] is True

    applied = service.apply_bundle(bundle_path=bundle_path)

    assert applied["status"] == "matched"
    assert str(target_user_support) in str(applied["environment"]["support_path"])
    assert str(target_fonts_dir) in str(applied["environment"]["support_path"])
    assert str(target_only_support) not in str(applied["environment"]["support_path"])
