# Changelog

All notable changes to SCRATCH Frame Grabber are documented here.

## 1.4.1 - 2026-08-26

### Fixed
- Naming patterns that end in a literal `.#ext` (e.g.
  `#project_#construct_#file.#ext`) no longer get the extension appended
  twice (`...file.jpg.jpg` -> `...file.jpg`). The export step now only
  appends the extension when the rendered pattern doesn't already end
  with it.
- `#file` now strips *every* trailing extension from the source filename,
  not just the last one — some sources report a compound extension (e.g.
  `...p1F9V.jpg.jpg`), which the old `os.path.splitext`-based logic left
  one copy of behind.

## 1.4.0 - 2026-08-25

macOS port, contributed by Wyatt.

### Added
- macOS support: per-user settings directory, Dock icon via the app
  bundle's `Info.plist`, a bundled logo so the header doesn't depend on
  an HTTPS fetch, `resource_path()` for running from a PyInstaller
  bundle.
- "Grab this group" and "Grab whole project" buttons, alongside the
  original open-timeline grab. A project walk skips groups whose names
  don't match the naming convention the rest of the project follows.
- "Last take of each scene only" filter (scene letters like `46A` count
  as their own scene; numeric take ranking so `10` beats `9`).
- "Skip clips shorter than N frames" (default 200), to drop false starts,
  camera tests, and single-frame stills.
- Optional running file-number prefix — with it off, re-grabbing a day
  overwrites its stills in place instead of renumbering everything.
- One output folder per group on group/project runs, each with its own
  `gallery.html`.
- A filename collision guard for a run where several timelines share one
  output folder.
- `build-macos/` — a working PyInstaller spec, icon generator, and build
  instructions for a macOS `.app`/`.dmg`.

### Fixed
- `#project` always rendered blank: the code called a nonexistent
  `get_project_current()` method; the real endpoint is
  `get_projects_current()` (plural).
- `#construct` and `#rtc` always rendered blank: `get_constructs_current()`
  returns the open construct directly, not a `.constructs` list to search
  through.
- A `ValueError` on shot metadata that doesn't match its declared type —
  most commonly `shot.audio.roll`, spec'd as a float but often an
  alphanumeric sound-roll ID like `26Y08M22` — could silently kill an
  entire API request, surfacing as a generic "couldn't connect to
  SCRATCH". The REST client's deserializer now keeps the raw value on a
  mismatch instead of raising.
- Timecode in filenames now renders as unbroken digits (`11390810`)
  instead of colon-mangled underscores (`11_39_08_10`).

## 1.0 - earlier

Initial release: grab a still (first or middle frame) from every shot in
the timeline currently open in SCRATCH, with SCRATCH's own `#flag` naming
syntax, adjustable output format/resolution, and an HTML gallery of the
results.
