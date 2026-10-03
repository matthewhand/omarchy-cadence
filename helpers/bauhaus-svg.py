#!/usr/bin/env python3
"""Procedural Bauhaus-minimalist SVG, for the cadence image slide.

This is the stand-in for an AI image backend, not the AI backend itself. The real
one would ask a model for a composition; this draws the same vocabulary
deterministically from a seed, so the pipeline can be exercised and reviewed
without spending a token.

The point of the constraint is that these shapes survive ASCII transcoding.
Braille cells give roughly 2x4 dots per character, and omarchy-transcode-ascii
treats dark pixels as ink and everything else as background. So colour is
meaningless here -- a red disc and a black disc are the same blob -- and the
palette is black on white like the reference smiley SVG. What survives is large
flat areas, hard edges and strong figure/ground contrast: circles, half discs,
quarter arcs, straight rules, generous whitespace. The Bauhaus part is therefore
in the geometry, not the colour.

Written into the directory cadence already watches, so the file is transcoded to
ASCII and joins the rotation on the next pass with no further wiring.

usage: bauhaus-svg.py [--seed N] [--out PATH]
"""
import argparse
import math
import os
import random
import sys

# Black on white. Colour does not survive the transcode, so the composition has
# to work as pure figure/ground.
INK = "#000000"
PAPER = "#ffffff"

WIDTH, HEIGHT = 640, 640


def quarter_arc(cx, cy, r, start_deg, sweep_deg, colour, width):
    """An arc as a stroked path. SVG has no arc primitive that renders as a
    single stroke, so approximate with a polyline -- at 2 degrees per segment
    the error is far below one braille dot."""
    points = []
    steps = max(4, int(abs(sweep_deg) / 2))
    for i in range(steps + 1):
        angle = math.radians(start_deg + sweep_deg * i / steps)
        points.append(f"{cx + r * math.cos(angle):.1f},{cy + r * math.sin(angle):.1f}")
    return (f'<polyline points="{" ".join(points)}" fill="none" '
            f'stroke="{colour}" stroke-width="{width}" stroke-linecap="butt"/>')


def build(seed):
    rng = random.Random(seed)
    parts = [f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{PAPER}"/>']

    # One dominant gesture: a big circle, half disc or quarter arc.
    cx, cy = rng.randint(220, 420), rng.randint(220, 420)
    r = rng.randint(150, 250)
    colour = INK
    gesture = rng.choice(("circle", "half", "quarter", "ring"))
    if gesture == "circle":
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{colour}"/>')
    elif gesture == "half":
        parts.append(f'<path d="M {cx - r} {cy} A {r} {r} 0 0 1 {cx + r} {cy} Z" fill="{colour}"/>')
    elif gesture == "quarter":
        parts.append(quarter_arc(cx, cy, r, 180, 90, colour, rng.randint(26, 40)))
    else:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                     f'stroke="{colour}" stroke-width="{rng.randint(24, 38)}"/>')

    # A straight rule. One axis only, to keep the composition calm.
    if rng.random() < 0.85:
        y = rng.randint(70, 570)
        parts.append(f'<rect x="0" y="{y}" width="{WIDTH}" height="{rng.randint(8, 16)}" '
                     f'fill="{INK}"/>')

    # Two or three small accents, kept far from the gesture.
    for _ in range(rng.randint(2, 3)):
        side = rng.randint(34, 96)
        x = rng.randint(0, WIDTH - side)
        y = rng.randint(0, HEIGHT - side)
        if rng.random() < 0.5:
            parts.append(f'<rect x="{x}" y="{y}" width="{side}" height="{side}" '
                         f'fill="{INK}"/>')
        else:
            parts.append(f'<circle cx="{x + side // 2}" cy="{y + side // 2}" '
                         f'r="{side // 2}" fill="{INK}"/>')

    return ('<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}">'
            + "".join(parts) + "</svg>\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    seed = args.seed if args.seed is not None else random.randrange(1 << 30)

    out = args.out
    if not out:
        # Numbered so cadence's own ordering keeps the newest last.
        slides = os.path.expanduser("~/Pictures/cadence-slides")
        os.makedirs(slides, exist_ok=True)
        highest = 0
        for name in os.listdir(slides):
            stem = name.split("-", 1)[0]
            if stem.isdigit():
                highest = max(highest, int(stem))
        out = os.path.join(slides, f"{highest + 1:02d}-bauhaus.svg")

    svg = build(seed)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(svg)
    os.replace(tmp, out)
    print(f"wrote {out} (seed {seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())