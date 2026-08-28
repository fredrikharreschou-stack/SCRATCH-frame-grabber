Building the macOS .app / .dmg
==============================

Requires a framework build of Python (python.org installer). 3.12 is the
safe choice -- it ships Tk 8.6. Avoid 3.14 for now: it pairs with Tk 9.0,
which CustomTkinter and PyInstaller are both least tested against.

    python3.12 -m venv venv
    ./venv/bin/python -m pip install customtkinter Pillow pyinstaller \
        "git+https://github.com/Assimilate-Inc/Assimilate-REST.git"

    ./venv/bin/python make_icon.py          # writes icon_1024.png / icon_512.png
    mkdir icon.iconset                      # 16/32/128/256/512 at @1x and @2x
    iconutil -c icns icon.iconset -o icon.icns

    ./venv/bin/python -m PyInstaller --noconfirm --clean FrameGrabber.spec
    codesign --force --deep --sign - "dist/SCRATCH Frame Grabber.app"

Then stage the .app plus a symlink to /Applications in a folder and:

    hdiutil create -volname "SCRATCH Frame Grabber" -srcfolder <folder> \
        -ov -format UDZO "SCRATCH Frame Grabber.dmg"

Notes
  - The spec collects customtkinter's data files (themes/fonts/icons) and
    bundles assimilate_logo.png. Without the collect step the app builds
    fine but dies at launch on a missing theme JSON.
  - assimilate_logo.png needs to sit next to the spec at build time. Any
    copy of the Assimilate logo will do; it is only the header image.
  - The build is arm64. For Intel or universal2 every wheel in the venv
    has to be universal2 too.
  - Ad-hoc signing (sign -) is enough to run locally. Distributing to
    other machines without an Apple Developer ID means each recipient
    hits Gatekeeper and must right-click - Open once. A locally built
    copy carries no quarantine flag and opens normally.

Testing without chasing ghosts
  SCRATCH writes the stills itself, so a failed render reports as
  "409 Can not create file" even when the real cause is offline media.
  Check that the shot's .file path exists before hunting for a
  permissions or output-folder problem. This cost us an hour once.
