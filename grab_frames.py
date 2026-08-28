"""
grab_frames.py
---------------
Saves one still frame from every shot in the currently-open SCRATCH
timeline, as JPEGs, into a folder called "scratch_frames" on your Desktop.

HOW TO RUN THIS
1. Open SCRATCH, open the project, and load the timeline you want frames from.
2. Make sure the REST API is still enabled (System Settings) and running
   on port 8080 (the default).
3. One-time setup, in Terminal / Command Prompt:
       macOS / Linux:  pip3 install git+https://github.com/Assimilate-Inc/Assimilate-REST.git
       Windows:        py -m pip install git+https://github.com/Assimilate-Inc/Assimilate-REST.git
4. Every time you want to run it, from the folder you saved this file in:
       macOS / Linux:  python3 grab_frames.py
       Windows:        py grab_frames.py

   (No Python at all yet? Get it from python.org/downloads. On Windows,
   tick "Add python.exe to PATH" during install, then reopen your terminal
   window before trying again.)

If SCRATCH has an access key set (System Settings > REST API), paste it
into ACCESS_KEY below. If not, leave it as None.
"""

import os
import assimilate_client
from assimilate_client.rest import ApiException

# ---- settings you might want to change ----------------------------------
HOST = "http://localhost:8080/APIV2"   # default SCRATCH REST API address
ACCESS_KEY = None                       # e.g. "abc123" if you set one, else None
OUTPUT_DIR = os.path.expanduser("~/Desktop/scratch_frames")
USE_PROXY_RES = False                    # True = fast/small, False = full resolution
# ---------------------------------------------------------------------------

configuration = assimilate_client.Configuration()
configuration.host = HOST
if ACCESS_KEY:
    configuration.api_key["Authorization"] = ACCESS_KEY

client = assimilate_client.ApiClient(configuration)
app_api = assimilate_client.ApplicationApi(client)
proj_api = assimilate_client.ProjectsApi(client)


def safe_filename(text):
    keep = "-_ "
    return "".join(c if c.isalnum() or c in keep else "_" for c in text).strip() or "shot"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        slots_data = proj_api.get_construct_current_slots(level="ALL")
    except ApiException as e:
        print("Couldn't reach SCRATCH's open timeline.")
        print("  - Is SCRATCH running with a project and timeline open?")
        print("  - Is the REST API still enabled in System Settings?")
        print(f"  - Details: {e}")
        return
    except Exception as e:
        print("Couldn't connect to SCRATCH at", HOST)
        print("  - Is SCRATCH running with the REST API turned on?")
        print(f"  - Details: {e}")
        return

    slots = slots_data.slots or []
    if not slots:
        print("No slots found in the current timeline. Is one open in SCRATCH?")
        return

    print(f"Found {len(slots)} slot(s) in the open timeline. Grabbing frames...")

    saved, failed, skipped = 0, 0, 0
    for i, slot in enumerate(slots, start=1):
        # a Slot can hold more than one Shot stacked in it (alternate takes);
        # we grab the first one, which is the one shown in the timeline
        slot_shots = slot.shots or []
        if not slot_shots:
            print(f"  [{i}/{len(slots)}] SKIP - slot '{slot.name}' has no shot in it")
            skipped += 1
            continue

        shot = slot_shots[0]

        # middle frame of the shot, so we get an actual picture rather than
        # a first-frame handle that might be black or a slate
        frame = (shot.length // 2) if shot.length else 0
        name = safe_filename(shot.name or shot.uuid)
        out_path = os.path.join(OUTPUT_DIR, f"{i:02d}_{name}_f{frame}.jpg")

        snapshot = assimilate_client.ImageSnapshot(
            uuid=shot.uuid,
            frame=frame,
            proxy=USE_PROXY_RES,
            file=out_path,
        )

        try:
            app_api.do_application_render_snapshot(snapshot)
            print(f"  [{i}/{len(slots)}] OK  - {shot.name}  (frame {frame}) -> {out_path}")
            saved += 1
        except ApiException as e:
            print(f"  [{i}/{len(slots)}] FAIL - {shot.name}: {e}")
            failed += 1

    print()
    print(f"Done: {saved} frame(s) saved, {failed} failed, {skipped} empty slot(s) skipped.")
    print("Folder:", OUTPUT_DIR)


if __name__ == "__main__":
    main()