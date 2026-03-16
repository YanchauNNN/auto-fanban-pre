from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path

from ..config import RuntimeConfig, get_config
from .autocad_path_resolver import AutoCADInstallation, list_available_autocad_installations


@dataclass(slots=True)
class CADSlot:
    slot_id: str
    cad_version: int | None
    install_dir: Path | None
    accoreconsole_exe: Path | None
    slot_root: Path
    profile_dir: Path
    profile_arg_path: Path
    support_root: Path
    plotters_dir: Path
    pmp_dir: Path
    plot_styles_dir: Path
    spool_dir: Path
    temp_dir: Path
    logs_dir: Path
    status: str = "idle"
    current_job_id: str | None = None


class CADSlotPool:
    def __init__(self, *, config: RuntimeConfig | None = None, slot_count: int = 4) -> None:
        self.config = config or get_config()
        self.slot_count = max(int(slot_count), 1)
        self.runtime_root = self.config.storage_dir / "runtime" / "cad-slots"
        self._lock = threading.Lock()
        self._queue: queue.Queue[str] = queue.Queue()
        self._slots: dict[str, CADSlot] = {}

        installations = list_available_autocad_installations(
            configured_install_dir=self.config.autocad.install_dir,
        )
        selected = self._select_installation(installations)
        self._installations = installations
        self._selected_installation = selected
        self._initialize_slots(selected)

    @property
    def selected_installation(self) -> AutoCADInstallation | None:
        return self._selected_installation

    def list_slots(self) -> list[CADSlot]:
        with self._lock:
            return [self._slots[slot_id] for slot_id in sorted(self._slots)]

    def acquire(self, job_id: str, timeout: float | None = None) -> CADSlot:
        slot_id = self._queue.get(timeout=timeout)
        with self._lock:
            slot = self._slots[slot_id]
            slot.status = "busy"
            slot.current_job_id = job_id
            return slot

    def release(self, slot_id: str) -> None:
        with self._lock:
            slot = self._slots.get(slot_id)
            if slot is None:
                return
            slot.status = "idle"
            slot.current_job_id = None
        self._queue.put(slot_id)

    def get_slot(self, slot_id: str) -> CADSlot | None:
        with self._lock:
            return self._slots.get(slot_id)

    def _initialize_slots(self, installation: AutoCADInstallation | None) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        for idx in range(1, self.slot_count + 1):
            slot_id = f"slot-{idx:02d}"
            slot_root = self.runtime_root / slot_id
            profile_dir = slot_root / "profile"
            support_root = slot_root / "support"
            plotters_dir = support_root / "Plotters"
            pmp_dir = plotters_dir / "PMP Files"
            plot_styles_dir = plotters_dir / "Plot Styles"
            spool_dir = slot_root / "spool"
            temp_dir = slot_root / "temp"
            logs_dir = slot_root / "logs"
            for path in (
                profile_dir,
                plotters_dir,
                pmp_dir,
                plot_styles_dir,
                spool_dir,
                temp_dir,
                logs_dir,
            ):
                path.mkdir(parents=True, exist_ok=True)

            profile_arg_path = profile_dir / f"fanban-{slot_id}.arg"
            profile_arg_path.write_text(
                "\n".join(
                    [
                        f"slot_id={slot_id}",
                        f"support_root={support_root}",
                        f"plotters_dir={plotters_dir}",
                        f"plot_styles_dir={plot_styles_dir}",
                        f"spool_dir={spool_dir}",
                        f"temp_dir={temp_dir}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            slot = CADSlot(
                slot_id=slot_id,
                cad_version=installation.year if installation else None,
                install_dir=installation.install_dir if installation else None,
                accoreconsole_exe=installation.accoreconsole_exe if installation else None,
                slot_root=slot_root,
                profile_dir=profile_dir,
                profile_arg_path=profile_arg_path,
                support_root=support_root,
                plotters_dir=plotters_dir,
                pmp_dir=pmp_dir,
                plot_styles_dir=plot_styles_dir,
                spool_dir=spool_dir,
                temp_dir=temp_dir,
                logs_dir=logs_dir,
            )
            self._slots[slot_id] = slot
            self._queue.put(slot_id)

    @staticmethod
    def _select_installation(
        installations: list[AutoCADInstallation],
    ) -> AutoCADInstallation | None:
        if not installations:
            return None
        installations = sorted(
            installations,
            key=lambda item: (item.year or 0, str(item.install_dir)),
            reverse=True,
        )
        return installations[0]
