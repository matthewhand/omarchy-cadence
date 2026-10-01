#!/usr/bin/env python3
"""Render the newest queued desktop notification as a cadence slide.

Pops nothing: each notification keeps a `seen` counter so it stays in the queue
until it has been shown `CADENCE_CYCLES` times, then it is dropped. That is what
makes a notification linger for several rotations instead of flashing past once.

Exits non-zero when there is nothing left to show, so cadence skips the slide.
"""
import importlib.util
import json
import os
import sys
import textwrap
import time


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
    return None


wordfont = load_wordfont()

QUEUE = os.environ.get("CADENCE_QUEUE", "")
CYCLES = int(os.environ.get("CADENCE_CYCLES", "8"))
MAX_AGE = 3600  # a notification older than this is not worth showing


def load():
    if not QUEUE or not os.path.exists(QUEUE):
        return []
    rows = []
    with open(QUEUE) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def save(rows):
    tmp = QUEUE + ".tmp"
    with open(tmp, "w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    os.replace(tmp, QUEUE)


def clean(text, limit=400):
    text = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in (text or ""))
    return " ".join(text.split())[:limit]


def headline(summary, width):
    """Big block-font headline when the summary is short, plain text otherwise."""
    summary = summary.upper()
    if wordfont and summary and len(summary) <= 14 and all(c in wordfont.FONT for c in summary):
        try:
            return wordfont.render(summary, width).rstrip("\n").split("\n")
        except SystemExit:
            pass
    return textwrap.wrap(summary or "NOTIFICATION", width=width) or ["NOTIFICATION"]


def main():
    rows = load()
    now = time.time()

    # Expire old entries and drop anything already shown enough times.
    kept = [r for r in rows if now - r.get("ts", 0) < MAX_AGE and r.get("seen", 0) < CYCLES]
    showable = [r for r in kept if r.get("summary") or r.get("body")]
    if len(kept) != len(rows):
        save(kept)
    if not showable:
        sys.exit(1)

    entry = showable[-1]
    entry["seen"] = entry.get("seen", 0) + 1
    save(kept)

    app = clean(entry.get("app"), 40) or "DESKTOP"
    body = clean(entry.get("body"), 300)

    lines = []
    lines += headline(clean(entry.get("summary"), 60), 76)
    lines.append("")
    if body:
        wrapped = textwrap.wrap(body, width=74)
        lines += wrapped[:7]
        if len(wrapped) > 7:
            lines.append("...")
        lines.append("")
    stamp = time.strftime("%H:%M", time.localtime(entry.get("ts", now)))
    lines.append(f"{app}  {stamp}  [shown {entry['seen']}/{CYCLES}]")

    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
