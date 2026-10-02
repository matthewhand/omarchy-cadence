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
STATE = os.environ.get("OMARCHY_SCREENSAVER_STATE", os.path.join(HERE, "state.jsonc"))
PLAN = os.path.expanduser("~/.cache/omarchy/cadence/resolved.plan")

BOOLEAN_KEYS = ("notifications_enabled",)
INT_KEYS = ("interval", "notify_cycles", "width", "height")
STRING_KEYS = ("mode",)


def strip_jsonc(text):
    """Accept hand-edited JSONC: drop // and /* */ comments and trailing commas.

    Python's json module rejects both, and this file is meant to be edited by a
    human, so comments are worth allowing. Kept deliberately small and dependency
    free rather than pulling in a JSONC parser.
    """
    out = []
    index, length = 0, len(text)
    in_string = escape = False
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index += 2
            continue
        out.append(char)
        index += 1
    import re as _re
    return _re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_jsonc(path):
    try:
        with open(path) as handle:
            return json.loads(strip_jsonc(handle.read()))
    except (OSError, json.JSONDecodeError):
        return None


def load_state():
    data = load_jsonc(STATE)
    return data if isinstance(data, dict) else {}


def save_state(data):
    """Update keys in place so hand-written comments survive.

    A json.load/json.dump round trip is simpler but rewrites the whole file, which
    silently deletes every comment the user wrote in this JSONC file -- exactly what
    the .jsonc choice was meant to avoid. So this edits surgically: known keys are
    rewritten on their own line, unknown ones inserted before the closing brace,
    and every other line (comments, blank lines, ordering) is left untouched.
    """
    import re

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    try:
        with open(STATE) as handle:
            lines = handle.read().splitlines()
    except OSError:
        lines = []

    body = "\n".join(lines)

    # Rewrite a key that already has its own line.
    for position, line in enumerate(lines):
        match = re.match(r'^(\s*)"([A-Za-z_][A-Za-z0-9_]*)"\s*:', line)
        if match and match.group(2) in data:
            key = match.group(2)
            trailing = "," if line.rstrip().endswith(",") else ""
            lines[position] = f'{match.group(1)}"{key}": {json.dumps(data[key])}{trailing}'
            data.pop(key, None)
            body = "\n".join(lines)
            break

    if not data:
        return _write_state(lines)

    # Anything left is new. Insert inside the object, never after the closing brace.
    close = None
    for position in range(len(lines) - 1, -1, -1):
        if lines[position].strip() in ("}", "},"):
            close = position
            break

    for key, value in data.items():
        if f'"{key}"' in body:
            continue
        entry = f'  "{key}": {json.dumps(value)}'
        if close is None:
            lines.append(entry)
            continue
        if close > 0:
            previous = lines[close - 1].rstrip()
            # Never append a comma to a comment: it is stripped before parsing, so
            # it is harmless, but rewriting someone's prose is rude.
            is_comment = previous.lstrip().startswith(("//", "/*", "*"))
            if previous and not is_comment and not previous.endswith((",", "{", "[")):
                lines[close - 1] = previous + ","
        lines.insert(close, entry)
        close += 1

    return _write_state(lines)


def _write_state(lines):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as handle:
        handle.write("\n".join(lines).rstrip("\n") + "\n")
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
    # ttfx is not a continuous signal: a short effect finishes and cadence rotates,
    # so there are gaps with no ttfx at all. The runner process is the honest test
    # for "the screensaver is up".
    for probe in (["pgrep", "-f", "bin/omarchy-screensaver-cadence"],):
        try:
            out = subprocess.run(probe, capture_output=True, timeout=5)
            if out.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
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