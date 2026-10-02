#!/usr/bin/env python3
"""Resolve cadence's YAML config into the line format the runner understands.

The runner is bash, and bash cannot parse YAML without extra tools. Rather than
drag in a dependency, this helper reads the config and prints the same line
format cadence has always used, so there is exactly one parser and the original
format stays valid input.

Toggle state (notifications on/off, and similar) lives in a separate JSON file
rather than being written back into the YAML: rewriting YAML with PyYAML would
drop every comment and reorder keys, which quietly ruins a config file people
edit by hand. So YAML is the intent, state.json is the current switch position,
and deleting state.json always returns to the config as written.

Usage:
  cadence-config.py [--config PATH] [--state PATH] [--check]

Prints the resolved plan to stdout. With --check, validates and prints nothing
but a summary, for the bar widget and for `install.sh`.
"""

import argparse
import json
import os
import shlex
import sys

DEFAULTS = {
    "interval": 20,
    "mode": "block",
    "width": 80,
    "height": 26,
    "notify_cycles": 8,
}

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".svg", ".webp")


def expand(path):
    return os.path.expanduser(os.path.expandvars(str(path)))


def note(message):
    print(f"cadence-config: {message}", file=sys.stderr)


def entry_lines(entry, default_mode):
    """One slide entry -> zero or more plan lines.

    An entry is a single-key mapping, so the key names the kind:
      ascii: PATH             text PATH
      image: PATH             image PATH [MODE]
      images: PATH            images PATH [MODE]   (a folder, watched live)
      command: CMD            exec CMD
      notify: true            notify
    An optional `mode` and `enabled` may accompany any of them.
    """
    if not isinstance(entry, dict):
        note(f"ignoring slide entry that is not a mapping: {entry!r}")
        return []

    mode = entry.get("mode", default_mode)
    if entry.get("enabled") is False:
        return []

    if "ascii" in entry:
        path = expand(entry["ascii"])
        if not os.path.isfile(path):
            note(f"ascii file not found, skipping: {path}")
            return []
        return [f"text {shlex.quote(path)}"]

    if "image" in entry:
        path = expand(entry["image"])
        if not os.path.isfile(path):
            note(f"image not found, skipping: {path}")
            return []
        return [f"image {shlex.quote(path)} {mode}"]

    if "images" in entry:
        path = expand(entry["images"])
        if not os.path.isdir(path):
            note(f"image folder not found, skipping: {path}")
            return []
        found = [
            f for f in sorted(os.listdir(path))
            if f.lower().endswith(IMAGE_SUFFIXES)
            and os.path.isfile(os.path.join(path, f))
        ]
        if not found:
            note(f"no images in folder yet, it will be watched: {path}")
        # Emitted as `images` rather than expanded to `image` lines, so cadence's
        # directory watcher picks up anything added later without a restart.
        return [f"images {shlex.quote(path)} {mode}"]

    if "command" in entry:
        return [f"exec {entry['command']}"]

    if entry.get("notify") is True:
        return ["notify"]

    note(f"ignoring slide entry with no recognised key: {entry!r}")
    return []


def resolve(config, state):
    lines = []
    slides = []

    def setting(key, cast=int):
        value = state.get(key, config.get(key, DEFAULTS[key]))
        try:
            return cast(value)
        except (TypeError, ValueError):
            note(f"invalid value for {key}: {value!r}, using default")
            return DEFAULTS[key]

    # Notifications are read first because `cycles` also drives a set line, and
    # the notification slide itself is appended last so the rotation reads in the
    # order the config lists things.
    notifications = config.get("notifications", {})
    if not isinstance(notifications, dict):
        notifications = {}
    notifications_enabled = notifications.get("enabled", True)
    # state.json wins over the config, so the bar toggle is reversible.
    if "notifications_enabled" in state:
        notifications_enabled = bool(state["notifications_enabled"])
    if notifications.get("cycles") is not None:
        try:
            DEFAULTS["notify_cycles"] = int(notifications["cycles"])
        except (TypeError, ValueError):
            note(f"invalid notifications.cycles: {notifications['cycles']!r}")

    interval = setting("interval")
    mode = str(state.get("mode", config.get("mode", DEFAULTS["mode"])))
    width = setting("width")
    height = setting("height")
    notify_cycles = setting("notify_cycles")

    lines += [
        f"set interval={interval}",
        f"set mode={mode}",
        f"set width={width}",
        f"set height={height}",
        f"set notify_cycles={notify_cycles}",
    ]

    primary = config.get("primary") or []
    if isinstance(primary, dict):
        primary = [primary]
    fallback = config.get("fallback") or []
    if isinstance(fallback, dict):
        fallback = [fallback]

    if primary or fallback:
        # Groups take precedence: the flat keys are ignored entirely, otherwise
        # the same ascii/image entries would appear in both fallback and the flat
        # list and rotate twice.
        lines.append("group primary")
        for entry in primary:
            lines += entry_lines(
                entry if isinstance(entry, dict) else {"notify": True}, mode)
        lines.append("group fallback")
        for entry in (fallback or []):
            lines += entry_lines(entry, mode)
    else:
        # Grouped shorthands: 1+ ascii, 1+ images, 1+ dynamic commands.
        slides = []
        for path in config.get("ascii", []) or []:
            slides.append({"ascii": path})
        for path in config.get("images", []) or []:
            slides.append({"images": path})
        for path in config.get("image", []) or []:
            slides.append({"image": path})
        for item in config.get("dynamic", []) or []:
            slides.append({"command": item} if isinstance(item, str) else item)

        # An explicit ordered list wins, and may mix every kind.
        if isinstance(config.get("slides"), list) and config["slides"]:
            slides = config["slides"]

        for entry in slides:
            lines += entry_lines(entry, mode)

    # Only add the implicit notification slide when the config has not already
    # listed one. Appending it after a `group` marker would silently file it under
    # whichever group was declared last, which is how it ended up in fallback too.
    if notifications_enabled:
        if "notify" not in lines:
            lines.append("notify")
    else:
        # The toggle governs notifications wherever they are listed. Without this,
        # `primary: [notify]` kept emitting a notification slide even with the
        # toggle off, because only the implicit append was conditional.
        lines = [line for line in lines if line != "notify"]

    # Count what actually became a slide, so --check and the widget never claim a
    # slide that was skipped for a missing file.
    emitted = sum(
        1 for line in lines
        if line.split(" ", 1)[0] in ("text", "image", "images", "exec", "notify")
    )
    return lines, emitted


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


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        note("PyYAML is not installed; cadence.yaml cannot be read")
        return None
    try:
        with open(path) as handle:
            data = yaml.safe_load(handle)
    except OSError as error:
        note(f"cannot read {path}: {error}")
        return None
    except yaml.YAMLError as error:
        note(f"{path} is not valid YAML: {error}")
        return None
    if data is None:
        return {}
    if not isinstance(data, dict):
        note(f"{path} must contain a mapping at the top level")
        return None
    return data


def load_state(path):
    data = load_jsonc(path)
    return data if isinstance(data, dict) else {}


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--config", default=os.path.expanduser(
        "~/.config/omarchy/screensaver/cadence.yaml"))
    parser.add_argument("--state", default=os.path.expanduser(
        "~/.config/omarchy/screensaver/state.jsonc"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if not os.path.isfile(args.config):
        note(f"no config at {args.config}")
        return 2

    config = load_yaml(args.config)
    if config is None:
        return 1

    state = load_state(args.state)
    lines, count = resolve(config, state)

    if args.check:
        print(f"ok: {count} slide(s) from {args.config}")
        return 0

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())