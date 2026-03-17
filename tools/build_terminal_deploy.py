from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from shutil import which


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.deploy import build_terminal_deploy_package, ensure_prereq_installers


def _resolve_optional_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.exists() else None


def _run_frontend_build(repo_root: Path) -> None:
    frontend_dir = repo_root / "frontend"
    npm = which("npm") or which("npm.cmd")
    if npm is None:
        raise FileNotFoundError("??? npm ? npm.cmd??????????")
    subprocess.run([npm, "run", "build"], cwd=frontend_dir, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="?????????")
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "build" / "fanban-terminal-deploy"),
        help="???????",
    )
    parser.add_argument(
        "--skip-frontend-build",
        action="store_true",
        help="?? frontend/dist ???????????",
    )
    parser.add_argument(
        "--dotnet-installer",
        default=os.environ.get("FANBAN_DOTNET48_INSTALLER", ""),
        help="???.NET Framework 4.8 ???????",
    )
    parser.add_argument(
        "--vc-redist-installer",
        default=os.environ.get("FANBAN_VCREDIST_INSTALLER", ""),
        help="???VC++ 2015-2022 x64 ???????",
    )
    args = parser.parse_args()

    if not args.skip_frontend_build:
        _run_frontend_build(REPO_ROOT)

    output_root = Path(args.output_root).resolve()
    installers_root = output_root.parent / "_downloads"
    dotnet_installer, vc_redist_installer = ensure_prereq_installers(
        download_root=installers_root,
        dotnet_installer=_resolve_optional_path(args.dotnet_installer),
        vc_redist_installer=_resolve_optional_path(args.vc_redist_installer),
    )
    build_terminal_deploy_package(
        repo_root=REPO_ROOT,
        output_root=output_root,
        dotnet_installer=dotnet_installer,
        vc_redist_installer=vc_redist_installer,
    )
    print(output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
