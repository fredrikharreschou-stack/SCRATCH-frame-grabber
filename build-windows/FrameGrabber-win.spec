# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the Windows build of SCRATCH Frame Grabber.
#
# NOTE: written on macOS and NOT tested on Windows. It mirrors the macOS
# spec, which is known good, minus the BUNDLE step (macOS-only) and with
# the icon swapped for .ico. Treat it as a starting point rather than a
# guarantee.
#
#     py -3.12 -m PyInstaller --noconfirm --clean FrameGrabber-win.spec
#
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

APP_NAME = "SCRATCH Frame Grabber"
VERSION  = "1.4.6"

# customtkinter loads its themes, fonts and icons from data files at runtime.
# Without this the app builds fine and then dies at launch on a missing
# theme JSON -- the single easiest thing to get wrong here.
datas  = collect_data_files("customtkinter")
datas += [("assimilate_logo.png", ".")]

# icon.ico is needed TWICE: once by EXE(icon=...) to brand the executable,
# and once as a bundled data file, because _setup_window_icon() looks it up
# at runtime through resource_path() to set the Tk window icon. Ship both or
# the window keeps Tk's default feather.
datas += [("icon.ico", ".")]

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
    excludes=["matplotlib", "pandas", "pytest", "setuptools", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX and antivirus heuristics are a bad mix
    console=False,        # GUI app -- no console window behind it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

# No BUNDLE() here: that step builds a macOS .app and does nothing on Windows.
# The result is dist/SCRATCH Frame Grabber/ containing the .exe plus its
# dependencies. For a single self-contained .exe instead, delete COLLECT and
# pass a.binaries + a.datas straight to EXE with exclude_binaries=False --
# slower to start, since it unpacks to a temp folder each launch.
