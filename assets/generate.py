#!/usr/bin/env python3
"""
Till Infinity mark generator.

The mark is two unequal circles, tangent at a single point.

    The load-bearing idea in this project is that a level is where volatility
    turns, not where price poked: the leg in and the leg out meet at an origin,
    and the wick beyond it is the zone's width rather than its position.

So the mark is drawn from the turn, not from the name. Two turns of unequal
width meet at one origin, which is the tangency. A lemniscate's defining
feature is its crossing point, so the infinity association survives without
anyone drawing an infinity symbol: the topology is there, the cliche is not.

The asymmetry is the whole point. Equal circles would be a figure eight,
which is a symbol for the name. Unequal circles are a statement about the
subject, and they are what makes the shape memorable at a glance.

What the previous mark did that this one does not:

  * It spelled the name twice, an infinity loop plus a rising tail, and said
    nothing about what the system does.
  * The tail broke out to a new high, which is a returns claim.
  * It used a gradient and a 12px stroke, so it died in one colour and blurred
    into a blob at favicon size.

Requires Pillow, and IBM Plex Sans Medium for the lockup.

    python3 generate.py --fonts /path/to/dir/with/PlexSans-500.ttf
"""

import argparse
import os
from PIL import Image, ImageDraw

# ── Geometry, on a 48 x 48 grid ─────────────────────────────────────────

VB = 48.0

R1, R2 = 13.0, 7.0          # the wide turn, and the tight one
STROKE = 2.5
C1X = 17.5                  # centres, chosen so the drawn shape sits centred
C2X = C1X + R1 + R2
CY = 24.0

# At or below this, a 2.5 stroke is under a pixel. The small variant thickens
# the ring and closes the ratio so both turns survive.
SMALL_CUTOFF = 20
S_R1, S_R2, S_STROKE = 12.5, 7.5, 3.4
S_C1X = 17.0
S_C2X = S_C1X + S_R1 + S_R2

INK         = "#14181A"
PAPER       = "#E7EAE6"
ACCENT      = "#0E6B55"
ACCENT_DARK = "#3FBF9C"
BLACK       = "#000000"
WHITE       = "#FFFFFF"

INKS = {"ink": INK, "paper": PAPER, "accent": ACCENT,
        "accent-dark": ACCENT_DARK, "black": BLACK, "white": WHITE}

GROUND_LIGHT = "#F4F5F3"
GROUND_DARK  = "#0E1113"

PNG_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def geom(small):
    if small:
        return S_C1X, S_R1, S_C2X, S_R2, S_STROKE
    return C1X, R1, C2X, R2, STROKE


# ── Raster ──────────────────────────────────────────────────────────────

def draw_mark(size, color, ground=None, small=None):
    if small is None:
        small = size <= SMALL_CUTOFF
    c1x, r1, c2x, r2, w = geom(small)

    ss = max(2, min(8, 4096 // max(size, 1)))
    n = size * ss
    k = n / VB
    rgb = hex_rgb(color)

    im = Image.new("RGBA", (n, n),
                   hex_rgb(ground) + (255,) if ground else (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    d.ellipse([(c1x - r1) * k, (CY - r1) * k, (c1x + r1) * k, (CY + r1) * k],
              outline=rgb + (255,), width=max(1, round(w * k)))
    d.ellipse([(c2x - r2) * k, (CY - r2) * k, (c2x + r2) * k, (CY + r2) * k],
              fill=rgb + (255,))

    return im.resize((size, size), Image.LANCZOS)


# ── SVG ─────────────────────────────────────────────────────────────────

def svg_mark(color=None, small=False):
    fill = color or "currentColor"
    c1x, r1, c2x, r2, w = geom(small)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none"\n'
        '     role="img" aria-label="Till Infinity">\n'
        '  <title>Till Infinity</title>\n'
        '  <desc>Two turns of unequal width, meeting at one origin.</desc>\n'
        f'  <circle cx="{c1x:g}" cy="{CY:g}" r="{r1:g}" '
        f'stroke="{fill}" stroke-width="{w:g}"/>\n'
        f'  <circle cx="{c2x:g}" cy="{CY:g}" r="{r2:g}" fill="{fill}"/>\n'
        '</svg>\n')


def wordmark_paths(ttf, text, font_px, tracking_em=-0.015):
    from fontTools.ttLib import TTFont
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.misc.transform import Transform

    font = TTFont(ttf)
    scale = font_px / font["head"].unitsPerEm
    gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    track = tracking_em * font_px

    out, x = [], 0.0
    for ch in text:
        g = cmap.get(ord(ch))
        if g is None:
            continue
        pen = SVGPathPen(gs)
        gs[g].draw(TransformPen(pen, Transform(scale, 0, 0, -scale, x, 0)))
        if pen.getCommands():
            out.append(pen.getCommands())
        x += hmtx[g][0] * scale + track
    font.close()
    return out, x - track


def svg_lockup(color, ttf):
    mark_h = 34.0
    gap = mark_h * 13 / 34
    font_px = mark_h * 26 / 34
    paths, adv = wordmark_paths(ttf, "Till Infinity", font_px)

    k = mark_h / VB
    tx = mark_h + gap
    ty = mark_h / 2 + (font_px * 0.70) / 2
    w = tx + adv

    L = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.2f} {mark_h:g}" '
         f'fill="none" role="img" aria-label="Till Infinity">',
         f'  <g transform="scale({k:.6f})">',
         f'    <circle cx="{C1X:g}" cy="{CY:g}" r="{R1:g}" stroke="{color}" '
         f'stroke-width="{STROKE:g}"/>',
         f'    <circle cx="{C2X:g}" cy="{CY:g}" r="{R2:g}" fill="{color}"/>',
         '  </g>',
         f'  <g transform="translate({tx:.3f},{ty:.3f})" fill="{color}">']
    L += [f'    <path d="{d}"/>' for d in paths]
    L += ['  </g>', '</svg>', '']
    return "\n".join(L)


# ── Build ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", help="dir containing PlexSans-500.ttf")
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    docs = os.path.join(os.path.dirname(here), "docs")
    for d in ("svg", "png", "favicon"):
        os.makedirs(os.path.join(here, d), exist_ok=True)

    def w(rel, text, root=here):
        p = os.path.join(root, rel)
        with open(p, "w") as f:
            f.write(text)
        print("  ", os.path.relpath(p, os.path.dirname(here)))

    print("svg/")
    w("svg/mark.svg", svg_mark())
    w("svg/mark-small.svg", svg_mark(small=True))
    for name, col in INKS.items():
        w(f"svg/mark-{name}.svg", svg_mark(col))
        w(f"svg/mark-small-{name}.svg", svg_mark(col, small=True))

    # The README points at docs/logo.svg; keep that path working.
    w("logo.svg", svg_mark(INK), root=docs)

    if a.fonts:
        med = os.path.join(a.fonts, "PlexSans-500.ttf")
        if os.path.exists(med):
            for name in ("ink", "paper", "accent", "accent-dark"):
                w(f"svg/lockup-{name}.svg", svg_lockup(INKS[name], med))

    print("png/")
    for name, col in INKS.items():
        for s in PNG_SIZES:
            draw_mark(s, col).save(os.path.join(here, f"png/mark-{name}-{s}.png"))
        print("  ", f"png/mark-{name}-*.png")

    draw_mark(512, INK).save(os.path.join(docs, "logo.png"))
    print("   docs/logo.png")

    print("favicon/")
    for s in (16, 32, 48):
        draw_mark(s, INK).save(os.path.join(here, f"favicon/favicon-{s}.png"))
        draw_mark(s, PAPER).save(os.path.join(here, f"favicon/favicon-dark-{s}.png"))
    # App icons sit on an opaque ground: a transparent iOS icon reads as a hole.
    for s in (180, 192, 256, 512):
        draw_mark(s, INK, ground=GROUND_LIGHT, small=False).save(
            os.path.join(here, f"favicon/app-icon-{s}.png"))
        draw_mark(s, ACCENT_DARK, ground=GROUND_DARK, small=False).save(
            os.path.join(here, f"favicon/app-icon-dark-{s}.png"))
    draw_mark(64, INK).save(os.path.join(here, "favicon/favicon.ico"),
                            sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print("   favicon/*.png, favicon.ico")


if __name__ == "__main__":
    main()
