import argparse
import re
from pathlib import Path


def _resolve_spec_path(p: Path) -> Path:
    if p.is_dir():
        target = p / "参数规范.yaml"
        if target.exists():
            return target
        matches = [x for x in p.glob("*.yaml") if x.name.endswith("参数规范.yaml")]
        if not matches:
            raise FileNotFoundError(
                f"Could not find 参数规范.yaml under directory: {p}"
            )
        return matches[0]
    return p


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sanity-check whether fixed-decimal rounding caused non-numeric damage."
    )
    ap.add_argument(
        "path",
        help="YAML file path OR a directory containing 参数规范.yaml (useful on Windows terminals where non-ASCII args may garble)",
    )
    ap.add_argument(
        "--bak",
        default=None,
        help="Backup file path; defaults to <path>.bak2 if exists else <path>.bak",
    )
    args = ap.parse_args()

    path = _resolve_spec_path(Path(args.path))
    if args.bak:
        bak = Path(args.bak)
    else:
        bak2 = path.with_suffix(path.suffix + ".bak2")
        bak1 = path.with_suffix(path.suffix + ".bak")
        bak = bak2 if bak2.exists() else bak1

    cur_lines = path.read_text(encoding="utf-8").splitlines()
    bak_lines = bak.read_text(encoding="utf-8").splitlines()

    # 1) Ensure all regex patterns are unchanged
    cur_patterns = [ln for ln in cur_lines if ln.lstrip().startswith("pattern:")]
    bak_patterns = [ln for ln in bak_lines if ln.lstrip().startswith("pattern:")]
    patterns_ok = cur_patterns == bak_patterns

    # 2) Ensure pipeline step numbers remain integers (no decimals)
    step_float = re.compile(r"^\s*-\s*step:\s*\d+\.\d+")
    pipeline_step_float_ok = not any(step_float.search(ln) for ln in cur_lines)

    # 3) Ensure page_info output indices remain integers
    page_output_float_ok = True
    for ln in cur_lines:
        if re.match(r"^\s*(page_total|page_index):\s*\d+\.\d+", ln):
            page_output_float_ok = False
            break

    # 4) Quick masked diff (ignore numbers) to detect unexpected structural changes
    num = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?(?![A-Za-z_])")

    def mask(s: str) -> str:
        return num.sub("<NUM>", s)

    masked_diffs = []
    for i in range(max(len(cur_lines), len(bak_lines))):
        a = cur_lines[i] if i < len(cur_lines) else ""
        b = bak_lines[i] if i < len(bak_lines) else ""
        if mask(a) != mask(b):
            masked_diffs.append(i)
            if len(masked_diffs) >= 20:
                break

    print(f"spec={path}")
    print(f"bak={bak}")
    print(f"patterns_ok={patterns_ok} (count={len(cur_patterns)})")
    print(f"pipeline_step_float_ok={pipeline_step_float_ok}")
    print(f"page_output_float_ok={page_output_float_ok}")
    print(f"masked_diff_lines_count={len(masked_diffs)} (showing up to 5)")

    if masked_diffs:
        for idx in masked_diffs[:5]:
            i = idx
            a = cur_lines[i] if i < len(cur_lines) else ""
            b = bak_lines[i] if i < len(bak_lines) else ""
            print("--- line", i + 1)
            print("cur:", a)
            print("bak:", b)

    ok = (
        patterns_ok
        and pipeline_step_float_ok
        and page_output_float_ok
        and not masked_diffs
    )
    if ok:
        print("RESULT=OK (no non-numeric damage detected)")
        return 0
    else:
        print("RESULT=WARNING (please inspect masked diffs above)")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
