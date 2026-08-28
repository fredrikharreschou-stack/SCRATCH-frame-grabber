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
    from PIL import Image
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
    "last_take_only": False,
    "skip_short": True,
    "min_length": 200,
    "number_prefix": True,
}


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
    f = ctx["shot"].file or ""
    base = os.path.splitext(os.path.basename(f))[0] if f else ""
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
        self.geometry("660x920")
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
                "SCRATCH offers that this API can't supply yet are simply left blank."
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

        # HTML gallery of the exported frames
        self.gallery_var = BooleanVar(value=self.settings.get("make_gallery", True))
        ctk.CTkCheckBox(
            card,
            text="Also build an HTML gallery page of the exported frames",
            variable=self.gallery_var,
        ).grid(row=9, column=0, columnspan=3, sticky="w", padx=(18, 18), pady=(0, 18))

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
            "last_take_only": bool(self.last_take_var.get()),
            "skip_short": bool(self.skip_short_var.get()),
            "min_length": min_length,
            "number_prefix": bool(self.number_prefix_var.get()),
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
        self._used_paths = set()
        output_dir = os.path.expanduser(settings["output_dir"])
        os.makedirs(output_dir, exist_ok=True)

        client = self._make_client(settings)
        app_api = assimilate_client.ApplicationApi(client)
        proj_api = assimilate_client.ProjectsApi(client)

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
        saved, failed, skipped, cancelled, _next = self._export_construct(
            app_api, slots, settings, naming_ctx, output_dir, "",
            gallery_entries, flag_sets,
        )
        self._finish_run(settings, output_dir, gallery_entries, naming_ctx[2],
                         flag_sets, saved, failed, skipped, cancelled)

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
        self._used_paths = set()
        output_dir = os.path.expanduser(settings["output_dir"])
        os.makedirs(output_dir, exist_ok=True)

        client = self._make_client(settings)
        app_api = assimilate_client.ApplicationApi(client)
        proj_api = assimilate_client.ProjectsApi(client)

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
                s, f, sk, c, group_index = self._export_construct(
                    app_api, slots, settings, naming_ctx,
                    group_dir, "", group_entries, flag_sets,
                    index_offset=group_index,
                )
                saved += s
                failed += f
                skipped += sk
                if c:
                    cancelled = True
                    break

            if settings.get("make_gallery") and group_entries:
                try:
                    title = f"{project_name} -- {gname}" if project_name else gname
                    path = build_html_gallery(group_dir, group_entries, title)
                    self._log(f"  Gallery for this group: {path}")
                except Exception as e:
                    self._log(f"  Note: couldn't build the gallery for '{gname}': {e}")

            gallery_entries.extend(
                {"filename": group_dirname + "/" + entry["filename"],
                 "shot_name": entry["shot_name"]}
                for entry in group_entries
            )

        self._log("")
        self._log(f"Covered {groups_done} group(s), {constructs_done} timeline(s).")
        # A single-group run must not rewrite the project-wide gallery -- that
        # page belongs to a full run and would be replaced by one day's stills.
        self._finish_run(settings, output_dir, gallery_entries, project_name,
                         flag_sets, saved, failed, skipped, cancelled,
                         write_gallery=(only_group is None))

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

    def _export_construct(self, app_api, slots, settings, naming_ctx, out_dir,
                          rel_prefix, gallery_entries, flag_sets, index_offset=0):
        """Grab one frame per slot for a single timeline.

        Shared by both the open-timeline and whole-project runs so the two
        can't drift apart. Returns (saved, failed, skipped, cancelled).
        rel_prefix is prepended to each gallery filename so a gallery page
        one level up can still find the images.

        index_offset continues the NN_ filename numbering from a previous
        timeline, which is what keeps prefixes unique when several
        timelines share one group folder. Returns the offset to hand to
        the next timeline as the fifth value.
        """
        project_name, group_name, construct_name, record_tc = naming_ctx
        all_unknown, all_unsupported = flag_sets

        ext = settings["file_format"].lower()
        if ext not in ("jpg", "png", "tif"):
            ext = "jpg"
        naming_pattern = settings.get("naming_pattern") or DEFAULT_SETTINGS["naming_pattern"]

        pairs = [(slot, (slot.shots or [None])[0]) for slot in slots]
        skipped = sum(1 for _slot, shot in pairs if shot is None)
        pairs = [(slot, shot) for slot, shot in pairs if shot is not None]

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

        if settings.get("last_take_only"):
            before = len(pairs)
            pairs = select_last_takes(pairs)
            if before != len(pairs):
                self._log(f"    last take of each scene: {before} shot(s) -> {len(pairs)}")

        if not pairs:
            return 0, 0, skipped, False, index_offset

        os.makedirs(out_dir, exist_ok=True)
        use_proxy = settings["resolution_mode"] == "proxy"
        saved = failed = 0
        cancelled = False
        total = len(pairs)

        consumed = 0
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
            # Without the running number the filename is whatever the pattern
            # produces, which stays stable from run to run -- so re-grabbing a
            # day overwrites its stills instead of leaving renumbered orphans.
            stem = sanitize_full_filename(rendered)
            if settings.get("number_prefix", True):
                stem = f"{seq:02d}_{stem}"
            out_path = unique_path(
                os.path.join(out_dir, f"{stem}.{ext}"),
                self._used_paths,
            )
            self._used_paths.add(out_path)
            fname = os.path.basename(out_path)

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

        return saved, failed, skipped, cancelled, index_offset + consumed

    def _finish_run(self, settings, output_dir, gallery_entries, title,
                    flag_sets, saved, failed, skipped, cancelled,
                    write_gallery=True):
        """Gallery, flag notes and the closing summary -- shared by all modes."""
        all_unknown, all_unsupported = flag_sets

        if write_gallery and settings.get("make_gallery") and gallery_entries:
            try:
                gallery_path = build_html_gallery(output_dir, gallery_entries, title)
                self._log(f"Gallery: {gallery_path}")
            except Exception as e:
                self._log(f"Note: couldn't build the HTML gallery page: {e}")

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
        self._log(("Cancelled. " if cancelled else "Done. ") + summary + ".")
        self._log(f"Folder: {output_dir}")
        status = f"Cancelled - {saved} saved" if cancelled else f"Done - {saved} saved"
        self.after(0, lambda: self.status_var.set(status))


def main():
    app = FrameGrabberApp()
    app.mainloop()


if __name__ == "__main__":
    main()
