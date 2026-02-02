"""
DEPRECATED: 已合并到 tools/anchor_calibration_tool.py。

等价用法：
  python tools/anchor_calibration_tool.py verify <原参数...>
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    tool = Path(__file__).with_name("anchor_calibration_tool.py")
    cmd = [sys.executable, str(tool), "verify", *sys.argv[1:]]
    print("[DEPRECATED] 请改用: python tools/anchor_calibration_tool.py verify ...")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
