from __future__ import annotations

from ..models import FrameMeta

ANCHOR_INVALID_FLAG = "未命中锚点文本"


def split_anchor_valid_frames(frames: list[FrameMeta]) -> tuple[list[FrameMeta], list[FrameMeta]]:
    """Split frames into effective frames and anchor-invalid frames.

    Frames that failed anchor validation must not continue into split/export/doc stages.
    A4 slave pages are not affected because they do not carry the anchor-invalid flag.
    """

    effective: list[FrameMeta] = []
    excluded: list[FrameMeta] = []
    for frame in frames:
        if ANCHOR_INVALID_FLAG in frame.runtime.flags:
            excluded.append(frame)
            continue
        effective.append(frame)
    return effective, excluded
