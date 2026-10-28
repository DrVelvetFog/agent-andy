#!/usr/bin/env python3
"""Make Agent Andy's app icon — one original glyph, drawn locally, no assets.

A single checkmark (the "it checked, and it's good" mark) on a rounded navy tile,
in the viewer's own colors. Pure stdlib: it rasterizes two signed-distance fields
(a rounded rectangle and the two check strokes) with 1px analytic anti-aliasing and
writes a 1024x1024 RGBA PNG by hand (zlib + struct). No face, no avatar, no
character art, no downloaded or stock image. scripts/build_mac_app.sh resizes this
master with sips and packs it into an .icns with iconutil.

    python3 scripts/make_app_icon.py OUT.png
"""

from __future__ import annotations

import math
import struct
import sys
import zlib

SIZE = 1024
NAVY = (14, 32, 51)       # tile fill   (#0e2033, the viewer's primary button navy)
EDGE = (39, 80, 127)      # tile hairline rim (#27507f)
GREEN = (46, 160, 67)     # checkmark   (#2ea043, the "allow" green)
BG = (0, 0, 0, 0)         # transparent outside the tile


def _sd_round_rect(px, py, cx, cy, hw, hh, r):
    qx, qy = abs(px - cx) - (hw - r), abs(py - cy) - (hh - r)
    ax, ay = max(qx, 0.0), max(qy, 0.0)
    return math.hypot(ax, ay) + min(max(qx, qy), 0.0) - r


def _sd_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _cov(d):
    """1px analytic anti-aliased coverage from a signed distance (inside is d<0)."""
    return max(0.0, min(1.0, 0.5 - d))


def _blend(dst, src, a):
    return tuple(int(round(dst[i] + (src[i] - dst[i]) * a)) for i in range(3))


def _write_png(path, w, h, rgba):
    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))
    raw = bytearray()
    row = w * 4
    for y in range(h):
        raw.append(0)                       # filter type 0 (none)
        raw += rgba[y * row:(y + 1) * row]
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def render(size=SIZE):
    s = float(size)
    # Tile: inset ~11% so the artwork carries macOS-style transparent padding.
    inset = 0.11 * s
    cx = cy = s / 2.0
    hw = hh = s / 2.0 - inset
    r = 0.235 * (2 * hw)                     # corner radius
    # Checkmark: three points, normalized to the icon, stroked with round caps.
    p = [(0.300, 0.540), (0.440, 0.680), (0.730, 0.345)]
    pts = [(x * s, y * s) for x, y in p]
    stroke = 0.082 * s                       # half-width added via the SDF threshold

    out = bytearray(size * size * 4)
    for y in range(size):
        py = y + 0.5
        base = y * size * 4
        for x in range(size):
            px = x + 0.5
            d_tile = _sd_round_rect(px, py, cx, cy, hw, hh, r)
            tile_a = _cov(d_tile)
            if tile_a <= 0.0:
                i = base + x * 4
                out[i:i + 4] = bytes(BG)
                continue
            # tile fill, with a faint rim near the edge
            rim = max(0.0, min(1.0, 1.0 - abs(d_tile + 3.0) / 3.0)) if d_tile > -6.0 else 0.0
            col = _blend(NAVY, EDGE, 0.6 * rim)
            # checkmark over the tile
            dseg = min(_sd_segment(px, py, *pts[0], *pts[1]),
                       _sd_segment(px, py, *pts[1], *pts[2]))
            chk_a = _cov(dseg - stroke)
            if chk_a > 0.0:
                col = _blend(col, GREEN, chk_a)
            i = base + x * 4
            out[i] = col[0]
            out[i + 1] = col[1]
            out[i + 2] = col[2]
            out[i + 3] = int(round(255 * tile_a))
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: make_app_icon.py OUT.png", file=sys.stderr)
        return 2
    _write_png(sys.argv[1], SIZE, SIZE, render(SIZE))
    print(f"wrote {sys.argv[1]} ({SIZE}x{SIZE})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
