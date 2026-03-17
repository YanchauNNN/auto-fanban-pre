from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from src.cad.slot_pool import CADSlotPool


def test_cad_slot_pool_initializes_four_slots(tmp_path: Path) -> None:
    config = SimpleNamespace(storage_dir=tmp_path / "storage", autocad=SimpleNamespace(install_dir=""))
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


def test_cad_slot_pool_acquire_and_release_updates_status(tmp_path: Path) -> None:
    config = SimpleNamespace(storage_dir=tmp_path / "storage", autocad=SimpleNamespace(install_dir=""))
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
    resources_root = tmp_path / "resources"
    plotters_root = resources_root / "plotters"
    plot_styles_root = resources_root / "plot_styles"
    plotters_root.mkdir(parents=True, exist_ok=True)
    plot_styles_root.mkdir(parents=True, exist_ok=True)
    (plotters_root / "打印PDF2.pc3").write_text("pc3", encoding="utf-8")
    (plotters_root / "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp").write_text(
        "pmp",
        encoding="utf-8",
    )
    for name in (
        "fanban_monochrome.ctb",
        "fanban_monochrome-same width.ctb",
        "打白图.ctb",
    ):
        (plot_styles_root / name).write_text(name * 64, encoding="utf-8")

    monkeypatch.setenv("FANBAN_PLOT_ASSET_ROOT", str(resources_root))
    config = SimpleNamespace(storage_dir=tmp_path / "storage", autocad=SimpleNamespace(install_dir=""))
    config.storage_dir.mkdir(parents=True, exist_ok=True)

    pool = CADSlotPool(config=cast(Any, config), slot_count=1)

    slot = pool.list_slots()[0]
    assert (slot.plotters_dir / "打印PDF2.pc3").exists()
    assert (slot.pmp_dir / "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp").exists()
    assert (slot.plot_styles_dir / "fanban_monochrome.ctb").exists()
    assert (slot.plot_styles_dir / "fanban_monochrome-same width.ctb").exists()
    assert (slot.plot_styles_dir / "打白图.ctb").exists()
