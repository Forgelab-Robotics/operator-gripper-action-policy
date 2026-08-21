# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


PROJECT_DIR = Path(SPEC).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
datas = []
binaries = []
hiddenimports = ["pyarrow"]

for package in ("dora", "forge_tool", "forge_msgs"):
    package_datas, package_binaries, package_hiddenimports = collect_all(
        package,
        include_py_files=True,
    )
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)

analysis = Analysis(
    [str(PROJECT_DIR / "scripts" / "gripper_action_policy_entry.py")],
    pathex=[str(SRC_DIR)],
    binaries=list(dict.fromkeys(binaries)),
    datas=list(dict.fromkeys(datas)),
    hiddenimports=list(dict.fromkeys(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="gripper_action_policy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
