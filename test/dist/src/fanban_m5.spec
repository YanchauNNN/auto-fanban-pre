# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


REPO_ROOT = Path.cwd().resolve()
TEST_DIST_ROOT = REPO_ROOT / "test" / "dist"
SRC_ROOT = TEST_DIST_ROOT / "src"

hiddenimports = (
    collect_submodules("src")
    + collect_submodules("ezdxf")
    + collect_submodules("pydantic")
    + collect_submodules("pydantic_settings")
    + collect_submodules("pypdf")
)

datas = [
    (str(REPO_ROOT / "documents"), "documents"),
    (str(REPO_ROOT / "bin"), "bin"),
    (str(REPO_ROOT / "backend" / "src" / "cad" / "scripts"), "backend/src/cad/scripts"),
    (
        str(
            REPO_ROOT
            / "backend"
            / "src"
            / "cad"
            / "dotnet"
            / "Module5CadBridge"
            / "bin"
            / "Release"
            / "net48"
        ),
        "backend/src/cad/dotnet/Module5CadBridge/bin/Release/net48",
    ),
    (str(TEST_DIST_ROOT / "assets"), "assets"),
]

block_cipher = None

a = Analysis(
    [str(SRC_ROOT / "fanban_m5_gui.py")],
    pathex=[str(SRC_ROOT), str(REPO_ROOT / "backend")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="fanban_m5",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="fanban_m5",
)
