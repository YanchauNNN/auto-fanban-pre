from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.cad.slot_pool import CADSlotPool


def test_cad_slot_pool_initializes_four_slots(tmp_path: Path) -> None:
    config = SimpleNamespace(storage_dir=tmp_path / "storage", autocad=SimpleNamespace(install_dir=""))
    config.storage_dir.mkdir(parents=True, exist_ok=True)

    pool = CADSlotPool(config=config, slot_count=4)

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
    pool = CADSlotPool(config=config, slot_count=1)

    slot = pool.acquire("job-1", timeout=1)
    assert slot.status == "busy"
    assert slot.current_job_id == "job-1"

    pool.release(slot.slot_id)
    released = pool.get_slot(slot.slot_id)
    assert released is not None
    assert released.status == "idle"
    assert released.current_job_id is None
