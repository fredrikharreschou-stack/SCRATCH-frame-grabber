# Changelog

All notable changes to SCRATCH Frame Grabber are documented here.

## 1.4.6 - 2026-09-08

### Added
- `#project` in the "Save frames to" path is replaced with the name of the
  open project, so exports land under a parent folder named for the show:
  `~/Desktop/scratch_frames/#project` -> `~/Desktop/scratch_frames/Cabin Retreat`.
  Works with all three grab buttons; the per-group folders are created
  underneath as before. The substituted name is sanitized, so a project
  called "Show: Pilot/2" cannot inject a path separator.

  Only `#project` is expanded there, deliberately: the output root is
  resolved once per run, while `#scene`, `#take` and the rest differ from
  shot to shot -- those belong in the naming pattern, which has made
  subfolders from a `\` or `/` since 1.4.2. Any other flag in the output
  path is left as typed and reported in the log. The project name is only
  looked up when the path contains a `#`, so ordinary paths cost no extra
  API call.

- Optional PDF contact sheet alongside the HTML gallery. `contact_sheet.pdf`
  in each folder that gets a gallery: US Letter portrait, twelve frames a
  page, shot name under each. Either, both or neither can be switched on.
  Composed with Pillow, so no new dependency -- Pillow was already required
  for the custom-width resize.

### Changed
- Contact sheets, HTML and PDF alike, are now built from the frames present
  in the folder rather than from the run that just finished. Grabbing one
  shoot day updates that day's sheets *and* the project-level pair to cover
  every frame grabbed for the project so far, instead of the project sheet
  showing whichever day happened to run last. It also self-corrects: a frame
  you delete stops appearing, where a stored manifest would have gone stale.

  Consequently the project-level sheets are written after every run,
  including a single-group or single-timeline grab. The previous reason for
  suppressing them -- that one day's stills would overwrite a whole-project
  sheet -- no longer applies now that they are rebuilt from the folder. The
  now-meaningless `write_gallery` parameter has been removed rather than
  left as a silent no-op.

  Cost: the project PDF is regenerated each run. About 20 seconds at 330
  frames, 40 at 700. Untick the PDF for quick runs.

- The three gallery-writing sites (project, per-group, unslated) go through
  one `_write_galleries` helper, so HTML and PDF cannot drift apart.

- The flags help text now mentions that `#project` works in the folder path.
  The feature was in the previous build but nothing in the UI said so, which
  made it effectively invisible.

### Note
- 1.4.4 and 1.4.5 were internal iterations and were never distributed; this
  entry covers everything since 1.4.3.

## 1.4.3 - 2026-08-28

Built on 1.4.2. Verified against a live SCRATCH 9.9 (build 1211) on an
8-group, 580-slot project.

### Added
- "Grab this group" button, alongside the open-timeline and whole-project
  grabs. Takes every timeline in the group the open timeline belongs to —
  for finishing a shooting day when the earlier days are already captured.
  It writes into the same `<output>/<group>/` folder a whole-project run
  uses, so a day grabbed on its own sits alongside days grabbed earlier
  instead of forming a parallel tree. A group chosen this way is never
  skipped for its name, and a single-group run does not overwrite the
  project-wide `gallery.html`.
- "Skip clips missing any of these flags", with the field pre-filled
  `#scene #take`. Accepts any naming flag, so `#reelid` works, or `#file`
  to drop shots whose media has gone offline. A clip is skipped when *any*
  listed flag renders empty. Unrecognised flag names are reported and
  ignored; if nothing in the field is recognised the run skips nothing on
  that basis, rather than dropping every clip on a typo.
- "…and keep them in an `unslated` subfolder instead of skipping". Diverted
  clips get their own folder inside the group folder, their own numbering
  and their own `gallery.html`, and are left out of the main contact sheet.
  Unslated is not always unwanted — pickups, inserts, plates and B-roll
  often run long without a slate, exactly like a blooper does.

### Fixed
- The gallery `href` for a frame is now derived from the path actually
  written, rather than rebuilt from the pattern segments. When the in-run
  collision guard renames a file (appending " 2" where two frames resolve
  to the same name), the segment-built href pointed at the un-renamed path
  and the gallery showed a broken image. Narrow, but the 1.4.2 subfolder
  feature makes same-name collisions more likely rather than less.
- The in-run collision guard was also counting files left by an *earlier*
  run as taken, so re-grabbing a day already captured produced a second
  copy of every still instead of refreshing it in place. Only names claimed
  within the current run are considered.
- A naming pattern that renders to nothing but its literal separators —
  `#scene_#take` on an unslated clip renders as `_` — was reduced by the
  sanitizer to its "shot" fallback, so every such clip collided on one
  filename. The check now looks for real characters and falls back to the
  clip's own name. It runs before the pattern is split into path segments,
  so the fallback lands in the filename instead of inventing a folder.

### Notes
- Pattern subfolders stack with the per-group folders a group or project
  run already creates: `\#group\#name` under a project run yields
  `<group>/<group>/<name>`. Working as designed, but easy to trip over.
- `shot.audio.roll` is declared a float in the OpenAPI spec but is really
  an alphanumeric sound-roll ID. The deserializer shim added in 1.4.0 keeps
  it from taking down a request, but the spec is where it belongs — any
  other tool built on that SDK hits the same thing.

## 1.4.2 - 2026-08-27

### Added
- A `\` or `/` in the naming pattern is now a folder boundary, matching
  SCRATCH's own naming/output module — `\#group\#construct\#name.#ext`
  writes into a `<group>/<construct>/` subfolder tree instead of one flat
  folder. Each segment between separators is sanitized on its own, and
  the app creates whatever subfolders the pattern calls for.

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
