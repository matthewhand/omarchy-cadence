#!/usr/bin/env python3
"""Read and change cadence's runtime switches for the bar widget.

Kept separate from cadence-config.py on purpose. That file resolves config into
the plan the runner consumes; this one answers "what is true right now" and
writes deliberate toggles. Toggles land in state.json, never in cadence.yaml, so
a switch flipped in the bar can always be undone by deleting one small file
instead of reconstructing the config from memory.

Usage:
  cadence-ctl.py status                 print one JSON object for the widget
  cadence-ctl.py set KEY VALUE         set notifications_enabled|interval|mode
  cadence-ctl.py config                print the resolved plan
  cadence-ctl.py edit-config           open cadence.yaml in $EDITOR
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.environ.get(
    "OMARCHY_SCREENSAVER_CONFIG", os.path.join(HERE, "cadence.yaml"))
STATE = os.environ.get("OMARCHY_SCREENSAVER_STATE", os.path.join(HERE, "state.json"))
PLAN = os.path.expanduser("~/.cache/omarchy/cadence/resolved.plan")

BOOLEAN_KEYS = ("notifications_enabled",)
INT_KEYS = ("interval", "notify_cycles", "width", "height")
STRING_KEYS = ("mode",)


def load_state():
    try:
        with open(STATE) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(data):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, STATE)


def coerce(key, raw):
    if key in BOOLEAN_KEYS:
        return str(raw).lower() in ("1", "true", "yes", "on")
    if key in INT_KEYS:
        return int(raw)
    if key in STRING_KEYS:
        return str(raw)
    raise SystemExit(f"cadence-ctl: unknown key: {key}")


def resolved():
    """Ask the resolver for the current plan so status matches what runs."""
    try:
        out = subprocess.run(
            ["python3", os.path.join(HERE, "cadence-config.py"),
             "--config", CONFIG, "--state", STATE],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return [line for line in out.stdout.splitlines() if line.strip()]


def status():
    plan = resolved()
    state = load_state()
    slides = []
    if plan:
        for line in plan:
            kind = line.split(" ", 1)[0]
            if kind in ("text", "image", "images", "exec", "notify"):
                slides.append(kind)
    interval = state.get("interval", 20)
    for line in plan or []:
        if line.startswith("set interval="):
            interval = int(line.split("=", 1)[1])
    notifications = any(kind == "notify" for kind in slides)
    return {
        "ok": True,
        "data": {
            "configured": plan is not None,
            "config": CONFIG,
            "state": STATE,
            "slides": len(slides),
            "kinds": slides,
            "interval": interval,
            "notifications": notifications,
            "running": screensaver_running(),
        }
    }


def screensaver_running():
    try:
        out = subprocess.run(["pgrep", "-x", "ttfx"], capture_output=True, timeout=5)
        return out.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main():
    args = sys.argv[1:]
    if not args or args[0] == "status":
        print(json.dumps(status(), separators=(",", ":")))
        return 0

    command = args[0]

    if command == "set":
        if len(args) != 3:
            raise SystemExit("cadence-ctl: usage: set KEY VALUE")
        key, raw = args[1], args[2]
        state = load_state()
        state[key] = coerce(key, raw)
        save_state(state)
        print(json.dumps(status(), separators=(",", ":")))
        return 0

    if command == "config":
        plan = resolved()
        if plan is None:
            print(f"cadence-ctl: cannot resolve {CONFIG}", file=sys.stderr)
            return 1
        print("\n".join(plan))
        return 0

    if command == "edit-config":
        editor = os.environ.get("EDITOR") or "nvim"
        subprocess.Popen([editor, CONFIG], start_new_session=True)
        return 0

    raise SystemExit(f"cadence-ctl: unknown command: {command}")


if __name__ == "__main__":
    sys.exit(main())