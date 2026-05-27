from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from subprocess import run
from urllib.request import urlopen

from ..config import load_mechanism_spec

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
    installers_cfg = load_mechanism_spec().deployment_mechanism.installers
    dotnet = _resolve_or_download(
        explicit_path=dotnet_installer,
        download_root=download_root / "dotnet",
        filename=_installer_value(installers_cfg, "dotnet48").filename,
        url=_installer_value(installers_cfg, "dotnet48").url,
        downloader=downloader,
    )
    vc_redist = _resolve_or_download(
        explicit_path=vc_redist_installer,
        download_root=download_root / "vc_redist",
        filename=_installer_value(installers_cfg, "vc_redist_x64").filename,
        url=_installer_value(installers_cfg, "vc_redist_x64").url,
        downloader=downloader,
    )
    python = _resolve_or_download(
        explicit_path=python_installer,
        download_root=download_root / "python",
        filename=_installer_value(installers_cfg, "python_313_x64").filename,
        url=_installer_value(installers_cfg, "python_313_x64").url,
        downloader=downloader,
    )
    url_rewrite = _resolve_or_download(
        explicit_path=url_rewrite_installer,
        download_root=download_root / "iis" / "url_rewrite",
        filename=_installer_value(installers_cfg, "url_rewrite_x64").filename,
        url=_installer_value(installers_cfg, "url_rewrite_x64").url,
        downloader=downloader,
    )
    arr = _resolve_or_download(
        explicit_path=arr_installer,
        download_root=download_root / "iis" / "arr",
        filename=_installer_value(installers_cfg, "arr_x64").filename,
        url=_installer_value(installers_cfg, "arr_x64").url,
        downloader=downloader,
    )
    return PrereqInstallerBundle(
        dotnet=dotnet,
        vc_redist=vc_redist,
        python=python,
        url_rewrite=url_rewrite,
        arr=arr,
    )


def _installer_value(installers: dict, key: str):
    try:
        return installers[key]
    except KeyError as exc:
        raise KeyError(f"参数规范-3.yaml 缺少 deployment_mechanism.installers.{key}") from exc


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
