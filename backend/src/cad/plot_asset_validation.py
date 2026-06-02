from __future__ import annotations

from pathlib import Path

CAD_PLOT_ASSETS_BACKUP_ZIP = "cad_plot_assets_backup.zip"
PC3_HEADER_PREFIX = b"PIAFILEVERSION_2.0,PC3VER1"
CTB_HEADER_PREFIX = b"PIAFILEVERSION_2.0,CTBVER1"
MIN_VALID_PC3_BYTES = 128
MIN_VALID_PMP_BYTES = 128
MIN_VALID_CTB_BYTES = 512


def is_valid_pc3_bytes(data: bytes, *, min_valid_bytes: int = MIN_VALID_PC3_BYTES) -> bool:
    return len(data) >= min_valid_bytes and data.startswith(PC3_HEADER_PREFIX)


def is_valid_pmp_bytes(data: bytes, *, min_valid_bytes: int = MIN_VALID_PMP_BYTES) -> bool:
    # AutoCAD PMP files use the same PIA/PC3 envelope as PC3 files.
    return len(data) >= min_valid_bytes and data.startswith(PC3_HEADER_PREFIX)


def is_valid_ctb_bytes(data: bytes, *, min_valid_bytes: int = MIN_VALID_CTB_BYTES) -> bool:
    return len(data) >= min_valid_bytes and data.startswith(CTB_HEADER_PREFIX)


def is_valid_pc3_file(path: Path, *, min_valid_bytes: int = MIN_VALID_PC3_BYTES) -> bool:
    try:
        return is_valid_pc3_bytes(Path(path).read_bytes(), min_valid_bytes=min_valid_bytes)
    except OSError:
        return False


def is_valid_pmp_file(path: Path, *, min_valid_bytes: int = MIN_VALID_PMP_BYTES) -> bool:
    try:
        return is_valid_pmp_bytes(Path(path).read_bytes(), min_valid_bytes=min_valid_bytes)
    except OSError:
        return False


def is_valid_ctb_file(path: Path, *, min_valid_bytes: int = MIN_VALID_CTB_BYTES) -> bool:
    try:
        return is_valid_ctb_bytes(Path(path).read_bytes(), min_valid_bytes=min_valid_bytes)
    except OSError:
        return False
