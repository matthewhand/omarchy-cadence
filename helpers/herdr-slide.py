#!/usr/bin/env python3
"""Render herdr agent status as a cadence slide, coloured by state.

Writes the art to stdout and ttfx arguments to $CADENCE_FLAGS. ttfx chooses its
effect and gradient when it starts and cannot change them mid-run, so the colour
is decided here, once per rotation, and applied by the restart cadence already
performs between slides.

Exits non-zero when herdr is not running, so cadence skips the slide.
"""
import json
import os
import subprocess
import sys
import textwrap
import time

# ttfx wants space separated, unquoted hex colours.
THEMES = {
    "waiting": "highlight --final-gradient-stops FFF75D FE650D E4002B",
    "busy": "fireworks --final-gradient-stops 00D1FF 8A008A",
    "idle": "colorshift --gradient-stops 0D3B66 1A6E8E 2FB5A0",
}
LABELS = {
    "waiting": "AGENT WAITING FOR INPUT",
    "busy": "AGENT PROCESSING",
    "idle": "ALL AGENTS IDLE",
}


def classify(state):
    s = str(state).lower()
    if any(k in s for k in ("wait", "input", "attn", "need", "prompt")):
        return "waiting"
    if any(k in s for k in ("run", "busy", "work", "proc", "exec", "active", "thinking")):
        return "busy"
    return "idle"


def walk(node, found):
    """Collect (name, state) pairs without assuming herdr's exact schema."""
    if isinstance(node, dict):
        state = node.get("state") or node.get("status")
        if state is not None:
            name = node.get("name") or node.get("title") or node.get("id") or "agent"
            found.append((str(name), classify(state)))
        for value in node.values():
            walk(value, found)
    elif isinstance(node, list):
        for item in node:
            walk(item, found)


def main():
    try:
        proc = subprocess.run(
            ["herdr", "api", "snapshot"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        sys.exit(1)
    if proc.returncode != 0 or not proc.stdout.strip():
        sys.exit(1)

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit(1)

    found = []
    walk(data, found)
    # Drop duplicates while preserving order.
    seen = set()
    agents = []
    for name, kind in found:
        if (name, kind) in seen:
            continue
        seen.add((name, kind))
        agents.append((name, kind))

    if not agents:
        sys.exit(1)

    # Waiting for input outranks busy, which outranks idle.
    for level in ("waiting", "busy", "idle"):
        if any(kind == level for _, kind in agents):
            overall = level
            break

    lines = ["", LABELS[overall], ""]
    for name, kind in agents[:8]:
        lines.append(f"  {name[:44]:<44} {kind.upper()}")
    if len(agents) > 8:
        lines.append(f"  ... and {len(agents) - 8} more")
    lines.append("")
    lines.append(f"{len(agents)} agent(s)  {time.strftime('%H:%M')}")

    flags = os.environ.get("CADENCE_FLAGS")
    if flags:
        try:
            with open(flags, "w") as handle:
                handle.write(THEMES[overall])
        except OSError:
            pass

    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
