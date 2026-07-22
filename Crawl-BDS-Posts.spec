# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


PROJECT_DIR = Path(globals().get("SPECPATH", Path.cwd())).resolve()

LOCAL_PACKAGES = (
    "controllers",
    "integrations",
    "models",
    "services",
    "utils",
    "workers",
)

LOCAL_DATA_DIRS = (
    "controllers",
    "integrations",
    "models",
    "resources",
    "services",
    "utils",
    "workers",
)

EXTRA_HIDDEN_IMPORTS = (
    "openpyxl",
    "PyQt5.sip",
    "playwright",
    "playwright.sync_api",
    "playwright._impl.__pyinstaller",
    "requests",
    "resources.ui.gui",
    "sqlite3",
)


def add_data_tree(source_dir: Path, target_dir: str) -> list[tuple[str, str]]:
    data_files = []
    if not source_dir.exists():
        return data_files

    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue

        relative_parent = path.relative_to(source_dir).parent
        destination = Path(target_dir) / relative_parent
        data_files.append((str(path), str(destination)))

    return data_files


datas = []
for data_dir in LOCAL_DATA_DIRS:
    datas += add_data_tree(PROJECT_DIR / data_dir, data_dir)

for file_name in (
    "app_config.py",
    "comment_AI.txt",
    "comment_san.txt",
    "tim_tro.txt",
    "tele.json",
):
    file_path = PROJECT_DIR / file_name
    if file_path.exists():
        datas.append((str(file_path), "."))

hiddenimports = list(EXTRA_HIDDEN_IMPORTS)
for package in LOCAL_PACKAGES:
    hiddenimports += collect_submodules(package)

hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Crawl-BDS-Posts",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(PROJECT_DIR / "icon.ico")],
)
