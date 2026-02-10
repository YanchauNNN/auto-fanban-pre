# -*- coding: utf-8 -*-
"""诊断 entity bbox 检测问题"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import ezdxf
from ezdxf import bbox as ezdxf_bbox

DXF = Path(__file__).resolve().parent.parent / "test" / "dwg" / "_dxf_out" / "1818仿真图.dxf"
doc = ezdxf.readfile(str(DXF))
msp = doc.modelspace()
entities = list(msp)
print(f"Total entities in modelspace: {len(entities)}")

# Entity types
types = Counter(e.dxftype() for e in entities)
for t, c in types.most_common():
    print(f"  {t}: {c}")

# Test old method: hasattr(entity, "bbox")
old_has = 0
old_none = 0
for e in entities:
    if hasattr(e, "bbox"):
        try:
            eb = e.bbox()
            if eb:
                old_has += 1
            else:
                old_none += 1
        except Exception:
            old_none += 1
    else:
        old_none += 1
print(f"\nOld method: has_bbox={old_has}, no_bbox={old_none}")

# Test new method: ezdxf.bbox.extents
cache = ezdxf_bbox.Cache()
new_has = 0
new_none = 0
for e in entities:
    try:
        ext = ezdxf_bbox.extents([e], cache=cache)
        if ext.has_data:
            new_has += 1
        else:
            new_none += 1
    except Exception:
        new_none += 1
print(f"New method: has_bbox={new_has}, no_bbox={new_none}")

# Show a few bboxes to confirm they're correct
print("\nSample bboxes (first 5 with data):")
cache2 = ezdxf_bbox.Cache()
shown = 0
for e in entities:
    if shown >= 5:
        break
    try:
        ext = ezdxf_bbox.extents([e], cache=cache2)
        if ext.has_data:
            print(f"  {e.dxftype()}: ({ext.extmin.x:.1f}, {ext.extmin.y:.1f}) -> ({ext.extmax.x:.1f}, {ext.extmax.y:.1f})")
            shown += 1
    except Exception:
        pass

# Also check: what percentage of entities would be filtered by a specific bbox
from src.models import BBox
# Use the first detected frame's bbox as test
from src.cad import FrameDetector
detector = FrameDetector()
frames = detector.detect_frames(DXF)
if frames:
    f0 = frames[0]
    ob = f0.runtime.outer_bbox
    print(f"\nTest clip_bbox (frame 0): ({ob.xmin:.0f}, {ob.ymin:.0f}) -> ({ob.xmax:.0f}, {ob.ymax:.0f})")
    margin = 0.015
    clip = BBox(
        xmin=ob.xmin - ob.width * margin,
        ymin=ob.ymin - ob.height * margin,
        xmax=ob.xmax + ob.width * margin,
        ymax=ob.ymax + ob.height * margin,
    )
    kept = 0
    filtered = 0
    no_data = 0
    cache3 = ezdxf_bbox.Cache()
    for e in entities:
        try:
            ext = ezdxf_bbox.extents([e], cache=cache3)
            if ext.has_data:
                eb = BBox(xmin=ext.extmin.x, ymin=ext.extmin.y,
                          xmax=ext.extmax.x, ymax=ext.extmax.y)
                if clip.intersects(eb):
                    kept += 1
                else:
                    filtered += 1
            else:
                no_data += 1
                kept += 1  # conservative: keep unknown
        except Exception:
            no_data += 1
            kept += 1
    print(f"  With new bbox: kept={kept}, filtered={filtered}, no_data={no_data}")
    print(f"  Filter rate: {filtered}/{len(entities)} = {filtered/len(entities)*100:.1f}%")
