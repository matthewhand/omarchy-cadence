#!/usr/bin/env python3
"""AI-generated slides for the cadence screensaver.

Two subcommands matter to the screensaver:

    ai-slides.py print <style>     render the cached text. Never calls a model.
    ai-slides.py generate <style>  refresh the cache if the cap allows it.

`print` never talks to a model, deliberately. The runner executes a dynamic
slide synchronously (`eval "$arg" >"$out"`), so a 30-second generation would
stall the rotation and hold the screen on a blank frame. Generation therefore
happens out of band from a systemd timer, and the slide only ever reads a file.

`generate` is where the quota protection lives:

  * a per-style interval cap (default 24h) - the reason this feature is not a
    way to quietly spend an agent subscription;
  * an flock, so a timer tick and a manual run cannot bill twice at once;
  * an atomic cache write, so a crash mid-generation leaves the previous slide
    intact rather than a truncated one;
  * on any failure the old cache is kept and the error is recorded. A broken
    backend must not empty the rotation.

Configuration is JSONC, next to this file, so the prompts stay readable and
commentable - see ai-slides.jsonc. The backend command is configurable rather
than hardcoded, because agent CLIs disagree sharply on whether they can run
without a terminal: `omarchy-agent --prompt` launches the agent's TUI, which
never exits, so it cannot be used from a timer at all.
"""
import errno
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.environ.get(
    "CADENCE_AI_CONFIG", os.path.join(HERE, "ai-slides.jsonc"))
CACHE = os.environ.get(
    "CADENCE_AI_CACHE",
    os.path.expanduser("~/.cache/omarchy/cadence/ai"))

DEFAULT_INTERVAL_MINUTES = 1440  # once a day
DEFAULT_TIMEOUT = 180


# ---------------------------------------------------------------- jsonc

def load_config():
    """Read the JSONC config. Comments are stripped, not the file rewritten -
    the same reason cadence writes toggles to a separate state file."""
    try:
        raw = open(CONFIG, encoding="utf-8").read()
    except OSError:
        return {}
    text = strip_jsonc(raw)
    try:
        return json.loads(text) or {}
    except json.JSONDecodeError as error:
        sys.stderr.write(f"ai-slides: bad config {CONFIG}: {error}\n")
        return {}


def strip_jsonc(text):
    """Remove // and /* */ comments that are not inside a JSON string."""
    out = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------- state

def state_path(style):
    return os.path.join(CACHE, f"{style}.json")


def text_path(style):
    return os.path.join(CACHE, f"{style}.txt")


def read_state(style):
    try:
        with open(state_path(style), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def write_json_atomic(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def write_text_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------- style

def style_config(config, style):
    styles = config.get("styles") or {}
    entry = styles.get(style)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        return None
    entry = dict(entry)
    entry.setdefault("enabled", True)
    entry.setdefault("interval_minutes",
                     config.get("default_interval_minutes", DEFAULT_INTERVAL_MINUTES))
    entry.setdefault("timeout_seconds",
                     config.get("timeout_seconds", DEFAULT_TIMEOUT))
    entry.setdefault("prompt", "")
    entry.setdefault("label", style.upper())
    return entry


def due(entry, state, force):
    """True when this style may call the model."""
    if force:
        return True, "forced"
    last = float(state.get("last_generated") or 0)
    if last <= 0:
        return True, "never generated"
    try:
        interval = int(entry.get("interval_minutes", DEFAULT_INTERVAL_MINUTES))
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL_MINUTES
    age_minutes = (time.time() - last) / 60.0
    if age_minutes >= interval:
        return True, f"due ({age_minutes:.0f}m since last, cap {interval}m)"
    return False, f"capped ({age_minutes:.0f}m since last, cap {interval}m)"


# ---------------------------------------------------------------- backend

def backend_command(config, entry):
    """argv for the model call.

    Configured, not hardcoded. `omarchy-agent --prompt` is the sanctioned entry
    point but it execs the agent's TUI, which renders and waits rather than
    answering once, so a timer would hang on it. Anything listed here must be a
    one-shot that prints the reply to stdout and exits.
    """
    argv = config.get("command")
    if isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv):
        return list(argv)
    agent = entry.get("command")
    if isinstance(agent, list) and agent and all(isinstance(a, str) for a in agent):
        return list(agent)
    return None


def call_model(config, entry, prompt):
    argv = backend_command(config, entry)
    if not argv:
        raise RuntimeError(
            "no backend command configured - set \"command\" in ai-slides.jsonc")
    timeout = int(entry.get("timeout_seconds", DEFAULT_TIMEOUT))
    proc = subprocess.run(
        argv + [prompt],
        capture_output=True, text=True, timeout=timeout,
        cwd=os.path.expanduser("~"), start_new_session=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(
            f"backend exited {proc.returncode}: {tail[-1] if tail else 'no output'}")
    return proc.stdout


# ---------------------------------------------------------------- cleaning

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def clean(text, max_lines=6, width=74):
    """Turn a model reply into a few plain ASCII lines."""
    text = ANSI.sub("", text or "")
    text = text.replace("`", "")
    # Fenced blocks and stray markdown emphasis.
    text = re.sub(r"^\s*```.*$", "", text, flags=re.M)
    text = text.replace("**", "").replace("*", "")
    lines = []
    for raw in text.splitlines():
        line = raw.strip().strip("#>-•").strip()
        if not line:
            continue
        # Non-ASCII would render inconsistently across ttfx effects.
        line = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in line)
        for piece in textwrap.wrap(line, width=width) or [line]:
            lines.append(piece)
        if len(lines) >= max_lines:
            break
    return lines[:max_lines]


# ---------------------------------------------------------------- render

def load_wordfont():
    candidates = [
        os.environ.get("CADENCE_WORD_FONT"),
        os.path.expanduser("~/omarchy.local/tools/word-to-ascii.py"),
        os.path.join(HERE, "wordfont.py"),
    ]
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location("wordfont", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception:
            continue
    return None


def render(entry, lines, width=74):
    """Centre the text. Plain, deliberately.

    The 6x8 block font in wordfont.py is not used here: it exits on any glyph
    outside A-Z0-9 and refuses text longer than about 13 characters, which is
    most of what a model writes. The AI slides also carry no label -- they are
    meant to sit in the rotation looking like any other slide, not announce
    themselves.
    """
    body = list(lines) or ["(no text yet)"]
    top = max(0, (26 - len(body)) // 2)
    out = [""] * top
    pad = max(0, (width - max(len(line) for line in body)) // 2)
    out.extend(" " * pad + line for line in body)
    return "\n".join(out).rstrip() + "\n"


def banner_path(style):
    return os.path.join(CACHE, f"{style}.banner")


def render_banner(lines, entry, width=80, height=26):
    """Render each line with word-banner.sh, or return None to fall back.

    Cached rather than rendered on demand: word-banner.sh shells out to
    ImageMagick and omarchy-transcode-ascii per line, which costs seconds. The
    slide has to be instant, because the runner executes it synchronously while
    the screensaver is on screen.
    """
    tool = os.environ.get("CADENCE_BANNER") or os.path.expanduser(
        "~/omarchy.local/tools/word-banner.sh")
    if not os.path.exists(tool):
        return None
    squeeze = str(entry.get("banner_squeeze") or 55)
    mode = str(entry.get("banner_mode") or "braille")
    blocks = []
    for line in lines:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "line.txt")
            try:
                subprocess.run(
                    [tool, line, out],
                    capture_output=True, text=True, timeout=90,
                    env={**os.environ, "WORD": line, "SQUEEZE": squeeze,
                         "MODE": mode, "WIDTH": str(width), "HEIGHT": str(height)},
                )
            except (subprocess.TimeoutExpired, OSError):
                return None
            try:
                with open(out, encoding="utf-8") as handle:
                    body = handle.read().rstrip("\n")
            except OSError:
                return None
        if body.strip():
            blocks.append(body)
    if not blocks:
        return None
    # Only use the banner if the whole thing actually fits the screen.
    combined = "\n\n".join(blocks)
    if len(combined.splitlines()) > height:
        return None
    return combined + "\n"


# ---------------------------------------------------------------- commands

def read_cache(style):
    try:
        with open(text_path(style), encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def cmd_print(config, style):
    entry = style_config(config, style)
    if entry is None:
        sys.stderr.write(f"ai-slides: no such style: {style}\n")
        return 1
    if not entry.get("enabled", True):
        return 1
    cached = read_cache(style)
    if not cached:
        # Belt and braces. `seed` normally puts the bundled default in the cache,
        # but if the cache was cleared, or this is a fresh install where seed
        # never ran, fall back to the default text inline rather than showing
        # nothing. Plain text rather than the banner: the banner costs seconds and
        # this path has to stay instant.
        default = str(entry.get("default_text") or "").strip()
        if not default:
            # No default and nothing cached: genuinely nothing to show. Stay
            # silent, because the runner reads empty output as "this slide cannot
            # be produced" and moves on.
            return 1
        sys.stdout.write(render(entry, [l for l in default.splitlines() if l.strip()]))
        return 0
    try:
        with open(banner_path(style), encoding="utf-8") as handle:
            banner = handle.read()
        if banner.strip():
            sys.stdout.write(banner)
            return 0
    except OSError:
        pass
    lines = [line for line in cached.splitlines() if line.strip()]
    sys.stdout.write(render(entry, lines))
    return 0


def cmd_generate(config, style, force):
    entry = style_config(config, style)
    if entry is None:
        sys.stderr.write(f"ai-slides: no such style: {style}\n")
        return 1
    if not entry.get("enabled", True):
        print(f"{style}: disabled")
        return 0

    os.makedirs(CACHE, exist_ok=True)
    lock_path = os.path.join(CACHE, f"{style}.lock")
    lock = open(lock_path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EAGAIN):
            print(f"{style}: another generation in progress, skipping")
            return 0
        raise

    state = read_state(style)
    allowed, why = due(entry, state, force)
    if not allowed:
        print(f"{style}: {why}")
        return 0

    print(f"{style}: generating ({why})")
    try:
        raw = call_model(config, entry, str(entry.get("prompt") or ""))
    except subprocess.TimeoutExpired:
        state["last_error"] = f"timeout after {entry.get('timeout_seconds')}"
        state["last_attempt"] = time.time()
        write_json_atomic(state_path(style), state)
        sys.stderr.write(f"ai-slides: {style}: backend timed out\n")
        return 0
    except Exception as error:  # noqa: BLE001 - any backend failure is recorded, not raised
        state["last_error"] = str(error)[:300]
        state["last_attempt"] = time.time()
        write_json_atomic(state_path(style), state)
        sys.stderr.write(f"ai-slides: {style}: {error}\n")
        return 0

    lines = clean(raw)
    if not lines:
        state["last_error"] = "backend produced no usable text"
        state["last_attempt"] = time.time()
        write_json_atomic(state_path(style), state)
        sys.stderr.write(f"ai-slides: {style}: nothing usable in the reply\n")
        return 0

    write_text_atomic(text_path(style), "\n".join(lines))
    # Pre-render the banner now, while it is cheap to be slow, rather than on the
    # screensaver's critical path.
    banner = render_banner(lines, entry)
    if banner:
        write_text_atomic(banner_path(style), banner)
    else:
        # No banner available: drop any stale one, or `print` would keep showing
        # art for text that no longer exists.
        try:
            os.remove(banner_path(style))
        except OSError:
            pass
    state["last_generated"] = time.time()
    state["last_attempt"] = state["last_generated"]
    state["last_error"] = ""
    state["generations"] = int(state.get("generations") or 0) + 1
    write_json_atomic(state_path(style), state)
    print(f"{style}: cached {len(lines)} line(s); "
          f"next allowed in {entry.get('interval_minutes')}m")
    return 0


def seed_style(config, style):
    """Write the bundled default for a style that has nothing cached.

    The slide then always has something to show, on a fresh install and when
    generation keeps failing. Deliberately only fills an *empty* cache, so it can
    never overwrite real model output.
    """
    entry = style_config(config, style)
    if entry is None:
        return 1
    if not entry.get("enabled", True):
        return 0
    if read_cache(style):
        return 0
    default = str(entry.get("default_text") or "").strip()
    if not default:
        return 0
    lines = [line for line in default.splitlines() if line.strip()]
    write_text_atomic(text_path(style), "\n".join(lines))
    banner = render_banner(lines, entry)
    if banner:
        write_text_atomic(banner_path(style), banner)
    state = read_state(style)
    state["seeded_default"] = True
    write_json_atomic(state_path(style), state)
    print(f"{style}: seeded bundled default ({len(lines)} line(s))")
    return 0


def cmd_seed(config):
    rc = 0
    for style in sorted((config.get("styles") or {}).keys()):
        rc |= seed_style(config, style)
    return rc


def cmd_status(config):
    out = {}
    for style in sorted((config.get("styles") or {}).keys()):
        entry = style_config(config, style) or {}
        state = read_state(style)
        last = float(state.get("last_generated") or 0)
        interval = entry.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)
        allowed, why = due(entry, state, False)
        out[style] = {
            "enabled": bool(entry.get("enabled", True)),
            "label": entry.get("label"),
            "has_cache": bool(read_cache(style)),
            "last_generated": int(last) if last else None,
            "age_minutes": int((time.time() - last) / 60) if last else None,
            "interval_minutes": interval,
            "due": allowed,
            "why": why,
            "generations": int(state.get("generations") or 0),
            "bundled_default": bool(state.get("seeded_default")),
            "last_error": state.get("last_error") or "",
        }
    print(json.dumps({"ok": True, "data": {"styles": out,
                                          "backend": backend_command(config, {})}},
                     indent=2))
    return 0


def main(argv):
    config = load_config()
    if not argv:
        sys.stderr.write(
            "usage: ai-slides.py print <style> | generate <style> [--force]"
            " | generate-all | seed | status\n")
        return 2
    command = argv[0]
    rest = argv[1:]

    if command == "print":
        if not rest:
            sys.stderr.write("ai-slides: print needs a style\n")
            return 2
        return cmd_print(config, rest[0])

    if command == "generate":
        force = "--force" in rest
        styles = [a for a in rest if not a.startswith("--")]
        if not styles:
            styles = sorted((config.get("styles") or {}).keys())
        rc = 0
        for style in styles:
            rc |= cmd_generate(config, style, force)
        return rc

    if command == "generate-all":
        force = "--force" in rest
        rc = 0
        for style in sorted((config.get("styles") or {}).keys()):
            rc |= cmd_generate(config, style, force)
        return rc

    if command == "seed":
        return cmd_seed(config)

    if command == "status":
        return cmd_status(config)

    sys.stderr.write(f"ai-slides: unknown command: {command}\n")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)