from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from subprocess import run
from urllib.request import urlopen

DOTNET48_URL = "https://go.microsoft.com/fwlink/?linkid=2088631"
VC_REDIST_X64_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
PYTHON_313_X64_URL = "https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip"
URL_REWRITE_X64_URL = (
    "https://download.microsoft.com/download/1/2/8/"
    "128E2E22-C1B9-44A4-BE2A-5859ED1D4592/rewrite_amd64_zh-CN.msi"
)
ARR_X64_URL = "https://go.microsoft.com/fwlink/?LinkID=615136"

DOTNET48_FILENAME = "ndp48-x86-x64-allos-enu.exe"
VC_REDIST_X64_FILENAME = "VC_redist.x64.exe"
PYTHON_313_X64_FILENAME = "python-3.13.12-embed-amd64.zip"
URL_REWRITE_X64_FILENAME = "rewrite_amd64_zh-CN.msi"
ARR_X64_FILENAME = "requestRouter_amd64.msi"

Downloader = Callable[[str, Path], Path]


@dataclass(frozen=True)
class PrereqInstallerBundle:
    dotnet: Path | None
    vc_redist: Path | None
    python: Path | None
    url_rewrite: Path | None
    arr: Path | None


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
    python_installer: Path | None = None,
    url_rewrite_installer: Path | None = None,
    arr_installer: Path | None = None,
    downloader: Downloader = download_file,
) -> PrereqInstallerBundle:
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
    python = _resolve_or_download(
        explicit_path=python_installer,
        download_root=download_root / "python",
        filename=PYTHON_313_X64_FILENAME,
        url=PYTHON_313_X64_URL,
        downloader=downloader,
    )
    url_rewrite = _resolve_or_download(
        explicit_path=url_rewrite_installer,
        download_root=download_root / "iis" / "url_rewrite",
        filename=URL_REWRITE_X64_FILENAME,
        url=URL_REWRITE_X64_URL,
        downloader=downloader,
    )
    arr = _resolve_or_download(
        explicit_path=arr_installer,
        download_root=download_root / "iis" / "arr",
        filename=ARR_X64_FILENAME,
        url=ARR_X64_URL,
        downloader=downloader,
    )
    return PrereqInstallerBundle(
        dotnet=dotnet,
        vc_redist=vc_redist,
        python=python,
        url_rewrite=url_rewrite,
        arr=arr,
    )


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
