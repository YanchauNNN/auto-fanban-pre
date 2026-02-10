# -*- coding: utf-8 -*-
"""快捷入口：测试 2016仿真图"""
import subprocess
import sys
from pathlib import Path

project = Path(__file__).resolve().parent.parent
dxf = project / "test" / "dwg" / "_dxf_out" / "2016仿真图.dxf"
sys.exit(subprocess.call([sys.executable, "tools/run_module5_test.py", str(dxf)], cwd=str(project)))
