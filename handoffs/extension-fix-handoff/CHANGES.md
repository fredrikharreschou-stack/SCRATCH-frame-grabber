# SCRATCH Frame Grabber — one fix on top of your handoff

`scratch_frame_grabber.py` in this folder is your version (the macOS port +
fixes + feature additions) with one additional bug fixed. `scratch_frame_grabber.diff`
is a unified diff against your handoff copy if you'd rather review it hunk by
hunk — it's small, two hunks, about a dozen real lines changed.

---

## Double file extension in naming patterns that end with `.#ext`

### Symptom

A naming pattern like `#project_#construct_#file.#ext` was producing
filenames with the extension twice, e.g.:

```
03_2608_KITCHEN_MENY_HOST_26_20s_01_A_0001C022_260812_091148_p1F9V.jpg.jpg
```

### Root cause

Nothing to do with `#file` or `#ext` individually — the export loop always
appends `.{ext}` to the rendered filename unconditionally, regardless of
whether the pattern already ends in a literal `.#ext`:

```python
stem = sanitize_full_filename(rendered)
...
out_path = unique_path(
    os.path.join(out_dir, f"{stem}.{ext}"),
    self._used_paths,
)
```

Since `#ext` is documented as usable inside a pattern (and the "Insert flag"
menu offers it), any pattern that puts `.#ext` at the end — which is the
natural way to write one — collides with this unconditional append.

### Fix

Only append the extension when the rendered stem doesn't already end with
it:

```python
suffix = f".{ext}"
filename = stem if stem.lower().endswith(suffix.lower()) else stem + suffix
out_path = unique_path(os.path.join(out_dir, filename), self._used_paths)
```

A pattern with no `#ext` in it (e.g. plain `#name`) still gets the extension
auto-appended exactly as before, so nothing changes for existing patterns
that don't reference `#ext` themselves.

### Also hardened while chasing this: `#file`'s extension stripping

Not the actual cause of the bug above (confirmed by testing — this alone
did not fix it), but a real latent issue found along the way and worth
carrying forward. `#file` stripped the source filename's extension with
`os.path.splitext`, which only removes the *last* extension:

```python
base = os.path.splitext(os.path.basename(f))[0] if f else ""
```

Some shots come back from SCRATCH with a compound extension on the
filename itself (e.g. a JPEG proxy literally named `...p1F9V.jpg.jpg`).
`splitext` on that leaves one `.jpg` behind. Changed to strip everything
from the first dot instead, since the "name" portion of a source filename
essentially never contains a literal dot of its own:

```python
base = os.path.basename(f).split(".", 1)[0] if f else ""
```

---

Both changes are confirmed working against a live SCRATCH instance
(v1.4.0 base, tested 2026-08-26).
