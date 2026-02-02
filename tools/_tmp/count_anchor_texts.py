from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import ezdxf  # type: ignore
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def normalize(text: str) -> str:
    return "".join(ch for ch in (text or "") if not ch.isspace())


def match_any(text: str, patterns: list[str]) -> bool:
    normalized = normalize(text)
    for pattern in patterns:
        if not pattern:
            continue
        if pattern.isascii():
            if pattern.upper() in normalized.upper():
                return True
        else:
            if pattern in text:
                return True
    return False


def short(text: str, n: int = 60) -> str:
    if len(text) <= n:
        return text
    return text[:n] + "..."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dxf", required=True, help="DXF path")
    ap.add_argument("--spec", default=str(REPO_ROOT / "documents" / "参数规范.yaml"))
    args = ap.parse_args()

    sys.path.insert(0, str(REPO_ROOT / "backend"))
    anchor_module = importlib.import_module("src.cad.detection.anchor_first_locator")
    AnchorFirstLocator = anchor_module.AnchorFirstLocator

    spec = yaml.safe_load(Path(args.spec).read_text(encoding="utf-8")) or {}
    anchor_cfg = (spec.get("titleblock_extract") or {}).get("anchor", {})
    texts = anchor_cfg.get("search_text", [])
    if isinstance(texts, str):
        texts = [texts]
    primary = anchor_cfg.get("primary_text")
    if primary:
        texts = [primary, *texts]
    patterns = [t for t in texts if t]

    dxf_path = Path(args.dxf)
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    items = list(AnchorFirstLocator._iter_text_items(msp))
    matches = [it for it in items if match_any(it.text or "", patterns)]

    print("patterns", len(patterns))
    print("text_items", len(items))
    print("anchor_matches", len(matches))
    uniq_texts = sorted({(it.text or "") for it in matches})
    print("unique_texts", len(uniq_texts))
    print("sample_texts", [short(t) for t in uniq_texts[:3]])
    for i, it in enumerate(matches[:5]):
        print(
            f"match[{i}] x={it.x:.3f} y={it.y:.3f} source={it.source} text={short(it.text or '')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
