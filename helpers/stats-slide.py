#!/usr/bin/env python3
"""Dynamic screensaver slide: clock, date and weather in the SurfaceBook font.

Rendered in the same 6x8 half-block font as the static word art so the rotating
slides look like one set. ASCII only: the weather comes from omarchy's own
commands, which emit non-ASCII glyphs (degree sign, Nerd Font icons) that would
render inconsistently depending on the effect ttfx picks.
"""
import datetime
import importlib.util
import os
import subprocess
import sys


def load_wordfont():
    """Find the block-font renderer: env override, workspace copy, then sibling."""
    candidates = [
        os.environ.get("CADENCE_WORD_FONT"),
        os.path.expanduser("~/omarchy.local/tools/word-to-ascii.py"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "wordfont.py"),
    ]
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        spec = importlib.util.spec_from_file_location("wordfont", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    sys.exit("stats-slide: block font not found (set CADENCE_WORD_FONT)")


wordfont = load_wordfont()


def ascii_only(text):
    table = {"°": "", "·": "-", "↘": "v", "↗": "^", "↑": "^", "↓": "v",
             "→": ">", "←": "<", " ": " "}
    for src, dst in table.items():
        text = text.replace(src, dst)
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)


def run(cmd, timeout=8):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def main():
    now = datetime.datetime.now()
    lines = []

    clock = wordfont.render(now.strftime("%H:%M")).rstrip("\n").split("\n")
    lines += clock
    lines.append("")

    lines.append(now.strftime("%A").upper())
    lines.append(now.strftime("%d %B %Y").upper())
    lines.append("")

    weather = ascii_only(run(["omarchy-weather-status"]))
    lines.append(weather if weather else "WEATHER UNAVAILABLE")

    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
