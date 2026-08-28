# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

APP_NAME = "SCRATCH Frame Grabber"
VERSION  = "1.4.3"

datas  = collect_data_files("customtkinter")       # themes + fonts live inside the package
datas += [("assimilate_logo.png", "."), ("icon_512.png", ".")]

hiddenimports  = collect_submodules("customtkinter")
hiddenimports += ["darkdetect", "PIL", "PIL._tkinter_finder", "assimilate_client"]

a = Analysis(
    ["scratch_frame_grabber.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "pytest", "setuptools", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SCRATCH Frame Grabber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # GUI app -- no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,              # native arm64
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.icns",
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="SCRATCH Frame Grabber",
)

app = BUNDLE(
    coll,
    name=APP_NAME + ".app",
    icon="icon.icns",
    bundle_identifier="com.assimilate.scratchframegrabber",
    version=VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.video",
        "NSHumanReadableCopyright": "Frame grabber for Assimilate SCRATCH.",
        # SCRATCH's REST API is plain http on localhost
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        "NSDesktopFolderUsageDescription":
            "Frame Grabber saves the stills it exports to the folder you choose.",
        "NSDocumentsFolderUsageDescription":
            "Frame Grabber saves the stills it exports to the folder you choose.",
        "NSDownloadsFolderUsageDescription":
            "Frame Grabber saves the stills it exports to the folder you choose.",
        "NSRemovableVolumesUsageDescription":
            "Frame Grabber can save stills to an external drive you choose.",
        "NSNetworkVolumesUsageDescription":
            "Frame Grabber can save stills to a network volume you choose.",
    },
)
