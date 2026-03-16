from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..cad import A4MultipageGrouper, FrameDetector, ODAConverter, TitleblockExtractor
from ..models import FrameMeta, SheetSet


@dataclass(frozen=True, slots=True)
class SharedPrepArtifacts:
    shared_dir: Path
    source_input_dwg: Path
    source_converted_dxf: Path
    frames: list[FrameMeta]
    sheet_sets: list[SheetSet]


class SharedPrepService:
    def __init__(self) -> None:
        self.oda = ODAConverter()
        self.frame_detector = FrameDetector()
        self.titleblock_extractor = TitleblockExtractor()
        self.a4_grouper = A4MultipageGrouper()

    def prepare(self, *, group_id: str, source_dwg: Path, shared_dir: Path) -> SharedPrepArtifacts:
        source_dwg = source_dwg.resolve()
        shared_dir = shared_dir.resolve()
        shared_dir.mkdir(parents=True, exist_ok=True)

        staged_source = shared_dir / f"source_input{source_dwg.suffix or '.dwg'}"
        if staged_source.resolve() != source_dwg:
            shutil.copy2(source_dwg, staged_source)
        else:
            staged_source = source_dwg

        dxf_path = self.oda.dwg_to_dxf(staged_source, shared_dir)
        frames = self.frame_detector.detect_frames(dxf_path)
        for frame in frames:
            frame.runtime.cad_source_file = staged_source
            self.titleblock_extractor.extract_fields(dxf_path, frame)
        frames, sheet_sets = self.a4_grouper.group_a4_pages(frames)

        self._write_json(shared_dir / "frames.json", [frame.model_dump(mode="json") for frame in frames])
        self._write_json(
            shared_dir / "sheet_sets.json",
            [sheet_set.model_dump(mode="json") for sheet_set in sheet_sets],
        )
        self._write_json(
            shared_dir / "titleblock_extracts.json",
            [
                {
                    "frame_id": frame.frame_id,
                    "titleblock": frame.titleblock.model_dump(mode="json"),
                    "raw_extracts": frame.raw_extracts,
                }
                for frame in frames
            ],
        )
        self._write_json(
            shared_dir / "audit_roi_context.json",
            {
                "group_id": group_id,
                "frames_total": len(frames),
                "sheet_sets_total": len(sheet_sets),
                "source_input_dwg": str(staged_source),
                "source_converted_dxf": str(dxf_path),
            },
        )
        self._write_json(
            shared_dir / "prep_summary.json",
            {
                "group_id": group_id,
                "source_input_dwg": str(staged_source),
                "source_converted_dxf": str(dxf_path),
                "frames_total": len(frames),
                "sheet_sets_total": len(sheet_sets),
            },
        )
        return SharedPrepArtifacts(
            shared_dir=shared_dir,
            source_input_dwg=staged_source,
            source_converted_dxf=dxf_path,
            frames=frames,
            sheet_sets=sheet_sets,
        )

    @staticmethod
    def load(shared_dir: Path) -> SharedPrepArtifacts:
        shared_dir = shared_dir.resolve()
        summary_path = shared_dir / "prep_summary.json"
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if summary_path.exists()
            else {}
        )
        frames_raw = json.loads((shared_dir / "frames.json").read_text(encoding="utf-8"))
        sheet_sets_raw = json.loads((shared_dir / "sheet_sets.json").read_text(encoding="utf-8"))
        source_input = summary.get("source_input_dwg")
        if not source_input:
            staged_sources = sorted(shared_dir.glob("source_input.*"))
            source_input = str(staged_sources[0]) if staged_sources else str(shared_dir / "source_converted.dxf")
        source_dxf = summary.get("source_converted_dxf") or str(shared_dir / "source_converted.dxf")
        return SharedPrepArtifacts(
            shared_dir=shared_dir,
            source_input_dwg=Path(source_input),
            source_converted_dxf=Path(source_dxf),
            frames=[FrameMeta.model_validate(item) for item in frames_raw],
            sheet_sets=[SheetSet.model_validate(item) for item in sheet_sets_raw],
        )

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
