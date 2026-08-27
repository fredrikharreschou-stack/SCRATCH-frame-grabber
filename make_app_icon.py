"""
make_app_icon.py
------------------
One-time helper: downloads the Assimilate logo and turns it into both
icon.ico (Windows -- window/taskbar icon, and the packaged .exe's file
icon) and icon.icns (macOS -- the packaged .app's Dock/Finder icon).
Both are written every time you run this, so it works the same way on
either platform.

Run this ONCE, from the same folder as scratch_frame_grabber.py:
    macOS / Linux:  python3 make_app_icon.py
    Windows:        py make_app_icon.py

Needs Pillow, which you should already have installed from the
custom-width step. If not:
    macOS / Linux:  pip3 install Pillow
    Windows:        py -m pip install Pillow
"""

import io
import os
import urllib.request

from PIL import Image

LOGO_URL = "https://www.assimilateinc.com/wp-content/uploads/2015/07/assimilate-logo2a.png"
FOLDER = os.path.dirname(os.path.abspath(__file__))
ICO_PATH = os.path.join(FOLDER, "icon.ico")
ICNS_PATH = os.path.join(FOLDER, "icon.icns")


def main():
    print("Downloading logo...")
    with urllib.request.urlopen(LOGO_URL, timeout=10) as resp:
        data = resp.read()

    logo = Image.open(io.BytesIO(data)).convert("RGBA")

    # Pad the logo onto a square, transparent canvas so nothing gets
    # cropped no matter how wide or tall the source logo is, and so it
    # sits naturally on both light and dark taskbars/docks.
    side = int(max(logo.width, logo.height) * 1.15)  # a little breathing room
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    offset = ((side - logo.width) // 2, (side - logo.height) // 2)
    canvas.paste(logo, offset, logo)

    canvas.save(
        ICO_PATH,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Saved {ICO_PATH}  (for the Windows build)")

    try:
        canvas.save(ICNS_PATH, format="ICNS")
        print(f"Saved {ICNS_PATH}  (for the macOS build)")
    except Exception as e:
        print(f"Couldn't write {ICNS_PATH} -- macOS build will just skip a custom icon. Details: {e}")


if __name__ == "__main__":
    main()
