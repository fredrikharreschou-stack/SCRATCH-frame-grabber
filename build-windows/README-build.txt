Building the Windows .exe
=========================

WRITTEN ON macOS, NOT TESTED ON WINDOWS. The spec mirrors the macOS one,
which is known good, minus the macOS-only BUNDLE step and with the icon
swapped for .ico. Expect it to need a nudge rather than to be perfect.

You almost certainly have your own Windows build already; the parts of
this worth stealing are the two marked (!) below, which are what this
source needs regardless of how you package it.

Setup
-----
Python 3.12 from python.org. Avoid 3.14 for now: it pairs with Tk 9.0,
which CustomTkinter and PyInstaller are both least tested against. On
macOS that combination was the difference between a working build and a
broken one, and there is no reason to expect Windows to differ.

    py -3.12 -m venv venv
    venv\Scripts\python -m pip install customtkinter Pillow pyinstaller ^
        "git+https://github.com/Assimilate-Inc/Assimilate-REST.git"

Icon
----
    venv\Scripts\python make_icon_ico.py

icon.ico is already in this folder, so you can skip that unless you want
to regenerate it. It carries ten sizes (16 through 256) because Windows
picks a different one for the title bar, the taskbar and large-icon
views; a single-size .ico looks blurry or is ignored at the sizes it
lacks.

Build
-----
    venv\Scripts\python -m PyInstaller --noconfirm --clean FrameGrabber-win.spec

Result: dist\SCRATCH Frame Grabber\ -- the .exe plus its dependencies.
For one self-contained .exe, see the comment at the bottom of the spec.
One-file starts slower because it unpacks to a temp folder each launch.

The two that actually matter
----------------------------
(!) collect_data_files("customtkinter")
    CustomTkinter loads themes, fonts and icons from data files at
    runtime. Without this the build succeeds and the app dies at launch
    on a missing theme JSON. This is the single easiest thing to get
    wrong.

(!) icon.ico bundled as a DATA file, not just passed to EXE(icon=...)
    It is needed twice. EXE(icon=) brands the executable in Explorer;
    the data copy is what _setup_window_icon() finds through
    resource_path() to set the Tk window icon at runtime. Ship only the
    first and the window keeps Tk's default feather.

Also worth knowing
------------------
- assimilate_logo.png must sit beside the spec at build time. Any copy of
  the Assimilate logo will do; it is only the header image. It is bundled
  so the header still draws on a machine with no internet -- on macOS the
  HTTPS fetch fails outright on a stock Python install because the
  framework builds ship no certificate store.

- Settings land in %APPDATA%\SCRATCH Frame Grabber\ once frozen, and stay
  beside the script when run from source. That branch is in settings_dir().
  It was checked by simulating a frozen Windows environment on macOS --
  os.name "nt" and a fake sys._MEIPASS -- and resolved correctly, but it
  has not been run on real Windows.

- UPX is off deliberately. Compressed executables trip antivirus
  heuristics, and a false positive on a tool people run on set is not
  worth the few megabytes.

- If you want version info in the .exe properties, PyInstaller takes a
  version resource file via EXE(version="file_version_info.txt"). Not
  included here since an untested one is worse than none.
