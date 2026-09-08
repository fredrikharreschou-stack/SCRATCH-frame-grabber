"""
scratch_frame_grabber.py  (modern UI edition)
------------------------------------------------
A small desktop app for grabbing frames from the shots in your currently
open SCRATCH timeline, with clickable options for file format, output
folder, and resolution. Uses "customtkinter" for a modern, flat,
dark/light-aware look.

HOW TO RUN THIS
1. Open SCRATCH, open the project, and load the timeline you want frames from.
2. Make sure the REST API is still enabled (System Settings) and running
   on port 8080 (the default).
3. One-time setup, in Terminal / Command Prompt:
       macOS / Linux:  pip3 install git+https://github.com/Assimilate-Inc/Assimilate-REST.git customtkinter Pillow
       Windows:        py -m pip install git+https://github.com/Assimilate-Inc/Assimilate-REST.git customtkinter Pillow
4. Every time you want to run it, from the folder you saved this file in:
       macOS / Linux:  python3 scratch_frame_grabber.py
       Windows:        py scratch_frame_grabber.py

Optional: run make_app_icon.py once (same folder) to generate icon.ico
from the Assimilate logo -- if it's present, the app picks it up
automatically as its window/taskbar icon.

Your settings (output folder, format, resolution) are remembered between
runs in a small file called scratch_frame_grabber_settings.json, saved
next to this script.
"""

import os
import io
import sys
import re
import json
import html
import shutil
import collections
import queue
import datetime
import threading
import urllib.request
from tkinter import StringVar, BooleanVar, filedialog

import customtkinter as ctk

import assimilate_client
from assimilate_client.rest import ApiException


def _install_lenient_primitive_deserializer():
    """Stop one odd metadata value from failing an entire request.

    Assimilate's generated REST client coerces each field to the type its
    OpenAPI spec declares. Some declared types don't match what SCRATCH
    actually sends -- the clearest case is a shot's audio "roll", declared
    as a float but genuinely an alphanumeric sound-roll ID (date-style
    rolls like "26Y08M22" are common from location sound recorders).

    float("26Y08M22") raises ValueError, and the client only guards against
    TypeError and UnicodeEncodeError, so the exception escapes and takes
    down the whole get-slots call -- the timeline simply appears
    unreachable. Keep the raw value instead when conversion fails; every
    field this app reads is turned into text anyway.
    """
    try:
        from assimilate_client.api_client import ApiClient
    except Exception:
        return False
    attr = "_ApiClient__deserialize_primitive"   # name-mangled private method
    original = getattr(ApiClient, attr, None)
    if original is None or getattr(original, "_fg_lenient", False):
        return False

    def lenient(self, data, klass):
        try:
            return original(self, data, klass)
        except ValueError:
            return data

    lenient._fg_lenient = True
    setattr(ApiClient, attr, lenient)
    return True


_install_lenient_primitive_deserializer()

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("green")

LOGO_URL = "https://www.assimilateinc.com/wp-content/uploads/2015/07/assimilate-logo2a.png"


def load_logo_image(url, target_height=32):
    """Return the Assimilate logo as a CTkImage sized to target_height.

    Prefers a copy bundled with the app so the header still renders on an
    offline machine; falls back to fetching it from the web. Returns None if
    neither works (Pillow missing, offline with no bundled copy, URL moved).
    """
    if not PIL_AVAILABLE:
        return None
    try:
        local = resource_path("assimilate_logo.png")
        if os.path.exists(local):
            data = open(local, "rb").read()
        else:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = resp.read()
        img = Image.open(io.BytesIO(data))
        img.load()
        width, height = img.size
        if height <= 0:
            return None
        target_width = max(1, round(width * (target_height / height)))
        return ctk.CTkImage(light_image=img, dark_image=img, size=(target_width, target_height))
    except Exception:
        return None

APP_NAME = "SCRATCH Frame Grabber"


def _is_frozen():
    """True when running from a PyInstaller bundle (.app / .exe)."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def resource_path(*parts):
    """Locate a read-only bundled resource, frozen or running from source."""
    if _is_frozen():
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def settings_dir():
    """A writable, per-user location for settings.

    Running from source this stays next to the script (unchanged behavior).
    Once bundled, the app directory is read-only -- and on macOS lives inside
    the .app -- so we use the platform's standard per-user config location.
    """
    if not _is_frozen():
        return os.path.dirname(os.path.abspath(__file__))
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~/Library/Application Support"), APP_NAME
        )
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "scratch-frame-grabber")


SETTINGS_DIR = settings_dir()
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "scratch_frame_grabber_settings.json")


def _migrate_legacy_settings():
    """Carry settings over from an older side-by-side install, once."""
    if os.path.exists(SETTINGS_FILE):
        return
    legacy = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "scratch_frame_grabber_settings.json",
    )
    if legacy != SETTINGS_FILE and os.path.exists(legacy):
        try:
            os.makedirs(SETTINGS_DIR, exist_ok=True)
            shutil.copy2(legacy, SETTINGS_FILE)
        except Exception:
            pass


_migrate_legacy_settings()

DEFAULT_SETTINGS = {
    "host": "http://localhost:8080/APIV2",
    "access_key": "",
    "output_dir": os.path.expanduser("~/Desktop/scratch_frames"),
    "file_format": "jpg",
    "proxy_res": True,
    "frame_choice": "middle",
    "resolution_mode": "proxy",   # "proxy", "full", or "custom"
    "custom_width": 1920,
    "naming_pattern": "#name",
    "make_gallery": True,
    "make_pdf": False,
    "last_take_only": False,
    "skip_short": True,
    "min_length": 200,
    "number_prefix": True,
    "skip_missing_flags": False,
    "require_flags": "#scene #take",
    "unslated_subfolder": False,
}

# Where clips that fail the required-flag check land, when the option to keep
# them is on. Kept as a constant so the folder name, the gallery title and the
# log messages can't disagree.
UNSLATED_DIRNAME = "unslated"


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            settings = DEFAULT_SETTINGS.copy()
            settings.update(data)
            return settings
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass


def safe_filename(text):
    keep = "-_ "
    return "".join(c if c.isalnum() or c in keep else "_" for c in text).strip() or "shot"


# ---------------------------------------------------------------------------
# SCRATCH-style naming flags -- e.g.  #reelid_#scene_#take_#name
#
# This mirrors the "#flag" syntax from SCRATCH's own naming/output docs
# (Assimilate Product Suite manual, "08 - Outputs" chapter). Parameter
# meanings below match that chapter exactly, flag by flag -- they are NOT
# all the same kind of parameter:
#   #reelid[n,m] / #name[n,m]   n = characters to skip, m = max length (0 = all)
#   #tc[p]                      p = left-padding digit count
#   #frame[p,o]                 p = left-padding digit count, o = frame offset
#   #date[ymd]                  each of y/m/d present emits that date part
#
# AVAILABLE_FLAGS are the flags we can back with real data from the REST
# API, with parameters matching the official syntax above. SCRATCH documents
# quite a few more (source-shot variants, metadata item codes, color/LUT,
# audio, subtitles, event/position counters) that this API doesn't expose in
# a way we can implement correctly -- those are listed in
# KNOWN_UNSUPPORTED_FLAGS so the app can tell you "that's a real SCRATCH
# flag, just not wired up here" rather than "unrecognized" (which would read
# like a typo). Anything not in either set is genuinely unrecognized.
# ---------------------------------------------------------------------------

FLAG_RE = re.compile(r"#([A-Za-z][A-Za-z0-9]*)(?:\[([^\]]*)\])?")


def _slice_chars(text, params):
    """Generic skip/limit clip, used both for #reelid/#name (where this is
    the documented behavior) and as a convenience extra on flags SCRATCH
    doesn't document parameters for at all."""
    if not params:
        return text
    parts = [p.strip() for p in params.split(",")]
    try:
        if len(parts) == 1:
            n = int(parts[0]) if parts[0] != "" else 0
            return (text[:n] if n >= 0 else text[n:]) if n else text
        skip = int(parts[0]) if parts[0] != "" else 0
        limit = int(parts[1]) if len(parts) > 1 and parts[1] != "" else 0
        clipped = text[skip:] if skip else text
        return clipped[:limit] if limit else clipped
    except ValueError:
        return text


def _pad_left(text, params):
    """#tc[p] -- p is a left-padding digit count, not a slice."""
    if not params:
        return text
    try:
        width = int(params.split(",")[0].strip())
    except (ValueError, IndexError):
        return text
    return text.rjust(width, "0") if width else text


def _h_reelid(ctx, params):
    return _slice_chars(ctx["shot"].reel_id or "", params)


def _h_scene(ctx, params):
    return _slice_chars(ctx["shot"].scene or "", params)


def _h_take(ctx, params):
    take = ctx["shot"].take
    return _slice_chars("" if take in (None, "") else str(take), params)


def _h_name(ctx, params):
    return _slice_chars(ctx["shot"].name or "", params)


def _h_uuid(ctx, params):
    return _slice_chars(ctx["shot"].uuid or "", params)


def _h_file(ctx, params):
    # os.path.splitext only strips the LAST extension. Some sources come
    # back from SCRATCH with a compound extension on the filename itself
    # (e.g. a JPEG proxy named "...p1F9V.jpg.jpg") -- splitext would leave
    # one ".jpg" behind, which then collides with a literal ".#ext" at the
    # end of the naming pattern. Strip everything from the first dot
    # instead, since a source filename's "name" portion essentially never
    # contains a literal dot of its own.
    f = ctx["shot"].file or ""
    base = os.path.basename(f).split(".", 1)[0] if f else ""
    return _slice_chars(base, params)


def _h_ext(ctx, params):
    # SCRATCH's #ext is "the default filename extension for the OUTPUT
    # format" -- not the source media's extension.
    return str(ctx.get("output_ext") or "")


TC_SEPARATORS = ":;."


def _strip_tc_separators(text):
    """Render a timecode as unbroken digits.

    Timecode arrives as 11:39:08:10 (or 11:39:08;10 when drop-frame). A
    colon can't appear in a filename, so the sanitizer would turn each one
    into an underscore -- 11_39_08_10. Dropping the separators here gives
    11390810 instead, which stays compact and sorts correctly.
    """
    return "".join(ch for ch in str(text) if ch not in TC_SEPARATORS)


def _h_tc(ctx, params):
    shot = ctx["shot"]
    tc = str(shot.timecode or getattr(shot, "frame_tc", None) or "")
    return _pad_left(_strip_tc_separators(tc), params)


def _h_rtc(ctx, params):
    return _slice_chars(_strip_tc_separators(ctx.get("record_tc") or ""), params)


def _h_frame(ctx, params):
    frame_val = ctx["frame"]
    width, offset = None, 0
    if params:
        parts = [p.strip() for p in params.split(",")]
        try:
            if parts and parts[0] != "":
                width = int(parts[0])
            if len(parts) > 1 and parts[1] != "":
                offset = int(parts[1])
        except ValueError:
            width, offset = None, 0
    s = str(frame_val + offset)
    return s.rjust(width, "0") if width else s


def _h_date(ctx, params):
    today = datetime.date.today()
    if not params:
        return today.strftime("%Y-%m-%d")
    parts_out = []
    for ch in params:
        lc = ch.lower()
        if lc == "y":
            parts_out.append(today.strftime("%Y"))
        elif lc == "m":
            parts_out.append(today.strftime("%m"))
        elif lc == "d":
            parts_out.append(today.strftime("%d"))
    return "".join(parts_out) if parts_out else today.strftime("%Y-%m-%d")


def _h_slotname(ctx, params):
    return _slice_chars(ctx["slot"].name or "", params)


def _h_fps(ctx, params):
    fps = ctx["shot"].fps
    return _slice_chars("" if fps in (None, "") else str(fps), params)


def _h_project(ctx, params):
    return _slice_chars(str(ctx.get("project_name") or ""), params)


def _h_group(ctx, params):
    return _slice_chars(str(ctx.get("group_name") or ""), params)


def _h_construct(ctx, params):
    return _slice_chars(str(ctx.get("construct_name") or ""), params)


AVAILABLE_FLAGS = {
    "reelid": _h_reelid,
    "scene": _h_scene,
    "take": _h_take,
    "name": _h_name,
    "uuid": _h_uuid,
    "file": _h_file,
    "ext": _h_ext,
    "tc": _h_tc,
    "rtc": _h_rtc,
    "frame": _h_frame,
    "date": _h_date,
    "slotname": _h_slotname,
    "fps": _h_fps,
    "project": _h_project,
    "group": _h_group,
    "construct": _h_construct,
}

# Real SCRATCH flags (per the official manual) that this app recognizes by
# name but can't back with reliable data from the REST API -- e.g. they
# need the "source shot" (the original media-pool item, a separate entity
# from the timeline shot this API gives us), a metadata-item-code lookup,
# or audio/color/subtitle sub-structures we haven't confirmed. Used flags
# will render blank; the run summary tells you which ones were skipped
# and why, instead of just calling them "unrecognized".
KNOWN_UNSUPPORTED_FLAGS = {
    "sname": "needs the source shot (this API gives us the timeline shot)",
    "suuid": "needs the source shot",
    "sfile": "needs the source shot",
    "stc": "needs the source shot",
    "sframe": "needs the source shot",
    "note": "shot annotation structure isn't confirmed",
    "snote": "needs the source shot",
    "seq_frame": "needs stereo/multi-view eye data, not confirmed available",
    "eventno": "needs source event numbering, not exposed here",
    "eventpos": "needs slot-relative frame position, not exposed here",
    "md": "needs a metadata-item-code lookup, not implemented",
    "pmd": "needs a metadata-item-code lookup, not implemented",
    "subtitle": "needs subtitle track data, not exposed here",
    "colorspace": "color-format sub-structure isn't confirmed",
    "srclut": "LUT sub-structure isn't confirmed",
    "gradelut": "LUT sub-structure isn't confirmed",
    "soundroll": "needs shot audio sub-structure, not confirmed",
    "audiotc": "needs shot audio sub-structure, not confirmed",
    "audiofile": "needs shot audio sub-structure, not confirmed",
    "res": "output pixel size isn't known until after export",
    "spath": "needs the source shot's media-folder-relative path, not exposed here",
}

# (token, human-readable label) -- used to populate the "Insert flag" menu
NAMING_FLAGS = [
    ("#reelid", "Reel ID"),
    ("#scene", "Scene"),
    ("#take", "Take"),
    ("#name", "Shot Name"),
    ("#uuid", "Shot GUID"),
    ("#file", "Shot Filename"),
    ("#ext", "Output Extension"),
    ("#tc", "Timecode"),
    ("#rtc", "Record TC"),
    ("#frame", "Frame Number"),
    ("#date", "Current Date"),
    ("#slotname", "Slot Name"),
    ("#fps", "Frame Rate"),
    ("#project", "Project Name"),
    ("#group", "Group Name"),
    ("#construct", "Timeline / Construct Name"),
]


def build_shot_context(shot, slot, frame, project_name, group_name, construct_name, record_tc, output_ext):
    return {
        "shot": shot,
        "slot": slot,
        "frame": frame,
        "project_name": project_name,
        "group_name": group_name,
        "construct_name": construct_name,
        "record_tc": record_tc,
        "output_ext": output_ext,
    }


def render_naming_pattern(pattern, ctx):
    """Returns (rendered_text, unknown_flags_used, known_unsupported_flags_used)."""
    unknown = set()
    known_unsupported = set()

    def _replace(m):
        flag = m.group(1).lower()
        params = m.group(2)
        handler = AVAILABLE_FLAGS.get(flag)
        if handler is None:
            if flag in KNOWN_UNSUPPORTED_FLAGS:
                known_unsupported.add(flag)
            else:
                unknown.add(flag)
            return ""
        try:
            value = handler(ctx, params)
        except Exception:
            value = ""
        return "" if value is None else str(value)

    rendered = FLAG_RE.sub(_replace, pattern)
    return rendered, unknown, known_unsupported


def sanitize_full_filename(text):
    keep = "-_. "
    cleaned = "".join(c if c.isalnum() or c in keep else "_" for c in text)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip(" ._")
    return cleaned or "shot"


def pick_snapshot_frame(shot, frame_choice):
    """The ImageSnapshot API's `frame` is a frame number into the shot's
    *source media*, not a position within the timeline -- so frame 0 is
    the very first frame of the raw camera file, which is often before
    the shot's trim-in point (and can be black, a slate, or unrelated
    footage). shot.handles.frame_in / frame_out are the source-frame
    numbers of the shot's actual trim-in/trim-out, i.e. what's really
    shown in the timeline, so we offset from there instead.
    """
    handles = getattr(shot, "handles", None)
    frame_in = getattr(handles, "frame_in", None) if handles else None
    frame_out = getattr(handles, "frame_out", None) if handles else None

    if frame_in is None:
        # No handle data available -- fall back to the old (source-frame-0)
        # behavior rather than fail.
        return 0 if frame_choice == "first" else ((shot.length // 2) if shot.length else 0)

    if frame_choice == "first":
        return frame_in

    if frame_out is not None:
        return frame_in + (frame_out - frame_in) // 2
    if shot.length:
        return frame_in + (shot.length // 2)
    return frame_in


GALLERY_FILENAME = "gallery.html"

GALLERY_CSS = """
:root { color-scheme: light dark; }
body {
    margin: 0; padding: 2.5rem 2rem 3rem;
    font-family: "Segoe UI", -apple-system, "IBM Plex Sans", Arial, sans-serif;
    background: #f4f3f0; color: #1e1d1b;
}
@media (prefers-color-scheme: dark) {
    body { background: #17181a; color: #eceae5; }
    figure { background: #212226 !important; border-color: #33343a !important; }
    figcaption .fname { color: #9a9992 !important; }
    header p { color: #a3a29c !important; }
}
header { margin-bottom: 2rem; }
header h1 { margin: 0 0 0.25rem; font-size: 1.6rem; }
header p { margin: 0; color: #6b6a66; font-size: 0.92rem; }
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 1.1rem;
}
figure {
    margin: 0; background: #ffffff; border: 1px solid #ddd9d0; border-radius: 10px;
    overflow: hidden; display: flex; flex-direction: column;
}
figure a { display: block; line-height: 0; }
figure img { width: 100%; height: 150px; object-fit: cover; display: block; background: #000; }
figcaption { padding: 0.6rem 0.75rem 0.75rem; font-size: 0.85rem; }
figcaption .sname { font-weight: 600; display: block; margin-bottom: 0.15rem; word-break: break-word; }
figcaption .fname { color: #6b6a66; font-size: 0.78rem; word-break: break-all; }
"""


def build_html_gallery(output_dir, entries, construct_name):
    """entries: list of dicts with keys filename, shot_name. Writes
    gallery.html into output_dir, referencing the images by relative
    filename (they're already sitting right next to it)."""
    title = f"SCRATCH Frame Grabber -- {construct_name}" if construct_name else "SCRATCH Frame Grabber"
    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    cards = []
    for entry in entries:
        fname = entry["filename"]
        shot_name = entry.get("shot_name") or fname
        cards.append(
            f'<figure><a href="{html.escape(fname)}" target="_blank">'
            f'<img src="{html.escape(fname)}" loading="lazy" alt="{html.escape(shot_name)}"></a>'
            f'<figcaption><span class="sname">{html.escape(shot_name)}</span>'
            f'<span class="fname">{html.escape(fname)}</span></figcaption></figure>'
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>{GALLERY_CSS}</style>
</head>
<body>
<header>
<h1>{html.escape(title)}</h1>
<p>{len(entries)} frame(s) &middot; generated {generated}</p>
</header>
<div class="grid">
{''.join(cards)}
</div>
</body>
</html>
"""
    gallery_path = os.path.join(output_dir, GALLERY_FILENAME)
    with open(gallery_path, "w", encoding="utf-8") as f:
        f.write(page)
    return gallery_path


def parse_flag_list(text):
    """Pull flag names out of a free-text field.

    Accepts the shapes people actually type -- "#scene #take", "scene, take",
    "#scene,#take". Returns (known, unknown) as lowercase names, order kept
    and duplicates dropped, so an unrecognised entry can be reported rather
    than silently changing what gets skipped.
    """
    found = re.findall(r"#?([A-Za-z][A-Za-z0-9]*)", text or "")
    known, unknown, seen = [], [], set()
    for name in found:
        name = name.lower()
        if name in seen:
            continue
        seen.add(name)
        (known if name in AVAILABLE_FLAGS else unknown).append(name)
    return known, unknown


OUTPUT_PATH_FLAG_RE = re.compile(r"#([A-Za-z][A-Za-z0-9]*)")


def expand_output_path(path, project_name):
    """Expand #project in the "Save frames to" path.

    Only a run-level token makes sense here. The output root is resolved once
    per run, whereas #scene, #take and the rest differ from shot to shot --
    those belong in the naming pattern, which already creates subfolders from
    a "\\" or "/". Keeping the two vocabularies apart is what stops
    "\\#scene" in the root from meaning something different in each mode.

    The substituted name is sanitized, so a project called "Show: Pilot 2"
    cannot inject a path separator or a character the filesystem rejects.

    Returns (expanded_path, unsupported_flags_used).
    """
    unsupported = set()

    def _sub(match):
        flag = match.group(1).lower()
        if flag != "project":
            unsupported.add(flag)
            return match.group(0)      # left as typed, so the mistake is visible
        cleaned = safe_filename(project_name) if project_name else ""
        return cleaned or match.group(0)

    return OUTPUT_PATH_FLAG_RE.sub(_sub, path), unsupported


PATH_SEPARATORS_RE = re.compile(r"[\\/]+")


def render_pattern_segments(rendered):
    """Split a rendered naming pattern into path segments.

    SCRATCH's own naming/output module treats "\\" (and "/") in a naming
    pattern as a folder boundary -- e.g. "\\#group\\#construct\\#name"
    writes into a <group>/<construct>/ subfolder tree instead of one flat
    folder. Frame Grabber's naming pattern now honors the same
    convention. Each segment between separators is sanitized on its own
    -- so a stray character in one folder's name can't leak into the
    next -- and a leading/doubled separator (patterns SCRATCH itself
    writes with a leading "\\") just means "nothing there", not an
    empty-named folder.

    Returns a non-empty list of sanitized segments; the caller treats the
    last one as the filename and the rest as folders to create.
    """
    raw_segments = [s for s in PATH_SEPARATORS_RE.split(rendered) if s.strip(" ._")]
    if not raw_segments:
        return ["shot"]
    return [sanitize_full_filename(s) for s in raw_segments]


PDF_FILENAME = "contact_sheet.pdf"

# macOS, Windows, then common Linux locations. Falls back to Pillow's builtin
# bitmap font, which is ugly but never missing.
PDF_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)


def _pdf_font(size):
    for path in PDF_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


FRAME_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")


def collect_existing_frames(root, skip_dirs=(UNSLATED_DIRNAME,)):
    """Every frame currently sitting under root, newest export included.

    A contact sheet built from the run that just finished only ever shows
    that run. Grabbing a shoot day at a time would leave the project-level
    sheet showing whichever day happened to go last. Reading the folder
    instead means the sheet always reflects everything grabbed for the
    project so far -- and it self-corrects, because a frame you deleted
    stops appearing rather than lingering in a stale manifest.

    Returns entries in the same shape build_html_gallery/build_pdf_gallery
    take, ordered by path so group folders stay together.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
        for name in sorted(filenames):
            if not name.lower().endswith(FRAME_EXTENSIONS):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            found.append({
                "filename": rel.replace(os.sep, "/"),
                "shot_name": os.path.splitext(name)[0],
            })
    return found


def build_pdf_gallery(output_dir, entries, title, columns=3, rows=4, dpi=150):
    """A printable contact sheet of the exported frames.

    Composed with Pillow rather than a PDF library, so the app gains no new
    dependency -- Pillow is already needed for the custom-width resize. Pages
    are US Letter portrait at 150 dpi, twelve frames to a page, each with its
    shot name underneath.
    """
    page_w, page_h = int(8.5 * dpi), int(11 * dpi)
    margin = int(0.40 * dpi)
    header_h = int(0.55 * dpi)
    gutter = int(0.12 * dpi)
    caption_h = int(0.18 * dpi)

    cell_w = (page_w - 2 * margin - gutter * (columns - 1)) // columns
    cell_h = (page_h - 2 * margin - header_h - gutter * (rows - 1)) // rows
    img_h = cell_h - caption_h

    font_title = _pdf_font(int(0.17 * dpi))
    font_sub = _pdf_font(int(0.10 * dpi))
    font_cap = _pdf_font(int(0.085 * dpi))

    per_page = columns * rows
    total_pages = max(1, (len(entries) + per_page - 1) // per_page)
    generated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    heading = title or "SCRATCH Frame Grabber"

    def fit(draw, label, width):
        """Trim a caption to the cell, with an ellipsis when it doesn't fit."""
        if draw.textlength(label, font=font_cap) <= width:
            return label
        while label and draw.textlength(label + "...", font=font_cap) > width:
            label = label[:-1]
        return label + "..."

    pages = []
    for page_index in range(total_pages):
        page = Image.new("RGB", (page_w, page_h), "white")
        draw = ImageDraw.Draw(page)
        draw.text((margin, margin - int(0.10 * dpi)), heading, fill=(20, 20, 20), font=font_title)
        draw.text(
            (margin, margin + int(0.12 * dpi)),
            "%d frame(s)   %s   page %d of %d"
            % (len(entries), generated, page_index + 1, total_pages),
            fill=(115, 115, 115), font=font_sub,
        )
        for i, entry in enumerate(entries[page_index * per_page:(page_index + 1) * per_page]):
            col, row = i % columns, i // columns
            x = margin + col * (cell_w + gutter)
            y = margin + header_h + row * (cell_h + gutter)
            try:
                with Image.open(os.path.join(output_dir, entry["filename"])) as im:
                    im = im.convert("RGB")
                    im.thumbnail((cell_w, img_h), Image.LANCZOS)
                    page.paste(im, (x + (cell_w - im.width) // 2, y + (img_h - im.height) // 2))
            except Exception:
                draw.rectangle([x, y, x + cell_w, y + img_h], outline=(205, 205, 205))
                draw.text((x + 6, y + 6), "missing", fill=(165, 165, 165), font=font_cap)
            label = entry.get("shot_name") or os.path.basename(entry["filename"])
            draw.text((x, y + img_h + int(0.035 * dpi)), fit(draw, label, cell_w),
                      fill=(60, 60, 60), font=font_cap)
        pages.append(page)

    path = os.path.join(output_dir, PDF_FILENAME)
    pages[0].save(path, "PDF", resolution=dpi, save_all=True, append_images=pages[1:])
    return path


def unique_path(path, taken):
    """Return a path no other frame in THIS run has claimed.

    Several timelines write into one group folder, so a naming pattern that
    doesn't distinguish them (a bare #scene_#take, say) could produce the
    same filename twice in one run; losing a frame silently is worse than a
    slightly ugly name, so the second one gets " 2" appended.

    Files left by an EARLIER run are deliberately not counted as taken --
    re-grabbing a day you've already captured should refresh those stills,
    not accumulate a second copy of every one of them.
    """
    if path not in taken:
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while f"{stem} {n}{ext}" in taken:
        n += 1
    return f"{stem} {n}{ext}"


def take_sort_key(take):
    """Order takes so "last" means the highest take, not the last string.

    Takes are normally zero-padded numbers ("01".."12") but can carry a
    letter ("2A"). Sorting on the leading number first keeps 10 after 9
    (plain string sort would not) and puts "2A" just after "2".
    """
    s = str(take or "").strip()
    m = re.match(r"(\d+)(.*)$", s)
    if m:
        return (0, int(m.group(1)), m.group(2).upper())
    return (1, 0, s.upper())


def select_last_takes(entries):
    """Keep only the highest-numbered take of each scene.

    entries is a list of (slot, shot). Scene letters are significant --
    46 and 46A are different setups, so each keeps its own last take.
    Any shot missing a scene or a take can't be ranked, so it is always
    kept. Results come back in timeline order.
    """
    best = {}
    passthrough = []
    for idx, (slot, shot) in enumerate(entries):
        scene = str(getattr(shot, "scene", None) or "").strip()
        take = str(getattr(shot, "take", None) or "").strip()
        if not scene or not take:
            passthrough.append((idx, slot, shot))
            continue
        key = scene.upper()
        rank = (take_sort_key(take), idx)
        if key not in best or rank > best[key][0]:
            best[key] = (rank, idx, slot, shot)
    kept = [(idx, slot, shot) for (_r, idx, slot, shot) in best.values()]
    kept.extend(passthrough)
    kept.sort(key=lambda t: t[0])
    return [(slot, shot) for _idx, slot, shot in kept]


def name_shape(name):
    """Collapse a name to its shape: runs of letters become A, runs of
    digits become #, separators stay put.

        DIKMH_08_22_2026_DAY_04  ->  A_#_#_#_A_#
        Stills                   ->  A
    """
    out = []
    for ch in str(name or ""):
        tok = "#" if ch.isdigit() else ("A" if ch.isalpha() else ch)
        if out and out[-1] == tok and tok in ("#", "A"):
            continue
        out.append(tok)
    return "".join(out)


def groups_matching_convention(names):
    """Split group names into (keep, dropped) by majority name shape.

    A project whose groups are shooting days -- DIKMH_08_22_2026_DAY_04 and
    friends -- plus one stray "Stills" group drops the odd one out.

    Fails open on purpose: with fewer than three groups, or no strict
    majority shape, everything is kept. Silently skipping real work is a
    worse outcome than grabbing a few frames you didn't want.
    """
    names = list(names)
    if len(names) < 3:
        return names, []
    shapes = [name_shape(n) for n in names]
    shape, hits = collections.Counter(shapes).most_common(1)[0]
    if hits * 2 <= len(names):
        return names, []
    keep = [n for n, s in zip(names, shapes) if s == shape]
    dropped = [n for n, s in zip(names, shapes) if s != shape]
    return keep, dropped


class FrameGrabberApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SCRATCH Frame Grabber")
        self.geometry("660x1000")
        self.minsize(600, 660)

        self._setup_window_icon()

        self.settings = load_settings()
        self.log_queue = queue.Queue()
        self.worker = None
        self.cancel_event = threading.Event()
        self.advanced_visible = False

        self._build_ui()
        self.after(100, self._poll_log_queue)

    def _setup_window_icon(self):
        """Apply the window icon using whatever the current platform accepts.

        macOS takes the icon from the .app bundle's Info.plist, and Tk's
        iconbitmap doesn't understand .icns, so there is nothing to do when
        bundled. Windows uses .ico via iconbitmap; Linux uses a PNG via
        iconphoto.
        """
        if sys.platform == "darwin":
            if not _is_frozen():
                self._apply_png_icon(resource_path("icon_512.png"))
            return

        if os.name == "nt":
            ico = resource_path("icon.ico")
            if os.path.exists(ico):
                self._apply_ico_icon(ico)
            return

        self._apply_png_icon(resource_path("icon_512.png"))

    def _apply_ico_icon(self, icon_path):
        # customtkinter resets the window icon back to Tk's default blue
        # feather a moment after startup, so setting it once in __init__
        # gets silently overridden. Re-apply it a couple of times shortly
        # after launch so our icon is the one that sticks.
        def set_icon():
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        set_icon()
        self.after(150, set_icon)
        self.after(400, set_icon)

    def _apply_png_icon(self, png_path):
        if not os.path.exists(png_path):
            return

        def set_icon():
            try:
                import tkinter
                self._icon_photo = tkinter.PhotoImage(file=png_path)
                self.iconphoto(True, self._icon_photo)
            except Exception:
                pass

        set_icon()
        self.after(150, set_icon)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="w", padx=24, pady=(24, 0))

        self._logo_image = load_logo_image(LOGO_URL, target_height=32)
        if self._logo_image is not None:
            ctk.CTkLabel(header_row, image=self._logo_image, text="").pack(
                side="left", padx=(0, 12)
            )

        ctk.CTkLabel(
            header_row, text="SCRATCH Frame Grabber", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(side="left")

        ctk.CTkLabel(
            self,
            text="Grab a still from every shot in your open timeline.",
            text_color=("gray40", "gray65"),
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(2, 16))

        card = ctk.CTkFrame(self, corner_radius=14)
        card.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 8))
        card.grid_columnconfigure(1, weight=1)

        # Output folder
        ctk.CTkLabel(card, text="Save frames to").grid(
            row=0, column=0, sticky="w", padx=(18, 8), pady=(18, 8)
        )
        self.out_dir_var = StringVar(value=self.settings["output_dir"])
        ctk.CTkEntry(card, textvariable=self.out_dir_var).grid(
            row=0, column=1, sticky="ew", pady=(18, 8)
        )
        ctk.CTkButton(card, text="Browse", width=90, command=self._browse_folder).grid(
            row=0, column=2, padx=(8, 18), pady=(18, 8)
        )

        # File format
        ctk.CTkLabel(card, text="File format").grid(row=1, column=0, sticky="w", padx=(18, 8), pady=8)
        self.format_btn = ctk.CTkSegmentedButton(card, values=["jpg", "png", "tif"])
        self.format_btn.set(self.settings["file_format"])
        self.format_btn.grid(row=1, column=1, columnspan=2, sticky="w", pady=8)

        # Resolution
        ctk.CTkLabel(card, text="Resolution").grid(row=2, column=0, sticky="w", padx=(18, 8), pady=8)
        res_values = ["Proxy (fast)", "Source resolution", "Custom width"]
        res_labels = {"proxy": res_values[0], "full": res_values[1], "custom": res_values[2]}
        self.res_btn = ctk.CTkSegmentedButton(card, values=res_values, command=self._on_res_change)
        self.res_btn.set(res_labels.get(self.settings["resolution_mode"], res_values[0]))
        self.res_btn.grid(row=2, column=1, columnspan=2, sticky="w", pady=8)

        # Custom width sub-row -- only shown when "Custom width" is selected
        self.custom_row = ctk.CTkFrame(card, fg_color="transparent")
        ctk.CTkLabel(self.custom_row, text="Width (px):").pack(side="left")
        self.custom_width_var = StringVar(value=str(self.settings["custom_width"]))
        ctk.CTkEntry(self.custom_row, textvariable=self.custom_width_var, width=90).pack(
            side="left", padx=(8, 0)
        )
        ctk.CTkLabel(
            self.custom_row,
            text="height keeps the same aspect ratio",
            text_color=("gray40", "gray65"),
        ).pack(side="left", padx=(10, 0))
        if self.settings["resolution_mode"] == "custom":
            self.custom_row.grid(row=3, column=1, columnspan=2, sticky="w", pady=(0, 8))

        # Which frame to grab
        ctk.CTkLabel(card, text="Frame to grab").grid(row=4, column=0, sticky="w", padx=(18, 8), pady=8)
        self.frame_btn = ctk.CTkSegmentedButton(card, values=["First frame", "Middle frame"])
        self.frame_btn.set("First frame" if self.settings["frame_choice"] == "first" else "Middle frame")
        self.frame_btn.grid(row=4, column=1, sticky="w", pady=8)

        self.last_take_var = BooleanVar(value=self.settings.get("last_take_only", False))
        ctk.CTkCheckBox(
            card,
            text="Last take of each scene only",
            variable=self.last_take_var,
        ).grid(row=4, column=2, sticky="w", padx=(12, 18), pady=8)

        # File naming pattern -- uses SCRATCH's own #flag syntax
        ctk.CTkLabel(card, text="File naming pattern").grid(
            row=5, column=0, sticky="w", padx=(18, 8), pady=8
        )
        self.naming_pattern_var = StringVar(
            value=self.settings.get("naming_pattern", DEFAULT_SETTINGS["naming_pattern"])
        )
        ctk.CTkEntry(card, textvariable=self.naming_pattern_var).grid(
            row=5, column=1, sticky="ew", pady=8
        )
        self.naming_flag_var = StringVar(value="Insert flag ▾")
        self.naming_menu = ctk.CTkOptionMenu(
            card,
            variable=self.naming_flag_var,
            values=[f"{label}  →  {token}" for token, label in NAMING_FLAGS],
            width=170,
            command=self._insert_naming_flag,
        )
        self.naming_menu.grid(row=5, column=2, padx=(8, 18), pady=8)

        ctk.CTkLabel(
            card,
            text=(
                "Uses SCRATCH's own #flag syntax, e.g. #reelid_#scene_#take_#name. Flags\n"
                "SCRATCH offers that this API can't supply yet are simply left blank. A \\ or /\n"
                "in the pattern creates subfolders, e.g. \\#group\\#construct\\#name.#ext.\n"
                "In the folder path above, #project stands in for the project name."
            ),
            justify="left",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65"),
        ).grid(row=6, column=0, columnspan=3, sticky="w", padx=(18, 18), pady=(0, 8))

        # Running number in front of each filename
        self.number_prefix_var = BooleanVar(value=self.settings.get("number_prefix", True))
        ctk.CTkCheckBox(
            card,
            text="Number files in shot order (01_, 02_ ...)",
            variable=self.number_prefix_var,
        ).grid(row=7, column=0, columnspan=3, sticky="w", padx=(18, 18), pady=(0, 8))

        # Skip very short clips -- false starts, camera tests, single-frame stills
        short_row = ctk.CTkFrame(card, fg_color="transparent")
        short_row.grid(row=8, column=0, columnspan=3, sticky="w", padx=(18, 18), pady=(0, 8))
        self.skip_short_var = BooleanVar(value=self.settings.get("skip_short", True))
        ctk.CTkCheckBox(
            short_row, text="Skip clips shorter than", variable=self.skip_short_var
        ).pack(side="left")
        self.min_length_var = StringVar(value=str(self.settings.get("min_length", 200)))
        ctk.CTkEntry(short_row, textvariable=self.min_length_var, width=64).pack(
            side="left", padx=(8, 8)
        )
        ctk.CTkLabel(short_row, text="frames").pack(side="left")

        # Require certain naming flags to carry data
        flags_row = ctk.CTkFrame(card, fg_color="transparent")
        flags_row.grid(row=9, column=0, columnspan=3, sticky="w", padx=(18, 18), pady=(0, 8))
        self.require_flags_on_var = BooleanVar(value=self.settings.get("skip_missing_flags", False))
        ctk.CTkCheckBox(
            flags_row,
            text="Skip clips missing any of these flags:",
            variable=self.require_flags_on_var,
        ).pack(side="left")
        self.require_flags_var = StringVar(
            value=self.settings.get("require_flags", "#scene #take")
        )
        ctk.CTkEntry(flags_row, textvariable=self.require_flags_var, width=190).pack(
            side="left", padx=(8, 0)
        )

        self.unslated_var = BooleanVar(value=self.settings.get("unslated_subfolder", False))
        ctk.CTkCheckBox(
            card,
            text=f"...and keep them in an '{UNSLATED_DIRNAME}' subfolder instead of skipping",
            variable=self.unslated_var,
        ).grid(row=10, column=0, columnspan=3, sticky="w", padx=(40, 18), pady=(0, 8))

        # Contact sheets of the exported frames
        sheets_row = ctk.CTkFrame(card, fg_color="transparent")
        sheets_row.grid(row=11, column=0, columnspan=3, sticky="w", padx=(18, 18), pady=(0, 18))
        self.gallery_var = BooleanVar(value=self.settings.get("make_gallery", True))
        ctk.CTkCheckBox(
            sheets_row,
            text="Also build an HTML gallery of the exported frames",
            variable=self.gallery_var,
        ).pack(side="left")
        self.pdf_var = BooleanVar(value=self.settings.get("make_pdf", False))
        ctk.CTkCheckBox(
            sheets_row, text="and a PDF contact sheet", variable=self.pdf_var
        ).pack(side="left", padx=(14, 0))

        # Advanced toggle
        self.adv_toggle = ctk.CTkButton(
            self,
            text="▸ Advanced settings",
            fg_color="transparent",
            text_color=("gray40", "gray65"),
            hover_color=("gray90", "gray20"),
            anchor="w",
            command=self._toggle_advanced,
        )
        self.adv_toggle.grid(row=3, column=0, sticky="w", padx=20)

        self.adv_frame = ctk.CTkFrame(self, corner_radius=14)
        self.adv_frame.grid_columnconfigure(1, weight=1)
        # not gridded yet -- hidden until toggled

        ctk.CTkLabel(self.adv_frame, text="SCRATCH API address").grid(
            row=0, column=0, sticky="w", padx=(18, 8), pady=(14, 6)
        )
        self.host_var = StringVar(value=self.settings["host"])
        ctk.CTkEntry(self.adv_frame, textvariable=self.host_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 18), pady=(14, 6)
        )

        ctk.CTkLabel(self.adv_frame, text="Access key (if set)").grid(
            row=1, column=0, sticky="w", padx=(18, 8), pady=(6, 14)
        )
        self.key_var = StringVar(value=self.settings["access_key"])
        ctk.CTkEntry(self.adv_frame, textvariable=self.key_var, show="*").grid(
            row=1, column=1, sticky="ew", padx=(0, 18), pady=(6, 14)
        )

        # Run / cancel row
        run_row = ctk.CTkFrame(self, fg_color="transparent")
        run_row.grid(row=5, column=0, sticky="ew", padx=24, pady=(16, 8))

        # Three grab buttons won't fit on one line beside the cancel button
        # and status text, so stack them: actions above, state below.
        buttons_row = ctk.CTkFrame(run_row, fg_color="transparent")
        buttons_row.pack(side="top", anchor="w")

        status_row = ctk.CTkFrame(run_row, fg_color="transparent")
        status_row.pack(side="top", anchor="w", pady=(10, 0))

        self.run_btn = ctk.CTkButton(
            buttons_row, text="Grab open timeline", height=38, command=self._on_run
        )
        self.run_btn.pack(side="left")

        self.group_btn = ctk.CTkButton(
            buttons_row,
            text="Grab this group",
            height=38,
            fg_color="transparent",
            border_width=1,
            command=lambda: self._on_run("group"),
        )
        self.group_btn.pack(side="left", padx=(10, 0))

        self.project_btn = ctk.CTkButton(
            buttons_row,
            text="Grab whole project",
            height=38,
            fg_color="transparent",
            border_width=1,
            command=lambda: self._on_run("project"),
        )
        self.project_btn.pack(side="left", padx=(10, 0))

        self.cancel_btn = ctk.CTkButton(
            status_row,
            text="Cancel export",
            height=38,
            width=130,
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray90"),
            state="disabled",
            command=self._on_cancel,
        )
        self.cancel_btn.pack(side="left", padx=(10, 0))

        self.status_var = StringVar(value="Ready.")
        ctk.CTkLabel(status_row, textvariable=self.status_var, text_color=("gray40", "gray65")).pack(
            side="left", padx=16
        )

        # Log
        ctk.CTkLabel(self, text="Log").grid(row=6, column=0, sticky="w", padx=24, pady=(4, 4))
        self.log_box = ctk.CTkTextbox(
            self, corner_radius=10, font=ctk.CTkFont(family="Consolas", size=12)
        )
        self.log_box.grid(row=7, column=0, sticky="nsew", padx=24, pady=(0, 24))
        self.log_box.configure(state="disabled")

        self.grid_rowconfigure(7, weight=1)

    def _insert_naming_flag(self, choice):
        token = choice.split("→")[-1].strip()
        self.naming_pattern_var.set(self.naming_pattern_var.get() + token)
        self.naming_flag_var.set("Insert flag ▾")

    def _on_res_change(self, value):
        if value == "Custom width":
            self.custom_row.grid(row=3, column=1, columnspan=2, sticky="w", pady=(0, 8))
        else:
            self.custom_row.grid_remove()

    def _toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.adv_toggle.configure(text="▾ Advanced settings")
            self.adv_frame.grid(row=4, column=0, sticky="ew", padx=24, pady=(6, 0))
        else:
            self.adv_toggle.configure(text="▸ Advanced settings")
            self.adv_frame.grid_forget()

    def _browse_folder(self):
        chosen = filedialog.askdirectory(
            initialdir=self.out_dir_var.get() or os.path.expanduser("~")
        )
        if chosen:
            self.out_dir_var.set(chosen)

    def _log(self, message):
        self.log_queue.put(message)

    def _poll_log_queue(self):
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_box.configure(state="normal")
            self.log_box.insert("end", message + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(100, self._poll_log_queue)

    def _on_run(self, mode="timeline"):
        if self.worker and self.worker.is_alive():
            return

        res_choice = self.res_btn.get()
        resolution_mode = {"Proxy (fast)": "proxy", "Source resolution": "full", "Custom width": "custom"}.get(
            res_choice, "proxy"
        )

        custom_width = self.settings.get("custom_width", 1920)
        if resolution_mode == "custom":
            if not PIL_AVAILABLE:
                self._log(
                    "Custom width needs the 'Pillow' package, which isn't installed. "
                    "Run: pip3 install Pillow  (Windows: py -m pip install Pillow), then try again."
                )
                return
            try:
                custom_width = int(self.custom_width_var.get().strip())
                if custom_width <= 0:
                    raise ValueError
            except ValueError:
                self._log(f"'{self.custom_width_var.get()}' isn't a valid width. Enter a whole number of pixels, e.g. 1920.")
                return

        min_length = self.settings.get("min_length", 200)
        if self.skip_short_var.get():
            try:
                min_length = int(self.min_length_var.get().strip())
                if min_length < 0:
                    raise ValueError
            except ValueError:
                self._log(
                    f"'{self.min_length_var.get()}' isn't a valid frame count. "
                    "Enter a whole number, e.g. 200."
                )
                return

        settings = {
            "host": self.host_var.get().strip(),
            "access_key": self.key_var.get().strip(),
            "output_dir": self.out_dir_var.get().strip(),
            "file_format": self.format_btn.get(),
            "resolution_mode": resolution_mode,
            "custom_width": custom_width,
            "frame_choice": "first" if self.frame_btn.get() == "First frame" else "middle",
            "naming_pattern": self.naming_pattern_var.get().strip() or DEFAULT_SETTINGS["naming_pattern"],
            "make_gallery": bool(self.gallery_var.get()),
            "make_pdf": bool(self.pdf_var.get()),
            "last_take_only": bool(self.last_take_var.get()),
            "skip_short": bool(self.skip_short_var.get()),
            "min_length": min_length,
            "number_prefix": bool(self.number_prefix_var.get()),
            "skip_missing_flags": bool(self.require_flags_on_var.get()),
            "require_flags": self.require_flags_var.get().strip(),
            "unslated_subfolder": bool(self.unslated_var.get()),
        }
        save_settings(settings)

        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        self.cancel_event.clear()
        self.run_btn.configure(state="disabled")
        self.group_btn.configure(state="disabled")
        self.project_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.status_var.set("Working...")

        self.worker = threading.Thread(target=self._grab_frames, args=(settings, mode), daemon=True)
        self.worker.start()

    def _on_cancel(self):
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.cancel_btn.configure(state="disabled")
            self.status_var.set("Cancelling...")
            self._log("Cancelling -- will stop after the frame currently in progress.")

    def _grab_frames(self, settings, mode="timeline"):
        try:
            if mode == "project":
                self._grab_project_inner(settings)
            elif mode == "group":
                self._grab_group_inner(settings)
            else:
                self._grab_frames_inner(settings)
        finally:
            self.after(0, self._set_idle)

    def _set_idle(self):
        self.run_btn.configure(state="normal")
        self.group_btn.configure(state="normal")
        self.project_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

    def _write_galleries(self, settings, out_dir, title, log_label="Gallery",
                         skip_dirs=(UNSLATED_DIRNAME,)):
        """HTML page, PDF contact sheet, or both -- whatever is switched on.

        Contents come from the folder, not from the run that just finished,
        so a sheet covers everything grabbed for that project or group to
        date rather than only the latest export.
        """
        entries = collect_existing_frames(out_dir, skip_dirs)
        if not entries:
            return []
        made = []
        if settings.get("make_gallery"):
            try:
                made.append(build_html_gallery(out_dir, entries, title))
            except Exception as e:
                self._log(f"  Note: couldn't build the HTML gallery: {e}")
        if settings.get("make_pdf"):
            if not PIL_AVAILABLE:
                self._log("  Note: the PDF contact sheet needs Pillow, which isn't installed.")
            else:
                try:
                    made.append(build_pdf_gallery(out_dir, entries, title))
                except Exception as e:
                    self._log(f"  Note: couldn't build the PDF contact sheet: {e}")
        for path in made:
            self._log(f"  {log_label}: {path}  ({len(entries)} frame(s))")
        return made

    def _resolve_output_dir(self, settings, proj_api):
        """Expand #project in the output path, then create the folder.

        The project name is only fetched when the path actually contains a
        token, so an ordinary path costs no extra API call.
        """
        raw = settings["output_dir"]
        project_name = ""
        if "#" in raw:
            project_name = self._lookup_name(
                proj_api, "get_projects_current", "get_project_current"
            )
            if not project_name:
                self._log("Note: couldn't read the project name -- #project left as typed.")
        expanded, unsupported = expand_output_path(raw, project_name)
        if unsupported:
            self._log(
                "Note: only #project works in the output folder (the rest belong in the "
                "naming pattern). Left as typed: "
                + ", ".join("#" + f for f in sorted(unsupported))
            )
        if expanded != raw:
            self._log(f"Output folder: {expanded}")
        output_dir = os.path.expanduser(expanded)
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    def _make_client(self, settings):
        configuration = assimilate_client.Configuration()
        configuration.host = settings["host"]
        if settings["access_key"]:
            configuration.api_key["Authorization"] = settings["access_key"]
        return assimilate_client.ApiClient(configuration)

    def _report_api_failure(self, e, settings, what):
        """One place for the three ways talking to SCRATCH can go wrong."""
        if isinstance(e, ApiException):
            self._log(f"Couldn't reach {what}.")
            self._log("  - Is SCRATCH running with a project open?")
            self._log("  - Is the REST API still enabled in System Settings?")
            self._log(f"  - Details: {e}")
        elif isinstance(e, (ValueError, TypeError)):
            self._log("SCRATCH answered, but part of the data couldn't be read.")
            self._log("  - A metadata field holds a value the REST API spec doesn't expect.")
            self._log(f"  - Details: {type(e).__name__}: {e}")
        else:
            self._log(f"Couldn't connect to SCRATCH at {settings['host']}")
            self._log("  - Is SCRATCH running with the REST API turned on?")
            self._log(f"  - Details: {e}")
        self.after(0, lambda: self.status_var.set("Failed - see log"))

    def _resize_to_width(self, path, target_width, ext):
        with Image.open(path) as img:
            width, height = img.size
            if width <= 0:
                return
            target_height = max(1, round(height * (target_width / width)))
            resized = img.convert("RGB") if ext == "jpg" else img
            resized = resized.resize((target_width, target_height), Image.LANCZOS)
            save_kwargs = {"quality": 95} if ext == "jpg" else {}
            resized.save(path, **save_kwargs)

    def _fetch_naming_context(self, proj_api):
        """Best-effort lookups for the #project / #group / #construct / #rtc
        flags. Any of these can fail (older SCRATCH builds, API differences,
        nothing open at that level) without stopping the export -- they just
        come out blank if we can't get them."""
        project_name = group_name = construct_name = record_tc = ""
        try:
            current = proj_api.get_constructs_current(level="ALL")
            # This endpoint returns the open construct itself. The original
            # code looked for a .constructs list hanging off it, found none,
            # and left #construct and #rtc blank on every run. Use the object
            # directly, but keep the list shape as a fallback in case another
            # SCRATCH build answers that way.
            target = current
            clist = getattr(current, "constructs", None) or []
            if clist:
                target = clist[0]
            construct_name = getattr(target, "name", "") or ""
            record_tc = getattr(target, "record_tc", "") or ""
        except Exception:
            pass
        project_name = self._lookup_name(proj_api, "get_projects_current", "get_project_current")
        group_name = self._lookup_name(proj_api, "get_group_current", "get_groups_current")
        return project_name, group_name, construct_name, record_tc

    def _lookup_name(self, proj_api, *candidates):
        """Read a "current object" name, tolerating the SDK's inconsistent
        singular/plural method names.

        The endpoint for the open project is exposed as
        get_projects_current (plural); the original script called
        get_project_current, which doesn't exist -- the AttributeError was
        swallowed by a bare except, so #project always rendered blank.
        Try each spelling and take the first that answers.
        """
        for attr in candidates:
            fn = getattr(proj_api, attr, None)
            if fn is None:
                continue
            try:
                return getattr(fn(), "name", "") or ""
            except Exception:
                continue
        return ""

    def _grab_frames_inner(self, settings):
        """Grab from the timeline currently open in SCRATCH."""
        self._short_skipped = 0
        self._missing_flag_skipped = 0
        self._used_paths = set()
        client = self._make_client(settings)
        app_api = assimilate_client.ApplicationApi(client)
        proj_api = assimilate_client.ProjectsApi(client)
        output_dir = self._resolve_output_dir(settings, proj_api)

        try:
            slots_data = proj_api.get_construct_current_slots(level="ALL")
        except Exception as e:
            self._report_api_failure(e, settings, "SCRATCH's open timeline")
            return

        slots = slots_data.slots or []
        if not slots:
            self._log("No slots found in the current timeline. Is one open in SCRATCH?")
            self.after(0, lambda: self.status_var.set("No shots found"))
            return

        self._log(f"Found {len(slots)} slot(s) in the open timeline. Grabbing frames...")

        naming_ctx = self._fetch_naming_context(proj_api)
        flag_sets = (set(), set())
        gallery_entries = []
        unslated_entries = []
        unslated_dir = (
            os.path.join(output_dir, UNSLATED_DIRNAME)
            if settings.get("unslated_subfolder") else None
        )
        result = self._export_construct(
            app_api, slots, settings, naming_ctx, output_dir, "",
            gallery_entries, flag_sets,
            unslated_dir=unslated_dir, unslated_entries=unslated_entries,
        )
        self._build_unslated_gallery(settings, unslated_dir, unslated_entries, naming_ctx[2])
        self._finish_run(settings, output_dir, naming_ctx[2],
                         flag_sets, result["saved"], result["failed"],
                         result["skipped"], result["cancelled"])

    def _grab_project_inner(self, settings, only_group=None):
        """Walk every group and timeline in the open project.

        Groups whose names don't match the convention the rest of the
        project follows are skipped -- a "Stills" group sitting alongside
        DIKMH_08_22_2026_DAY_04 and friends is not a shooting day, and its
        timelines don't hold slated takes.

        Frames land in one folder per group, with numbering running on
        across the group's timelines so the prefixes stay unique.
        """
        self._short_skipped = 0
        self._missing_flag_skipped = 0
        self._used_paths = set()
        client = self._make_client(settings)
        app_api = assimilate_client.ApplicationApi(client)
        proj_api = assimilate_client.ProjectsApi(client)
        output_dir = self._resolve_output_dir(settings, proj_api)

        try:
            groups_data = proj_api.get_groups(level="ALL")
        except Exception as e:
            self._report_api_failure(e, settings, "the project's groups")
            return

        groups = groups_data.groups or []
        if not groups:
            self._log("No groups found in the open project.")
            self.after(0, lambda: self.status_var.set("Nothing found"))
            return

        project_name = self._lookup_name(proj_api, "get_projects_current", "get_project_current")

        if only_group is not None:
            # An explicitly chosen group is never second-guessed -- if you
            # opened a timeline inside it, you meant it, even if its name
            # doesn't match the others.
            if not any((g.name or "") == only_group for g in groups):
                self._log(f"Couldn't find the group '{only_group}' in this project.")
                self.after(0, lambda: self.status_var.set("Group not found"))
                return
            keep_set = {only_group}
            self._log(f"Project '{project_name}' -- grabbing group '{only_group}'.")
        else:
            keep, dropped = groups_matching_convention([g.name or "" for g in groups])
            keep_set = set(keep)
            self._log(f"Project '{project_name}': {len(groups)} group(s).")
            for name in dropped:
                self._log(f"  Skipping group '{name}' -- its name doesn't match the pattern the others use.")
            if not dropped and len(groups) >= 3:
                self._log("  All group names follow one pattern; none skipped.")

        flag_sets = (set(), set())
        gallery_entries = []
        saved = failed = skipped = 0
        cancelled = False
        groups_done = constructs_done = 0

        for group in groups:
            if cancelled:
                break
            gname = group.name or ""
            if gname not in keep_set:
                continue
            constructs = getattr(group, "constructs", None) or []
            if not constructs:
                continue

            groups_done += 1
            group_dirname = safe_filename(gname)
            group_dir = os.path.join(output_dir, group_dirname)
            group_entries = []
            group_index = 0
            group_unslated_entries = []
            group_unslated_index = 0
            group_unslated_dir = (
                os.path.join(group_dir, UNSLATED_DIRNAME)
                if settings.get("unslated_subfolder") else None
            )
            self._log("")
            self._log(f"Group: {gname}  ({len(constructs)} timeline(s))")

            for construct in constructs:
                if self.cancel_event.is_set():
                    cancelled = True
                    break
                cname = construct.name or ""
                slots = getattr(construct, "slots", None) or []
                if not slots:
                    self._log(f"  Timeline '{cname}': empty, skipped.")
                    continue

                constructs_done += 1
                self._log(f"  Timeline: {cname}")
                naming_ctx = (
                    project_name, gname, cname,
                    getattr(construct, "record_tc", "") or "",
                )
                # Every timeline in a group writes straight into the group
                # folder -- one folder per shooting day, no per-timeline
                # subfolders. Numbering runs on across the group so the NN_
                # prefixes stay unique, and gallery filenames are bare names
                # relative to that same folder.
                result = self._export_construct(
                    app_api, slots, settings, naming_ctx,
                    group_dir, "", group_entries, flag_sets,
                    index_offset=group_index,
                    unslated_dir=group_unslated_dir,
                    unslated_entries=group_unslated_entries,
                    unslated_offset=group_unslated_index,
                )
                group_index = result["next_offset"]
                group_unslated_index = result["next_unslated_offset"]
                saved += result["saved"]
                failed += result["failed"]
                skipped += result["skipped"]
                if result["cancelled"]:
                    cancelled = True
                    break

            if group_entries:
                self._write_galleries(
                    settings, group_dir,
                    f"{project_name} -- {gname}" if project_name else gname,
                    log_label="Gallery for this group",
                )

            self._build_unslated_gallery(
                settings, group_unslated_dir, group_unslated_entries,
                f"{project_name} -- {gname}" if project_name else gname,
            )

            gallery_entries.extend(
                {"filename": group_dirname + "/" + entry["filename"],
                 "shot_name": entry["shot_name"]}
                for entry in group_entries
            )

        self._log("")
        self._log(f"Covered {groups_done} group(s), {constructs_done} timeline(s).")
        # A single-group run must not rewrite the project-wide gallery -- that
        # page belongs to a full run and would be replaced by one day's stills.
        self._finish_run(settings, output_dir, project_name,
                         flag_sets, saved, failed, skipped, cancelled)

    def _grab_group_inner(self, settings):
        """Grab every timeline in the group the open timeline belongs to.

        Meant for the end of a shooting day when the earlier days are
        already captured. It writes into the same <output>/<group>/ folder
        a whole-project run would use, so a day grabbed on its own sits
        alongside days grabbed earlier instead of duplicating them.
        """
        proj_api = assimilate_client.ProjectsApi(self._make_client(settings))
        group_name = self._lookup_name(proj_api, "get_group_current", "get_groups_current")
        if not group_name:
            self._log("Couldn't tell which group is open in SCRATCH.")
            self._log("  - Open a timeline inside the group you want, then try again.")
            self.after(0, lambda: self.status_var.set("No group open"))
            return
        self._grab_project_inner(settings, only_group=group_name)

    def _build_unslated_gallery(self, settings, unslated_dir, entries, title):
        """Contact sheet for the diverted clips, inside their own folder."""
        if not (unslated_dir and entries):
            return
        self._write_galleries(
            settings, unslated_dir,
            f"{title} -- {UNSLATED_DIRNAME}" if title else UNSLATED_DIRNAME,
            log_label=f"Gallery for {UNSLATED_DIRNAME}",
            skip_dirs=(),          # this folder IS the unslated one
        )

    def _render_pairs(self, app_api, pairs, settings, naming_ctx, out_dir,
                      rel_prefix, gallery_entries, flag_sets, index_offset):
        """Render one frame for each (slot, shot) into out_dir.

        The main pass and the unslated pass both come through here, so the
        two can't drift apart in naming, numbering or resize handling.
        Returns (saved, failed, cancelled, next_offset).
        """
        project_name, group_name, construct_name, record_tc = naming_ctx
        all_unknown, all_unsupported = flag_sets
        ext = settings["file_format"].lower()
        if ext not in ("jpg", "png", "tif"):
            ext = "jpg"
        naming_pattern = settings.get("naming_pattern") or DEFAULT_SETTINGS["naming_pattern"]

        if not pairs:
            return 0, 0, False, index_offset

        os.makedirs(out_dir, exist_ok=True)
        use_proxy = settings["resolution_mode"] == "proxy"
        saved = failed = consumed = 0
        cancelled = False
        total = len(pairs)

        for i, (slot, shot) in enumerate(pairs, start=1):
            if self.cancel_event.is_set():
                self._log(f"    Cancelled after {i - 1}/{total}.")
                cancelled = True
                break
            consumed = i
            seq = index_offset + i

            frame = pick_snapshot_frame(shot, settings["frame_choice"])
            ctx = build_shot_context(
                shot, slot, frame, project_name, group_name, construct_name, record_tc, ext
            )
            rendered, unknown_flags, unsupported_flags = render_naming_pattern(naming_pattern, ctx)
            all_unknown |= unknown_flags
            all_unsupported |= unsupported_flags
            # An unslated clip renders a pattern like #scene_#take as nothing
            # but its literal separators -- "_" -- which the sanitizer then
            # strips down to its own "shot" fallback, so every such file would
            # collide on one name. Test for real characters rather than for an
            # empty string, and fall back to the clip's own name. Done before
            # the pattern is split into path segments, so the fallback name
            # lands in the filename rather than inventing a folder.
            if not any(ch.isalnum() for ch in rendered):
                rendered = shot.name or "shot"
            # A "\" or "/" in the pattern is a folder boundary, matching
            # SCRATCH's own naming module, so #group\#construct\#name writes
            # into a <group>/<construct>/ tree. Only the last segment is the
            # filename; everything before it is folders under out_dir.
            segments = render_pattern_segments(rendered)
            stem = segments[-1]
            folders = segments[:-1]
            # Without the running number the filename is whatever the pattern
            # produces, which stays stable from run to run -- so re-grabbing a
            # day overwrites its stills instead of leaving renumbered orphans.
            if settings.get("number_prefix", True):
                stem = f"{seq:02d}_{stem}"
            # The pattern may already end in a literal ".#ext" -- #ext is meant
            # to be usable inside a pattern -- so only append the extension
            # when the rendered name doesn't already carry it.
            suffix = f".{ext}"
            filename = stem if stem.lower().endswith(suffix.lower()) else stem + suffix
            out_path = unique_path(
                os.path.join(out_dir, *(folders + [filename])),
                self._used_paths,
            )
            self._used_paths.add(out_path)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            # Derive the gallery href from the path we actually wrote. Building
            # it from the segments instead would go stale whenever unique_path
            # had to rename the file, leaving a broken image link.
            fname = os.path.relpath(out_path, out_dir).replace(os.sep, "/")

            try:
                app_api.do_application_render_snapshot(
                    assimilate_client.ImageSnapshot(
                        uuid=shot.uuid, frame=frame, proxy=use_proxy, file=out_path
                    )
                )
            except ApiException as e:
                self._log(f"    [{i}/{total}] FAIL - {shot.name}: {e}")
                failed += 1
                continue

            note = ""
            if settings["resolution_mode"] == "custom":
                try:
                    self._resize_to_width(out_path, settings["custom_width"], ext)
                    note = f", resized to {settings['custom_width']}px wide"
                except Exception as e:
                    note = f" [kept full size -- resize failed: {e}]"
            self._log(f"    [{i}/{total}] OK   - {shot.name} (frame {frame}{note})")

            gallery_entries.append({"filename": rel_prefix + fname, "shot_name": shot.name})
            saved += 1

        return saved, failed, cancelled, index_offset + consumed

    def _export_construct(self, app_api, slots, settings, naming_ctx, out_dir,
                          rel_prefix, gallery_entries, flag_sets, index_offset=0,
                          unslated_dir=None, unslated_entries=None, unslated_offset=0):
        """Grab frames for a single timeline, applying the export filters.

        Shared by all three run modes so they can't drift apart. Returns a
        dict rather than a tuple -- there are too many counters now for
        positional results to stay readable.

        index_offset continues the NN_ filename numbering from a previous
        timeline, which keeps prefixes unique when several timelines share
        one group folder. unslated_dir, when set, receives the clips that
        fail the required-flag check instead of dropping them.
        """
        project_name, group_name, construct_name, record_tc = naming_ctx
        ext = settings["file_format"].lower()
        if ext not in ("jpg", "png", "tif"):
            ext = "jpg"

        pairs = [(slot, (slot.shots or [None])[0]) for slot in slots]
        skipped = sum(1 for _slot, shot in pairs if shot is None)
        pairs = [(slot, shot) for slot, shot in pairs if shot is not None]
        diverted = []

        # Length first, then last-take. Doing it the other way round would let
        # a scene whose final take is a false start lose its frame entirely;
        # this way it falls back to the last take that's actually long enough.
        minimum = int(settings.get("min_length") or 0) if settings.get("skip_short") else 0
        if minimum > 0:
            before = len(pairs)
            pairs = [
                (slot, shot) for slot, shot in pairs
                if not isinstance(getattr(shot, "length", None), int)
                or shot.length >= minimum
            ]
            dropped = before - len(pairs)
            if dropped:
                self._short_skipped = getattr(self, "_short_skipped", 0) + dropped
                self._log(f"    shorter than {minimum} frames: {dropped} clip(s) skipped")

        # Clips whose required flags come back empty -- an unslated clip has no
        # #scene or #take, media that went offline has no #file. Reuses the
        # same flag handlers the naming pattern uses.
        if settings.get("skip_missing_flags") and pairs:
            required, unrecognised = parse_flag_list(settings.get("require_flags", ""))
            if unrecognised:
                self._log(
                    "    note: ignoring unrecognised flag(s): "
                    + ", ".join("#" + f for f in unrecognised)
                )
            if not required:
                self._log(
                    "    note: no recognised flags to require, so nothing was skipped "
                    "on that basis."
                )
            else:
                kept = []
                for slot, shot in pairs:
                    frame = pick_snapshot_frame(shot, settings["frame_choice"])
                    ctx = build_shot_context(
                        shot, slot, frame, project_name, group_name,
                        construct_name, record_tc, ext,
                    )
                    if all(
                        str(AVAILABLE_FLAGS[name](ctx, None) or "").strip()
                        for name in required
                    ):
                        kept.append((slot, shot))
                    else:
                        diverted.append((slot, shot))
                pairs = kept
                if diverted:
                    where = "moved to %s/" % UNSLATED_DIRNAME if unslated_dir else "skipped"
                    self._missing_flag_skipped = getattr(self, "_missing_flag_skipped", 0) + len(diverted)
                    self._log(
                        "    missing %s: %d clip(s) %s"
                        % (" / ".join("#" + f for f in required), len(diverted), where)
                    )

        if settings.get("last_take_only"):
            before = len(pairs)
            pairs = select_last_takes(pairs)
            if before != len(pairs):
                self._log(f"    last take of each scene: {before} shot(s) -> {len(pairs)}")

        saved, failed, cancelled, next_offset = self._render_pairs(
            app_api, pairs, settings, naming_ctx, out_dir, rel_prefix,
            gallery_entries, flag_sets, index_offset,
        )

        # The diverted clips go to their own folder with their own numbering
        # and their own gallery, so the main contact sheet stays clean while
        # nothing is silently thrown away.
        unslated_saved = 0
        next_unslated = unslated_offset
        if diverted and unslated_dir is not None and unslated_entries is not None and not cancelled:
            self._log(f"    {len(diverted)} clip(s) -> {UNSLATED_DIRNAME}/")
            unslated_saved, u_failed, u_cancelled, next_unslated = self._render_pairs(
                app_api, diverted, settings, naming_ctx, unslated_dir, "",
                unslated_entries, flag_sets, unslated_offset,
            )
            failed += u_failed
            cancelled = cancelled or u_cancelled

        return {
            "saved": saved,
            "failed": failed,
            "skipped": skipped,
            "cancelled": cancelled,
            "next_offset": next_offset,
            "unslated_saved": unslated_saved,
            "next_unslated_offset": next_unslated,
        }

    def _finish_run(self, settings, output_dir, title,
                    flag_sets, saved, failed, skipped, cancelled):
        """Gallery, flag notes and the closing summary -- shared by all modes."""
        all_unknown, all_unsupported = flag_sets

        # Written after every run now, including a single group or timeline.
        # The old reason for suppressing it -- that one day's stills would
        # replace a whole-project sheet -- is gone, because the sheet is built
        # from the folder rather than from this run.
        self._write_galleries(settings, output_dir, title)

        self._log("")
        for flag in sorted(all_unsupported):
            self._log(
                f"Note: #{flag} is a real SCRATCH flag, but not supported here yet "
                f"({KNOWN_UNSUPPORTED_FLAGS[flag]}) -- left blank."
            )
        if all_unknown:
            flag_list = ", ".join(f"#{f}" for f in sorted(all_unknown))
            self._log(
                f"Note: naming pattern used flag(s) not recognized (check spelling, left blank): {flag_list}"
            )
        summary = f"{saved} saved, {failed} failed, {skipped} empty slot(s) skipped"
        short_skipped = getattr(self, "_short_skipped", 0)
        if short_skipped:
            minimum = int(settings.get("min_length") or 0)
            summary += f", {short_skipped} clip(s) under {minimum} frames skipped"
        missing_flags = getattr(self, "_missing_flag_skipped", 0)
        if missing_flags:
            where = (
                f"moved to {UNSLATED_DIRNAME}/"
                if settings.get("unslated_subfolder") else "skipped"
            )
            summary += f", {missing_flags} clip(s) missing required flags {where}"
        self._log(("Cancelled. " if cancelled else "Done. ") + summary + ".")
        self._log(f"Folder: {output_dir}")
        status = f"Cancelled - {saved} saved" if cancelled else f"Done - {saved} saved"
        self.after(0, lambda: self.status_var.set(status))


def main():
    app = FrameGrabberApp()
    app.mainloop()


if __name__ == "__main__":
    main()
