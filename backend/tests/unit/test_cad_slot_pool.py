from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from src.cad.plot_resource_manager import (
    MANAGED_CTB_NAME,
    MANAGED_REVIEW_WHITE_CTB_NAME,
    MANAGED_SAME_WIDTH_CTB_NAME,
    PDF2_PC3_NAME,
    PDF2_PMP_NAME,
)
from src.cad.slot_pool import CADSlotPool


def _isolate_autocad_user_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))


def _valid_pc3_text(label: str = "pc3") -> str:
    return f"PIAFILEVERSION_2.0,PC3VER1,compressed-test,{label}\n" * 8


def _valid_pmp_text(label: str = "pmp") -> str:
    return f"PIAFILEVERSION_2.0,PC3VER1,compressed-test,{label}\n" * 8


def _valid_ctb_text(label: str = "ctb") -> str:
    return f"PIAFILEVERSION_2.0,CTBVER1,compressed-test,{label}\n" * 64


def _build_slot_pool_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        storage_dir=tmp_path / "storage",
        autocad=SimpleNamespace(install_dir=""),
        module5_export=SimpleNamespace(
            plot=SimpleNamespace(
                pc3_name=PDF2_PC3_NAME,
                ctb_name=MANAGED_CTB_NAME,
                plot_style_profiles={
                    "default": MANAGED_CTB_NAME,
                    "review": MANAGED_SAME_WIDTH_CTB_NAME,
                },
            )
        ),
        plot_assets=SimpleNamespace(
            asset_roots=[],
            pmp_name=PDF2_PMP_NAME,
            managed_ctb_names=[
                MANAGED_CTB_NAME,
                MANAGED_SAME_WIDTH_CTB_NAME,
                MANAGED_REVIEW_WHITE_CTB_NAME,
            ],
            min_valid_ctb_bytes=512,
        ),
    )


def test_cad_slot_pool_initializes_four_slots(tmp_path: Path, monkeypatch) -> None:
    _isolate_autocad_user_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr("src.cad.slot_pool.ensure_plot_resources", lambda **kwargs: None)
    config = _build_slot_pool_config(tmp_path)
    config.storage_dir.mkdir(parents=True, exist_ok=True)

    pool = CADSlotPool(config=cast(Any, config), slot_count=4)

    slots = pool.list_slots()
    assert [slot.slot_id for slot in slots] == ["slot-01", "slot-02", "slot-03", "slot-04"]
    for slot in slots:
        assert slot.profile_arg_path.exists()
        assert slot.plotters_dir.exists()
        assert slot.pmp_dir.exists()
        assert slot.plot_styles_dir.exists()
        assert slot.spool_dir.exists()
        assert slot.temp_dir.exists()
        assert slot.logs_dir.exists()


def test_cad_slot_pool_acquire_and_release_updates_status(tmp_path: Path, monkeypatch) -> None:
    _isolate_autocad_user_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr("src.cad.slot_pool.ensure_plot_resources", lambda **kwargs: None)
    config = _build_slot_pool_config(tmp_path)
    config.storage_dir.mkdir(parents=True, exist_ok=True)
    pool = CADSlotPool(config=cast(Any, config), slot_count=1)

    slot = pool.acquire("job-1", timeout=1)
    assert slot.status == "busy"
    assert slot.current_job_id == "job-1"

    pool.release(slot.slot_id)
    released = pool.get_slot(slot.slot_id)
    assert released is not None
    assert released.status == "idle"
    assert released.current_job_id is None


def test_cad_slot_pool_preloads_all_managed_plot_styles(tmp_path: Path, monkeypatch) -> None:
    _isolate_autocad_user_dirs(tmp_path, monkeypatch)
    resources_root = tmp_path / "resources"
    plotters_root = resources_root / "plotters"
    plot_styles_root = resources_root / "plot_styles"
    plotters_root.mkdir(parents=True, exist_ok=True)
    plot_styles_root.mkdir(parents=True, exist_ok=True)
    (plotters_root / PDF2_PC3_NAME).write_text(_valid_pc3_text(), encoding="utf-8")
    (plotters_root / PDF2_PMP_NAME).write_text(_valid_pmp_text(), encoding="utf-8")
    for name in (
        MANAGED_CTB_NAME,
        MANAGED_SAME_WIDTH_CTB_NAME,
        MANAGED_REVIEW_WHITE_CTB_NAME,
    ):
        (plot_styles_root / name).write_text(_valid_ctb_text(name), encoding="utf-8")

    monkeypatch.setenv("FANBAN_PLOT_ASSET_ROOT", str(resources_root))
    config = _build_slot_pool_config(tmp_path)
    config.plot_assets.asset_roots = [resources_root]
    config.storage_dir.mkdir(parents=True, exist_ok=True)

    pool = CADSlotPool(config=cast(Any, config), slot_count=1)

    slot = pool.list_slots()[0]
    assert (slot.plotters_dir / PDF2_PC3_NAME).exists()
    assert (slot.pmp_dir / PDF2_PMP_NAME).exists()
    assert (slot.plot_styles_dir / MANAGED_CTB_NAME).exists()
    assert (slot.plot_styles_dir / MANAGED_SAME_WIDTH_CTB_NAME).exists()
    assert (slot.plot_styles_dir / MANAGED_REVIEW_WHITE_CTB_NAME).exists()


def test_cad_slot_pool_passes_configured_plot_resource_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate_autocad_user_dirs(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}

    def _fake_ensure_plot_resources(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr("src.cad.slot_pool.ensure_plot_resources", _fake_ensure_plot_resources)
    config = SimpleNamespace(
        storage_dir=tmp_path / "storage",
        autocad=SimpleNamespace(install_dir=""),
        module5_export=SimpleNamespace(
            plot=SimpleNamespace(
                pc3_name="custom.pc3",
                ctb_name="custom.ctb",
                plot_style_profiles={
                    "default": "custom.ctb",
                    "review": "review.ctb",
                },
            )
        ),
        plot_assets=SimpleNamespace(
            asset_roots=[tmp_path / "assets-a", tmp_path / "assets-b"],
            pmp_name="custom.pmp",
            managed_ctb_names=["custom.ctb", "review.ctb"],
            min_valid_ctb_bytes=4096,
        ),
    )
    config.storage_dir.mkdir(parents=True, exist_ok=True)

    CADSlotPool(config=cast(Any, config), slot_count=1)

    assert captured["pc3_name"] == "custom.pc3"
    assert captured["ctb_name"] == "custom.ctb"
    assert captured["pmp_name"] == "custom.pmp"
    assert captured["managed_ctb_names"] == ["custom.ctb", "review.ctb"]
    assert captured["min_valid_ctb_bytes"] == 4096
    assert captured["asset_roots"] == [tmp_path / "assets-a", tmp_path / "assets-b"]
