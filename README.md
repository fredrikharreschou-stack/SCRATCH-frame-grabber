# SCRATCH Frame Grabber

A small desktop app for grabbing reference stills out of Assimilate SCRATCH,
built with [customtkinter](https://github.com/TomSchimansky/CustomTkinter)
for a modern, dark/light-aware UI. Cross-platform: Windows and macOS.

## What it does

- Grabs one frame (first or middle) from every shot in the timeline
  currently open in SCRATCH — or from a whole group, or a whole project.
- Filenames follow SCRATCH's own `#flag` naming syntax (`#reelid`, `#scene`,
  `#take`, `#name`, `#tc`, `#frame`, `#project`, `#construct`, ...), typed
  into the naming pattern box or picked from a dropdown.
- Grabs at proxy resolution, full source resolution, or a custom width.
- Optional: skip clips shorter than N frames, keep only the last take of
  each scene, number files in shot order.
- Writes an HTML gallery of everything it exported.
- Settings are remembered between runs.

## Requirements

- Assimilate SCRATCH, with the REST API enabled (System Settings) and
  running on its default port (8080).
- Python 3.9+.
- ```
  pip install customtkinter pillow "git+https://github.com/Assimilate-Inc/Assimilate-REST.git"
  ```
  (Windows: use `py -m pip install ...` instead of `pip install ...`.)

## Running it

From the folder you cloned this into:

```
python scratch_frame_grabber.py   # macOS/Linux
py scratch_frame_grabber.py       # Windows
```

Open SCRATCH, open the project/timeline you want frames from, then run the
grabber and pick an output folder.

Optional one-time step: run `make_app_icon.py` to (re)generate `icon.ico`
(and `icon.icns` for macOS) from the Assimilate logo. A ready-made
`icon.ico` is already included, so this is only needed if you want to
regenerate it.

## Building a standalone app

- **macOS**: see `build-macos/README-build.txt` for the full PyInstaller
  `.app`/`.dmg` build process.
- **Windows**: `build-windows/SCRATCH-Frame-Grabber.spec` is a PyInstaller
  spec — from a venv with the requirements above plus `pyinstaller`
  installed, run:
  ```
  pyinstaller --noconfirm --clean build-windows/SCRATCH-Frame-Grabber.spec
  ```

## History

See [`CHANGELOG.md`](CHANGELOG.md).

## License

MIT — see [`LICENSE`](LICENSE).
