from __future__ import annotations

from pathlib import Path
from shutil import which
from subprocess import run
from typing import Callable
from urllib.request import urlopen


DOTNET48_URL = "https://go.microsoft.com/fwlink/?linkid=2088631"
VC_REDIST_X64_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

DOTNET48_FILENAME = "ndp48-x86-x64-allos-enu.exe"
VC_REDIST_X64_FILENAME = "VC_redist.x64.exe"

Downloader = Callable[[str, Path], Path]


def download_file(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(url) as response, destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        return destination
    except Exception:
        curl = which("curl.exe") or which("curl")
        if curl is None:
            raise
        run([curl, "-L", url, "-o", str(destination)], check=True)
        return destination


def ensure_prereq_installers(
    *,
    download_root: Path,
    dotnet_installer: Path | None = None,
    vc_redist_installer: Path | None = None,
    downloader: Downloader = download_file,
) -> tuple[Path | None, Path | None]:
    dotnet = _resolve_or_download(
        explicit_path=dotnet_installer,
        download_root=download_root / "dotnet",
        filename=DOTNET48_FILENAME,
        url=DOTNET48_URL,
        downloader=downloader,
    )
    vc_redist = _resolve_or_download(
        explicit_path=vc_redist_installer,
        download_root=download_root / "vc_redist",
        filename=VC_REDIST_X64_FILENAME,
        url=VC_REDIST_X64_URL,
        downloader=downloader,
    )
    return dotnet, vc_redist


def _resolve_or_download(
    *,
    explicit_path: Path | None,
    download_root: Path,
    filename: str,
    url: str,
    downloader: Downloader,
) -> Path | None:
    if explicit_path is not None:
        return explicit_path if explicit_path.exists() else None

    target = download_root / filename
    if target.exists():
        return target

    return downloader(url, target)
