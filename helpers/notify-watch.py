#!/usr/bin/env python3
"""Watch the freedesktop notification bus and queue notifications for cadence.

Omarchy serves org.freedesktop.Notifications from quickshell, not mako or dunst,
so watching the bus works regardless of which daemon is running.

Notify is a *method call* on the bus, not a signal, so it cannot be received with
a signal subscription -- it has to be eavesdropped. That is what dbus-monitor
does, so this runs it and parses the argument list. In order, the string
arguments of Notify are: app_name, app_icon, summary, body; the other arguments
are a uint32, an actions array, a hints dict and an int32, none of which are
strings and so are skipped by the parser.
"""
import json
import os
import subprocess
import sys
import time

QUEUE = os.path.expanduser(
    os.environ.get("CADENCE_QUEUE", "~/.cache/omarchy/cadence/notifications.jsonl")
)
KEEP = 20

BUS_ARGS = [
    "dbus-monitor",
    "--session",
    "interface='org.freedesktop.Notifications',member='Notify'",
]


def append(app, summary, body):
    if not summary and not body:
        return
    entry = {
        "app": app.split(".")[0] if app else "desktop",
        "summary": summary,
        "body": body,
        "ts": time.time(),
        "seen": 0,
    }
    os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
    with open(QUEUE, "a") as handle:
        handle.write(json.dumps(entry) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    # Trim the tail so the queue cannot grow without bound.
    #
    # Written to a temp file and renamed, not truncated in place. Truncating with
    # open(QUEUE, "w") leaves the file empty or half-written for as long as the
    # rewrite takes, and this watcher runs continuously against the same file the
    # notify slide rewrites -- so a notification arriving in that window was lost,
    # and a reader could see a truncated file. os.replace is atomic.
    try:
        with open(QUEUE) as handle:
            rows = [line for line in handle if line.strip()]
        if len(rows) > KEEP:
            tmp = QUEUE + ".tmp"
            with open(tmp, "w") as handle:
                handle.writelines(rows[-KEEP:])
            os.replace(tmp, QUEUE)
    except OSError:
        pass
    print(f"queued: {entry['app']}: {summary[:60]}", flush=True)


def unescape(text):
    out, escaped = [], False
    for ch in text:
        if escaped:
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(ch, ch))
            escaped = False
        elif ch == "\\":
            escaped = True
        else:
            out.append(ch)
    return "".join(out)


def parse_string(line):
    line = line.strip()
    if not line.startswith('string "'):
        return None
    value = line[len('string "'):]
    if value.endswith('"'):
        value = value[:-1]
    return unescape(value)


def main():
    proc = subprocess.Popen(BUS_ARGS, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, bufsize=1)
    print(f"cadence notification watcher listening on {QUEUE}", flush=True)

    collecting = False
    strings = []
    for line in proc.stdout:
        if "member=Notify" in line:
            collecting, strings = True, []
            continue
        if not collecting:
            continue
        # A new call header ends the previous one.
        if line.startswith(("method call", "method return", "signal ")):
            collecting = False
            continue
        value = parse_string(line)
        if value is not None:
            strings.append(value)
            if len(strings) == 4:
                app, _icon, summary, body = strings
                append(app, summary, body)
                collecting = False


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
