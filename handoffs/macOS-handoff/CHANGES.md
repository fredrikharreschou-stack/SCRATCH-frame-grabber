# SCRATCH Frame Grabber — macOS port and fixes

`scratch_frame_grabber.py` in this folder replaces the original. It is still
a **single cross-platform file** — every change is branched on the platform
rather than swapped for a macOS-only path, so the Windows build keeps working
exactly as before. `scratch_frame_grabber.diff` is a unified diff against the
original if you'd rather review it hunk by hunk.

---

## 1. Two bugs in Assimilate's REST client (these affect Windows too)

### 1a. One odd metadata value kills an entire request

`assimilate_client`'s `ApiClient.__deserialize_primitive` coerces every field
to the type the OpenAPI spec declares, and guards only `TypeError` and
`UnicodeEncodeError`:

```python
try:
    return klass(data)
except UnicodeEncodeError:
    return six.text_type(data)
except TypeError:
    return data
```

`ValueError` escapes. The spec declares `shot.audio.roll` as a **float**, but a
sound roll is an alphanumeric ID — location recorders very often name rolls by
date. On a project with audio, `float('26Y08M22')` raises `ValueError`, and the
whole `get_construct_slots` call dies. The app reports it as "couldn't connect
to SCRATCH", so it reads as a network or REST-API problem and sends you
looking in the wrong place entirely.

Symptom: one timeline works, the next is simply unreachable. The difference is
whether the timeline has synced audio.

Fix here: a small shim installed at import that keeps the raw value when
conversion fails. It's general, so any other spec/reality mismatch degrades
gracefully instead of taking down the request. **The real fix belongs in
Assimilate's spec** — `roll` should be a string.

### 1b. `#project`, `#construct` and `#rtc` always rendered blank

Two method-name mistakes, both swallowed by bare `except Exception: pass`:

- The endpoint for the open project is `get_projects_current()` — plural. The
  original called `get_project_current()`, which doesn't exist, so every call
  raised `AttributeError` and `#project` came out empty.
- `get_constructs_current()` returns the open construct **itself**. The
  original looked for a `.constructs` list hanging off it, found none, and
  left `#construct` and `#rtc` empty.

Both now resolve. `#group` is populated too (it was assigned `""` and never
set).

---

## 2. macOS packaging changes

- **Settings location.** The original writes its JSON next to the script,
  which is inside the read-only `.app` once bundled. Settings now go to the
  platform's per-user config dir — `~/Library/Application Support/…` on macOS,
  `%APPDATA%\…` on Windows, `$XDG_CONFIG_HOME` on Linux — and only when
  frozen. Running from source keeps the original side-by-side behavior. An
  existing side-by-side settings file is migrated once.
- **Icon.** `iconbitmap()` can't load `.icns`, so the original's `icon.ico`
  path silently no-ops on macOS. Now branched: `.ico` via `iconbitmap` on
  Windows, `.png` via `iconphoto` on Linux, and on macOS nothing — the Dock
  icon comes from the bundle's `Info.plist`.
- **`resource_path()`** resolves `sys._MEIPASS` when frozen.
- **Bundled logo.** python.org's framework builds ship without a populated
  certificate store, so the header logo's HTTPS fetch fails with
  `CERTIFICATE_VERIFY_FAILED` on a stock macOS install. `assimilate_logo.png`
  is now bundled and preferred, with the network fetch as fallback.

## 3. Behavior changes

- **Timecode in filenames** renders as unbroken digits (`11390810`). A colon
  can't appear in a filename, so the sanitizer was turning `11:39:08:10` into
  `11_39_08_10`. Drop-frame `;` and `.` are stripped too. Same for `#rtc`.
- **Skip clips shorter than N frames** (default 200, editable). Drops false
  starts, camera tests and single-frame stills. Measures the clip's timeline
  length, which matches the trimmed handle span.
- **Last take of each scene only.** Scene letters count as their own scene, so
  46 and 46A each keep a take. Ranking is numeric, so take `10` beats `9`.
  Shots with no scene or take are kept. Runs *after* the length filter, so a
  scene whose final take is a false start falls back to the last usable take
  rather than dropping out.
- **Grab this group / Grab whole project**, alongside the original open-timeline
  button. The project walk skips groups whose names don't match the majority
  name-shape of the others (a "Stills" group next to `SHOW_08_22_2026_DAY_04`
  and friends). It fails open below three groups or with no clear majority. A
  group chosen explicitly is never skipped for its name.
- **Output layout** for group and project runs: one folder per group, with
  filename numbering running on across that group's timelines. Each group gets
  its own `gallery.html`; a whole-project run also writes one at the top. A
  single-group run deliberately does not overwrite the project-wide gallery.
- **Numbering is now optional** ("Number files in shot order"). With it off,
  each shot maps to a stable filename, so re-grabbing a day overwrites in
  place. With it on, a shot that shifts position is rewritten under a new
  number and the old file is orphaned — re-grabbing one day after a threshold
  change left 60 files on disk where 32 belonged.
- **Collision guard.** Several timelines now share a folder, so a filename
  already claimed *within the same run* gets " 2" appended rather than
  silently overwriting. Files from an earlier run are not counted, which is
  what lets a re-grab refresh cleanly.
- **Error messages** distinguish a parse failure from a connection failure.

## 4. Building for macOS

See `build-macos/`. The short version: build against a framework Python 3.12
(Tk 8.6), have PyInstaller collect customtkinter's data files, and ad-hoc sign
the bundle. `make_icon.py` generates the icon — the Assimilate ring around a
flat six-blade shutter, in the brand orange (#FF5001).
