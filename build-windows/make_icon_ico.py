"""Generate icon.ico for the Windows build.

Runs make_icon.py first if icon_1024.png isn't there, then writes a
multi-resolution .ico. Windows picks the size it needs -- 16px in the title
bar, 32px in the taskbar, 256px in large-icon views -- so all of them have
to be inside the one file. A single-size .ico looks blurry or is silently
ignored at the sizes it lacks.
"""
import os
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "icon_1024.png")
TARGET = os.path.join(HERE, "icon.ico")

# Every size Windows asks for across its various shell contexts.
SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
         (48, 48), (64, 64), (96, 96), (128, 128), (256, 256)]

if not os.path.exists(SOURCE):
    subprocess.run([sys.executable, os.path.join(HERE, "make_icon.py")], check=True)

img = Image.open(SOURCE).convert("RGBA")
# Pillow downsamples for each requested size itself, but doing it explicitly
# with LANCZOS gives noticeably cleaner small sizes than its default.
frames = [img.resize(s, Image.LANCZOS) for s in SIZES]
frames[-1].save(TARGET, format="ICO", sizes=SIZES, append_images=frames[:-1])
print("wrote", TARGET, "%.1f KB" % (os.path.getsize(TARGET) / 1024))
